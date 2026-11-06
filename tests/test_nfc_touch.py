"""Tk touch-path checks with synthetic taps/swipes and a fake reader process."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nfc'))

from nfc_archive import set_coverage
from pt35_nfc import new_record


UID = 'E002000000000000'


@unittest.skipUnless(os.environ.get('DISPLAY'), 'graphical display needed')
class TouchTests(unittest.TestCase):
    def setUp(self):
        from pt35_nfc_gui import NFCWindow
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.app = NFCWindow(self.root / 'archive', self.root / 'settings.json', fullscreen=False)
        self.addCleanup(self.close)
        self.app.geometry('800x390')
        self.wait(lambda: self.app.ready)

    def close(self):
        import tkinter as tk
        try:
            self.app.close()
            self.wait(lambda: self.app.closing and self.app.worker is None and not self.app.tasks)
        except tk.TclError:
            pass

    def wait(self, condition):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            self.app.update()
            if condition():
                return
            time.sleep(.01)
        self.fail(f'Condition timed out on {self.app.screen}')

    def button(self, title, index=0):
        from nfc_touch import Button

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        for widget in descendants(self.app.layout):
            if isinstance(widget, Button) and widget['text'].split('\n')[0] == title:
                if not index:
                    return widget
                index -= 1
        self.fail(f'{title!r} is missing on {self.app.screen}')

    @staticmethod
    def gesture(widget, *, drag=0):
        x, y = widget.winfo_width() // 2, widget.winfo_height() // 2
        widget.event_generate('<Enter>', x=x, y=y)
        widget.event_generate('<ButtonPress-1>', x=x, y=y)
        if drag:
            widget.event_generate('<B1-Motion>', x=x, y=y + drag)
        widget.event_generate('<ButtonRelease-1>', x=x, y=y + drag)

    def reveal(self, button):
        scroll = self.app.scroll
        if scroll is None or not str(button).startswith(str(scroll.content) + '.'):
            return
        for _ in range(15):
            canvas = scroll.canvas
            relative = button.winfo_rooty() - canvas.winfo_rooty()
            if 0 <= relative <= canvas.winfo_height() - button.winfo_height():
                return
            self.gesture(canvas, drag=135 if relative < 0 else -135)
            self.app.update()
        self.fail(f'Unreachable button {button["text"]!r} on {self.app.screen}')

    def tap(self, title, *, reveal=True, index=0):
        self.app.update()
        button = self.button(title, index)
        if reveal:
            self.reveal(button)
        self.assertTrue(button.winfo_ismapped())
        self.assertGreaterEqual(button.winfo_height(), 44, title)
        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth(), title)
        self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                             self.app.winfo_rootx() + self.app.winfo_width(), title)
        self.assertGreaterEqual(button.winfo_rooty(), self.app.winfo_rooty(), title)
        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                             self.app.winfo_rooty() + self.app.winfo_height(), title)
        self.assertNotEqual(button['state'], 'disabled', title)
        self.gesture(button)
        self.app.update()

    def test_settings_touch_keyboard_and_persistence(self):
        self.tap('Settings')
        # Drag over a choice. Release should scroll without changing it.
        backend = self.button('Internal')
        self.gesture(backend, drag=-60)
        self.app.update()
        self.assertEqual(self.app.draft['backend'], 'auto')
        for title in ('Proxmark3', 'Auto', 'Internal', 'NFC-A', 'NFC-B', 'NFC-F', 'NFC-V',
                      'All known', '8', '32'):
            self.tap(title)
        self.assertEqual(self.app.draft['blocks'], '32')
        self.tap('Auto', index=1)
        self.assertEqual(self.app.draft['blocks'], '0')
        self.tap('Custom block count')
        self.tap('Clear')
        self.tap('1')
        self.tap('2')
        self.tap('Done')
        self.assertEqual(self.app.draft['blocks'], '12')
        self.tap('LF')
        self.tap('Include onboard ST25DV   OFF')
        self.tap('Save all tags   OFF')
        self.tap('Auto-save known Tonies   ON')
        self.tap('Auto-save unverified NXP tags   OFF')
        self.tap('Onboard ST25DV UID')
        for digit in UID:
            self.tap(digit)
        self.tap('Done')
        for title in ('Iceman client path', 'Proxmark serial port'):
            self.tap(title)
            self.tap('123 / symbols')
            self.tap('/')
            self.tap('ABC')
            self.tap('p')
            self.tap('Done')
        self.tap('Save settings', reveal=False)
        self.wait(lambda: 'Saved' in self.app.notice.get())
        saved = json.loads((self.root / 'settings.json').read_text())
        self.assertEqual({key: saved[key] for key in ('backend', 'protocol_mode', 'blocks', 'exclude_uid',
                                                      'client', 'port', 'pm3_mode')},
                         dict(backend='internal', protocol_mode='ISO15693', blocks='12', exclude_uid=UID,
                              client='/p', port='/p', pm3_mode='LF'))
        self.tap('‹ Back', reveal=False)
        self.tap('Exit', reveal=False)
        self.close()
        from pt35_nfc_gui import NFCWindow
        self.app = NFCWindow(self.root / 'archive', self.root / 'settings.json', fullscreen=False)
        self.wait(lambda: self.app.ready)
        self.assertEqual(self.app.settings, saved)

    def test_scan_touch_navigation_archive_exports_and_diagnostics(self):
        self.app.geometry('800x480')
        record = new_record(UID, 'internal')
        record['blocks'] = [{'index': 0, 'hex': '00000000', 'size': 4}]
        set_coverage(record, 1, {'blocks': 1, 'size': 4, 'source': 'synthetic'})
        worker = self.root / 'fake_reader.py'
        worker.write_text(
            'import json, time\n'
            'def send(**event): print(json.dumps(event), flush=True)\n'
            'send(event="backend", message="Synthetic reader", backend="internal")\n'
            f'send(event="tag", record={record!r})\n'
            'for _ in range(420): send(event="diagnostic", stage="read_block", result="crc", block=0, uid="private")\n'
            'try:\n    time.sleep(30)\n'
            'except KeyboardInterrupt:\n    send(event="diagnostic", stage="shutdown", result="ok", rf_bits=0)\n')
        with patch('pt35_nfc_gui.BACKEND_SCRIPT', worker):
            self.tap('Start scan')
        self.wait(lambda: self.app.newest and self.app.rf.counts['read_block.crc'] == 420)
        self.tap(f'NFC-V  {UID}')
        self.assertIsNotNone(self.app.worker)
        self.tap('Hex / data', reveal=False)
        self.tap('‹ Back', reveal=False)
        self.tap('Save tag', reveal=False)
        self.wait(lambda: 'Tag saved' in self.app.notice.get())
        self.tap('Export', reveal=False)
        self.tap('Export JSON record')
        self.wait(lambda: 'Saved tag-' in self.app.notice.get())
        self.tap('Export verified binary range')
        self.wait(lambda: self.app.notice.get().endswith('.bin'))
        self.assertEqual(next((self.root / 'exports').glob('tag-*.bin')).read_bytes(), bytes(4))
        self.tap('Stop scan', reveal=False)
        self.wait(lambda: self.app.worker is None)
        self.assertEqual(self.app.last_rf_bits, 0)
        self.tap('‹ Back', reveal=False)
        self.tap('‹ Back', reveal=False)
        self.tap('Archive', reveal=False)
        self.wait(lambda: len(self.app.saved) == 1)
        self.tap('Search tags')
        self.tap('123 / symbols')
        self.tap('0')
        self.tap('0')
        self.tap('Done', reveal=False)
        self.tap(f'NFC-V   {UID}')
        self.tap('‹ Back', reveal=False)
        self.tap('‹ Back', reveal=False)
        self.tap('Tools', reveal=False)
        self.tap('RF diagnostics')
        self.tap('Export redacted log', reveal=False)
        self.wait(lambda: 'Saved nfc-v-diagnostics' in self.app.notice.get())
        exported = next((self.root / 'exports').glob('nfc-v-diagnostics-*.json')).read_text()
        self.assertNotIn(UID, exported)
        self.assertNotIn('private', exported)
        self.assertEqual(json.loads(exported)['counts']['shutdown.ok'], 1)


if __name__ == '__main__':
    unittest.main()
