#!/usr/bin/env python3
"""AS7341 spectrum GUI for PT35. Same sensor acquisition/recovery as pt35_tools.py.

No sensor operations on Tk thread. Reads relative raw counts, NOT calibrated lux,
power, or spectral irradiance. Flicker mode is deliberately not enabled.
"""
import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nfc"))
from nfc_touch import THEMES, Button, font_for, label, FONT, SMALL, LARGE
from pt35_tools import WAVES, make_as7341

WAVE_COLORS = ("#9279e8", "#6987ef", "#4aaee9", "#4dc7b0",
               "#a6d66a", "#e6c75b", "#f6a05f", "#e97b75")
POLL_SECONDS = 0.4


def validate_sample(values, clear, nir):
    """Return normalized raw counts and a quality warning; never fabricate a channel."""
    data = tuple(int(x) for x in values)
    if len(data) != len(WAVES) or any(n < 0 or n > 65535 for n in data):
        raise ValueError("AS7341 must return eight unsigned 16-bit channels")
    clear, nir = int(clear), int(nir)
    if not 0 <= clear <= 65535 or not 0 <= nir <= 65535:
        raise ValueError("Invalid Clear or NIR channel")
    warning = ("Near saturation — reduce illumination or gain" if max(data) >= 65000
               else "Suspicious zero channels — try Recover" if
               data.count(0) >= 2 and max(data) > 1000 else "")
    return {"values": data, "clear": clear, "nir": nir, "warning": warning}


def relative_heights(values, available):
    """Normalize to the strongest current band, without implying absolute irradiance."""
    if not values or available <= 0:
        return (0,) * len(WAVES)
    peak = max(1, *values)
    return tuple(round(max(0, value) / peak * available) for value in values)


class SensorWorker:
    """Sole owner of the AS7341 object and I2C writes for this GUI."""
    def __init__(self, emit, *, factory=None, interval=POLL_SECONDS):
        self.emit = emit
        self.factory = factory or self.default_factory
        self.interval = interval
        self.commands = queue.Queue()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name="pt35-as7341", daemon=True)

    @staticmethod
    def default_factory():
        import board
        import adafruit_as7341
        return make_as7341(board, adafruit_as7341)

    def start(self):
        self.thread.start()

    def send(self, command):
        if command not in ("led", "recover", "pause", "resume", "stop"):
            raise ValueError("Unsupported AS7341 command")
        self.commands.put(command)

    def close(self):
        self.stopped.set()
        self.commands.put("stop")

    def run(self):
        sensor = None
        led_on = False
        paused = False
        errors = 0
        next_sample = 0
        try:
            try:
                sensor = self.factory()
                self.emit({"kind": "state", "text": "Connected · I²C 0x39", "led": False, "paused": False})
            except Exception as exc:
                self.emit({"kind": "error", "text": f"AS7341 initialization: {exc}"})
            while not self.stopped.is_set():
                wait = max(0.02, min(0.15, next_sample - time.monotonic()))
                try:
                    command = self.commands.get(timeout=wait)
                except queue.Empty:
                    command = None
                if command == "stop":
                    break
                if command == "pause":
                    paused = True
                    self.emit({"kind": "state", "text": "Paused", "led": led_on, "paused": True})
                elif command == "resume":
                    paused = False
                    next_sample = 0
                    self.emit({"kind": "state", "text": "Sampling", "led": led_on, "paused": False})
                elif command == "recover":
                    try:
                        if sensor is not None:
                            sensor.led = False
                        sensor = self.factory()  # same tested CFG0/SMUX recovery path
                        led_on = False
                        errors = 0
                        next_sample = 0
                        self.emit({"kind": "state", "text": "Recovered · I²C 0x39",
                                   "led": False, "paused": paused})
                    except Exception as exc:
                        sensor = None
                        self.emit({"kind": "error", "text": f"Recovery failed: {exc}"})
                elif command == "led":
                    if sensor is not None:
                        try:
                            sensor.led = not led_on
                            led_on = not led_on
                            self.emit({"kind": "state", "text": "LED on (4 mA)" if led_on else "LED off",
                                       "led": led_on, "paused": paused})
                        except Exception as exc:
                            self.emit({"kind": "error", "text": f"AS7341 LED control: {exc}"})
                if sensor is None or paused or self.stopped.is_set():
                    continue
                if time.monotonic() < next_sample:
                    continue
                # On repeated errors keep last valid data in GUI and allow recovery.
                try:
                    result = None
                    for attempt in range(3):
                        try:
                            result = validate_sample(sensor.all_channels,
                                                     sensor.channel_clear,
                                                     sensor.channel_nir)
                            break
                        except OSError:
                            errors += 1
                            if attempt < 2:
                                time.sleep(0.04)
                    if result is None:
                        self.emit({"kind": "error", "text": "I²C read failed; retaining last sample",
                                   "errors": errors})
                    else:
                        self.emit({"kind": "sample", **result, "errors": errors})
                except Exception as exc:
                    errors += 1
                    self.emit({"kind": "error", "text": f"AS7341 read: {exc}", "errors": errors})
                next_sample = time.monotonic() + self.interval
        finally:
            if sensor is not None:
                try:
                    sensor.led = False
                except Exception:
                    pass
            self.emit({"kind": "closed"})


class SpectrumWindow(tk.Tk):
    def __init__(self, *, windowed=False, worker_factory=None):
        super().__init__()
        self.title("PT35 · Spectrum Analyzer")
        self.palette = THEMES["dark"]
        self.configure(bg=self.palette.background)
        w, h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(w, 980)}x{min(h, 720)}")
        self.minsize(min(w, 480), min(h, 320))
        self.attributes("-fullscreen", not windowed)
        self.ui_scale = 1
        self.ui_fonts = {}
        self.events = queue.Queue(maxsize=64)
        self.worker = (worker_factory or SensorWorker)(self.offer)
        self.sample = None
        self.led_on = False
        self.paused = False
        self.closing = False
        self.status = tk.StringVar(self, "Connecting to AS7341…")
        self.info = tk.StringVar(self, "Clear —    NIR —    I²C errors 0")
        self.caption = tk.StringVar(self, "Raw relative counts · not calibrated irradiance")
        self.configure_ui()
        self.bind("<Configure>", self.resize_ui, add="+")
        self.bind("<Escape>", lambda _: self.close())
        self.bind("<l>", lambda _: self.worker.send("led"))
        self.bind("<L>", lambda _: self.worker.send("led"))
        self.bind("<z>", lambda _: self.worker.send("recover"))
        self.bind("<Z>", lambda _: self.worker.send("recover"))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.worker.start()
        self.after(75, self.drain)

    def configure_ui(self):
        header = tk.Frame(self, bg=self.palette.background, padx=10, pady=7)
        header.pack(fill="x")
        label(header, "AS7341 · Spectrum", font=LARGE).pack(side="left", fill="x", expand=True)
        Button(header, "Close", self.close).pack(side="right")
        label(self, textvariable=self.caption, font=SMALL, muted=True,
              padx=10).pack(fill="x")
        graph_panel = tk.Frame(self, bg=self.palette.panel, padx=6, pady=5)
        graph_panel.pack(fill="both", expand=True, padx=10, pady=(6, 4))
        self.graph = tk.Canvas(graph_panel, bg=self.palette.panel, highlightthickness=0,
                               height=220)
        self.graph.pack(fill="both", expand=True)
        label(self, textvariable=self.info, font=FONT, padx=10).pack(fill="x", pady=(1, 3))
        buttons = tk.Frame(self, bg=self.palette.background, padx=8)
        buttons.pack(fill="x", pady=3)
        self.led_button = Button(buttons, "Sensor LED · OFF", lambda: self.worker.send("led"))
        self.pause_button = Button(buttons, "Pause", self.toggle_pause)
        self.recover_button = Button(buttons, "Recover", lambda: self.worker.send("recover"))
        for index, button in enumerate((self.led_button, self.pause_button, self.recover_button)):
            buttons.grid_columnconfigure(index, weight=1, uniform="controls")
            button.grid(row=0, column=index, sticky="nsew", padx=2)
        label(self, textvariable=self.status, font=SMALL, muted=True, padx=10,
              wraplength=900).pack(fill="x", pady=(2, 6))
        self.graph.bind("<Configure>", lambda _: self.draw_graph())
        self.draw_graph()

    def resize_ui(self, event):
        if event.widget is not self:
            return
        scale = max(1, min(1.7, event.width / 640, event.height / 480))
        if abs(scale - self.ui_scale) > .04:
            self.ui_scale = scale
            for spec, font in self.ui_fonts.items():
                font.configure(size=round(spec[1] * scale))

    def draw_graph(self):
        canvas = self.graph
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 320), max(canvas.winfo_height(), 140)
        top, bottom = 14, height - 46
        left, right = 8, width - 8
        if bottom <= top:
            return
        for step in range(5):
            y = bottom - (bottom - top) * step / 4
            canvas.create_line(left, y, right, y, fill=self.palette.border if step == 0 else "#304351",
                               dash=() if step == 0 else (2, 7))
        data = self.sample["values"] if self.sample else (0,) * 8
        heights = relative_heights(data, bottom - top)
        column = (right - left) / len(WAVES)
        for i, (nm, value, extent) in enumerate(zip(WAVES, data, heights)):
            center = left + (i + .5) * column
            half = max(5, column * .28)
            canvas.create_rectangle(center - half, bottom - extent, center + half, bottom,
                                    fill=WAVE_COLORS[i], outline="")
            canvas.create_text(center, bottom + 14, text=str(nm),
                               fill=self.palette.text, font=("DejaVu Sans", 10))
            canvas.create_text(center, bottom + 30, text=str(value) if self.sample else "—",
                               fill=self.palette.muted, font=("DejaVu Sans", 9))
        if self.sample is None:
            canvas.create_text(width / 2, (top + bottom) / 2, text="Waiting for spectral data…",
                               fill=self.palette.text, font=("DejaVu Sans", 14))
        else:
            peak = max(self.sample["values"])
            canvas.create_text(right, top, text=f"Peak {peak} counts", fill=self.palette.muted,
                               anchor="ne", font=("DejaVu Sans", 9))

    def offer(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full:
            # Drop stale frames rather than blocking I2C acquisition or Tk.
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.events.put_nowait(event)
            except queue.Full:
                pass

    def drain(self):
        if self.closing:
            return
        for _ in range(20):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event["kind"]
            if kind == "sample":
                self.sample = event
                self.info.set(f"Clear {event['clear']:>5}    NIR {event['nir']:>5}    "
                              f"I²C errors {event['errors']}")
                self.status.set(event["warning"] or "Live · 8 spectral channels at ~2.5 Hz")
                self.draw_graph()
            elif kind == "state":
                self.led_on = event["led"]
                self.paused = event["paused"]
                self.led_button.configure(text=f"Sensor LED · {'ON' if self.led_on else 'OFF'}")
                self.pause_button.configure(text="Resume" if self.paused else "Pause")
                self.status.set(event["text"])
            elif kind == "error":
                self.status.set(event["text"])
        self.after(75, self.drain)

    def toggle_pause(self):
        self.worker.send("resume" if self.paused else "pause")

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.status.set("Stopping sensor · switching illumination LED off…")
        self.worker.close()
        self.shutdown_started = time.monotonic()
        self.after(60, self.finish_close)

    def finish_close(self):
        # Let the sensor owner thread disable its LED before the GUI process exits.
        if self.worker.thread.is_alive() and time.monotonic() - self.shutdown_started < 3:
            self.after(60, self.finish_close)
            return
        self.destroy()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--windowed", action="store_true")
    options = ap.parse_args(argv)
    SpectrumWindow(windowed=options.windowed).mainloop()


if __name__ == "__main__":
    main()
