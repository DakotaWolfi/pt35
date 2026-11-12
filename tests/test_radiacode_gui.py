"""Offline RadiaCode serialization tests; no physical detector or GUI required."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from radiacode_gui import normalize, spectrum_row

def spectrum(counts, seconds):
    return SimpleNamespace(counts=counts, duration=timedelta(seconds=seconds),
                           a0=6.7, a1=2.3, a2=0.0003)

class TestRadiaCode(unittest.TestCase):
    def test_timestamped_record(self):
        Record = type("RealTimeData", (), {})
        value = Record()
        value.dt = datetime(2026, 5, 22, 9, 48, 19)
        value.count_rate = 123.4
        value.dose_rate = 0.51
        value.flags = 3
        value.count_rate_err = 2
        value.dose_rate_err = 4
        row = normalize(value)
        self.assertEqual(row["device_time"], "2026-05-22T09:48:19")
        self.assertEqual(row["count_rate_cps"], 123.4)
        self.assertEqual(row["flags"], 3)

    def test_valid_delta_and_cumulative(self):
        first, old = spectrum_row(spectrum([3, 4], 10))
        self.assertIsNone(first["counts_delta"])
        second, _ = spectrum_row(spectrum([7, 6], 11), old)
        self.assertEqual(second["counts_delta"], [4, 2])
        self.assertEqual(second["counts_cumulative"], [7, 6])

    def test_reset_or_bad_time_invalidates_delta(self):
        _, old = spectrum_row(spectrum([10, 12], 10))
        self.assertFalse(spectrum_row(spectrum([1, 1], 11), old)[0]["delta_valid"])
        self.assertFalse(spectrum_row(spectrum([12, 13], 10), old)[0]["delta_valid"])

if __name__ == "__main__":
    unittest.main()
