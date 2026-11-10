#!/usr/bin/env python3
"""PT35 built-in ST25DV16K I2C NFC tag manager (user memory 0x53 only)."""
import os
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nfc_touch import THEMES, Button, ScrollArea, FONT, SMALL, LARGE, label
from nfc_ndef import decode_message
from pt35_i2c_tag import PRESETS, format_blank_tag, inspect, make_ndef, write_payload

BACKUPS = Path.home() / '.local/share/pt35-nfc-tag-backups'


def save_backup(buffer):
    """Keep exact pre-write 512-byte user-memory snapshot with private mode."""
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = datetime.now(timezone.utc).strftime('st25dv-%Y%m%dT%H%M%S-%fZ.bin')
    path = BACKUPS / name
    with path.open('xb') as file:
        os.chmod(path, 0o600)
        file.write(buffer)
    return path


def decode_snapshot(snapshot):
    if snapshot.get('state') != 'ndef':
        return []
    return decode_message(snapshot['message'])


class TagWindow(tk.Tk):
    def __init__(self, *, windowed=False):
        super().__init__()
        self.title('PT35 · I²C NFC Tag')
        self.palette = THEMES['dark']
        self.configure(bg=self.palette.background)
        w, h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{min(900, w)}x{min(700, h)}')
        self.minsize(min(480, w), min(320, h))
        self.attributes('-fullscreen', not windowed)
        self.ui_scale = 1
        self.ui_fonts = {}
        self.root_frame = None
        self.busy = False
        self.snapshot = None
        self.status = tk.StringVar(self, 'Ready · read-only until you confirm a write')
        self.input_value = ''
        self.bind('<Configure>', self.resize, add='+')
        self.bind('<Escape>', lambda _: self.home())
        self.bind('<Prior>', lambda _: self.scroll(-1))
        self.bind('<Next>', lambda _: self.scroll(1))
        self.home()

    def scroll(self, direction):
        if hasattr(self, 'scroller') and self.scroller.winfo_exists():
            self.scroller.canvas.yview_scroll(direction * 160, 'units')

    def resize(self, event):
        if event.widget is not self:
            return
        scale = max(1, min(1.7, event.width / 640, event.height / 480))
        if abs(scale - self.ui_scale) > .04:
            self.ui_scale = scale
            for spec, font in self.ui_fonts.items():
                font.configure(size=round(spec[1] * scale))

    def page(self, title, back=None):
        if self.root_frame is not None:
            self.root_frame.destroy()
        frame = tk.Frame(self, bg=self.palette.background, padx=10, pady=8)
        frame.pack(fill='both', expand=True)
        self.root_frame = frame
        head = tk.Frame(frame, bg=self.palette.background)
        head.pack(fill='x')
        if back:
            Button(head, '‹ Back', back).pack(side='left', padx=(0, 8))
        label(head, title, font=LARGE, wraplength=580).pack(side='left', fill='x', expand=True)
        self.scroller = ScrollArea(frame)
        self.scroller.pack(fill='both', expand=True, pady=6)
        label(frame, textvariable=self.status, font=SMALL, muted=True,
              wraplength=600).pack(fill='x', pady=2)
        return self.scroller.content

    def add(self, area, title, action, description=''):
        Button(area, title, action, anchor='w').pack(fill='x', pady=4)
        if description:
            label(area, description, font=SMALL, muted=True,
                  wraplength=550).pack(fill='x')

    def run_io(self, func, done):
        if self.busy:
            self.status.set('An I²C operation is already running')
            return
        self.busy = True
        self.status.set('Working with ST25DV over I²C…')
        def worker():
            try:
                result, error = func(), None
            except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                result, error = None, str(exc)
            try:
                self.after(0, lambda: self.complete_io(done, result, error))
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def complete_io(self, done, result, error):
        self.busy = False
        if error is not None:
            self.status.set('I²C error: ' + error[:200])
            messagebox.showerror('ST25DV I²C operation failed', error, parent=self)
        else:
            done(result)

    def home(self):
        area = self.page('I²C NFC Tag · ST25DV16K')
        label(area, 'Built-in dynamic NFC tag · user memory 0x53',
              font=FONT, wraplength=550).pack(fill='x', pady=4)
        label(area, 'Separate from the ST25R3916/Proxmark3 reader. System memory '
                    '0x57 is never written. This screen does not use RF.',
              font=SMALL, muted=True, wraplength=550).pack(fill='x', pady=4)
        self.add(area, 'Read / refresh NDEF', self.refresh,
                 'Reads the first 512 bytes, shows decoded URI or text and raw header.')
        self.add(area, 'Write a preset URL', self.presets,
                 'CollarPet / PT35, Telegram, GitHub')
        self.add(area, 'Write a custom URL or text', self.custom)
        self.add(area, 'Format blank tag for NDEF', self.format_confirm,
                 'ONLY if the first 32 bytes are completely blank (00/FF); requires confirmation')
        if self.snapshot:
            state = self.snapshot['state']
            self.add(area, 'View last read: ' + state.upper(), self.last_read)
        self.add(area, 'Close', self.destroy)
        self.status.set('Ready · writes require confirmation and a private backup')

    def refresh(self):
        self.run_io(inspect, self.got_snapshot)

    def got_snapshot(self, value):
        self.snapshot = value
        self.status.set('Read completed · ' + value['state'])
        self.last_read()

    def last_read(self):
        area = self.page('ST25DV · Current NDEF', self.home)
        if not self.snapshot:
            label(area, 'No read yet').pack(fill='x')
            return
        state = self.snapshot['state']
        label(area, 'State: ' + state, font=FONT).pack(fill='x', pady=4)
        if state == 'ndef':
            off, width, n = self.snapshot['tlv']
            label(area, f'NDEF TLV offset: 0x{off:04X} · {n} bytes · header {width}',
                  font=SMALL, wraplength=540).pack(fill='x', pady=3)
            decoded = decode_snapshot(self.snapshot)
            for value in decoded or ['NDEF exists but this record type is not decoded.']:
                label(area, value, font=FONT, wraplength=540).pack(fill='x', pady=5)
            label(area, 'NDEF bytes: ' + self.snapshot['message'].hex(' ').upper(),
                  font=SMALL, muted=True, wraplength=540).pack(fill='x', pady=8)
        elif state == 'blank':
            label(area, 'Blank or unformatted tag. Formatting is an explicit write.',
                  font=SMALL, wraplength=540).pack(fill='x', pady=5)
        else:
            label(area, 'Unknown/non-NDEF contents. No automatic formatting.',
                  font=SMALL, wraplength=540).pack(fill='x', pady=5)
        self.add(area, 'Read again', self.refresh)

    def presets(self):
        area = self.page('Write NDEF preset', self.home)
        for title, value in PRESETS.items():
            self.add(area, title, lambda name=title, data=value: self.confirm_write(name, data),
                     value)

    def custom(self):
        area = self.page('Custom URL / text', self.home)
        label(area, 'An http(s) URL becomes an NDEF URI; all other input becomes '
                    'an NDEF text record. Maximum 240 encoded message bytes.',
              font=SMALL, wraplength=560).pack(fill='x', pady=5)
        entry = tk.Text(area, bg=self.palette.panel, fg=self.palette.text,
                        insertbackground=self.palette.text, font=FONT, wrap='word',
                        height=4, padx=8, pady=8)
        entry.pack(fill='x', pady=8)
        entry.insert('1.0', self.input_value)
        def next_step():
            self.input_value = entry.get('1.0', 'end-1c').strip()
            try:
                make_ndef(self.input_value)
            except ValueError as exc:
                self.status.set(str(exc))
                return
            self.confirm_write('custom data', self.input_value)
        self.add(area, 'Review and confirm write', next_step)
        self.after_idle(entry.focus_set)

    def confirm_write(self, name, value):
        try:
            message_bytes = make_ndef(value)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        answer = messagebox.askyesno(
            'Write built-in I²C tag?',
            f'Replace the ST25DV NDEF with {name}?\n\n{value[:180]}\n\n'
            f'{len(message_bytes)} NDEF bytes. A private 512-byte backup is saved '
            'before writing. The write is verified on readback.',
            parent=self)
        if not answer:
            return
        def job():
            previous = inspect()
            backup = save_backup(previous['buffer'])
            length = write_payload(value)
            return length, backup
        def done(result):
            length, backup = result
            self.status.set(f'Wrote and verified {length} bytes · backup {backup.name}')
            messagebox.showinfo('NFC written', f'Verified {length} NDEF bytes.\n'
                                f'Backup: {backup}', parent=self)
            self.refresh()
        self.run_io(job, done)

    def format_confirm(self):
        answer = messagebox.askyesno(
            'Format built-in NFC tag?',
            'Format the blank ST25DV16K for NFC Forum Type-5 NDEF?\n\n'
            'This writes the original CC16 and empty NDEF TLV to user memory '
            '0x53 only. It refuses nonblank memory. A private backup is saved.',
            parent=self)
        if not answer:
            return
        def job():
            previous = inspect()
            backup = save_backup(previous['buffer'])
            format_blank_tag()
            return backup
        def done(backup):
            self.status.set(f'Formatted and verified · backup {backup.name}')
            messagebox.showinfo('ST25DV formatted', f'Format verified.\nBackup: {backup}',
                                parent=self)
            self.refresh()
        self.run_io(job, done)


def main():
    TagWindow(windowed='--windowed' in sys.argv[1:]).mainloop()


if __name__ == '__main__':
    main()
