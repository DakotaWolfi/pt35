"""Offline preservation/safety tests for the original ST25DV I2C tag menu."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nfc'))

import pt35_i2c_tag as tag
from nfc_ndef import decode_message


class FakeI2C:
    def __init__(self, raw=None):
        self.memory = bytearray(raw if raw is not None else bytes(512))
        self.writes = []

    def read_mem(self, off, n):
        return bytes(self.memory[off:off+n])

    def write_mem(self, off, data):
        self.memory[off:off + len(data)] = data
        self.writes.append((off, bytes(data)))


class TagTests(unittest.TestCase):
    def test_original_presets_and_ndef_encoding(self):
        self.assertEqual(set(tag.PRESETS), {'CollarPet / PT35 info', 'Telegram', 'GitHub'})
        for text in ('https://example.org', 'http://example.org', 'Hello there'):
            msg = tag.make_ndef(text)
            decoded = decode_message(msg)
            self.assertTrue(decoded)
            self.assertIn(text, decoded[0])
        with self.assertRaises(ValueError):
            tag.make_ndef('A' * 241)
        with self.assertRaises(ValueError):
            tag.make_ndef('')

    def test_bounds_are_limited_to_16kbit_user_memory(self):
        with self.assertRaises(ValueError):
            tag.check_bounds(-1, 4)
        with self.assertRaises(ValueError):
            tag.check_bounds(2040, 16)
        tag.check_bounds(2040, 8)

    def test_blank_format_reproduces_v14_and_verifies(self):
        fake = FakeI2C()
        with patch.object(tag, 'read_mem', side_effect=fake.read_mem), \
                patch.object(tag, 'write_mem', side_effect=fake.write_mem):
            tag.format_blank_tag()
        self.assertEqual(fake.memory[:11], tag.CC16 + b'\x03\x00\xfe')
        self.assertTrue(all(off < 0x53 for off, _ in fake.writes))

    def test_nonblank_tag_is_not_formatted(self):
        fake = FakeI2C(b'\x11' + bytes(511))
        with patch.object(tag, 'read_mem', side_effect=fake.read_mem), \
                patch.object(tag, 'write_mem', side_effect=fake.write_mem):
            with self.assertRaisesRegex(RuntimeError, 'not blank'):
                tag.format_blank_tag()
        self.assertEqual(fake.writes, [])

    def test_write_has_length_commit_last_and_roundtrip(self):
        fake = FakeI2C(tag.CC16 + b'\x03\x00\xfe' + bytes(501))
        with patch.object(tag, 'read_mem', side_effect=fake.read_mem), \
                patch.object(tag, 'write_mem', side_effect=fake.write_mem):
            length = tag.write_payload('https://example.org')
            self.assertEqual(tag.inspect()['state'], 'ndef')
            self.assertEqual(tag.inspect()['message'], tag.ndef_uri('https://example.org'))
        self.assertEqual(fake.writes[0], (9, b'\x00'))
        self.assertEqual(fake.writes[-1], (9, bytes([length])))

    def test_writer_preserves_unknown_tlv_after_old_record(self):
        raw = bytearray(tag.CC16 + b'\x03\x01\x00\xfd\x01\x05' + bytes(500))
        fake = FakeI2C(raw)
        with patch.object(tag, 'read_mem', side_effect=fake.read_mem), \
                patch.object(tag, 'write_mem', side_effect=fake.write_mem):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected data|occupied memory'):
                tag.write_payload('https://example.org')
        self.assertEqual(fake.writes, [])

    def test_writer_detects_occupied_memory_when_expanding(self):
        raw = bytearray(tag.CC16 + b'\x03\x00\xfe' + bytes(501))
        raw[50] = 0x61
        fake = FakeI2C(raw)
        with patch.object(tag, 'read_mem', side_effect=fake.read_mem), \
                patch.object(tag, 'write_mem', side_effect=fake.write_mem):
            with self.assertRaisesRegex(RuntimeError, 'occupied memory'):
                tag.write_payload('A' * 75)
        self.assertEqual(fake.writes, [])


if __name__ == '__main__':
    unittest.main()
