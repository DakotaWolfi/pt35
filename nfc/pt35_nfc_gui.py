#!/usr/bin/env python3
"""PT35 NFC reader and archive for touch navigation and keyboard input."""
import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from nfc_archive import atomic_write, range_bytes, record_bytes, record_path, save_record
from nfc_config import DEFAULT_ARCHIVE
from nfc_diagnostics import Diagnostics
from nfc_led import NFCLeds
from nfc_ndef import decode_message, extract_message, ndef_area
from nfc_pm3 import SIM_SECONDS, simulation_eligibility, simulation_image, em410x_eligibility
from nfc_tonies import scan_archive as index_tonie_archive, shareable_catalog as share_tonie_catalog, export_teddy_custom, catalog_path as tonie_catalog_path
from nfc_touch import FONT, LARGE, MONO, SMALL, THEMES, Button, ScrollArea, font_for, label, row, touch_size

BACKEND_SCRIPT = Path(__file__).resolve().with_name('pt35_nfc.py')
SETTINGS = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'pt35-nfc' / 'settings.json'
PROTOCOLS = {'auto': 'Auto', 'ISO15693': 'NFC-V', 'NFC-A': 'NFC-A', 'NFC-B': 'NFC-B', 'NFC-F': 'NFC-F'}
BACKENDS = {'auto': 'Auto', 'internal': 'Internal', 'proxmark3': 'Proxmark3'}
PAGE_SIZE = 24
DEFAULTS = dict(backend='auto', protocol_mode='auto', pm3_mode='HF', blocks='0',
                include_st=False, exclude_uid=os.environ.get('PT35_NFC_ONBOARD_UID', ''),
                auto_tonie=True, auto_candidates=False, save_all=False, client='', port='', theme='dark',
                led_enabled=False, led_effect='sweep', led_brightness='12')


def write_local(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(path, data)
    return path


def load_settings(path):
    values = dict(DEFAULTS)
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return values
    if not isinstance(stored, dict):
        raise ValueError('Settings must be a JSON object')
    values = {**stored, **values}
    for key, default in DEFAULTS.items():
        value = stored.get(key)
        if type(value) is type(default):
            values[key] = value
    for key, options in (('backend', BACKENDS), ('protocol_mode', PROTOCOLS),
                         ('pm3_mode', ('HF', 'LF', 'ISO15693')), ('theme', THEMES),
                         ('led_effect', ('sweep', 'pulse', 'minimal'))):
        if values[key] not in options:
            values[key] = DEFAULTS[key]
    if not re.fullmatch(r'-1|[0-9]{1,4}', values['blocks']) or int(values['blocks']) > 2048:
        values['blocks'] = '0'
    if not re.fullmatch(r'[0-9]{1,2}', values['led_brightness']) or not 1 <= int(values['led_brightness']) <= 32:
        values['led_brightness'] = DEFAULTS['led_brightness']
    if values['exclude_uid'] and not re.fullmatch(r'E002[0-9A-F]{12}', values['exclude_uid'], re.I):
        values['exclude_uid'] = ''
    return values


def read_archive(archive):
    records = []
    for path in archive.glob('*/record.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(record['uid'], str) and isinstance(record['protocol'], str):
                records.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(records, key=lambda item: str(item.get('last_seen_utc') or ''), reverse=True)


def coverage(record):
    geometry = record.get('geometry') or {}
    requested = record.get('requested_range') or {}
    readable = len(record.get('blocks') or [])
    if not requested:
        if record.get('read_capability') == 'discovery_only':
            return 'Tag identified · discovery only'
        return f'{readable} readable blocks' if readable else 'Tag identified'
    status = {'addressable_memory_complete': 'Full memory', 'requested_range_complete': 'Range complete',
              'partial': 'Partial read', 'failed': 'Read failed'}.get(record.get('dump_status'), 'Captured')
    total = f" · {geometry['blocks']} on tag" if geometry else ' · size unknown'
    return f"{status} · {readable}/{requested['count']} blocks{total}"


def summary(record):
    result = [f"{record.get('manufacturer', 'Unknown maker')} · {record.get('backend', '?')}", coverage(record)]
    if record.get('chip'):
        result.append(record['chip'])
    result.append('Classification: ' + str(record.get('classification', 'unknown')))
    if record.get('last_comparison'):
        result.append('Previous scan comparison: ' + str(record['last_comparison']).replace('_', ' '))
    if record.get('scan_count'):
        result.append(f"Scans recorded: {record['scan_count']}")
    geometry = record.get('geometry')
    if geometry:
        result.append(f"{geometry['blocks']} blocks × {geometry['size']} bytes · {geometry.get('source', 'reported size')}")
    for key in ('error', 'extended_error'):
        if (problem := (record.get('system_info') or {}).get(key)):
            result.append(f"System Information · {problem['error']}")
    for err in (record.get('read_errors') or [])[:4]:
        result.append(f"Block {err.get('index', '?')} · {err.get('error', err.get('kind', 'unreadable'))}")
    data = range_bytes(record)
    if data is not None:
        message = extract_message(ndef_area(record, data))
        if message is not None:
            result.extend(decode_message(message) or ['NDEF message present'])
    return '\n\n'.join(result)


class ScanWorker:
    """One RF process group. Launch and pipe reads stay off the Tk thread."""
    def __init__(self, command, events):
        self.events = events
        self.process = None
        self.pending_signal = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, args=(command,), daemon=True)

    def start(self):
        self.thread.start()

    def send_signal(self, signum):
        with self.lock:
            if self.process is None:
                self.pending_signal = signum
            else:
                self.signal_group(signum)

    def signal_group(self, signum):
        try:
            os.killpg(self.process.pid, signum)
        except ProcessLookupError:
            pass

    def run(self, command):
        code = 2
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors='replace',
                                    start_new_session=True)
            with self.lock:
                self.process = proc
                if self.pending_signal is not None:
                    self.signal_group(self.pending_signal)
            with proc.stdout:
                for line in proc.stdout:
                    try:
                        item = json.loads(line)
                        if not isinstance(item, dict) or 'event' not in item:
                            raise ValueError
                    except ValueError:
                        item = {'event': 'log', 'message': line.strip()}
                    self.events.put(item)
            code = proc.wait()
        except OSError as exc:
            self.events.put({'event': 'fault', 'message': str(exc)})
            if self.process is not None:
                self.send_signal(signal.SIGTERM)
                code = self.process.wait()
        finally:
            self.events.put({'event': 'exit', 'code': code})


class NFCWindow(tk.Tk):
    def __init__(self, archive=DEFAULT_ARCHIVE, settings=SETTINGS, *, fullscreen=True):
        super().__init__()
        self.title('PT35 NFC Reader')
        self.palette = THEMES['dark']
        self.configure(bg=self.palette.background)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{min(1100, screen_width)}x{min(700, screen_height)}')
        self.minsize(min(480, screen_width), min(320, screen_height))
        self.ui_scale = 1
        self.ui_fonts = {}
        self.attributes('-fullscreen', fullscreen)
        self.archive = Path(archive)
        self.settings_path = Path(settings)
        self.exports = self.archive.parent / 'exports'
        self.settings = dict(DEFAULTS)
        self.draft = None
        self.ready = False
        self.worker = None
        self.led = None
        self.led_operation = False
        self.read_progress = None
        self.stopping = False
        self.closing = False
        self.had_fault = False
        self.available_pm3_actions = set()
        self.pm3_simulation_capability = 'Check Iceman connection before starting emulation'
        self.events = queue.Queue(maxsize=128)
        self.io = ThreadPoolExecutor(max_workers=1, thread_name_prefix='nfc-files')
        self.tasks = {}
        self.rf = Diagnostics()
        self.last_rf_bits = None
        self.pm3_log = ''
        self.newest = self.current = self.latest_st = None
        self.saved = []
        self.query = ''
        self.archive_page = 0
        self.archive_dirty = True
        self.status = tk.StringVar(self, value='Loading settings…')
        self.reader = tk.StringVar(self, value='Ready to scan')
        self.reader_backend = None
        self.pm3_status = tk.StringVar(self)
        self.led_status = tk.StringVar(self)
        self.notice = tk.StringVar(self)
        self.layout = tk.Frame(self, bg=self.palette.background)
        self.layout.pack(fill='both', expand=True)
        self.home()
        self.submit('load settings', lambda: load_settings(self.settings_path), self.loaded)
        self.after(40, self.drain)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Configure>', self.resize_ui, add='+')

    def resize_ui(self, event):
        if event.widget is not self:
            return
        scale = max(1, min(1.8, event.width / 640, event.height / 480))
        if abs(scale - self.ui_scale) < .04:
            return
        self.ui_scale = scale
        for spec, font in self.ui_fonts.items():
            font.configure(size=round(spec[1] * scale))
        pending = [self.layout]
        while pending:
            widget = pending.pop()
            if isinstance(widget, Button):
                widget.configure(pady=touch_size(widget, 15))
            elif isinstance(widget, ScrollArea):
                widget.scrollbar.configure(width=touch_size(widget, 44))
            pending.extend(widget.winfo_children())

    def loaded(self, values):
        self.settings = values or dict(DEFAULTS)
        self.ready = True
        self.status.set('Ready · tap Start scan')
        if self.screen == 'home':
            self.home()

    def submit(self, key, work, done=lambda _: None):
        if key not in self.tasks and not self.closing:
            self.tasks[key] = self.io.submit(work), done

    def page(self, title, back=None, *, scroll=True, footer=()):
        for widget in self.layout.winfo_children():
            widget.destroy()
        self.notice.set('')
        self.palette = THEMES[(self.draft if self.draft is not None else self.settings)['theme']]
        self.configure(bg=self.palette.background)
        self.layout.configure(bg=self.palette.background)
        header = tk.Frame(self.layout, bg=self.palette.background)
        header.pack(fill='x', padx=10, pady=(6, 2))
        if back:
            Button(header, '‹ Back', back, width=7).pack(side='left', padx=(0, 10))
        else:
            Button(header, 'Exit', self.close, width=6).pack(side='right')
        self.header_stop = None
        if back:
            self.header_stop = Button(header, 'Stop scan', self.stop)
            self.update_header_stop()
        label(header, title, font=LARGE).pack(side='left', fill='x', expand=True)
        if footer:
            row(self.layout, footer).pack(side='bottom', fill='x', padx=10, pady=(4, 8))
        notice = label(self.layout, textvariable=self.notice, font=SMALL, muted=True)
        notice.pack(side='bottom', fill='x', padx=12)
        notice.bind('<Configure>', lambda e: notice.configure(wraplength=e.width))
        if scroll:
            self.scroll = ScrollArea(self.layout)
            self.scroll.pack(fill='both', expand=True, padx=10)
            self.body = self.scroll.content
        else:
            self.scroll = None
            self.body = tk.Frame(self.layout, bg=self.palette.background)
            self.body.pack(fill='both', expand=True, padx=10)
        return self.body

    def update_header_stop(self):
        if self.header_stop:
            if self.worker and not self.header_stop.winfo_manager():
                self.header_stop.pack(side='right')
            elif not self.worker and self.header_stop.winfo_manager():
                self.header_stop.pack_forget()
            self.header_stop.configure(state='disabled' if self.stopping else 'normal')

    def wrap(self, parent, text='', **kwargs):
        widget = label(parent, text, **kwargs)
        widget.pack(fill='x', pady=(2, 5))
        widget.bind('<Configure>', lambda e: widget.configure(wraplength=max(40, e.width - 4)))
        return widget

    def finish_page(self, position=0):
        if self.scroll:
            scroll = self.scroll
            scroll.enable_swipe()
            if position:
                self.after_idle(lambda: scroll.winfo_exists() and scroll.canvas.yview_moveto(position))

    def scroll_position(self):
        return self.scroll.canvas.yview()[0] if self.scroll else 0

    def home(self):
        self.draft = None
        self.screen = 'home'
        body = self.page('PT35 NFC', footer=(
            ('Archive', self.open_archive, {}), ('Settings', self.open_settings, {'state': 'normal' if self.ready else 'disabled'}),
            ('Tools', self.tools, {})))
        self.wrap(body, textvariable=self.reader, font=LARGE)
        self.wrap(body, textvariable=self.status, muted=True)
        self.wrap(body, textvariable=self.pm3_status, muted=True, font=SMALL)
        self.wrap(body, textvariable=self.led_status, muted=True, font=SMALL)
        self.scan_button = Button(body, '', self.toggle_scan, primary=True)
        self.scan_button.pack(fill='x', pady=(7, 10))
        self.sync_scan()
        self.wrap(body, 'LATEST TAG', font=SMALL, muted=True)
        self.latest = Button(body, '', self.open_latest, lines=2, anchor='w')
        self.latest.pack(fill='x')
        self.update_latest()
        self.finish_page()

    def update_latest(self):
        if self.screen != 'home':
            return
        if self.newest:
            item = self.newest
            self.latest.configure(text=f"{PROTOCOLS.get(item['protocol'], item['protocol'])}  {item['uid']}\n{coverage(item)}",
                                  state='normal')
        else:
            self.latest.configure(text='No tag captured yet\nHold one tag against the antenna', state='disabled')

    def sync_scan(self):
        if self.screen == 'home':
            self.scan_button.configure(text='Stopping…' if self.stopping else 'Stop scan' if self.worker else 'Start scan',
                                       state='normal' if self.ready and not self.stopping else 'disabled')
        self.update_header_stop()

    def open_latest(self):
        if self.newest:
            self.current = self.newest
            self.detail(self.home)

    def open_settings(self):
        self.draft = dict(self.settings)
        self.show_settings()

    def show_settings(self, position=0):
        self.screen = 'settings'
        body = self.page('Settings', self.home, footer=(('Save settings', self.save_settings, {'primary': True}),))
        self.wrap(body, 'Changes apply to the next scan.', muted=True)
        self.options(body, 'Reader backend', 'backend', BACKENDS)
        self.options(body, 'Internal protocol', 'protocol_mode', PROTOCOLS)
        self.options(body, 'NFC-V block count', 'blocks', {'0': 'Auto', '8': '8', '32': '32', '-1': 'All known'})
        block_value = self.draft['blocks']
        self.setting_edit(body, 'Custom block count', 'blocks',
                          {'0': 'Auto', '-1': 'All known'}.get(block_value, block_value))
        self.options(body, 'Proxmark watch mode', 'pm3_mode', {'HF': 'HF', 'LF': 'LF', 'ISO15693': 'NFC-V'})
        for title, key in (('Include onboard ST25DV', 'include_st'), ('Save all tags', 'save_all'),
                           ('Auto-save known Tonies', 'auto_tonie'), ('Auto-save unverified NXP tags', 'auto_candidates')):
            enabled = self.draft[key]
            Button(body, f"{title}   {'ON' if enabled else 'OFF'}", lambda k=key: self.change(k, not self.draft[k]),
                   selected=enabled, anchor='w').pack(fill='x', pady=3)
        self.setting_edit(body, 'Onboard ST25DV UID', 'exclude_uid')
        if self.latest_st:
            Button(body, 'Use latest ST tag as onboard UID', lambda: self.change('exclude_uid', self.latest_st)).pack(fill='x', pady=3)
        self.setting_edit(body, 'Iceman client path', 'client')
        self.setting_edit(body, 'Proxmark serial port', 'port')
        self.options(body, 'Appearance', 'theme', {'dark': 'Dark', 'light': 'Light'})
        enabled = self.draft['led_enabled']
        Button(body, f"NFC LED effects   {'ON' if enabled else 'OFF'}",
               lambda: self.change('led_enabled', not enabled), selected=enabled, anchor='w').pack(fill='x', pady=3)
        self.options(body, 'LED search effect', 'led_effect',
                     {'sweep': 'Sweep', 'pulse': 'Pulse', 'minimal': 'Minimal'})
        self.setting_edit(body, 'LED brightness', 'led_brightness')
        self.finish_page(position)

    def options(self, parent, title, key, choices):
        self.wrap(parent, title, muted=True)
        row(parent, [(name, lambda v=value: self.change(key, v), {'selected': self.draft[key] == value})
                     for value, name in choices.items()]).pack(fill='x', pady=(0, 6))

    def change(self, key, value):
        position = self.scroll_position()
        self.draft[key] = value
        self.show_settings(position)

    def setting_edit(self, parent, title, key, display=None):
        value = self.draft[key]
        display = display or value or 'Automatic / unset'
        if len(display) > 40:
            display = '…' + display[-39:]
        Button(parent, f'{title}\n{display}', lambda: self.edit_setting(title, key),
               lines=2, anchor='w').pack(fill='x', pady=3)

    def edit_setting(self, title, key):
        position = self.scroll_position()
        initial = self.draft[key]
        hint = None
        if key == 'blocks':
            hint = 'Enter 0–2048. Zero selects Auto.'
            if initial == '-1':
                initial = ''
        elif key == 'led_brightness':
            hint = 'Enter a dim brightness from 1 to 32.'
        elif key == 'exclude_uid':
            hint = 'Enter the 16-digit ST UID beginning E002, or clear it.'

        def apply(value):
            value = value.strip()
            if key == 'blocks':
                if not re.fullmatch(r'[0-9]{1,4}', value) or int(value) > 2048:
                    return hint
                value = str(int(value))
            elif key == 'led_brightness':
                if not re.fullmatch(r'[0-9]{1,2}', value) or not 1 <= int(value) <= 32:
                    return hint
                value = str(int(value))
            elif key == 'exclude_uid':
                if value and not re.fullmatch(r'E002[0-9A-F]{12}', value, re.I):
                    return hint
                value = value.upper()
            self.draft[key] = value
            self.show_settings(position)
            return None

        self.edit_field(title, initial, apply, lambda: self.show_settings(position), hint=hint)

    def save_settings(self):
        snapshot = dict(self.draft)
        self.submit('save settings', lambda: write_local(self.settings_path, record_bytes(snapshot)),
                    lambda path: self.settings_saved(snapshot, path))

    def settings_saved(self, snapshot, path):
        if path:
            led_changed = any(self.settings[key] != snapshot[key]
                              for key in ('led_enabled', 'led_effect', 'led_brightness'))
            self.settings = snapshot
            if led_changed:
                self.apply_led_settings()
            self.notice.set('Settings saved')

    def edit_field(self, title, initial, apply, cancel, *, hint=None):
        self.screen = 'editor'

        def clear():
            entry.delete(0, 'end')
            entry.focus_set()

        def done(_event=None):
            error = apply(entry.get())
            if error:
                self.notice.set(error)
                entry.focus_set()
            return 'break'

        def cancel_edit(_event=None):
            cancel()
            return 'break'

        body = self.page(title, cancel_edit, scroll=False,
                         footer=(('Clear', clear, {}), ('Done', done, {'primary': True})))
        palette = self.palette
        entry = tk.Entry(body, font=font_for(body, FONT), bg=palette.panel, fg=palette.text,
                         insertbackground=palette.text, selectbackground=palette.accent,
                         selectforeground=palette.accent_text, highlightbackground=palette.border,
                         highlightcolor=palette.border, highlightthickness=2, relief='flat')
        entry.pack(fill='x', ipady=12, pady=(12, 6))
        entry.insert(0, initial)
        entry.selection_range(0, 'end')
        entry.bind('<Return>', done)
        entry.bind('<KP_Enter>', done)
        entry.bind('<Escape>', cancel_edit)
        self.wrap(body, 'Type on the built-in keyboard. Enter confirms · Esc cancels.', muted=True)
        if hint:
            self.wrap(body, hint, muted=True)
        self.after_idle(lambda: entry.winfo_exists() and entry.focus_set())

    def open_archive(self):
        self.archive_view()
        if self.archive_dirty:
            self.submit('read archive', lambda: read_archive(self.archive), self.archive_loaded)

    def archive_loaded(self, records):
        if records is not None:
            self.saved = records
            self.archive_dirty = False
            if self.screen == 'archive':
                self.archive_view(self.scroll_position())

    def archive_view(self, position=0):
        self.screen = 'archive'
        query = self.query.casefold()
        matches = [record for record in self.saved if not query or query in ' '.join(
            str(record.get(key, '')) for key in ('uid', 'protocol', 'manufacturer', 'labels', 'tonie_status', 'classification')).casefold()
            or query == PROTOCOLS.get(record['protocol'], '').casefold()]
        self.archive_page = min(self.archive_page, max(0, (len(matches) - 1) // PAGE_SIZE))
        offset = self.archive_page * PAGE_SIZE
        pages = []
        if offset:
            pages.append(('‹ Previous', lambda: self.move_archive(-1), {}))
        if offset + PAGE_SIZE < len(matches):
            pages.append(('Next ›', lambda: self.move_archive(1), {}))
        body = self.page('Archive', self.home, footer=pages)
        row(body, [('Search tags', self.search_archive, {'primary': True}),
                   ('Clear search', lambda: self.set_search(''), {'state': 'normal' if query else 'disabled'}),
                   ('Refresh', self.reload_archive, {})]).pack(fill='x', pady=(1, 6))
        if query:
            self.wrap(body, f'Search: {self.query}', muted=True)
        self.wrap(body, f'{len(matches)} matching tags' if self.saved else
                  'Loading archive…' if self.archive_dirty else 'Archive is empty', muted=True)
        for record in matches[offset:offset + PAGE_SIZE]:
            title = f"{PROTOCOLS.get(record['protocol'], record['protocol'])}   {record['uid']}"
            try:
                subtitle = coverage(record)
            except (TypeError, KeyError):
                subtitle = 'Open saved record'
            Button(body, title + '\n' + subtitle, lambda item=record: self.open_saved(item),
                   lines=2, anchor='w').pack(fill='x', pady=(0, 5))
        self.finish_page(position)

    def reload_archive(self):
        self.archive_dirty = True
        self.open_archive()

    def move_archive(self, delta):
        self.archive_page += delta
        self.archive_view()

    def set_search(self, query):
        self.query = query.strip()
        self.archive_page = 0
        self.archive_view()

    def search_archive(self):
        self.edit_field('Search archive', self.query, self.set_search, self.open_archive)

    def open_saved(self, record):
        position = self.scroll_position()
        self.current = record
        self.detail(lambda: self.archive_view(position), saved=True)

    def detail(self, back, saved=False):
        self.screen = 'detail'
        record = self.current
        protocol = PROTOCOLS.get(record['protocol'], record['protocol'])
        footer = (('Save tag', self.save_tag, {'primary': True}), ('Export', lambda: self.export_screen(back, saved), {}),
                  ('Hex / data', lambda: self.hex_view(back, saved), {}))
        body = self.page(f'{protocol} tag', back, footer=footer)
        self.wrap(body, record['uid'], font=LARGE)
        try:
            text = summary(record)
        except (ValueError, KeyError, TypeError) as exc:
            text = f'Record summary unavailable · {exc}'
        self.wrap(body, text, muted=True)
        Button(body, 'Scan history / compare captures', lambda: self.open_capture_history(back),
               anchor='w').pack(fill='x', pady=4)
        if record.get('pm3_log'):
            Button(body, 'Show local Iceman output', lambda: self.log_view(
                record['pm3_log'], lambda: self.detail(back, saved))).pack(fill='x')
        self.finish_page()

    def open_capture_history(self, back):
        original = self.current
        def load():
            path = record_path(self.archive, original['uid'], original['protocol'])
            saved = json.loads(path.read_text(encoding='utf-8'))
            return saved.get('capture_history') or []
        self.submit('read capture history', load,
                    lambda entries: self.capture_history_view(back, original, entries))

    def capture_history_view(self, back, original, entries):
        self.screen = 'history'
        body = self.page('Scan history', lambda: self.restore_detail(original, back))
        self.wrap(body, f"{original['protocol']} · {original['uid']}", muted=True)
        self.wrap(body, 'Every distinct scan is saved locally. Partial or conflicting reads do not replace confirmed data.',
                  muted=True)
        for entry in reversed(entries[-150:]):
            label_text = (str(entry.get('at', '?'))[:19] + ' · ' +
                          str(entry.get('comparison', 'unknown')).replace('_', ' ') +
                          '\n' + str(entry.get('status', '?')) + ' · ' +
                          str(entry.get('blocks', 0)) + ' blocks · ' +
                          str(entry.get('classification', 'unknown')))
            Button(body, label_text,
                   lambda e=entry: self.open_snapshot(original, back, e),
                   lines=2, anchor='w').pack(fill='x', pady=3)
        if not entries:
            self.wrap(body, 'No recorded scans yet. Scan the tag again or save it to the archive.')
        self.finish_page()

    def restore_detail(self, record, back):
        self.current = record
        self.detail(back, saved=True)

    def open_snapshot(self, original, back, entry):
        digest = entry.get('id') or ''
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            self.notice.set('Invalid capture history reference')
            return
        def load():
            folder = record_path(self.archive, original['uid'], original['protocol']).parent
            return json.loads((folder / 'captures' / (digest + '.json')).read_text(encoding='utf-8'))
        def done(snapshot):
            if snapshot:
                self.current = snapshot
                self.detail(lambda: self.open_capture_history_for(original, back), saved=True)
        self.submit('open saved capture', load, done)

    def open_capture_history_for(self, original, back):
        self.current = original
        self.open_capture_history(back)

    def hex_view(self, back, saved, offset=0):
        self.screen = 'hex'
        record = self.current
        blocks = record.get('blocks') or []
        width = 24
        footer = []
        if offset:
            footer.append(('‹ Previous blocks', lambda: self.hex_view(back, saved, offset - width), {}))
        if offset + width < len(blocks):
            footer.append(('Next blocks ›', lambda: self.hex_view(back, saved, offset + width), {}))
        body = self.page('Tag memory', lambda: self.detail(back, saved), footer=footer)
        self.wrap(body, coverage(record), muted=True)
        if not blocks:
            self.wrap(body, 'No memory blocks captured.')
        for block in blocks[offset:offset + width]:
            try:
                data = bytes.fromhex(block['hex'])
                printable = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
                self.wrap(body, f"{block['index']:04d}  {data.hex(' ').upper()}   {printable}", font=MONO)
            except (KeyError, TypeError, ValueError):
                self.wrap(body, 'Invalid saved block', muted=True)
        self.finish_page()

    def save_tag(self):
        record = self.current
        def saved(path):
            if path:
                self.archive_dirty = True
                self.notice.set('Tag saved to the archive')
        self.submit('save tag', lambda: save_record(self.archive, record), saved)

    def export_screen(self, back, saved):
        self.screen = 'export'
        record = self.current
        body = self.page('Export tag', lambda: self.detail(back, saved))
        self.wrap(body, f'Files are saved in {self.exports}', muted=True)
        Button(body, 'Export JSON record', lambda: self.export_tag(record, False), primary=True).pack(fill='x', pady=4)
        try:
            binary = range_bytes(record)
        except (ValueError, KeyError, TypeError):
            binary = None
        Button(body, 'Export verified binary range', lambda: self.export_tag(record, True),
               state='normal' if binary is not None else 'disabled').pack(fill='x', pady=4)
        if binary is None:
            self.wrap(body, 'Binary export requires a complete verified range.', muted=True)
        self.finish_page()

    def export_tag(self, record, binary):
        def work():
            uid = record['uid']
            if not re.fullmatch(r'[0-9a-fA-F]{2,64}', uid):
                raise ValueError('Invalid identifier in the archive record')
            data = range_bytes(record) if binary else record_bytes(record)
            if data is None:
                raise ValueError('Binary export requires a complete verified range')
            return self.write_export('tag-' + uid, 'bin' if binary else 'json', data)
        self.submit('export tag', work, self.exported)

    def write_export(self, prefix, suffix, data):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        return write_local(self.exports / f'{prefix}-{stamp}.{suffix}', data)

    def exported(self, path):
        if path:
            self.notice.set(f'Saved {path.name}')

    def tools(self):
        self.screen = 'tools'
        body = self.page('Tools', self.home)
        for title, action in (('RF diagnostics', self.diagnostics), ('Proxmark3', self.pm3),
                              ('PM3 · Emulation', self.emulation_menu),
                              ('Possible Tonies catalog', self.tonies_tool),
                              ('Reader status', lambda: self.launch('status')),
                              ('Toggle full screen', self.toggle_fullscreen)):
            Button(body, title, action, anchor='w').pack(fill='x', pady=4)
        self.finish_page()

    def tonies_tool(self):
        self.screen = 'tonies'
        body = self.page('Possible Tonies', self.tools)
        path = tonie_catalog_path(self.archive)
        self.wrap(body, 'NXP ISO15693 UIDs are candidates only, not confirmed '
                  'Tonies. A confirmed UID from known_tonies.txt is marked separately.',
                  muted=True)
        self.wrap(body, 'Local catalog: ' + str(path), font=SMALL, muted=True)
        self.wrap(body, 'A live scan already updates this file automatically '
                  'after the archive is saved. Existing records can be indexed below.',
                  muted=True)
        Button(body, 'Scan saved NFC archives', self.tonies_reindex,
               anchor='w').pack(fill='x', pady=5)
        self.wrap(body, 'Review before sharing: even a UID can identify a physical '
                  'tag. Share export omits memory, audio, timestamps and reader logs.',
                  muted=True)
        Button(body, 'Export candidate UIDs (metadata only)',
               self.tonies_share_confirm, anchor='w').pack(fill='x', pady=5)
        self.wrap(body, 'TeddyCloud tonies.custom.json maps model numbers to '
                  'audio IDs and hashes, not raw NFC UIDs. Only records enriched '
                  'with verified metadata can be exported in that format.',
                  muted=True)
        Button(body, 'Export verified TeddyCloud metadata',
               self.tonies_export_custom, anchor='w').pack(fill='x', pady=5)
        self.wrap(body, 'Files are saved under the NFC archive or adjacent exports '
                  'folder; TeddyCloud is not modified or contacted.', muted=True)
        self.finish_page()

    def tonies_reindex(self):
        def done(summary):
            self.notice.set(f"Indexed {summary['scanned']} archives · "
                            f"{summary['candidates']} candidates · "
                            f"{summary['changed']} additions/updates · "
                            f"{summary['invalid']} invalid files")
        self.submit('index possible tonies', lambda: index_tonie_archive(self.archive), done)

    def tonies_share_confirm(self):
        if not messagebox.askyesno(
            'Share candidate UIDs?',
            'Export candidate NFC UIDs and limited evidence only?\\n\\n'
            'Tag UIDs may identify a physical object or be reusable in simple '
            'identifier-based systems. The output does NOT contain audio or '
            'NFC memory. Review the file before publishing.',
            parent=self):
            return
        def work():
            index_tonie_archive(self.archive)
            return share_tonie_catalog(self.archive,
                self.exports / 'possible_tonies-share.json')
        self.submit('export possible tonies', work,
                    lambda output: self.notice.set(
                        f'Exported {output[1]} entries to {output[0]}'))

    def tonies_export_custom(self):
        def work():
            index_tonie_archive(self.archive)
            return export_teddy_custom(self.archive,
                self.exports / 'tonies.custom.json')
        self.submit('export TeddyCloud metadata', work,
                    lambda output: self.notice.set(
                        f'Exported {output[1]} verified TeddyCloud entries to {output[0]}. '
                        'An empty [] means no model/audio mappings were supplied.'))

    def toggle_fullscreen(self):
        self.attributes('-fullscreen', not self.attributes('-fullscreen'))

    def diagnostics(self):
        self.screen = 'diagnostics'
        body = self.page('RF diagnostics', self.tools,
                         footer=(('Refresh counts', self.diagnostics, {}),
                                 ('Export redacted log', self.export_diagnostics, {'primary': True})))
        self.wrap(body, 'Only RF metadata is exported. Tag identifiers and memory are omitted.', muted=True)
        if self.last_rf_bits is not None:
            self.wrap(body, f'Last shutdown RF bits: 0x{self.last_rf_bits:02X}', font=LARGE)
        if not self.rf.counts:
            self.wrap(body, 'No internal reader events collected this session.')
        for key, count in sorted(self.rf.counts.items()):
            self.wrap(body, f"{key.replace('_', ' ')}   {count}")
        self.finish_page()

    def export_diagnostics(self):
        report = self.rf.export()
        self.submit('export RF log', lambda: self.write_export('nfc-v-diagnostics', 'json', record_bytes(report)),
                    self.exported)

    def pm3(self):
        self.screen = 'pm3'
        body = self.page('Proxmark3', self.tools)
        self.wrap(body, textvariable=self.pm3_status, muted=True)
        self.wrap(body, 'HF discovers multiple NFC types. Use LF mode for LF tags.', muted=True)
        self.wrap(body, textvariable=self.status, muted=True)
        enabled = 'disabled' if self.worker else 'normal'
        target = self.current or self.newest
        iso_v = bool(target and target.get('protocol') == 'ISO15693')
        self.wrap(body, f"Selected tag: {target['uid']}" if iso_v else
                  'Open an ISO15693 tag to select it.', muted=True)
        for title, action, state in (
            ('Check Iceman connection', lambda: self.launch('status', 'proxmark3'), enabled),
            ('Identify HF / LF', lambda: self.launch('identify', 'proxmark3'), enabled),
            ('Read selected NFC-V tag', lambda: self.launch('pm3-dump', 'proxmark3', target['uid']),
             enabled if iso_v and 'pm3-dump' in self.available_pm3_actions else 'disabled'),
            ('Emulation · saved tags', self.emulation_menu, enabled),
            ('View last Iceman output', lambda: self.log_view(self.pm3_log, self.pm3),
             'normal' if self.pm3_log else 'disabled'),
        ):
            Button(body, title, action, state=state, anchor='w').pack(fill='x', pady=4)
        self.finish_page()

    def emulation_menu(self):
        """A dedicated, non-RF page for browsing safely emulatable local captures."""
        self.screen = 'emulation'
        body = self.page('Emulation · PM3 / Internal', self.pm3, footer=(
            ('Refresh archive', self.reload_emulation_archive, {}),
            ('Check PM3', lambda: self.launch('status', 'proxmark3'),
             {'state': 'disabled' if self.worker else 'normal'})))
        self.wrap(body, 'Proxmark3: ISO15693 / SLIX-L and fixed-ID LF EM410x.',
                  font=FONT)
        self.wrap(body, 'Internal ST25R3916: NFC-A/F target hardware, but no tested '
                  'PT35 target-mode driver yet. NFC-V uses the separate ST25DV I²C tag.',
                  muted=True)
        self.wrap(body, 'NFC-A NTAG/Ultralight full emulation requires original '
                  'manufacturer/configuration pages absent from current captures. '
                  'NFC-B and other protocols are not offered as clones.', muted=True)
        self.wrap(body, f'Maximum {SIM_SECONDS} seconds per run · Stop or PM3 button aborts.',
                  muted=True)
        if 'pm3-simulate' not in self.available_pm3_actions:
            self.wrap(body, self.pm3_simulation_capability, muted=True)
            self.wrap(body, 'A firmware revision difference is advisory, not an emulation '
                      'blocker. Simulation requires a verified hardware ping plus supported '
                      'Iceman ISO15693 eload/sim commands.', muted=True)
        else:
            self.wrap(body, 'Iceman ISO15693 emulation commands advertised.',
                      muted=True)
        self.wrap(body, textvariable=self.pm3_status, muted=True)
        self.wrap(body, textvariable=self.status, muted=True)
        self.wrap(body, 'Verified saved ISO15693 captures', font=FONT)
        if self.archive_dirty:
            self.wrap(body, 'Loading archive…', muted=True)
            self.submit('read emulation archive', lambda: read_archive(self.archive),
                        self.emulation_archive_loaded)
        items = [record for record in self.saved if record.get('protocol') == 'ISO15693']
        if not items and not self.archive_dirty:
            self.wrap(body, 'No ISO15693 tags in the local archive. Read a tag fully first.',
                      muted=True)
        eligible = [record for record in items if simulation_eligibility(record)[0]]
        self.wrap(body, f'{len(eligible)} verified complete / {len(items)} ISO15693 records',
                  muted=True)
        for record in eligible:
            _, summary = simulation_eligibility(record)
            title = f"{record['uid']}\n{summary}"
            Button(body, title, lambda item=record: self.confirm_simulation(item),
                   state='normal' if not self.worker else 'disabled',
                   lines=2, anchor='w').pack(fill='x', pady=3)
        incomplete = [record for record in items if not simulation_eligibility(record)[0]]
        if incomplete:
            self.wrap(body, f'{len(incomplete)} incomplete/unsupported NFC-V captures are not selectable.',
                      muted=True)
        self.wrap(body, 'PM3 · LF EM410x (ID-only)', font=FONT)
        lf = [record for record in self.saved if record.get('protocol') == 'EM410X']
        good_lf = [record for record in lf if em410x_eligibility(record)[0]]
        for record in good_lf:
            Button(body, record['uid'] + '\\n125 kHz · ID only',
                   lambda item=record: self.confirm_em410x(item),
                   lines=2, anchor='w',
                   state='normal' if not self.worker else 'disabled').pack(fill='x', pady=3)
        if not good_lf:
            self.wrap(body, 'No verified EM410x identifiers in the archive. Scan LF first.',
                      muted=True)
        if len(good_lf) != len(lf):
            self.wrap(body, f'{len(lf)-len(good_lf)} invalid LF IDs omitted.', muted=True)
        self.finish_page()

    def pm3_simulation_allowed(self):
        return 'pm3-simulate' in self.available_pm3_actions

    def emulation_archive_loaded(self, records):
        if records is not None:
            self.saved = records
            self.archive_dirty = False
            if self.screen == 'emulation':
                self.emulation_menu()

    def reload_emulation_archive(self):
        self.archive_dirty = True
        self.emulation_menu()

    def confirm_simulation(self, record):
        if self.worker:
            self.notice.set('Stop the current NFC operation before emulation.')
            return
        allowed, reason = simulation_eligibility(record)
        if not allowed:
            self.notice.set(reason)
            return
        self.screen = 'confirm'
        body = self.page('Confirm PM3 emulation', self.emulation_menu, footer=(
            ('Cancel', self.emulation_menu, {}),
            ('Start 10 s', lambda: self.begin_simulation(record['uid']), {'primary': True,
              'state': 'normal' if self.pm3_simulation_allowed() else 'disabled'})))
        self.wrap(body, f"Saved tag: {record['uid']}", font=FONT)
        self.wrap(body, reason, muted=True)
        self.wrap(body, 'Iceman will temporarily load this verified user-memory image '
                  'into the PM3 emulator; it does not reprogram firmware or your physical tag.')
        self.wrap(body, 'For your SLIX-L custom firmware, the emulation may handle '
                  'privacy/password challenges, but this capture only supplies UID and '
                  'user memory. Test the entire exchange with your own reader/tag.', muted=True)
        if 'pm3-simulate' not in self.available_pm3_actions:
            self.wrap(body, self.pm3_simulation_capability, muted=True)
        self.finish_page()

    def confirm_em410x(self, record):
        if self.worker:
            self.notice.set('Stop the current NFC operation before emulation.')
            return
        allowed, description = em410x_eligibility(record)
        if not allowed:
            self.notice.set(description)
            return
        self.screen = 'confirm'
        body = self.page('Confirm LF EM410x', self.emulation_menu, footer=(
            ('Cancel', self.emulation_menu, {}),
            ('Start 10 s', lambda: self.begin_em410x(record['uid']), {'primary': True})))
        self.wrap(body, f"EM410x identifier: {record['uid']}", font=FONT)
        self.wrap(body, description, muted=True)
        self.wrap(body, 'The Proxmark3 LF antenna will transmit this fixed '
                  'identifier for up to ten seconds. This does not emulate '
                  'smartcard memory or authentication. Use only tags you own '
                  'or are authorized to test.', muted=True)
        self.finish_page()

    def begin_em410x(self, uid):
        if self.worker:
            return
        self.emulation_menu()
        self.launch('pm3-em410x', 'proxmark3', uid)

    def begin_simulation(self, uid):
        if self.worker or not self.pm3_simulation_allowed():
            self.notice.set('Simulation is unavailable on this Proxmark3 connection.')
            return
        self.emulation_menu()
        self.launch('pm3-simulate', 'proxmark3', uid)

    def log_view(self, output, back):
        self.screen = 'log'
        body = self.page('Local reader output', back)
        self.wrap(body, output[-12000:], font=MONO)
        self.finish_page()

    def toggle_scan(self):
        if self.worker:
            self.stop()
        else:
            self.launch('watch')

    def apply_led_settings(self):
        if self.led_operation and self.settings['led_enabled']:
            if self.led is None:
                self.led = NFCLeds()
            self.led.start(self.settings['led_effect'], int(self.settings['led_brightness']))
            if self.read_progress is not None:
                self.led.reading(*self.read_progress)
        elif self.led is not None:
            self.led.stop()

    def launch(self, action, force=None, uid=None):
        if self.worker or self.closing or not self.ready:
            return
        values = dict(self.settings)
        cmd = [sys.executable, '-u', str(BACKEND_SCRIPT), action]
        if uid:
            cmd.append(uid)
        cmd.extend(('--json-lines', '--backend', force or values['backend'], '--archive', str(self.archive),
                    '--protocol', values['protocol_mode'], '--blocks', values['blocks'], '--pm3-mode', values['pm3_mode']))
        cmd.append(f"--exclude-uid={values['exclude_uid']}")
        for key, flag in (('client', '--client'), ('port', '--port')):
            if values[key]:
                cmd.append(f'{flag}={values[key]}')
        for key, flag in (('auto_tonie', '--auto-tonie'), ('auto_candidates', '--auto-candidates'),
                          ('save_all', '--save'), ('include_st', '--include-st')):
            if values[key]:
                cmd.append(flag)
        if action in ('pm3-simulate', 'pm3-em410x'):
            cmd.append('--confirm-emulation')
        if action == 'watch':
            self.last_rf_bits = None
        self.worker = ScanWorker(cmd, self.events)
        self.read_progress = None
        self.led_operation = action in ('watch', 'pm3-dump', 'identify')
        self.apply_led_settings()
        self.had_fault = False
        self.stopping = False
        self.status.set('Connecting to reader…')
        if self.screen == 'pm3':
            self.pm3()
        self.sync_scan()
        self.worker.start()

    def stop(self):
        if self.worker and not self.stopping:
            self.stopping = True
            self.status.set('Stopping · waiting for RF shutdown…')
            worker = self.worker
            worker.send_signal(signal.SIGINT)
            self.sync_scan()
            self.after(3500, self.escalate, worker, signal.SIGTERM)
            self.after(5000, self.escalate, worker, signal.SIGKILL)

    def escalate(self, worker, signum):
        if self.worker is worker:
            worker.send_signal(signum)

    def event(self, item):
        kind = item['event']
        message = item.get('message', '')
        if kind == 'exit':
            self.worker = None
            self.led_operation = False
            self.read_progress = None
            if self.led is not None and not self.closing:
                self.led.stop(fault=self.had_fault and not self.stopping)
            code = item['code']
            if self.stopping or not self.had_fault:
                if self.reader_backend == 'internal' and self.last_rf_bits == 0:
                    self.status.set('Stopped · RF off')
                elif code not in (0, 130):
                    self.status.set(f'Reader exited ({code})')
                else:
                    self.status.set('Stopped' if self.stopping else 'Ready')
            self.stopping = False
            if not self.closing:
                if self.screen == 'pm3':
                    self.pm3()
                elif self.screen == 'emulation':
                    self.emulation_menu()
                elif self.screen == 'confirm':
                    self.notice.set('Simulation finished · return to Emulation to select another tag')
            self.sync_scan()
        elif kind == 'tag_detected':
            if not self.stopping and self.led_operation and self.settings['led_enabled'] and self.led is not None:
                self.led.detected(item.get('protocol', ''), item.get('rssi_am'))
        elif kind == 'read_progress':
            protocol = PROTOCOLS.get(item['protocol'], item['protocol'])
            completed, total = item['completed'], item['total']
            self.read_progress = completed, total
            if not self.stopping:
                self.status.set(f'Reading {protocol} · {completed}/{total} verified' if total else
                                f'Reading {protocol} · {completed} verified · size unknown')
                if self.led_operation and self.settings['led_enabled'] and self.led is not None:
                    self.led.reading(completed, total)
        elif kind == 'tag':
            self.read_progress = None
            self.newest = item['record']
            if self.led is not None and self.led_operation and self.settings['led_enabled']:
                # PM3 has no comparable per-tag RSSI; internal discovery already sent one.
                if self.newest.get('backend') == 'proxmark3':
                    self.led.detected('LF' if self.newest.get('protocol') == 'EM410X' else
                                      self.newest.get('protocol', ''), None)
            if not self.stopping and self.led_operation and self.settings['led_enabled'] and self.led is not None:
                comparison = item.get('comparison', 'new')
                if comparison in ('same', 'improved', 'changed_verified', 'different_partial'):
                    self.led.result({'same': 'same', 'improved': 'improved',
                                     'changed_verified': 'changed',
                                     'different_partial': 'uncertain'}[comparison])
                else:
                    self.led.result('success' if self.newest.get('dump_status') in (
                        'addressable_memory_complete', 'requested_range_complete') else
                        'partial' if self.newest.get('dump_status') in ('partial', 'failed') else 'hold')
            if self.newest['protocol'] == 'ISO15693' and self.newest['uid'].startswith('E002'):
                self.latest_st = self.newest['uid']
            self.update_latest()
            comparison = item.get('comparison')
            self.status.set((comparison.replace('_', ' ') + ' · ' if comparison else '') + coverage(self.newest))
        elif kind == 'archived':
            self.archive_dirty = True
        elif kind == 'pm3_status':
            self.pm3_status.set(message[:240])
            if item['state'] != 'connected':
                self.available_pm3_actions.clear()
                self.pm3_simulation_capability = 'Proxmark3 unavailable: ' + message
            else:
                self.pm3_simulation_capability = (
                    'Connected · emulator availability depends on supported Iceman commands. '
                    'Firmware revision differences are advisory.')
        elif kind == 'backend':
            self.reader_backend = item['backend']
            self.reader.set(message)
            self.available_pm3_actions = set(item.get('pm3_actions', []))
            if 'pm3-simulate' in self.available_pm3_actions:
                self.pm3_simulation_capability = 'Iceman advertises ISO15693 emulator commands'
            else:
                self.pm3_simulation_capability = (
                    'Iceman does not advertise both hf 15 eload and hf 15 sim. '
                    'Check command support; version matching alone will not fix this.')
            self.status.set('Scanning · hold a tag by the antenna')
        elif kind == 'fault':
            self.had_fault = True
            if not self.stopping and self.led_operation and self.settings['led_enabled'] and self.led is not None:
                self.led.result('error')
            if item.get('backend') == 'proxmark3':
                self.available_pm3_actions.clear()
            self.status.set(message[:180])
        elif kind == 'scan_state' and not self.stopping:
            self.status.set(message[:180])
        elif kind == 'diagnostic':
            stage, result = item['stage'], item['result']
            self.rf.add(stage, result, **{k: v for k, v in item.items() if k not in ('stage', 'result')})
            if stage == 'shutdown':
                self.last_rf_bits = item.get('rf_bits')
        elif kind == 'log':
            self.pm3_log = (self.pm3_log + '\n' + message)[-12000:]

    def drain(self):
        for _ in range(80):
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            self.event(item)
        for key, (task, done) in list(self.tasks.items()):
            if task.done():
                del self.tasks[key]
                try:
                    result = task.result()
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                    self.notice.set(f'{key.capitalize()} failed · {exc}')
                    result = None
                if not self.closing:
                    done(result)
        if self.led is not None:
            self.led_status.set(self.led.status)
        if self.closing and not self.worker and not self.tasks and (self.led is None or not self.led.thread.is_alive()):
            self.io.shutdown(wait=False, cancel_futures=True)
            self.destroy()
        else:
            self.after(40, self.drain)

    def close(self):
        self.closing = True
        self.stop()
        if self.led is not None:
            self.led.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windowed', action='store_true', help='open with a desktop title bar')
    args = parser.parse_args()
    try:
        window = NFCWindow(fullscreen=not args.windowed)
    except tk.TclError as exc:
        raise SystemExit(f'Launch PT35 NFC from the graphical desktop: {exc}') from exc
    window.mainloop()


if __name__ == '__main__':
    main()
