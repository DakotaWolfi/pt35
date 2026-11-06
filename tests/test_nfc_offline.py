"""Synthetic protocol and local archive checks. No I2C, RF or tag data."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nfc'))

from nfc_archive import migrate_archive, range_bytes, save_record, set_coverage
from nfcv_dump import Reader, TagError, read_memory
from nfcv_scan import Chip, FrameError, InventorySearch, crc15693, decode_response
from nfc_diagnostics import Diagnostics
from pt35_nfc import new_record, skip_internal_uid

UID = 'E004030000000000'
UNKNOWN = 'E004000000000000'


def wire(payload, bad_crc=False):
    crc = crc15693(payload) ^ bad_crc
    bits, shift = 0x17, 5
    for byte in payload + crc.to_bytes(2, 'little'):
        for bit in range(8):
            bits |= (2 if byte & 1 << bit else 1) << shift
            shift += 2
    bits |= 0x1d << shift
    return bits.to_bytes((shift + 12) // 8, 'little')


class FakeChip(Chip):
    def __init__(self, statuses, sizes=()):
        super().__init__(None)
        self.statuses = iter(statuses)
        self.sizes = iter(sizes)
        self.commands = []
        self.raw = wire(bytes.fromhex('0000 00000000000004E0'))

    def send(self, *data):
        self.commands.append(data[0])

    def update(self, *args, **kwargs):
        pass

    def irqs(self):
        return next(self.statuses)

    def read(self, operation, length):
        if operation == 0x5e:
            return bytes((next(self.sizes, len(self.raw)), 0))
        return self.raw


class NoSystemInfo(Reader):
    def system_info(self, uid, verbose=False):
        raise TimeoutError('Synthetic timeout')

    def exchange(self, payload, timeout=.12, verbose=False):
        return decode_response(wire(bytes(5)))


class RFTests(unittest.TestCase):
    def test_zero_block_and_unknown_geometry(self):
        for uid, full in ((UID, True), (UNKNOWN, False)):
            with self.subTest(uid=uid):
                capture = read_memory(NoSystemInfo(None), uid)
                self.assertEqual(range_bytes(capture), bytes(32))
                self.assertTrue(capture['requested_range_complete'])
                self.assertEqual(capture['addressable_memory_complete'], full)

    def test_wrong_block_size(self):
        with self.assertRaisesRegex(FrameError, 'unexpected length'):
            NoSystemInfo(None).read_single(UID, 0, expected_size=2)

    def test_crc_and_malformed_frames(self):
        data = bytes(5)
        bad_crc = wire(data, bad_crc=True)
        malformed = bytes([wire(data)[0] & 0x9f]) + wire(data)[1:]
        for raw, kind in ((bad_crc, 'crc'), (malformed, 'manchester'),
                          (wire(data)[:-1], 'framing'), (wire(data) + b'\x01', 'framing')):
            with self.subTest(kind=kind):
                with self.assertRaises(FrameError) as err:
                    decode_response(raw)
                self.assertEqual(err.exception.kind, kind)

    def test_poll_both_irqs_and_recover_after_timeout(self):
        idle, nrt, reply = (0, 0, 0, 0), (8, 0x40, 0, 0), (0x18, 0, 0, 0)
        chip = FakeChip([idle, nrt, idle, idle, reply], sizes=[0])
        self.assertIsNone(chip.inventory())
        self.assertIsInstance(chip.inventory_error, TimeoutError)
        self.assertEqual(chip.inventory()[0], UNKNOWN)
        self.assertEqual(chip.commands.count(0xc2), 1)

    def test_fifo_and_terminal_symbol_recovery_still_requires_crc(self):
        idle, nrt = (0, 0, 0, 0), (8, 0x40, 0, 0)
        chip = FakeChip([idle, nrt, idle])
        report = Diagnostics()
        chip.diagnostic = report.add
        chip.raw = chip.raw[:-1]
        self.assertEqual(chip.inventory()[0], UNKNOWN)
        self.assertTrue(report.events[-1]['fifo_recovered'])
        self.assertTrue(report.events[-1]['end_recovered'])
        with self.assertRaisesRegex(FrameError, 'CRC'):
            decode_response(wire(bytes(5), bad_crc=True)[:-1], recover_end=True)
        with self.assertRaises(FrameError):
            decode_response(wire(bytes(5))[:-1], recover_end=True, last_bits=4)

    def test_st_i2c_contention_retry_keeps_zero_blocks(self):
        class SyntheticST(Reader):
            system_calls = 0
            block_calls = 0

            def system_info(self, uid, verbose=False):
                self.system_calls += 1
                if self.system_calls == 1:
                    raise TagError(0x0f)
                return {'geometry': {'blocks': 2, 'size': 4}}

            def read_single(self, uid, index, verbose=False, expected_size=None):
                self.block_calls += 1
                if self.block_calls == 1:
                    raise TagError(0x0f)
                return bytes(4)

        reader = SyntheticST(None)
        capture = read_memory(reader, 'E002000000000000')
        self.assertEqual(reader.system_calls, 2)
        self.assertEqual(reader.block_calls, 3)
        self.assertEqual(range_bytes(capture), bytes(8))
        self.assertTrue(capture['addressable_memory_complete'])

    def test_mask_search_keeps_external_tag_visible(self):
        onboard = 'E002000000000000'
        external = 'E004000000000001'

        class MaskedReader:
            def trace(self, *args, **kwargs):
                pass

            def inventory(self, mask_bits, mask, **kwargs):
                self.inventory_error = None
                if not mask_bits:
                    return onboard, b''
                if (mask_bits, mask) == (1, 1):
                    return external, b''
                return None

        search = InventorySearch(onboard)
        reader = MaskedReader()
        self.assertIsNone(search.poll(reader))
        self.assertEqual(search.poll(reader)[0], external)

    def test_report_only_exports_allowlisted_metadata(self):
        report = Diagnostics(capacity=1)
        report.add('inventory', 'ok', uid=UID, raw='AA BB CC', irq_main=24)
        report.add('read_block', 'crc', block=2, message=UID, fifo_status='AA BB')
        self.assertEqual(report.export()['events'], [{'stage': 'read_block', 'result': 'crc', 'block': 2}])
        self.assertEqual(report.counts['inventory.ok'], 1)

    def test_filter_excludes_only_configured_uid(self):
        self.assertTrue(skip_internal_uid('E002000000000000', False, 'E002000000000000'))
        self.assertFalse(skip_internal_uid('E002000000000001', False, 'E002000000000000'))
        self.assertFalse(skip_internal_uid('E002000000000000', True, 'E002000000000000'))


class ArchiveTests(unittest.TestCase):
    def test_later_partial_cannot_replace_full(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            good = new_record(UID, 'internal')
            good.update(read_memory(NoSystemInfo(None), UID))
            good['labels'] = ['synthetic']
            path = save_record(archive, good)
            poor = new_record(UID, 'internal')
            poor.update(blocks=[{'index': 0, 'hex': '12345678'}], read_errors=[{'index': 1}])
            set_coverage(poor, 8, good['geometry'])
            for _ in range(4):
                save_record(archive, poor)
            saved = json.loads(path.read_text())
            self.assertTrue(saved['addressable_memory_complete'])
            self.assertEqual(saved['blocks'], good['blocks'])
            self.assertEqual(saved['labels'], ['synthetic'])
            self.assertEqual(list(path.parent.glob('*.bin')), [path.parent / saved['memory_binary']])
            self.assertEqual((path.parent / saved['memory_binary']).read_bytes(), bytes(32))

    def test_migrate_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            src, dst = Path(directory) / 'old', Path(directory) / 'new'
            src.mkdir()
            dst.mkdir()
            (src / 'known_tonies.txt').write_text('old')
            (dst / 'known_tonies.txt').write_text('new')
            (src / UID).mkdir()
            (src / UID / 'record.json').write_text('{}')
            self.assertEqual(migrate_archive(src, dst), 1)
            self.assertEqual(migrate_archive(src, dst), 0)
            self.assertEqual((src / 'known_tonies.txt').read_text(), 'old')
            self.assertEqual((dst / 'known_tonies.txt').read_text(), 'new')
            self.assertEqual((dst / UID / 'record.json').read_text(), '{}')


class LaunchTests(unittest.TestCase):
    def test_installer_in_scratch_home(self):
        try:
            __import__('tkinter')
        except ImportError:
            self.skipTest('Tkinter unavailable')
        with tempfile.TemporaryDirectory(prefix='pt35 home ') as directory:
            home = Path(directory)
            archive = home / 'pt35-nfc' / 'archive'
            archive.mkdir(parents=True)
            marker = archive / 'known_tonies.txt'
            marker.write_text('test\n')
            subprocess.run(['bash', str(ROOT / 'scripts/install_nfc_gui.sh')], check=True,
                           env={**os.environ, 'HOME': str(home)}, capture_output=True)
            desktop = home / '.local/share/applications/pt35-nfc.desktop'
            launcher = home / '.local/bin/pt35-nfc-gui'
            self.assertIn(f'Exec="{launcher}"', desktop.read_text())
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertEqual(marker.read_text(), 'test\n')


if __name__ == '__main__':
    unittest.main()
