"""Exercise protocol parsers with synthetic responses."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'nfc'))

from nfc_ndef import decode_message, extract_message, ndef_area
from nfc_poll import crc_a, poll_a, poll_b, poll_f, read_ntag
from nfcv_dump import Reader
from nfcv_scan import FrameError, crc15693


class Radio:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def wr(self, *args):
        pass

    def transceive(self, data, *args, **kwargs):
        self.requests.append(data)
        return next(self.replies), 0, 0


def append_crc(data, checksum=crc_a):
    return data + checksum(data).to_bytes(2, 'little')


class PollTests(unittest.TestCase):
    def test_nfc_a_cascade(self):
        radio = Radio([b'\x44\x00', bytes.fromhex('88041122BF'), append_crc(b'\x04'),
                       bytes.fromhex('3344556644'), append_crc(b'\x00')])
        self.assertEqual(poll_a(radio)[0], '04112233445566')
        self.assertIn(bytes.fromhex('937088041122BF'), radio.requests)

    def test_nfc_a_rejects_bad_bcc(self):
        with self.assertRaisesRegex(FrameError, 'BCC'):
            poll_a(Radio([bytes(2), bytes.fromhex('0411223300')]))

    def test_nfc_b_atqb(self):
        radio = Radio([append_crc(bytes.fromhex('5011223344') + bytes(7), crc15693)])
        self.assertEqual(poll_b(radio)[0], '11223344')

    def test_nfc_f_poll(self):
        radio = Radio([bytes.fromhex('14010102030405060708') + bytes(8) + bytes.fromhex('12FC0000')])
        self.assertEqual(poll_f(radio)[1]['system_code'], '12FC')

    def test_ntag215_stops_at_last_user_page(self):
        header = bytes.fromhex('041122003344556600000000E1103E00')
        radio = Radio([append_crc(bytes.fromhex('0004040201001103')), append_crc(header)] +
                      [append_crc(bytes(16))] * 32)
        record = read_ntag(radio, '04112233445566', {'sak': 0})
        self.assertTrue(record['addressable_memory_complete'])
        self.assertEqual(len(record['blocks']), 126)
        self.assertEqual(record['blocks'][-1]['index'], 129)
        self.assertEqual(radio.requests[-1], bytes((0x30, 126)))

    def test_ndef_text_and_truncation(self):
        message = bytes.fromhex('D101055402656E4869')
        area = ndef_area({'protocol': 'NFC-A', 'cc': 'E1101200'},
                         bytes((3, len(message))) + message + b'\xfe')
        self.assertEqual(decode_message(extract_message(area)), ['Text: Hi'])
        self.assertEqual(decode_message(message[:-1]), [])

    def test_st25dv_extended_geometry_and_address(self):
        uid = 'E002000000000000'
        air = bytes.fromhex(uid)[::-1]
        requests = []

        class Tag(Reader):
            def exchange(self, payload, *args, **kwargs):
                requests.append(payload)
                return {0x2b: b'\x00\x08' + air + b'\x26',
                        0x3b: b'\x00\x14' + air + b'\xff\x01\x03',
                        0x30: bytes(5)}[payload[1]]

        tag = Tag(None)
        self.assertEqual(tag.system_info(uid)['geometry']['blocks'], 512)
        self.assertEqual(tag.read_single(uid, 511), bytes(4))
        self.assertEqual(requests[1], b'\x22\x3b\x14' + air)
        self.assertEqual(requests[2], b'\x22\x30' + air + b'\xff\x01')
