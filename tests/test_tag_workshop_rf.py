"""Offline tests for read-only CRC retry and stage-specific diagnostics."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from tag_workshop_rf import read_all


class RFError(Exception):
    def __init__(self, kind, detail):
        self.kind = kind
        super().__init__(detail)


class FakeReader:
    rf_state = {"irq_error": 0x80}


def simulate(page_failures=None, poll_failures=0):
    failures = dict(page_failures or {})
    calls = []
    ident = bytes.fromhex("530B8200D033000100000000E1101200")
    def poll(chip):
        nonlocal poll_failures
        if poll_failures:
            poll_failures -= 1
            raise RFError("crc", "RF receive error 0x80")
        return "530B82D0330001", {"sak": 0, "atqa": "0044"}
    def receive(chip, command, *, checksum):
        page = command[1]
        calls.append(page)
        if failures.get(page, 0):
            failures[page] -= 1
            raise RFError("crc", "RF receive error 0x80")
        if page == 0:
            return ident
        return bytes(16)
    return poll, receive, calls


class RFStageTests(unittest.TestCase):
    def test_single_page_crc_recovers_and_reads_all(self):
        poll, receive, calls = simulate({8: 1}, poll_failures=1)
        result = read_all(FakeReader(), poll, receive, lambda x: 0, RFError)
        self.assertEqual(result["capacity"], 144)
        self.assertEqual(len(result["data"]), 144)
        self.assertEqual(calls.count(8), 2)

    def test_persistent_crc_names_page(self):
        poll, receive, calls = simulate({8: 3})
        with self.assertRaisesRegex(RuntimeError, r"READ page 8.*0x80"):
            read_all(FakeReader(), poll, receive, lambda x: 0, RFError)
        self.assertEqual(calls.count(8), 3)

    def test_failed_select_reports_stage(self):
        poll, receive, calls = simulate(poll_failures=4)
        with self.assertRaisesRegex(RuntimeError, r"NFC-A anticollision/selection.*0x80"):
            read_all(FakeReader(), poll, receive, lambda x: 0, RFError)


if __name__ == "__main__":
    unittest.main()
