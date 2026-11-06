#!/usr/bin/env python3
"""Standalone Tk application for the PT35 NFC worker and local archive."""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from nfc_archive import atomic_write, range_bytes, record_bytes, record_path, save_record
from nfc_pm3 import PM3_MODES, SIM_SECONDS, simulation_image
from nfc_config import DEFAULT_ARCHIVE
from nfc_ndef import decode_message, extract_message, ndef_area
from nfc_poll import MODES

BACKEND_SCRIPT = Path(__file__).resolve().with_name('pt35_nfc.py')
SETTINGS = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'pt35-nfc' / 'settings.json'


def read_events(proc, events):
    try:
        with proc.stdout:
            for line in proc.stdout:
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict) or 'event' not in item:
                        raise ValueError
                except ValueError:
                    item = {'event': 'log', 'message': line.strip()}
                events.put(item)
    except OSError as exc:
        events.put({'event': 'fault', 'message': f'Scanner output unavailable: {exc}'})
    finally:
        events.put({'event': 'exit', 'code': proc.wait()})


def format_record(record):
    geom = record.get('geometry')
    lines = [
        f"{record['protocol']} | {record['uid']}",
        f"{record.get('manufacturer', 'Unknown')} | {record.get('tonie_status', 'Unclassified')}",
        f"Source {record.get('capture_backend', record.get('backend', '?'))} | "
        f"{record.get('captured_utc', record.get('last_seen_utc', ''))}",
        record.get('chip', ''),
        f"Geometry: {geom['blocks']} × {geom['size']} bytes ({geom.get('source', 'legacy')})"
        if geom else 'Geometry: unknown',
        f"Coverage: {record.get('dump_status', '?').replace('_', ' ')}",
    ]
    requested = record.get('requested_range')
    if requested:
        start, count = requested['start'], requested['count']
        lines.append(f"Range {start}–{start + count - 1} | Readable {len(record.get('blocks', []))}/{count}")
    if record.get('blocks') and record.get('capture_format') != 2:
        lines.append('Legacy capture. Check its raw record for the original coverage claims.')
    if record.get('verification'):
        lines.append(record['verification'])
    if record.get('system_info', {}).get('error'):
        lines.append('System Information: ' + record['system_info']['error']['error'])
    if record.get('discovery'):
        lines.append('Discovery: ' + json.dumps(record['discovery']))
    data = range_bytes(record)
    if data is not None:
        message = extract_message(ndef_area(record, data))
        if message is not None:
            lines.extend(decode_message(message) or ['NDEF message present (no supported preview)'])
        try:
            preview = data.rstrip(b'\0').decode('utf-8')
            if preview and all(char.isprintable() or char in '\r\n\t' for char in preview):
                lines.append('UTF-8: ' + preview)
        except UnicodeDecodeError:
            pass
    if record.get('pm3_log'):
        lines += ['', record['pm3_log']]
    lines.append('')
    for block in record.get('blocks', []):
        data = bytes.fromhex(block['hex'])
        printable = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
        lines.append(f"{block['index']:04d}   {data.hex(' ').upper():<24} {printable}")
    for error in record.get('read_errors', []):
        lines.append(f"{error['index']:04d}   {error.get('kind', 'failed')}: "
                     f"{error.get('error', error.get('reason', '?'))}")
    return '\n'.join(lines)


class NFCWindow(tk.Tk):
    def __init__(self, archive=DEFAULT_ARCHIVE, settings=SETTINGS):
        super().__init__()
        self.title('PT35 NFC Reader')
        self.geometry(f'{min(900, self.winfo_screenwidth())}x{min(630, self.winfo_screenheight() - 60)}')
        self.minsize(440, 330)
        self.archive = archive
        self.settings_path = settings
        self.available_pm3_actions = set()
        self.proc = None
        self.worker = None
        self.events = queue.Queue(maxsize=128)
        self.closing = False
        self.stopping = False
        self.had_fault = False
        self.current = None
        self.live = {}
        self.saved = {}
        self.backend = tk.StringVar(value='auto')
        self.protocol_mode = tk.StringVar(value='ISO15693')
        self.pm3_mode = tk.StringVar(value='HF')
        self.auto_tonie = tk.BooleanVar(value=True)
        self.auto_candidates = tk.BooleanVar(value=False)
        self.save_all = tk.BooleanVar(value=False)
        self.include_st = tk.BooleanVar(value=False)
        self.exclude_uid = tk.StringVar(value=os.environ.get('PT35_NFC_ONBOARD_UID', ''))
        self.blocks = tk.StringVar(value='0')
        self.client = tk.StringVar()
        self.port = tk.StringVar()
        self.query = tk.StringVar()
        self.status = tk.StringVar(value='Ready')
        self.reader = tk.StringVar(value='Reader status unknown')
        self.settings_vars = {
            'backend': self.backend, 'protocol_mode': self.protocol_mode, 'pm3_mode': self.pm3_mode,
            'auto_tonie': self.auto_tonie, 'auto_candidates': self.auto_candidates, 'save_all': self.save_all,
            'include_st': self.include_st, 'exclude_uid': self.exclude_uid, 'blocks': self.blocks,
            'client': self.client, 'port': self.port,
        }
        self._build()
        self.load_settings()
        self.refresh_archive()
        self.after(50, self.drain)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def _build(self):
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill='both', expand=True)
        bar = ttk.Frame(frame)
        bar.pack(fill='x', pady=(0, 6))
        self.buttons = []
        for label, action in (('Start', 'watch'), ('Reader status', 'status')):
            button = ttk.Button(bar, text=label, command=lambda a=action: self.launch(a))
            button.pack(side='left', padx=(0, 4))
            self.buttons.append(button)
        self.stop_button = ttk.Button(bar, text='Stop', state='disabled', command=self.stop)
        self.stop_button.pack(side='left')
        ttk.Label(frame, textvariable=self.reader).pack(fill='x')
        status = ttk.Label(frame, textvariable=self.status, wraplength=410)
        status.pack(fill='x', pady=(0, 4))
        status.bind('<Configure>', lambda event: status.configure(wraplength=event.width))
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill='both', expand=True)
        scan, self.data_tab, archive, proxmark, settings = [
            ttk.Frame(self.tabs, padding=5) for _ in range(5)
        ]
        for pane, title in zip((scan, self.data_tab, archive, proxmark, settings),
                               ('Scan', 'Data', 'Archive', 'Proxmark', 'Settings')):
            self.tabs.add(pane, text=title)
        self.live_tree = self.make_tree(scan, self.live)
        self.log = ScrolledText(scan, height=5, wrap='word', state='disabled')
        self.log.pack(fill='x', pady=(5, 0))
        self.raw = tk.BooleanVar()
        actions = ttk.Frame(self.data_tab)
        actions.pack(fill='x')
        ttk.Button(actions, text='Save tag', command=self.save_current).pack(side='left')
        ttk.Button(actions, text='Export…', command=self.export_current).pack(side='left', padx=4)
        ttk.Checkbutton(actions, text='Raw JSON', variable=self.raw, command=self.render).pack(side='left')
        self.data = ScrolledText(self.data_tab, height=8, wrap='word', state='disabled')
        self.data.pack(fill='both', expand=True, pady=(5, 0))
        search = ttk.Frame(archive)
        search.pack(fill='x', pady=(0, 5))
        ttk.Label(search, text='Search').pack(side='left')
        ttk.Entry(search, textvariable=self.query).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(search, text='Refresh', command=self.refresh_archive).pack(side='right')
        self.archive_tree = self.make_tree(archive, self.saved)
        self.query.trace_add('write', lambda *_: self.populate_archive())
        ttk.Label(proxmark, text='Iceman must respond and match the connected firmware.',
                  wraplength=400).pack(anchor='w')
        identify = ttk.Button(proxmark, text='Identify HF / LF',
                              command=lambda: self.launch('identify', force='proxmark3'))
        identify.pack(anchor='w', pady=6)
        self.buttons.append(identify)
        ttk.Label(proxmark, text='Watch mode').pack(anchor='w')
        ttk.Combobox(proxmark, textvariable=self.pm3_mode, values=PM3_MODES,
                     state='readonly', width=14).pack(anchor='w', pady=(0, 4))
        self.pm3_actions = {}
        for label, action in (('Read selected ISO15693 memory', 'pm3-dump'),
                              ('Simulate saved ISO15693 tag…', 'pm3-simulate')):
            button = ttk.Button(proxmark, text=label, command=lambda a=action: self.pm3_action(a),
                                state='disabled')
            button.pack(anchor='w', pady=(0, 4))
            self.pm3_actions[action] = button
        ttk.Label(proxmark, text='Client path and serial port are configurable in Settings.',
                  wraplength=400).pack(anchor='w')
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text='Backend').grid(row=0, column=0, sticky='w')
        ttk.Combobox(settings, textvariable=self.backend, state='readonly',
                     values=('auto', 'internal', 'proxmark3')).grid(row=0, column=1, sticky='ew')
        ttk.Label(settings, text='Internal protocol').grid(row=1, column=0, sticky='w')
        ttk.Combobox(settings, textvariable=self.protocol_mode, state='readonly',
                     values=('ISO15693', *MODES)).grid(row=1, column=1, sticky='ew')
        for row, (label, var) in enumerate((
                ('Blocks (0 = auto)', self.blocks), ('Onboard ST25DV UID', self.exclude_uid),
                ('Iceman client path', self.client), ('Proxmark3 serial port', self.port)), start=2):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky='w', padx=(0, 6))
            ttk.Entry(settings, textvariable=var).grid(row=row, column=1, sticky='ew')
        for row, (label, var) in enumerate((
                ('Include configured onboard tag', self.include_st), ('Save every tag', self.save_all),
                ('Auto-save known Tonie UIDs', self.auto_tonie),
                ('Also auto-save unverified NXP candidates', self.auto_candidates)), start=6):
            ttk.Checkbutton(settings, text=label, variable=var).grid(row=row, columnspan=2, sticky='w')
        ttk.Button(settings, text='Save settings', command=self.save_settings).grid(row=10, column=0, sticky='w')

    def load_settings(self):
        try:
            values = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if not isinstance(values, dict):
                raise ValueError('Expected a settings object')
            for key, var in self.settings_vars.items():
                value = values.get(key)
                if type(value) is type(var.get()):
                    var.set(value)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.append_log(f'Settings could not be read: {exc}')

    def save_settings(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write(self.settings_path, record_bytes({key: var.get() for key, var in self.settings_vars.items()}))
        except OSError as exc:
            messagebox.showerror('Settings could not be saved', str(exc))
        else:
            self.status.set('Settings saved')

    def update_pm3_actions(self):
        for action, button in self.pm3_actions.items():
            enabled = action in self.available_pm3_actions and self.proc is None
            button.configure(state='normal' if enabled else 'disabled')

    def pm3_action(self, action):
        record = self.current
        if not record or record.get('protocol') != 'ISO15693':
            messagebox.showinfo('Select a tag', 'Select an ISO15693 tag in Scan or Archive.')
            return
        uid = record['uid']
        if action == 'pm3-simulate':
            try:
                saved = json.loads(record_path(self.archive, uid).read_text(encoding='utf-8'))
                simulation_image(saved)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                messagebox.showerror('Saved capture required', str(exc))
                return
            if not messagebox.askyesno(
                    'Confirm experimental simulation',
                    f'Load the saved user memory and simulate {uid} for {SIM_SECONDS} seconds? '
                    'Use a bench tag and reader you are authorized to test. '
                    'Protected configuration and authentication are outside the simulation.'):
                return
        self.tabs.select(0)
        self.launch(action, force='proxmark3', uid=uid)

    def make_tree(self, parent, records):
        columns = ('uid', 'protocol', 'type', 'status')
        tree = ttk.Treeview(parent, columns=columns, show='headings', selectmode='browse', height=5)
        for col, width in zip(columns, (150, 90, 140, 155)):
            tree.heading(col, text=col.capitalize())
            tree.column(col, width=width, minwidth=50)
        scroll = ttk.Scrollbar(parent, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True)
        tree.bind('<<TreeviewSelect>>', lambda _: self.select(tree, records))
        tree.bind('<Double-1>', lambda _: self.tabs.select(self.data_tab))
        tree.bind('<Return>', lambda _: self.tabs.select(self.data_tab))
        return tree

    def select(self, tree, records):
        selected = tree.selection()
        if selected and selected[0] in records:
            self.current = records[selected[0]]
            self.render()

    def render(self):
        if self.current:
            try:
                content = (record_bytes(self.current).decode() if self.raw.get() else format_record(self.current))
            except (KeyError, TypeError, ValueError) as exc:
                content = f'Cannot decode record: {exc}'
            self.data.configure(state='normal')
            self.data.delete('1.0', 'end')
            self.data.insert('end', content)
            self.data.configure(state='disabled')

    def save_current(self):
        if self.current:
            try:
                save_record(self.archive, self.current)
                self.status.set(f"Saved {self.current['uid']}")
                self.refresh_archive()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                messagebox.showerror('Archive save failed', str(exc))

    def export_current(self):
        if not self.current:
            return
        try:
            binary = range_bytes(self.current)
            formats = [('JSON record', '*.json')]
            if binary is not None:
                formats.append(('Verified range binary', '*.bin'))
            target = filedialog.asksaveasfilename(filetypes=formats, defaultextension='.json',
                                                   initialfile=self.current['uid'])
            if target:
                path = Path(target)
                if path.suffix.lower() == '.bin' and binary is None:
                    raise ValueError('This capture has no verified complete binary range')
                atomic_write(path, binary if path.suffix.lower() == '.bin' else record_bytes(self.current))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror('Export failed', str(exc))

    @staticmethod
    def values(record):
        return (record['uid'], record['protocol'], record.get('tonie_status', record.get('manufacturer', '?')),
                record.get('dump_status', '?').replace('_', ' '))

    def refresh_archive(self):
        self.saved.clear()
        for path in sorted(self.archive.glob('*/record.json')):
            try:
                record = json.loads(path.read_text())
                self.values(record)
                self.saved[path.parent.name] = record
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self.append_log(f'Cannot open archive record {path.parent.name}: {exc}')
        self.populate_archive()

    def populate_archive(self):
        self.archive_tree.delete(*self.archive_tree.get_children())
        query = self.query.get().strip().casefold()
        for key, record in self.saved.items():
            if not query or query in json.dumps(record, ensure_ascii=False).casefold():
                self.archive_tree.insert('', 'end', iid=key, values=self.values(record))

    def append_log(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message[-16000:] + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 900:
            self.log.delete('1.0', '301.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def launch(self, action, force=None, uid=None):
        if self.proc is not None or self.closing:
            return
        cmd = [sys.executable, '-u', str(BACKEND_SCRIPT), action]
        if uid:
            cmd.append(uid)
        cmd.extend(('--json-lines', '--backend', force or self.backend.get(), '--archive', str(self.archive),
                    '--blocks', self.blocks.get(), '--protocol', self.protocol_mode.get(),
                    '--pm3-mode', self.pm3_mode.get()))
        if action == 'pm3-simulate':
            cmd.append('--confirm-emulation')
        for flag, value in (('--exclude-uid', self.exclude_uid), ('--client', self.client),
                            ('--port', self.port)):
            if value.get().strip():
                cmd.extend((flag, value.get().strip()))
        for flag, setting in (('--auto-tonie', self.auto_tonie), ('--auto-candidates', self.auto_candidates),
                              ('--save', self.save_all), ('--include-st', self.include_st)):
            if setting.get():
                cmd.append(flag)
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors='replace',
                                         start_new_session=True)
        except OSError as exc:
            self.status.set(f'Cannot start reader: {exc}')
            return
        self.status.set('Connecting…')
        self.had_fault = False
        self.stopping = False
        for button in self.buttons:
            button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.update_pm3_actions()
        self.worker = threading.Thread(target=read_events, args=(self.proc, self.events), daemon=True)
        self.worker.start()

    def drain(self):
        for _ in range(40):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event['event']
            message = event.get('message', '')
            if kind == 'exit':
                self.proc = None
                self.worker.join()
                self.worker = None
                if self.closing:
                    self.destroy()
                    return
                if self.stopping or not self.had_fault:
                    self.status.set(f"Stopped (exit {event['code']})" if event['code'] not in (0, 130) else
                                    'Stopped' if self.stopping else 'Ready')
                self.stop_button.configure(state='disabled')
                for button in self.buttons:
                    button.configure(state='normal')
                self.update_pm3_actions()
                continue
            if kind == 'tag':
                record = event['record']
                key = f"{record['protocol']}:{record['uid']}"
                if self.live_tree.exists(key):
                    self.live_tree.item(key, values=self.values(record))
                else:
                    if len(self.live) >= 256:
                        old = next(iter(self.live))
                        del self.live[old]
                        self.live_tree.delete(old)
                    self.live_tree.insert('', 0, iid=key, values=self.values(record))
                self.live[key] = record
                if not self.live_tree.selection() or key in self.live_tree.selection():
                    self.live_tree.selection_set(key)
                    self.select(self.live_tree, self.live)
            elif kind == 'archived':
                self.refresh_archive()
            elif kind == 'backend':
                self.reader.set(message)
                self.available_pm3_actions = set(event.get('pm3_actions', []))
                self.append_log('Capabilities: ' + ', '.join(event.get('capabilities', [])))
            elif kind == 'fault':
                self.had_fault = True
                if event.get('backend') == 'proxmark3':
                    self.available_pm3_actions = set()
                    self.reader.set('Proxmark3 unavailable')
            if kind in ('backend', 'fault', 'scan_state', 'tag') and not self.stopping:
                self.status.set(message)
            if kind != 'scan_state':
                self.append_log(message)
        self.after(50, self.drain)

    def signal_worker(self, proc, signum):
        if self.proc is proc:
            try:
                os.killpg(proc.pid, signum)
            except ProcessLookupError:
                pass

    def stop(self):
        if self.proc is None or self.stopping:
            return
        self.stopping = True
        self.status.set('Stopping…')
        self.stop_button.configure(state='disabled')
        proc = self.proc
        self.signal_worker(proc, signal.SIGINT)
        self.after(3500, self.signal_worker, proc, signal.SIGTERM)
        self.after(5000, self.signal_worker, proc, signal.SIGKILL)

    def close(self):
        self.closing = True
        if self.proc is None:
            self.destroy()
        else:
            self.stop()


def main():
    try:
        window = NFCWindow()
    except tk.TclError as exc:
        raise SystemExit(f'Launch PT35 NFC from the graphical desktop: {exc}') from exc
    window.after_idle(window.launch, 'status')
    window.mainloop()


if __name__ == '__main__':
    main()
