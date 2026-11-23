"""Offline coverage for the opt-in generic NFC Forum Type 2 reader."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from pi5_type2_reader import read_type2


class FrameError(Exception):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def failure(exc):
    return {"kind": getattr(exc, "kind", "io"), "error": str(exc)}


def coverage(rec, count, geometry, start=0):
    rec["dump_status"] = (
        "addressable_memory_complete" if len(rec["blocks"]) == geometry["blocks"]
        else "partial" if rec["blocks"] else "failed"
    )


class Type2Tests(unittest.TestCase):
    uid = "530B82D0330001"

    def simulate(self, cc=bytes.fromhex("E1101200"), fail=None):
        seen = []
        header = bytes.fromhex("530B8200D033000100000000") + cc

        def receive(_chip, data, *, checksum):
            page = data[1]
            seen.append(page)
            if page == fail:
                raise FrameError("crc", "simulated corrupted response")
            if page == 0:
                return header
            return b"".join(bytes((i & 255, 1, 2, 3)) for i in range(page, page+4))

        result = read_type2(
            None, self.uid, {"sak": 0}, progress=None, receive=receive,
            crc_a=lambda x: 0, set_coverage=coverage, failure=failure,
            frame_error=FrameError,
        )
        return result, seen

    def test_generic_type2_with_7_byte_uid(self):
        result, seen = self.simulate()
        self.assertEqual(result["dump_status"], "addressable_memory_complete")
        self.assertEqual(len(result["blocks"]), 36)
        self.assertEqual([b["index"] for b in result["blocks"]], list(range(4, 40)))
        self.assertEqual(result["cc"], "E1101200")
        self.assertEqual(seen[0], 0)

    def test_crc_error_preserves_partial(self):
        result, _ = self.simulate(fail=8)
        self.assertEqual(result["dump_status"], "partial")
        self.assertTrue(result["read_errors"])

    def test_non_type2_not_read(self):
        calls = []
        def receive(*a, **kw):
            calls.append(1)
            return b""
        result = read_type2(
            None, self.uid, {"sak": 0x20}, progress=None, receive=receive,
            crc_a=lambda x: 0, set_coverage=coverage, failure=failure,
            frame_error=FrameError,
        )
        self.assertEqual(result["read_capability"], "discovery_only")
        self.assertFalse(calls)

    def test_bad_cc_not_claimed_full(self):
        result, _ = self.simulate(cc=b"\x00\x00\x00\x00")
        self.assertEqual(result["read_capability"], "type2_cc_missing_or_unsupported")
        self.assertEqual(result["blocks"], [])


if __name__ == "__main__":
    unittest.main()
