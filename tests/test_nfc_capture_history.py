"""Offline regression tests for safe NFC rescanning and local capture history."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nfc'))

from nfc_archive import record_path, save_record, set_coverage
from nfc_capture_history import compare
from nfc_ndef import decode_message


UID = 'E004030000000000'


def capture(data=None, *, count=2, indices=None):
    blocks = []
    if data is not None:
        indices = [0, 1] if indices is None else indices
        blocks = [{'index': i, 'hex': h, 'size': 4} for i, h in zip(indices, data)]
    record = {'uid': UID, 'protocol': 'ISO15693', 'backend': 'internal',
              'classification': 'other', 'last_seen_utc': '2026-11-07T12:00:00+00:00',
              'blocks': blocks, 'read_errors': []}
    set_coverage(record, count, {'blocks': count, 'start': 0, 'size': 4})
    return record


class HistoryTests(unittest.TestCase):
    def test_duplicate_snapshots_deduplicated_but_sighting_count_increases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tag = capture(['00000000', '01020304'])
            save_record(root, tag)
            next_scan = {**tag, 'last_seen_utc': '2026-11-07T12:00:01+00:00'}
            save_record(root, next_scan)
            saved = json.loads(record_path(root, UID).read_text())
            self.assertEqual(saved['scan_count'], 2)
            self.assertEqual(len(saved['capture_history']), 1)
            self.assertEqual(saved['last_comparison'], 'same')
            self.assertEqual(len(list((root / UID / 'captures').glob('*.json'))), 1)

    def test_gui_save_same_timestamp_does_not_increment_rf_scan_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tag = capture(['00000000', '01020304'])
            save_record(root, tag)
            save_record(root, tag)
            self.assertEqual(json.loads(record_path(root, UID).read_text())['scan_count'], 1)

    def test_two_valid_conflicting_reads_are_retained_without_replacing_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = capture(['00000000', '01020304'])
            changed = capture(['00000000', 'FEEDBEEF'])
            save_record(root, original)
            save_record(root, changed)
            saved = json.loads(record_path(root, UID).read_text())
            self.assertEqual(saved['blocks'], original['blocks'])
            self.assertEqual(saved['last_comparison'], 'changed_verified')
            self.assertEqual(len(saved['capture_history']), 2)
            history = [json.loads((root / UID / 'captures' / (item['id'] + '.json')).read_text())
                       for item in saved['capture_history']]
            self.assertEqual(history[1]['blocks'], changed['blocks'])

    def test_partial_capture_kept_but_does_not_replace_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = capture(['00000000', '01020304'])
            partial = capture(['FEEDBEEF'], indices=[0])
            save_record(root, original)
            save_record(root, partial)
            saved = json.loads(record_path(root, UID).read_text())
            self.assertEqual(saved['blocks'], original['blocks'])
            self.assertEqual(saved['last_comparison'], 'different_partial')
            self.assertEqual(len(saved['capture_history']), 2)

    def test_coverage_improvement_and_discovery_only_history(self):
        partial = capture(['00000000'], indices=[0])
        improved = capture(['00000000', '01020304'])
        self.assertEqual(compare(partial, improved), 'improved')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovered = {'uid': UID, 'protocol': 'ISO15693', 'backend': 'proxmark3',
                          'last_seen_utc': '2026-11-07T12:00:00+00:00',
                          'classification': 'other', 'blocks': [], 'read_errors': [],
                          'dump_status': 'not_requested', 'read_capability': 'discovery_only'}
            save_record(root, discovered)
            saved = json.loads(record_path(root, UID).read_text())
            self.assertEqual(len(saved['capture_history']), 1)
            self.assertEqual(saved['capture_history'][0]['blocks'], 0)


class NDEFTests(unittest.TestCase):
    def test_vcard_previews_name_phone_email_and_company(self):
        payload = (b'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jane Example\r\n'
                   b'ORG:Example Corp\r\nTEL;TYPE=CELL:+41 123 456\r\n'
                   b'EMAIL:jane@example.invalid\r\nEND:VCARD\r\n')
        mime = b'text/vcard'
        msg = bytes([0xD2, len(mime), len(payload)]) + mime + payload
        decoded = decode_message(msg)
        self.assertEqual(decoded[0], 'Business card (vCard)')
        self.assertIn('Name: Jane Example', decoded)
        self.assertIn('Organization: Example Corp', decoded)
        self.assertIn('Phone: +41 123 456', decoded)
        self.assertIn('Email: jane@example.invalid', decoded)

    def test_ordinary_ndef_text_still_decodes(self):
        payload = b'\x02enHello!'
        msg = bytes([0xD1, 1, len(payload)]) + b'T' + payload
        self.assertEqual(decode_message(msg), ['Text: Hello!'])


if __name__ == '__main__':
    unittest.main()
