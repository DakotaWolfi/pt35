"""Offline tests for AS7341 GUI validation and sensor-thread ownership."""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import as7341_gui as spectrum


class FakeSensor:
    def __init__(self):
        self.led = False
        self.read_count = 0

    @property
    def all_channels(self):
        self.read_count += 1
        return (12, 15, 50, 90, 100, 60, 30, 10)

    @property
    def channel_clear(self):
        return 150

    @property
    def channel_nir(self):
        return 40


class SpectrumTests(unittest.TestCase):
    def test_channel_validation_and_count_warning(self):
        sample = spectrum.validate_sample(range(8), 120, 60)
        self.assertEqual(sample["values"], tuple(range(8)))
        self.assertEqual(sample["clear"], 120)
        self.assertEqual(sample["nir"], 60)
        with self.assertRaises(ValueError):
            spectrum.validate_sample((1, 2, 3), 4, 5)
        with self.assertRaises(ValueError):
            spectrum.validate_sample((0,) * 7 + (70000,), 10, 10)
        warning = spectrum.validate_sample((0, 0, 5000, 4000, 3000, 2000, 1000, 600), 500, 500)
        self.assertIn("zero", warning["warning"])

    def test_all_ten_gauges_are_in_requested_order(self):
        self.assertEqual(spectrum.GAUGE_LABELS,
                         ("Clear", "415", "445", "480", "515", "555",
                          "590", "630", "680", "NIR"))
        self.assertEqual(spectrum.GAUGE_COLORS[0], "#f2f7fb")
        self.assertEqual(spectrum.GAUGE_COLORS[-1], "#f07dc6")
        sample = spectrum.validate_sample(range(8), 111, 222)
        self.assertEqual(spectrum.gauge_values(sample),
                         (111, 0, 1, 2, 3, 4, 5, 6, 7, 222))
        self.assertEqual(spectrum.gauge_values(None), (0,) * 10)

    def test_graph_heights_are_only_relative(self):
        self.assertEqual(spectrum.relative_heights([0] * 8, 100), (0,) * 8)
        heights = spectrum.relative_heights([10, 20, 40, 80, 100, 0, 0, 0], 80)
        self.assertEqual(heights[4], 80)
        self.assertEqual(heights[5], 0)
        self.assertEqual(len(heights), 8)

    def test_worker_samples_and_disables_led_on_close(self):
        events = queue.Queue()
        sensor = FakeSensor()
        worker = spectrum.SensorWorker(events.put, factory=lambda: sensor, interval=.06)
        worker.start()
        try:
            deadline = time.monotonic() + 2
            while not sensor.read_count and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertGreater(sensor.read_count, 0)
            worker.send("led")
            deadline = time.monotonic() + 2
            while not sensor.led and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(sensor.led)
        finally:
            worker.close()
            worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())
        self.assertFalse(sensor.led)
        self.assertTrue(any(item["kind"] == "sample" for item in list(events.queue)))

    def test_worker_recover_reinitializes_and_turns_off_led(self):
        sensors = []
        events = queue.Queue()
        def factory():
            sensor = FakeSensor()
            sensors.append(sensor)
            return sensor
        worker = spectrum.SensorWorker(events.put, factory=factory, interval=.06)
        worker.start()
        try:
            deadline = time.monotonic() + 2
            while len(sensors) < 1 and time.monotonic() < deadline:
                time.sleep(.01)
            worker.send("led")
            deadline = time.monotonic() + 2
            while not sensors[0].led and time.monotonic() < deadline:
                time.sleep(.01)
            worker.send("recover")
            deadline = time.monotonic() + 2
            while len(sensors) < 2 and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(len(sensors), 2)
            self.assertFalse(sensors[0].led)
        finally:
            worker.close()
            worker.thread.join(2)
        self.assertFalse(sensors[-1].led)

    def test_invalid_worker_commands_refused(self):
        worker = spectrum.SensorWorker(lambda _: None, factory=FakeSensor)
        with self.assertRaises(ValueError):
            worker.send("flicker")


if __name__ == "__main__":
    unittest.main()
