#!/usr/bin/env python3
"""Touch/keyboard PT35 tools launcher. No GPIO or RF hardware is accessed here."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nfc'))
from nfc_touch import THEMES, Button, ScrollArea, font_for, label, FONT, LARGE, SMALL
from nfc_config import DEFAULT_ARCHIVE
from nfc_archive import range_bytes
from nfc_ndef import decode_message, extract_message, ndef_area

SOCKET = Path(os.environ.get('PT35_LED_SOCKET', '/run/pt35-led.sock'))
LOCK = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / ('pt35-launcher-' + str(os.getuid()) + '.lock')
TAG_ADDRS = ('0x53', '0x57')
COLOR_TESTS = (
    ('Red', 'flash 16 0 0'),
    ('Green', 'flash 0 16 0'),
    ('Blue', 'flash 0 0 16'),
    ('Amber', 'flash 12 6 0'),
    ('Purple', 'flash 10 0 12'),
)
LED_COMMANDS = {'status', 'nfc-test', 'battery', 'boot', 'flash 16 0 0',
                'flash 0 16 0', 'flash 0 0 16', 'flash 12 6 0', 'flash 10 0 12'}


def led_command(command, socket_path=SOCKET):
    """Only allow a fixed set of existing daemon commands; never own GPIO."""
    if command not in LED_COMMANDS:
        raise ValueError('Unsupported LED test command')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(1.5)
        conn.connect(str(socket_path))
        conn.sendall((command + '\n').encode('ascii'))
        reply = conn.recv(512).decode('utf-8', errors='replace').strip()
    if reply.startswith('ERR'):
        raise RuntimeError(reply)
    return reply


def latest_tag_records(root=DEFAULT_ARCHIVE, limit=20):
    """Read the ordinary archive, without touching the NFC hardware."""
    output = []
    if not Path(root).is_dir():
        return output
    for path in Path(root).glob('*/record.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(record, dict) or not isinstance(record.get('uid'), str):
                continue
            output.append(record)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(output, key=lambda r: str(r.get('last_seen_utc', '')), reverse=True)[:limit]


def target_command(name):
    """Use source from the checkout. No hardcoded stale installed NFC scripts."""
    if name == 'reader':
        return [sys.executable, str(ROOT / 'nfc/pt35_nfc_gui.py')]
    if name == 'spectrum':
        script = ROOT / 'tools/pt35_tools.py'
        python = Path.home() / 'as7341-env/bin/python'
        interpreter = str(python) if python.is_file() else sys.executable
        return [interpreter, str(script), '--device', 'as7341']
    raise ValueError('Unknown PT35 application')


def terminal_command(argv):
    """Launch the existing curses spectrometer in its own terminal window."""
    for name in ('x-terminal-emulator', 'lxterminal', 'xfce4-terminal', 'xterm'):
        exe = shutil.which(name)
        if exe:
            if name == 'xfce4-terminal':
                return [exe, '--disable-server', '-e', ' '.join(shlex_quote(part) for part in argv)]
            if name == 'lxterminal':
                return [exe, '--command=' + ' '.join(shlex_quote(part) for part in argv)]
            return [exe, '-e', *argv]
    return None


def shlex_quote(value):
    import shlex
    return shlex.quote(str(value))


class Launcher(tk.Tk):
    def __init__(self, *, fullscreen=True):
        super().__init__()
        self.title('PT35 Launcher')
        self.palette = THEMES['dark']
        self.configure(bg=self.palette.background)
        w, h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{min(w, 960)}x{min(h, 700)}')
        self.minsize(min(w, 480), min(h, 320))
        self.attributes('-fullscreen', fullscreen)
        self.ui_scale = 1
        self.ui_fonts = {}
        self.frame = None
        self.notice = tk.StringVar(self, value='Ready')
        self.bind('<Escape>', self.go_home)
        self.bind('<Prior>', lambda _: self.focus_relative(-1))
        self.bind('<Next>', lambda _: self.focus_relative(1))
        self.bind('<Configure>', self.resize_ui, add='+')
        self.home()

    def resize_ui(self, event):
        if event.widget is not self:
            return
        scale = max(1, min(1.6, event.width / 640, event.height / 480))
        if abs(self.ui_scale - scale) >= .04:
            self.ui_scale = scale
            for spec, font in self.ui_fonts.items():
                font.configure(size=round(spec[1] * scale))

    def focus_relative(self, offset):
        buttons = [widget for widget in self.all_widgets(self.frame)
                   if isinstance(widget, tk.Button) and widget['state'] == 'normal']
        if buttons:
            current = self.focus_get()
            index = buttons.index(current) if current in buttons else 0
            buttons[(index + offset) % len(buttons)].focus_set()

    def all_widgets(self, widget):
        if widget is None:
            return
        yield widget
        for child in widget.winfo_children():
            yield from self.all_widgets(child)

    def page(self, title, back=None):
        if self.frame is not None:
            self.frame.destroy()
        self.frame = tk.Frame(self, bg=self.palette.background, padx=12, pady=8)
        self.frame.pack(fill='both', expand=True)
        head = tk.Frame(self.frame, bg=self.palette.background)
        head.pack(fill='x')
        if back is not None:
            Button(head, '‹ Back', back).pack(side='left', padx=(0, 8))
        label(head, title, font=LARGE).pack(side='left', fill='x', expand=True)
        body = ScrollArea(self.frame)
        body.pack(fill='both', expand=True, pady=(8, 2))
        label(self.frame, textvariable=self.notice, font=SMALL, muted=True).pack(fill='x')
        return body.content

    def add(self, area, title, action, description=None):
        button = Button(area, title, action, primary=False, anchor='w')
        button.pack(fill='x', pady=4)
        if description:
            label(area, description, font=SMALL, muted=True,
                  wraplength=max(280, min(820, self.winfo_screenwidth()-110))).pack(fill='x', pady=(0, 5))
        return button

    def home(self, event=None):
        area = self.page('PT35 · Tools')
        self.add(area, 'NFC Tag', self.tag_page, 'Onboard ST25DV and saved tag information')
        self.add(area, 'NFC Reader', lambda: self.launch('reader'),
                 'Internal ST25R3916 and USB Proxmark3 · scans and archive')
        self.add(area, 'Spectrum Analyzer', lambda: self.launch('spectrum'),
                 'Existing AS7341 spectrum application in a terminal')
        self.add(area, 'LED Test', self.led_page,
                 'Rear 16-pixel WS2812 strip · shared service, no direct GPIO')
        self.add(area, 'Exit', self.destroy)
        self.notice.set('R opens this launcher · A/Enter selects · Y/Esc goes back')

    def go_home(self, event=None):
        self.home()

    def launch(self, name):
        command = target_command(name)
        if name == 'spectrum':
            command = terminal_command(command)
            if command is None:
                self.notice.set('A desktop terminal is required for the existing spectrum analyzer.')
                return
        try:
            subprocess.Popen(command, start_new_session=True, cwd=str(ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.notice.set('Cannot launch: ' + str(exc)[:130])
        else:
            self.notice.set('Opened ' + ('NFC Reader' if name == 'reader' else 'Spectrum Analyzer'))

    def tag_page(self):
        area = self.page('NFC Tag · Overview', self.home)
        label(area, 'Built-in ST25DV16K dynamic NFC tag', font=FONT).pack(fill='x')
        label(area, 'I²C user/system interfaces: 0x53 / 0x57 (hardware-dependent). '
                    'This page does not modify the tag or start RF.', font=SMALL,
                    muted=True, wraplength=520).pack(fill='x', pady=8)
        present = Path('/dev/i2c-1').exists()
        label(area, 'I²C bus 1: ' + ('device available' if present else 'device not found'),
              muted=not present).pack(fill='x', pady=4)
        self.add(area, 'Open NFC Reader / tag archive', lambda: self.launch('reader'),
                 'Use the reader to scan, decode and save actual NFC data')
        self.add(area, 'Refresh saved tags', self.tag_page)
        tags = latest_tag_records()
        label(area, f'Recent archived tags ({len(tags)} shown):', font=FONT).pack(fill='x', pady=(12, 4))
        if not tags:
            label(area, 'Nothing archived yet. The old tag configuration menu is not replaced by '
                        'unverified I²C writes.', muted=True, wraplength=520).pack(fill='x')
        for record in tags:
            uid = record['uid']
            caption = (f"{record.get('protocol', '?')} · {uid}\n"
                       f"{record.get('classification', '?')} · "
                       f"{record.get('dump_status', '?')} · "
                       f"{record.get('scan_count', 1)} scan(s)")
            self.add(area, caption, lambda item=record: self.saved_tag_detail(item))

    def saved_tag_detail(self, record):
        area = self.page('NFC Tag · Saved capture', self.tag_page)
        uid = record.get('uid', '?')
        label(area, uid, font=FONT, wraplength=560).pack(fill='x', pady=5)
        for field, key in (('Protocol', 'protocol'), ('Classification', 'classification'),
                           ('Manufacturer', 'manufacturer'), ('Read status', 'dump_status'),
                           ('Last seen', 'last_seen_utc'), ('Scans', 'scan_count')):
            value = record.get(key, 'unknown')
            label(area, f'{field}: {value}', font=SMALL, wraplength=560).pack(fill='x', pady=2)
        history = record.get('capture_history') or []
        if history:
            label(area, f'Distinct stored captures: {len(history)}',
                  font=FONT).pack(fill='x', pady=(8, 4))
            for entry in reversed(history[-8:]):
                label(area, f"{entry.get('at', '?')}: {entry.get('comparison', 'unknown')}, "
                            f"{entry.get('status', 'unknown')} ({entry.get('blocks', 0)} blocks)",
                      font=SMALL, wraplength=560).pack(fill='x', pady=3)
        blocks = record.get('blocks') or []
        label(area, f'Memory: {len(blocks)} readable blocks', font=FONT).pack(fill='x', pady=(8, 4))
        try:
            data = range_bytes(record)
            items = decode_message(extract_message(ndef_area(record, data)) or b'') if data else []
        except (ValueError, TypeError, KeyError):
            items = []
        if items:
            label(area, 'Decoded NDEF content', font=FONT).pack(fill='x', pady=(8, 4))
            for item in items[:16]:
                label(area, item, font=SMALL, wraplength=560).pack(fill='x', pady=3)
        elif record.get('content_preview'):
            for item in record['content_preview'][:16]:
                label(area, str(item), font=SMALL, wraplength=560).pack(fill='x', pady=3)
        elif blocks:
            label(area, 'No verified NDEF preview. Raw blocks are shown below.',
                  muted=True, font=SMALL).pack(fill='x', pady=4)
        for block in blocks[:24]:
            try:
                line = f"{block['index']:04d}  {bytes.fromhex(block['hex']).hex(' ').upper()}"
            except (ValueError, TypeError, KeyError):
                continue
            label(area, line, font=SMALL, wraplength=560).pack(fill='x', pady=1)
        if len(blocks) > 24:
            label(area, 'Showing first 24 blocks. Open the reader archive for full memory.',
                  font=SMALL, muted=True, wraplength=560).pack(fill='x', pady=4)
        self.add(area, 'Open full NFC archive', lambda: self.launch('reader'))

    def led_page(self):
        area = self.page('LED Test · WS2812', self.home)
        label(area, '16 rear LEDs · GPIO12 · service-controlled only', font=FONT).pack(fill='x')
        label(area, 'Rear-view serpentine: top 0–7 left→right; '
                    'bottom 15–8 left→right. Tests stay dim.',
              muted=True, font=SMALL, wraplength=550).pack(fill='x', pady=6)
        label(area, 'Physical rear layout (hinge below)', muted=True,
              font=SMALL).pack(fill='x', pady=(8, 2))
        for sequence in (tuple(range(8)), tuple(range(15, 7, -1))):
            strip = tk.Frame(area, bg=self.palette.background)
            strip.pack(fill='x', pady=3)
            for index in sequence:
                tk.Label(strip, text=str(index), bg=self.palette.panel,
                         fg=self.palette.text, font=font_for(self, SMALL),
                         padx=2, pady=6, relief='ridge').pack(
                             side='left', fill='x', expand=True, padx=2)
        self.add(area, 'Read LED daemon status', lambda: self.led_test('status'))
        self.add(area, 'Pixel-by-pixel indexing test', lambda: self.led_test('nfc-test'),
                 'Existing daemon test cycle · refuses while NFC has the LED lease')
        self.add(area, 'Battery display', lambda: self.led_test('battery'))
        for name, command in COLOR_TESTS:
            self.add(area, f'{name} · short flash', lambda cmd=command: self.led_test(cmd))
        label(area, 'No persistent color change, no service restart, '
                    'and no direct access to the LED data pin.',
              muted=True, font=SMALL, wraplength=550).pack(fill='x', pady=8)

    def led_test(self, command):
        # Nonblocking UI: bounded socket request in a thread, Tk callback for result.
        import threading

        def work():
            try:
                output = led_command(command)
            except (OSError, RuntimeError, ValueError) as exc:
                output = 'LED service unavailable: ' + str(exc)
            try:
                self.after(0, self.notice.set, output)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windowed', action='store_true')
    args = parser.parse_args(argv)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('w') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # A second press of R must not create overlapping fullscreen UIs.
            return 0
        app = Launcher(fullscreen=not args.windowed)
        app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
