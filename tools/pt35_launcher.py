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

HOME_TILES = (
    ('NFC Tag · I²C', 'Built-in ST25DV16K', 'tag'),
    ('NFC Reader', 'ST25R3916 · Proxmark3', 'reader'),
    ('Spectrum Analyzer', 'AS7341 · 10 channels', 'spectrum'),
    ('LED Test', '16 WS2812 LEDs', 'led'),
    ('LRA Haptic Test', 'DRV2605L motor', 'lra'),
    ('Exit', 'Close launcher', 'exit'),
)


def home_tile_positions():
    """Stable two-column, three-row layout for the six launcher actions."""
    return [(name, row, column) for index, (name, _, _) in enumerate(HOME_TILES)
            for row, column in [divmod(index, 2)]]



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


def lra_command(action, effect=None):
    """Bounded user-triggered haptic diagnostics via installed controller."""
    cli = '/usr/local/bin/lra_ctl'
    if action in ('status', 'stop') and effect is None:
        return [cli, action]
    if action == 'play' and effect in (1, 10, 47) and type(effect) is int:
        return [cli, action, str(effect)]
    raise ValueError('Unsupported haptic test request')


def target_command(name):
    """Use source from the checkout. No hardcoded stale installed NFC scripts."""
    if name == 'tag':
        return [sys.executable, str(ROOT / 'nfc/pt35_i2c_tag_gui.py')]
    if name == 'reader':
        return [sys.executable, str(ROOT / 'nfc/pt35_nfc_gui.py')]
    if name == 'spectrum':
        script = ROOT / 'tools/as7341_gui.py'
        python = Path.home() / 'as7341-env/bin/python'
        interpreter = str(python) if python.is_file() else sys.executable
        return [interpreter, str(script)]
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
        # Fixed 2 × 3 grid fits the native 640×480 PT35 display without
        # requiring scrolling. Information/status stays BELOW the buttons.
        if self.frame is not None:
            self.frame.destroy()
        self.frame = tk.Frame(self, bg=self.palette.background, padx=10, pady=7)
        self.frame.pack(fill='both', expand=True)
        label(self.frame, 'PT35 · Tools', font=LARGE).pack(fill='x', pady=(0, 7))
        grid = tk.Frame(self.frame, bg=self.palette.background)
        grid.pack(fill='both', expand=True)
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform='tiles')
        for row_index in range(3):
            grid.grid_rowconfigure(row_index, weight=1, uniform='tiles')
        actions = {
            'tag': lambda: self.launch('tag'),
            'reader': lambda: self.launch('reader'),
            'spectrum': lambda: self.launch('spectrum'),
            'led': self.led_page,
            'lra': self.lra_page,
            'exit': self.destroy,
        }
        for index, (name, subtitle, key) in enumerate(HOME_TILES):
            row_index, column = divmod(index, 2)
            tile = tk.Frame(grid, bg=self.palette.panel)
            tile.grid(row=row_index, column=column, sticky='nsew', padx=4, pady=4)
            tile.grid_rowconfigure(0, weight=1)
            tile.grid_columnconfigure(0, weight=1)
            button = Button(tile, name, actions[key], primary=(index == 0),
                            wraplength=220)
            button.configure(anchor='center', justify='center', padx=4, pady=5)
            button.grid(row=0, column=0, sticky='nsew')
            subtitle_label = label(tile, subtitle, font=SMALL, muted=True,
                                   wraplength=220)
            subtitle_label.configure(anchor='center', justify='center')
            subtitle_label.grid(row=1, column=0, sticky='ew', pady=(0, 3))
        info = tk.Frame(self.frame, bg=self.palette.background)
        info.pack(fill='x', pady=(6, 0))
        label(info, 'R: launcher · A/Enter: select · Y/Esc: back',
              font=SMALL, muted=True, wraplength=610).pack(fill='x')
        label(info, textvariable=self.notice, font=SMALL, muted=True,
              wraplength=610).pack(fill='x')
        self.notice.set('Ready · Five tools and Exit')


    def go_home(self, event=None):
        self.home()

    def launch(self, name):
        command = target_command(name)
        try:
            subprocess.Popen(command, start_new_session=True, cwd=str(ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.notice.set('Cannot launch: ' + str(exc)[:130])
        else:
            self.notice.set('Opened ' + {'tag': 'I²C NFC Tag', 'reader': 'NFC Reader',
                                         'spectrum': 'Spectrum Analyzer'}[name])

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

    def lra_page(self):
        area = self.page('LRA Haptic Test', self.home)
        label(area, 'DRV2605L · I²C bus 1 · address 0x5A', font=FONT).pack(fill='x')
        label(area, 'Test existing motor driver without changing its configuration '
                    'outside the normal effect playback initialization. '
                    'Use Stop to cancel an active effect.',
              font=SMALL, muted=True, wraplength=550).pack(fill='x', pady=8)
        self.add(area, 'Read driver status', lambda: self.lra_test('status'))
        for effect, title in ((1, 'Strong click'), (10, 'Double click'),
                              (47, 'Alert pulse')):
            self.add(area, f'Effect {effect} · {title}',
                     lambda number=effect: self.lra_test('play', number))
        self.add(area, 'Stop haptic playback', lambda: self.lra_test('stop'))
        label(area, 'No continuous real-time playback or automatic effect cycling.',
              font=SMALL, muted=True, wraplength=550).pack(fill='x', pady=6)

    def lra_test(self, action, effect=None):
        import threading

        def work():
            try:
                argv = lra_command(action, effect)
                result = subprocess.run(argv, capture_output=True, text=True,
                                        timeout=4, check=False)
                message = (result.stdout or result.stderr or
                           ('Command completed' if result.returncode == 0 else
                            f'LRA returned exit {result.returncode}')).strip()
                if result.returncode:
                    message = f'LRA error ({result.returncode}): ' + message
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                message = 'LRA unavailable: ' + str(exc)
            try:
                self.after(0, self.notice.set, message[:220])
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

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
