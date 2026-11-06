"""Offline checks for Iceman output, switching readers and simulation boundaries."""
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nfc'))

import nfc_pm3 as pm3
from nfc_archive import set_coverage
from nfcv_scan import FrameError, crc15693
from pt35_nfc import main, run_reader

UID = 'E004030000000000'


class IcemanTests(unittest.TestCase):
    def test_probe_requires_ping_and_matching_revision(self):
        output = ('[+] Ping response received in 1 ms and content ( ok )\n'
                  ' [ Client ]\n  Iceman/HEAD/v4.123 2026-01-02 12:00:00\n'
                  'OS......... Iceman/master/v4.123 2026-01-01 12:00:00 123456789\n')
        self.assertIsNone(pm3.version_fault(0, output))
        self.assertIsNotNone(pm3.version_fault(0, 'Proxmark3 Iceman firmware online'))
        self.assertIsNotNone(pm3.version_fault(0, output.replace('content ( ok )', 'content ( fail )')))
        self.assertIsNotNone(pm3.version_fault(0, output.replace('master/v4.123', 'master/v4.122')))

    def test_classify_hf_and_lf(self):
        output = ('Searching for ISO14443-A tag...\n[+] UID: 04 11 22 33 44 55 66 (fixed)\n'
                  '[+] Valid ISO 14443-A tag found\n'
                  'Searching for ISO15693 tag...\n[+] UID.... E0 04 03 00 00 00 00 00\n'
                  '[+] Valid ISO 15693 tag found\n')
        self.assertEqual(pm3.discoveries('HF', output),
                         [('NFC-A', '04112233445566'), ('ISO15693', UID)])
        self.assertEqual(pm3.discoveries('LF', '[+] EM 410x ID 0102030405\nValid EM410x ID found!'),
                         [('EM410X', '0102030405')])
        self.assertEqual(pm3.discoveries('HF', 'UID: 00 00 00 00\n'), [])

    def test_crc_checked_raw_read_and_malformed_size(self):
        frame = bytes(5)
        valid = frame + crc15693(frame).to_bytes(2, 'little')
        reader = pm3.PM3Reader('fake', '/dev/fake')
        with patch.object(pm3.Path, 'exists', return_value=True), \
                patch.object(pm3, 'run_pm3', return_value=(0, f'[+] (7) {valid.hex(" ")}\n')) as client:
            self.assertEqual(reader.read_single(UID, 0), bytes(4))
            self.assertIn('hf 15 raw -ac -d 222000000000000304e000', client.call_args.args)
        with patch.object(pm3.Path, 'exists', return_value=True), \
                patch.object(pm3, 'run_pm3', return_value=(0, '[+] (7) 00 00 00 00 00 00 00\n')):
            with self.assertRaisesRegex(FrameError, 'CRC'):
                reader.read_single(UID, 0)

    def test_emulation_requires_complete_capture_and_confirmation(self):
        record = {'uid': UID, 'protocol': 'ISO15693', 'blocks': [{'index': 0, 'hex': '00000000'}],
                  'read_errors': []}
        set_coverage(record, 1, None)
        with self.assertRaises(ValueError):
            pm3.simulation_image(record)
        set_coverage(record, 1, {'blocks': 1, 'size': 4})
        image = pm3.simulation_image(record)
        self.assertEqual(image['Card']['uid'], '00000000000304E0')
        self.assertEqual(image['blocks'], {'0': '00000000'})
        with patch('sys.argv', ['pt35_nfc.py', 'pm3-simulate', UID]), patch('sys.stderr'):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 2)

    def test_simulate_only_after_confirmed_upload(self):
        record = {'uid': UID, 'protocol': 'ISO15693', 'blocks': [{'index': 0, 'hex': '00000000'}],
                  'read_errors': []}
        set_coverage(record, 1, {'blocks': 1, 'size': 4})
        responses = [(0, '--file'), (0, '--timeout'), (0, 'Memory image not matching')]
        with patch.object(pm3, 'run_pm3', side_effect=responses) as client:
            with self.assertRaisesRegex(RuntimeError, 'did not confirm emulator'):
                pm3.simulate('client', '/dev/fake', record, Mock())
        self.assertEqual(client.call_count, 3)

    def test_auto_releases_internal_before_resuming_pm3_after_unplug(self):
        args = Namespace(action='watch', watch=True, backend='auto')
        emit = Mock()
        pm3_selected = ('proxmark3', 'client', 'serial')
        with patch('pt35_nfc.backend_choice', return_value=pm3_selected), \
                patch('pt35_nfc.internal_operation', return_value=pm3_selected) as internal, \
                patch('pt35_nfc.pm3_operation', side_effect=[OSError('unplugged'), None]) as external:
            self.assertEqual(run_reader(args, emit), 0)
        self.assertEqual(external.call_count, 2)
        internal.assert_called_once()

    def test_package_prompt_precedes_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_sudo = Path(directory) / 'sudo'
            marker = Path(directory) / 'sudo-ran'
            fake_sudo.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
            fake_sudo.chmod(0o755)
            result = subprocess.run(
                ['bash', str(ROOT / 'scripts/install_iceman.sh'), '--platform', 'PM3GENERIC',
                 '--rev', 'v4.1', '--install-deps'], input='no\n', text=True, capture_output=True,
                env={**os.environ, 'PATH': directory + ':' + os.environ['PATH'], 'HOME': directory})
            self.assertEqual(result.returncode, 1)
            self.assertFalse(marker.exists())
