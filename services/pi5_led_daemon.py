#!/usr/bin/env python3
"""PT35 Pi 5 NeoPixel daemon; Adafruit RP1 PIO, configurable LEDs on BCM GPIO18.
Only start after verifying hardware wiring and /dev/pio0. Default output OFF.
Unix socket protocol compatible with the old PT35 LED controls:
off, idle, rainbow, battery, color R G B, flash R G B, status.
"""
import math
import os
import socket
import threading
import time
from pathlib import Path

import board
from adafruit_raspberry_pi5_neopixel_write import neopixel_write

COUNT = int(os.getenv("PT35_LED_COUNT", "16"))
if not 1 <= COUNT <= 256:
    raise SystemExit("PT35_LED_COUNT must be 1..256")
GPIO = int(os.getenv("PT35_LED_GPIO", "18"))
SOCKET = os.getenv("PT35_LED_SOCKET", f"/run/user/{os.getuid()}/pt35-led.sock")
BRIGHTNESS = min(max(float(os.getenv("PT35_LED_BRIGHTNESS", "0.15")), 0.0), 0.30)
PIN = getattr(board, f"D{GPIO}")
DEFAULT_MODE = os.getenv("PT35_LED_IDLE_MODE", "off").strip().lower()
if DEFAULT_MODE not in ("off", "idle", "rainbow"):
    DEFAULT_MODE = "off"
mode = DEFAULT_MODE
color = (0, 0, 0)
lock = threading.RLock()
running = True


def send(pixels):
    # WS2812: buffer is GRB byte order; PIO backend handles timing.
    output = bytearray()
    for r, g, b in pixels:
        output.extend((int(g*BRIGHTNESS), int(r*BRIGHTNESS), int(b*BRIGHTNESS)))
    neopixel_write(PIN, output)


def solid(rgb):
    send([rgb] * COUNT)


def gradient(phase):
    out = []
    for index in range(COUNT):
        hue = (phase + index / max(COUNT, 1)) % 1.0
        k = int(hue*6)
        f = hue*6-k
        v = int(120)
        choices = [(v,int(f*v),0),(int((1-f)*v),v,0),
                   (0,v,int(f*v)),(0,int((1-f)*v),v),
                   (int(f*v),0,v),(v,0,int((1-f)*v))]
        out.append(choices[k % 6])
    send(out)


def battery():
    for supply in Path("/sys/class/power_supply").glob("*"):
        try:
            if (supply/"type").read_text().strip() != "Battery":
                continue
            soc = max(0, min(100, int((supply/"capacity").read_text())))
            n = int(round(COUNT*soc/100))
            rgb = (130,0,0) if soc <= 15 else (120,65,0) if soc <= 40 else (0,120,20)
            send([rgb if i < n else (0,0,0) for i in range(COUNT)])
            return f"OK battery {soc}%"
        except (OSError, ValueError):
            pass
    return "ERR no battery power_supply"


def animate():
    phase = 0.0
    last = None
    while running:
        with lock:
            current = mode
            current_color = color
        if current == "idle":
            # Original Pi4 breathing effect, including the per-pixel offset.
            level = int((math.sin(phase) + 1.0) * 10)
            send([(level // 2, 0, level + ((i * 4) % 16) // 4)
                  for i in range(COUNT)])
        elif current == "rainbow":
            gradient(phase)
        elif current == "solid":
            if last != (current, current_color):
                solid(current_color)
        elif current == "off" and last != (current, current_color):
            solid((0,0,0))
        last = (current, current_color)
        phase = (phase + (0.08 if current == "idle" else 0.004)) % (2 * math.pi)
        time.sleep(.05 if current == "idle" else .04)


def command(line):
    global mode, color
    parts = line.strip().split()
    if not parts:
        return "ERR empty command"
    cmd = parts[0].lower()
    with lock:
        if cmd in ("off", "idle", "rainbow") and len(parts) == 1:
            mode = cmd
            return f"OK {mode}"
        if cmd == "status":
            return f"OK mode={mode} count={COUNT} gpio={GPIO} brightness={BRIGHTNESS}"
        if cmd == "pixel" and len(parts) == 5:
            try:
                n = int(parts[1])
                rgb = tuple(max(0, min(255, int(x))) for x in parts[2:])
            except ValueError:
                return "ERR expected pixel N R G B"
            if not 1 <= n <= COUNT:
                return f"ERR pixel index 1..{COUNT}"
            mode = "hold"
            pixels = [(0, 0, 0)] * COUNT
            pixels[n - 1] = rgb
            send(pixels)
            return f"OK pixel {n}/{COUNT}"
        if cmd == "segment" and len(parts) == 2:
            try:
                n = int(parts[1])
            except ValueError:
                return "ERR expected segment 1..N"
            if not 1 <= n <= (COUNT + 7) // 8:
                return f"ERR segment index 1..{(COUNT + 7) // 8}"
            # Low-power R/G/B rows; each segment is eight LEDs.
            rgb = ((45,0,0), (0,45,0), (0,0,45))[(n-1) % 3]
            mode = "hold"
            send([rgb if (i // 8) == n-1 else (0,0,0)
                  for i in range(COUNT)])
            return f"OK segment {n} pixels {(n-1)*8+1}..{min(COUNT,n*8)}"
        if cmd == "color" and len(parts) == 4:
            try:
                color = tuple(max(0,min(255,int(x))) for x in parts[1:])
            except ValueError:
                return "ERR invalid rgb"
            mode = "solid"
            return "OK color"
        if cmd in ("battery", "flash") :
            prev = mode
            mode = "hold"
            try:
                if cmd == "battery":
                    result = battery()
                    time.sleep(1.2)
                elif len(parts) == 4:
                    rgb = tuple(max(0,min(255,int(x))) for x in parts[1:])
                    solid(rgb)
                    time.sleep(.16)
                    result = "OK flash"
                else:
                    result = "ERR expected flash R G B"
                return result
            except (ValueError, OSError) as exc:
                return f"ERR {exc}"
            finally:
                mode = prev
        return "ERR unknown command"


def main():
    path = Path(SOCKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # Never unlink a socket belonging to a running daemon.
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(0.25)
            try:
                probe.connect(str(path))
                raise SystemExit("PT35 LED daemon already running at " + str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(4)
        server.settimeout(1)
        worker = threading.Thread(target=animate, daemon=True)
        worker.start()
        try:
            while True:
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    data=conn.recv(256).decode("ascii", errors="ignore")
                    with lock:
                        reply=command(data)
                    conn.sendall((reply+"\n").encode())
        finally:
            global running
            running=False
            worker.join(timeout=1)
            solid((0,0,0))
            path.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
