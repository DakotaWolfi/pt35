#!/usr/bin/env python3
"""PT35 RadiaCode companion: read-only telemetry and optional spectrum snapshots."""
import argparse
import csv
import json
import queue
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("received_utc", "device_time", "record_type", "count_rate_cps",
          "dose_rate_protocol", "count_rate_err_pct", "dose_rate_err_pct",
          "flags", "temperature_c", "battery_pct", "event")
DEFAULT_DIR = Path.home() / ".local/share/pt35/radiacode"

def timestamp(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return ""

def normalize(record):
    """Preserve device timestamps and distinguish raw, status and event records."""
    kind = type(record).__name__
    row = dict.fromkeys(FIELDS, "")
    row["received_utc"] = datetime.now(timezone.utc).isoformat()
    row["device_time"] = timestamp(getattr(record, "dt", None))
    row["record_type"] = kind
    for source, dest in (("count_rate", "count_rate_cps"),
                         ("dose_rate", "dose_rate_protocol"),
                         ("count_rate_err", "count_rate_err_pct"),
                         ("dose_rate_err", "dose_rate_err_pct"),
                         ("flags", "flags"), ("temperature", "temperature_c"),
                         ("charge_level", "battery_pct")):
        val = getattr(record, source, None)
        if val is not None:
            row[dest] = val
    if kind == "Event":
        row["event"] = str(getattr(record, "event", ""))
    return row

def spectrum_row(spectrum, previous=None):
    """Return a timestamped cumulative snapshot and interval DELTA when valid."""
    counts = list(spectrum.counts)
    elapsed = spectrum.duration.total_seconds()
    delta = None
    if previous is not None:
        old_duration, old_counts = previous
        if elapsed > old_duration and len(counts) == len(old_counts) and all(
                a >= b for a, b in zip(counts, old_counts)):
            delta = [a - b for a, b in zip(counts, old_counts)]
    result = {"captured_utc": datetime.now(timezone.utc).isoformat(),
              "duration_s": elapsed, "calibration_keV": [spectrum.a0, spectrum.a1, spectrum.a2],
              "counts_cumulative": counts, "counts_delta": delta,
              "delta_valid": delta is not None,
              "note": "Host-polled spectrum; not per-photon timestamps. Delta is between reads."}
    return result, (elapsed, counts)

class Recorder:
    def __init__(self, dest):
        self.dest = Path(dest)
        self.csv_file = None
        self.json_file = None
        self.writer = None

    def start(self):
        self.dest.mkdir(parents=True, exist_ok=True)
        stem = datetime.now().strftime("radiacode_%Y%m%d_%H%M%S_%f")
        self.csv_file = (self.dest / (stem + "_telemetry.csv")).open("x", newline="", encoding="utf-8")
        self.json_file = (self.dest / (stem + "_spectra.jsonl")).open("x", encoding="utf-8")
        self.writer = csv.DictWriter(self.csv_file, fieldnames=FIELDS)
        self.writer.writeheader()
        return stem

    def telemetry(self, data):
        self.writer.writerow(normalize(data))
        self.csv_file.flush()

    def spectrum(self, data):
        self.json_file.write(json.dumps(data, separators=(",", ":")) + "\n")
        self.json_file.flush()

    def close(self):
        for handle in (self.csv_file, self.json_file):
            if handle:
                handle.close()
        self.csv_file = self.json_file = None

class Worker:
    """Only this thread touches the USB/BLE device, never Tk."""
    def __init__(self, emit, *, address=None, interval=1.0, output=DEFAULT_DIR, factory=None):
        self.emit, self.address, self.interval = emit, address, interval
        self.output, self.factory = output, factory
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
    def start(self):
        self.thread.start()
    def close(self):
        self.stop_event.set()
    def run(self):
        recorder = Recorder(self.output)
        try:
            if self.factory is None:
                from radiacode import RadiaCode
                self.factory = RadiaCode
            kwargs = {"bluetooth_mac": self.address} if self.address else {}
            self.emit({"kind": "state", "text": "Connecting via BLE" if self.address else "Connecting via USB"})
            with self.factory(**kwargs) as device:
                self.emit({"kind": "state", "text": "Connected — read-only"})
                stem = recorder.start()
                self.emit({"kind": "file", "text": str(Path(self.output) / stem)})
                previous = None
                while not self.stop_event.is_set():
                    started = time.monotonic()
                    for sample in device.data_buf():
                        recorder.telemetry(sample)
                        if hasattr(sample, "count_rate") and hasattr(sample, "dose_rate"):
                            self.emit({"kind": "sample", "data": normalize(sample)})
                    # Device spectrum is cumulative, so preserve both full and delta.
                    current = device.spectrum()
                    data, previous = spectrum_row(current, previous)
                    recorder.spectrum(data)
                    self.emit({"kind": "spectrum", "counts": sum(current.counts),
                               "delta": sum(data["counts_delta"]) if data["delta_valid"] else None})
                    self.stop_event.wait(max(0.0, self.interval - (time.monotonic() - started)))
        except Exception as exc:
            self.emit({"kind": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            recorder.close()
            self.emit({"kind": "state", "text": "Disconnected"})

class App(tk.Tk):
    def __init__(self, address=None, interval=1.0, output=DEFAULT_DIR, windowed=False):
        super().__init__()
        self.title("PT35 · RadiaCode 103")
        self.configure(bg="#101c29")
        self.geometry("640x480")
        if not windowed:
            self.attributes("-fullscreen", True)
        self.values = deque(maxlen=180)
        self.messages = queue.Queue()
        self.worker = None
        self.address, self.interval, self.output = address, interval, output
        self.state = tk.StringVar(value="Disconnected")
        self.reading = tk.StringVar(value="— CPS")
        self.dose = tk.StringVar(value="— dose rate (protocol units)")
        self.counter = tk.StringVar(value="No spectrum yet")
        self.file_info = tk.StringVar(value="CSV + JSONL saved to " + str(output))
        title = tk.Label(self, text="☢  RadiaCode 103", bg="#101c29", fg="#e4eef7",
                         font=("DejaVu Sans", 19, "bold"))
        title.pack(pady=(8, 3))
        for var, size in ((self.reading, 22), (self.dose, 14), (self.counter, 11),
                          (self.state, 11)):
            tk.Label(self, textvariable=var, bg="#101c29", fg="#68d5c3",
                     font=("DejaVu Sans", size)).pack()
        self.graph = tk.Canvas(self, bg="#142638", highlightthickness=0, height=120)
        self.graph.pack(fill="both", expand=True, padx=12, pady=6)
        buttons = tk.Frame(self, bg="#101c29")
        buttons.pack(fill="x", padx=12, pady=4)
        for label, command in (("Start", self.start), ("Stop", self.stop), ("Close", self.close)):
            tk.Button(buttons, text=label, command=command, bg="#244253",
                      fg="#ffffff", font=("DejaVu Sans", 12), height=2).pack(
                          side="left", fill="x", expand=True, padx=4)
        tk.Label(self, textvariable=self.file_info, wraplength=590, bg="#101c29",
                 fg="#9db3c4", font=("DejaVu Sans", 8)).pack(pady=(0, 6))
        self.bind("<Escape>", lambda _: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.consume)
    def start(self):
        if self.worker and self.worker.thread.is_alive():
            return
        self.values.clear()
        self.worker = Worker(self.messages.put, address=self.address,
                             interval=self.interval, output=self.output)
        self.worker.start()
    def stop(self):
        if self.worker:
            self.worker.close()
            self.state.set("Stopping…")
    def close(self):
        self.stop()
        self.destroy()
    def consume(self):
        try:
            while True:
                item = self.messages.get_nowait()
                kind = item["kind"]
                if kind in ("state", "error"):
                    self.state.set(item["text"])
                elif kind == "file":
                    self.file_info.set("Recording: " + item["text"] + "_*")
                elif kind == "sample":
                    row = item["data"]
                    cps = row["count_rate_cps"]
                    dose = row["dose_rate_protocol"]
                    self.reading.set(f"{float(cps):.1f} CPS")
                    self.dose.set(f"Dose rate: {dose} (device protocol units)")
                    self.values.append(float(cps))
                    self.draw()
                elif kind == "spectrum":
                    self.counter.set(f"Cumulative spectrum: {item['counts']:,} counts | "
                                     f"interval: {item['delta'] if item['delta'] is not None else '—'}")
        except queue.Empty:
            pass
        self.after(100, self.consume)
    def draw(self):
        canvas = self.graph
        canvas.delete("all")
        w, h = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if len(self.values) < 2:
            return
        peak = max(1, max(self.values))
        pts = []
        for i, y in enumerate(self.values):
            pts.extend([i * (w - 12) / max(1, len(self.values) - 1) + 6,
                        h - 8 - y / peak * (h - 18)])
        canvas.create_line(*pts, fill="#68d5c3", width=2)
        canvas.create_text(w - 8, 8, anchor="ne", text=f"Scale: {peak:.1f} CPS",
                           fill="#b1c5d4", font=("DejaVu Sans", 9))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bluetooth-mac", help="BLE MAC address; omit for USB")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args()
    if not .25 <= args.interval <= 600:
        parser.error("interval must be between 0.25 and 600 seconds")
    app = App(args.bluetooth_mac, args.interval, args.output, args.windowed)
    app.mainloop()

if __name__ == "__main__":
    main()
