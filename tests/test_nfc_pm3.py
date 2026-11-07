"""Offline checks for Iceman output, switching readers and simulation boundaries."""
import os
import subprocess
import sys
import tempfile
import threading
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
    def test_probe_requires_ping_and_reports_revision_warning(self):
        output = ('[+] Ping response received in 1 ms and content ( ok )\n'
                  ' [ Client ]\n  Iceman/HEAD/v4.123 2026-01-02 12:00:00\n'
                  'OS......... Iceman/master/v4.123 2026-01-01 12:00:00 123456789\n')
        self.assertIsNone(pm3.version_fault(0, output))
        self.assertIsNotNone(pm3.version_fault(0, 'Proxmark3 Iceman firmware online'))
        self.assertIsNotNone(pm3.version_fault(0, output.replace('content ( ok )', 'content ( fail )')))
        mismatched = output.replace('master/v4.123', 'master/v4.122')
        self.assertIsNone(pm3.version_fault(0, mismatched))
        self.assertIn('revisions differ', pm3.revision_warning(mismatched))

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

    def test_emulation_selector_only_accepts_complete_iso15693(self):
        record = {'uid': UID, 'protocol': 'ISO15693',
                  'blocks': [{'index': 0, 'hex': '00000000'}], 'read_errors': []}
        set_coverage(record, 1, None)
        self.assertEqual(pm3.simulation_eligibility(record)[0], False)
        set_coverage(record, 1, {'blocks': 1, 'size': 4})
        allowed, summary = pm3.simulation_eligibility(record)
        self.assertTrue(allowed)
        self.assertIn('10 s', summary)
        self.assertEqual(pm3.simulation_eligibility({**record, 'protocol': 'NFC-A'})[0], False)
        self.assertEqual(pm3.simulation_eligibility(
            {**record, 'addressable_memory_complete': False})[0], False)

    def test_simulate_only_after_confirmed_upload(self):
        record = {'uid': UID, 'protocol': 'ISO15693', 'blocks': [{'index': 0, 'hex': '00000000'}],
                  'read_errors': []}
        set_coverage(record, 1, {'blocks': 1, 'size': 4})
        responses = [(0, '--file'), (0, '--timeout'), (0, 'Memory image not matching')]
        with patch.object(pm3, 'run_pm3', side_effect=responses) as client:
            with self.assertRaisesRegex(RuntimeError, 'did not confirm emulator'):
                pm3.simulate('client', '/dev/fake', record, Mock())
        self.assertEqual(client.call_count, 3)

    def test_patched_slix_emulator_uses_short_timeout_and_loaded_uid(self):
        record = {'uid': UID, 'protocol': 'ISO15693',
                  'blocks': [{'index': 0, 'hex': '00000000'}], 'read_errors': []}
        set_coverage(record, 1, {'blocks': 1, 'size': 4})
        commands = []
        def fake_client(client, port, command, **kwargs):
            commands.append(command)
            if command == 'hf 15 eload -h':
                return 0, 'options: -f <filename>  --file'
            if command == 'hf 15 sim -h':
                return 0, 'options: -t <milliseconds>  --timeout'
            if command.startswith('hf 15 eload -f '):
                return 0, 'uploaded 4 bytes to emulator memory'
            if command == 'hf 15 sim -t 10000':
                return 0, 'Press pm3 button to abort simulation\\nDone!'
            if command == 'hw break':
                return 0, 'OK'
            raise AssertionError(command)
        with patch.object(pm3, 'run_pm3', side_effect=fake_client), \\
                patch.object(pm3.Path, 'exists', return_value=True):
            pm3.simulate('client', '/dev/fake', record, Mock())
        self.assertIn('hf 15 sim -t 10000', commands)
        self.assertFalse(any(' -u ' in cmd for cmd in commands))
        self.assertFalse(any('sim --timeout' in cmd for cmd in commands))

    def test_older_ping_and_git_revision_aliases(self):
        result = ('[+] Ping response received in 2 ms\n'
                  'Client.... Iceman/HEAD/cafebad1\nOS........ Iceman/master/v4.123-9-gcafebad1\n')
        self.assertIsNone(pm3.version_fault(0, result))
        self.assertIn('revisions differ', pm3.revision_warning(result.replace('-gcafebad1', '-gbedface0')))

    def test_build_binary_is_preferred_to_upstream_shell_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / 'proxmark3/pm3'
            binary = launcher.parent / 'client/build/proxmark3'
            binary.parent.mkdir(parents=True)
            for path in (launcher, binary):
                path.touch(mode=0o755)
            with patch.object(pm3.Path, 'home', return_value=root), patch.dict(os.environ, clear=True):
                self.assertEqual(pm3.pm3_client(), str(binary))
                self.assertEqual(pm3.pm3_client(str(launcher)), str(binary))

    def test_usb_identity_without_a_product_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dev, sys_tty = root / 'dev', root / 'tty'
            dev.mkdir()
            for name, vendor, product in (('ttyACM0', '9ac4', '4b8f'), ('ttyUSB0', '10c4', 'ea60')):
                (dev / name).touch()
                parent = sys_tty / name / 'device'
                parent.mkdir(parents=True)
                (parent / 'idVendor').write_text(vendor)
                (parent / 'idProduct').write_text(product)
                (parent / 'product').write_text('USB Serial Device')
            self.assertEqual(pm3.usb_ports(dev, sys_tty), [str(dev / 'ttyACM0')])

    def test_no_client_inaccessible_and_failed_ping_states(self):
        with patch.object(pm3, 'usb_ports', return_value=[]):
            self.assertEqual(pm3.connect().state, 'absent')
        with patch.object(pm3, 'usb_ports', return_value=['/dev/ttyACM5']):
            with patch.object(pm3, 'pm3_client', return_value=None):
                self.assertEqual(pm3.connect().state, 'no_client')
            with patch.object(pm3, 'pm3_client', return_value='/bin/fake'):
                with patch('nfc_pm3.os.access', return_value=False):
                    self.assertEqual(pm3.connect().state, 'inaccessible')
                with patch('nfc_pm3.os.access', return_value=True), patch.object(
                        pm3, 'run_pm3', return_value=(0, 'ARM firmware does not match')):
                    self.assertEqual(pm3.connect().state, 'unresponsive')

    def test_verified_ping_allows_custom_firmware_and_capability_checked_simulation(self):
        output = ('[+] Ping response received in 1 ms and content ( ok )\n'
                  'Client.... Iceman/master/v4.23346-275-g770cf1268\n'
                  'OS........ Iceman/jenna-slix-r1/v4.23346-188-g3bd526700-suspect\n'
                  '[!] ARM firmware does not match the source at the time the client was compiled\n')
        with patch.object(pm3, 'usb_ports', return_value=['/dev/ttyACM0']), \
                patch.object(pm3, 'pm3_client', return_value='/home/jenna/proxmark3-iceman/client/proxmark3'), \
                patch('nfc_pm3.os.access', return_value=True), \
                patch.object(pm3, 'reader_lock'), \
                patch.object(pm3, 'run_pm3', return_value=(0, output)), \
                patch.object(pm3, 'iso15693_actions', return_value=['pm3-dump', 'pm3-simulate']), \
                patch.object(pm3.Path, 'exists', return_value=True):
            link = pm3.connect()
        self.assertEqual(link.state, 'connected')
        self.assertIn('revisions differ', link.message)
        self.assertEqual(link.actions, ('pm3-dump', 'pm3-simulate'))
        self.assertTrue(link.client.endswith('/proxmark3'))

    def test_custom_firmware_simulation_availability_is_not_revision_blocked(self):
        output = ('[+] Ping response received in 2 ms\n'
                  'Client.... Iceman/master/v4.2-1-gcafebad1\n'
                  'OS........ Iceman/custom/v4.2-1-gbedface0\n')
        helpers = [
            patch.object(pm3, 'usb_ports', return_value=['/dev/ttyACM0']),
            patch.object(pm3, 'pm3_client', return_value='/bin/pm3'),
            patch('nfc_pm3.os.access', return_value=True),
            patch.object(pm3, 'reader_lock'),
            patch.object(pm3, 'run_pm3', return_value=(0, output)),
            patch.object(pm3, 'iso15693_actions', return_value=['pm3-dump', 'pm3-simulate']),
            patch.object(pm3.Path, 'exists', return_value=True),
        ]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for context in helpers:
                stack.enter_context(context)
            default = pm3.connect()
            self.assertIn('pm3-simulate', default.actions)
            self.assertIn('revisions differ', default.message)
            self.assertNotIn('simulation disabled', default.message)
            permitted = pm3.connect(allow_simulation_mismatch=True)
            self.assertEqual(permitted.actions, default.actions)
            self.assertNotIn('experimental emulation override', permitted.message)

    def test_automatically_finds_owners_existing_iceman_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            client = home / 'proxmark3-iceman/client/proxmark3'
            client.parent.mkdir(parents=True)
            client.write_text('binary')
            client.chmod(0o755)
            with patch.object(pm3.Path, 'home', return_value=home), patch.dict(os.environ, clear=True):
                self.assertEqual(pm3.pm3_client(), str(client))

    def test_probe_does_not_block_the_internal_scan_loop(self):
        from pt35_nfc import PM3Monitor
        started, finish = threading.Event(), threading.Event()

        def probe(client, port, cancel):
            started.set()
            finish.wait(2)
            return pm3.Link('absent', 'No USB device')

        args = Namespace(client=None, port=None)
        with patch('nfc_pm3.connect', side_effect=probe):
            monitor = PM3Monitor(args, Mock())
            try:
                self.assertIsNone(monitor.poll())
                self.assertTrue(started.wait(1))
                self.assertIsNone(monitor.poll())
            finally:
                finish.set()
                monitor.close()

    def test_auto_releases_internal_before_resuming_pm3_after_unplug(self):
        args = Namespace(action='watch', watch=True, backend='auto')
        emit = Mock()
        link = pm3.Link('connected', 'Ready', 'client', 'serial')
        actions = []

        def internal(*_):
            actions.append('internal released')
            return link

        def external(*_):
            actions.append('pm3 active')
            if actions.count('pm3 active') == 1:
                raise OSError('unplugged')

        with patch('pt35_nfc.PM3Monitor'), patch('pt35_nfc.internal_operation', side_effect=internal), \
                patch('pt35_nfc.pm3_operation', side_effect=external):
            self.assertEqual(run_reader(args, emit), 0)
        self.assertEqual(actions, ['internal released', 'pm3 active'] * 2)

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
