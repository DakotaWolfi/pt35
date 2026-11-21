"""Offline test of automatic Tonie candidates and opt-in metadata exports."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nfc'))
from nfc_tonies import (add_scan, catalog_path, eligibility, scan_archive,
                        shareable_catalog, export_teddy_custom, teddy_custom_entries)

UID = 'E004030000000001'


class CatalogTests(unittest.TestCase):
    def test_vendor_prefix_is_candidate_not_verified_tonie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = {'uid': UID, 'protocol': 'ISO15693', 'classification': 'tonie_candidate'}
            self.assertEqual(eligibility(rec, root)['status'], 'possible_tonie')
            self.assertEqual(eligibility(rec, root)['verified'], False)
            self.assertEqual(eligibility({**rec, 'uid': 'E002000000000000'}, root), None)
            self.assertEqual(eligibility({**rec, 'protocol': 'NFC-A'}, root), None)
            self.assertIsNone(eligibility({**rec, 'classification_verified': True,
                                'classification': 'ndef_link'}, root))

    def test_known_uid_is_explicitly_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'known_tonies.txt').write_text(UID + '\n')
            evidence = eligibility({'uid': UID, 'protocol': 'ISO15693'}, root)
            self.assertEqual(evidence['status'], 'known_tonie')
            self.assertEqual(evidence['evidence'], 'local_known_uid_list')
            self.assertTrue(evidence['verified'])

    def test_automatic_add_is_idempotent_and_keeps_user_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = {'uid': UID, 'protocol': 'ISO15693', 'last_seen_utc': '2026-11-07T10:00:00Z',
                   'blocks': [{'hex': 'DEADBEEF'}], 'pm3_log': 'SECRET', 'password': 'SECRET'}
            self.assertTrue(add_scan(root, rec))
            self.assertFalse(add_scan(root, rec))
            path = catalog_path(root)
            data = json.loads(path.read_text())
            self.assertEqual(len(data), 1)
            self.assertNotIn('blocks', data[0])
            self.assertNotIn('password', data[0])
            self.assertNotIn('pm3_log', data[0])
            data[0]['teddycloud'] = {'model': '123456',
                                      'audio_id': ['369519776'],
                                      'hash': ['af9e61a9c1b12138fb060908d595742334b04515'],
                                      'title': 'Custom Title'}
            path.write_text(json.dumps(data))
            self.assertTrue(add_scan(root, {**rec, 'last_seen_utc': '2026-11-08T10:00:00Z'}))
            self.assertEqual(json.loads(path.read_text())[0]['teddycloud']['title'], 'Custom Title')

    def test_archive_scan_deduplicates_and_preserves_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for uid, protocol in ((UID, 'ISO15693'), ('E002000000000000', 'ISO15693')):
                folder = root / uid
                folder.mkdir()
                (folder / 'record.json').write_text(json.dumps(
                    {'uid': uid, 'protocol': protocol, 'last_seen_utc': '2026-11-08'}))
            summary = scan_archive(root)
            self.assertEqual(summary['scanned'], 2)
            self.assertEqual(summary['candidates'], 1)
            self.assertEqual(summary['changed'], 1)
            self.assertEqual(scan_archive(root)['changed'], 0)

    def test_later_ndef_verification_revokes_false_positive_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observed = {'uid': UID, 'protocol': 'ISO15693', 'classification': 'tonie_candidate'}
            self.assertTrue(add_scan(root, observed))
            proven_ndef = {**observed, 'classification': 'ndef_text',
                           'classification_verified': True,
                           'content_preview': ['Text: example']}
            self.assertTrue(add_scan(root, proven_ndef))
            self.assertEqual(json.loads(catalog_path(root).read_text()), [])
            _, count = shareable_catalog(root, root / 'share.json')
            self.assertEqual(count, 0)

    def test_share_export_has_no_private_dump_or_internal_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_scan(root, {'uid': UID, 'protocol': 'ISO15693', 'pm3_log': 'not public'})
            destination, count = shareable_catalog(root, root / 'exports' / 'share.json')
            public = json.loads(destination.read_text())
            self.assertEqual(count, 1)
            self.assertEqual(public[0]['uid'], UID)
            self.assertFalse(set(public[0]) & {
                'blocks', 'memory', 'pm3_log', 'first_seen_utc', 'last_seen_utc',
                'teddycloud', 'password', 'audio'})
            self.assertEqual(public[0]['status'], 'possible_tonie')

    def test_teddy_custom_requires_real_model_audio_id_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            add_scan(root, {'uid': UID, 'protocol': 'ISO15693'})
            dest, count = export_teddy_custom(root, root / 'exports' / 'tonies.custom.json')
            self.assertEqual(count, 0)
            self.assertEqual(json.loads(dest.read_text()), [])
            data = json.loads(catalog_path(root).read_text())
            data[0]['teddycloud'] = {'model': '123456', 'audio_id': ['12345'],
                'hash': ['not-a-hash'], 'title': 'Unverified'}
            catalog_path(root).write_text(json.dumps(data))
            self.assertEqual(teddy_custom_entries(root), [])
            data[0]['teddycloud']['hash'] = ['af9e61a9c1b12138fb060908d595742334b04515']
            catalog_path(root).write_text(json.dumps(data))
            entries = teddy_custom_entries(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]['model'], '123456')
            self.assertEqual(entries[0]['audio_id'], ['12345'])
            self.assertNotIn('uid', entries[0])


if __name__ == '__main__':
    unittest.main()
