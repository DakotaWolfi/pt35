#!/usr/bin/env python3
"""Single-owner renderer for the PT35 rear LED strip and its Unix socket."""
import argparse
import fcntl
import math
import os
import re
import signal
import socket
import socketserver
import stat
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

LED_COUNT = 16
LED_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 64
LED_INVERT = False
LED_CHANNEL = 0

SOCKET_PATH = '/run/pt35-led.sock'
HARDWARE_LOCK = '/run/pt35-led.lock'
FRAME_SECONDS = .04
LEASE_SECONDS = 2
MAX_NFC_BRIGHTNESS = 32
INDEX_SECONDS = .24
COLUMNS = tuple((column, 15 - column) for column in range(8))
TOP_ROW = tuple(range(8))
BOTTOM_LEFT_TO_RIGHT = tuple(range(15, 7, -1))
PROTOCOL_COLORS = {'ISO15693': (0, 2, 4), 'NFC-A': (0, 4, 1),
                   'NFC-B': (4, 2, 0), 'NFC-F': (3, 0, 4),
                   'LF': (4, 0, 1)}
BLACK = ((0, 0, 0),) * LED_COUNT
EFFECTS = {'sweep', 'pulse', 'minimal'}
STAGES = {'scan', 'read', 'success', 'partial', 'error'}


def battery_sysfs():
    try:
        for device in Path('/sys/class/power_supply').iterdir():
            capacity = device / 'capacity'
            if capacity.exists():
                soc = float(capacity.read_text())
                voltage = device / 'voltage_now'
                return soc, float(voltage.read_text()) / 1_000_000 if voltage.exists() else None
    except (OSError, ValueError):
        pass
    return None, None


def get_battery():
    soc, voltage = battery_sysfs()
    if soc is not None:
        return soc, voltage
    try:
        from smbus2 import SMBus

        with SMBus(1) as bus:
            soc = bus.read_byte_data(0x36, 0x04) + bus.read_byte_data(0x36, 0x05) / 256
            raw = (bus.read_byte_data(0x36, 0x02) << 8) | bus.read_byte_data(0x36, 0x03)
            return soc, (raw >> 4) * .00125
    except (ImportError, OSError):
        return None, None


def lra(effect):
    try:
        subprocess.run(['/usr/local/bin/lra_ctl', 'play', str(effect)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def wheel(position):
    pos = position & 255
    if pos < 85:
        return pos * 3, 255 - pos * 3, 0
    if pos < 170:
        pos -= 85
        return 255 - pos * 3, 0, pos * 3
    pos -= 170
    return 0, pos * 3, 255 - pos * 3


@dataclass(frozen=True)
class Lease:
    token: str
    effect: str
    brightness: int
    stage: str
    completed: int
    total: int
    expires: float
    protocol: str = 'none'
    rssi: int = -1


def nfc_frame(lease, now):
    """Top 8 pixels: scan/progress; bottom 8: tag type and optional relative RSSI.

    RSSI is a 4-bit receiver peak measurement, not calibrated field strength.
    Absent RSSI only illuminates one dim bottom type marker; never fake bars.
    """
    brightness = lease.brightness
    frame = list(BLACK)
    if lease.stage == 'read' and lease.total:
        # Real completed blocks; floor avoids displaying completion prematurely.
        count = lease.completed * len(TOP_ROW) // lease.total
        for i in TOP_ROW[:count]:
            frame[i] = (0, brightness, max(1, brightness // 4))
    elif lease.stage in ('success', 'partial', 'error'):
        color = {'success': (0, brightness, 0),
                 'partial': (brightness, brightness // 3, 0),
                 'error': (brightness, 0, 0)}[lease.stage]
        for i in TOP_ROW:
            frame[i] = color
    elif lease.effect == 'minimal':
        frame[0] = (0, 0, max(1, brightness // 3))
    elif lease.effect == 'pulse':
        level = max(1, int(brightness * (.45 + .35 * math.sin(now * 4))))
        for i in TOP_ROW:
            frame[i] = (0, level // 4, level)
    else:
        head = int(now * 9) % len(TOP_ROW)
        frame[head] = (0, brightness // 5, brightness)
        frame[(head - 1) % 8] = (0, 0, brightness // 3)

    if lease.protocol in PROTOCOL_COLORS:
        base = PROTOCOL_COLORS[lease.protocol]
        # Use brightness as the peak for the largest color component.
        maximum = max(base)
        color = tuple(max(0, brightness * value // maximum) for value in base)
        if lease.rssi >= 0:
            count = min(8, max(0, (lease.rssi * 8 + 14) // 15))
            for index in BOTTOM_LEFT_TO_RIGHT[:count]:
                frame[index] = color
        else:
            # Type-only status, explicitly distinct from a signal-strength bar.
            frame[BOTTOM_LEFT_TO_RIGHT[0]] = tuple(max(1, value // 3) if value else 0 for value in color)
    return tuple(frame)

class LEDState:
    """Command handlers change state only. The renderer alone owns GPIO."""
    def __init__(self, *, clock=time.monotonic, battery=get_battery, haptic=lra):
        self.clock = clock
        self.battery_reader = battery
        self.haptic = haptic
        self.lock = threading.Lock()
        self.io = ThreadPoolExecutor(max_workers=1, thread_name_prefix='led-status')
        self.mode = 'idle'
        self.color = BLACK[0]
        self.temporary = None
        self.lease = None
        self.battery = (None, None)
        self.battery_job = None
        self.haptic_jobs = []
        self.battery_sampled = -math.inf
        self.boot_phase = 0

    def close(self):
        self.io.shutdown(wait=False, cancel_futures=True)

    def sample_battery(self, now):
        if self.battery_job is not None and self.battery_job.done():
            soc, voltage = self.battery_job.result()
            self.battery = (soc, voltage) if soc is not None and math.isfinite(soc) else (None, None)
            self.battery_job = None
            self.battery_sampled = now

    def request_battery(self, now):
        self.sample_battery(now)
        if self.battery_job is None and now - self.battery_sampled >= .25:
            self.battery_job = self.io.submit(self.battery_reader)

    def play(self, effect):
        self.haptic_jobs = [job for job in self.haptic_jobs if not job.done()]
        if len(self.haptic_jobs) < 2:
            self.haptic_jobs.append(self.io.submit(self.haptic, effect))

    def start_temporary(self, kind, now, color=None):
        self.temporary = kind, now, color
        if kind in ('battery', 'boot'):
            self.request_battery(now)
        if kind == 'boot':
            self.boot_phase = 0

    def expire(self, now):
        if self.lease and now >= self.lease.expires:
            self.lease = None

    def nfc(self, parts, now):
        if len(parts) < 3 or not re.fullmatch(r'[a-f0-9]{16}', parts[1]):
            return 'ERR invalid NFC lease'
        token = parts[1]
        self.expire(now)
        if self.lease and self.lease.token != token:
            return 'ERR NFC lease busy'
        if parts[2:] == ['release']:
            self.lease = None
            return 'OK'
        if len(parts) not in (7, 9) or parts[2] not in EFFECTS or parts[4] not in STAGES:
            return 'ERR invalid NFC frame'
        try:
            brightness, completed, total = map(int, (parts[3], parts[5], parts[6]))
        except ValueError:
            return 'ERR invalid NFC frame'
        if not 1 <= brightness <= MAX_NFC_BRIGHTNESS or not 0 <= completed <= 2048 or not (
                total == 0 or completed <= total <= 2048):
            return 'ERR invalid NFC frame'
        protocol, rssi = ('none', -1) if len(parts) == 7 else (parts[7], int(parts[8]) if re.fullmatch(r'-1|[0-9]{1,2}', parts[8]) else -2)
        if protocol != 'none' and protocol not in PROTOCOL_COLORS or not -1 <= rssi <= 15:
            return 'ERR invalid NFC signal'
        self.lease = Lease(token, parts[2], brightness, parts[4], completed, total, now + LEASE_SECONDS,
                           protocol, rssi)
        return 'OK'

    def command(self, command):
        parts = command.split()
        if not parts:
            return 'ERR empty'
        kind = parts[0].lower()
        with self.lock:
            now = self.clock()
            if kind == 'nfc':
                return self.nfc(parts, now)
            if kind == 'nfc-test' and len(parts) == 1:
                self.expire(now)
                if self.lease:
                    return 'ERR NFC scan active'
                self.start_temporary('index', now)
                return 'OK'
            if kind in ('off', 'idle', 'rainbow'):
                self.mode = kind
                self.temporary = None
                return 'OK'
            if kind in ('battery', 'boot'):
                self.start_temporary(kind, now)
                return 'OK'
            if kind in ('flash', 'color') and len(parts) >= 4:
                try:
                    color = tuple(max(0, min(255, int(value))) for value in parts[1:4])
                except ValueError:
                    return 'ERR bad RGB'
                if kind == 'flash':
                    self.start_temporary('flash', now, color)
                else:
                    self.mode = 'solid'
                    self.color = color
                    self.temporary = None
                return 'OK'
            if kind == 'status':
                self.request_battery(now)
                soc, voltage = self.battery
                mode = 'temporary' if self.temporary else self.mode
                return f'mode={mode} soc={soc if soc is not None else "unknown"} voltage={voltage if voltage is not None else "unknown"}'
            return 'ERR unknown command'

    def battery_frame(self, elapsed):
        soc, _ = self.battery
        if soc is None:
            return ((64, 0, 0),) * LED_COUNT if elapsed < .9 and int(elapsed / .15) % 2 == 0 else BLACK
        color = (100, 0, 0) if soc < 15 else (80, 35, 0) if soc < 40 else (0, 80, 10)
        count = max(0, min(LED_COUNT, round(soc * LED_COUNT / 100)))
        return (color,) * count + BLACK[count:]

    def temporary_frame(self, now):
        kind, start, color = self.temporary
        elapsed = now - start
        if kind == 'index':
            index = int(elapsed / INDEX_SECONDS)
            if index < LED_COUNT:
                return BLACK[:index] + ((0, 0, 20),) + BLACK[index + 1:]
        elif kind == 'flash' and elapsed < .38:
            return (color,) * LED_COUNT if elapsed < .15 or elapsed >= .23 else BLACK
        elif kind == 'battery' and elapsed < 3:
            return self.battery_frame(elapsed)
        elif kind == 'boot':
            if elapsed < .56:
                count = min(LED_COUNT, 1 + int(elapsed / .035))
                return ((0, 0, 70),) * count + BLACK[count:]
            if self.boot_phase < 1:
                self.boot_phase = 1
                self.play(1)
            if elapsed < .71:
                return ((0, 0, 70),) * LED_COUNT
            if elapsed < .95:
                count = min(LED_COUNT, 1 + int((elapsed - .71) / .015))
                return ((0, 50, 100),) * count + ((0, 0, 70),) * (LED_COUNT - count)
            if self.boot_phase < 2:
                self.boot_phase = 2
                self.play(10)
            if elapsed < 1.25:
                return ((0, 50, 100),) * LED_COUNT
            if elapsed < 3.25:
                return self.battery_frame(elapsed - 1.25)
            if elapsed < 3.77:
                level = max(0, 50 - int((elapsed - 3.25) / .02) * 2)
                return ((0, 0, level),) * LED_COUNT
        self.temporary = None
        return None

    def frame(self):
        with self.lock:
            now = self.clock()
            self.expire(now)
            self.sample_battery(now)
            if self.temporary:
                frame = self.temporary_frame(now)
                if frame is not None:
                    return frame
            if self.mode == 'off':
                return BLACK
            if self.lease:
                return nfc_frame(self.lease, now)
            if self.mode == 'solid':
                return (self.color,) * LED_COUNT
            if self.mode == 'rainbow':
                offset = int(now * 67)
                return tuple(tuple(channel // 4 for channel in wheel(i * 256 // LED_COUNT + offset))
                             for i in range(LED_COUNT))
            level = int((math.sin(now * 1.6) + 1) * 10)
            return tuple((level // 2, 0, level + i % 4) for i in range(LED_COUNT))


class LEDRequest(socketserver.BaseRequestHandler):
    def handle(self):
        deadline = time.monotonic() + .15
        data = bytearray()
        try:
            while b'\n' not in data and len(data) < 1024:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.request.settimeout(remaining)
                try:
                    chunk = self.request.recv(1024 - len(data))
                except TimeoutError:
                    break
                if not chunk:
                    break
                data.extend(chunk)
            # Older one-shot clients may omit the line terminator.
            if not data or len(data) >= 1024:
                return
            line, newline, tail = data.partition(b'\n')
            if tail.strip() or (not newline and line.startswith(b'nfc ')):
                return
            reply = self.server.state.command(line.decode('ascii'))
            self.request.settimeout(.15)
            self.request.sendall((reply + '\n').encode())
        except (OSError, UnicodeError):
            pass


def prepare_socket(path):
    if not path.exists() and not path.is_symlink():
        return
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise RuntimeError(f'Refusing to remove a non-socket file at {path}')
    with socket.socket(socket.AF_UNIX) as probe:
        probe.settimeout(.2)
        try:
            probe.connect(str(path))
        except ConnectionRefusedError:
            path.unlink()
        else:
            raise RuntimeError(f'LED daemon already listening on {path}')


def serve(path, state, draw, stopped, *, mode=0o666):
    prepare_socket(path)
    server = socketserver.UnixStreamServer(str(path), LEDRequest)
    thread = None
    try:
        os.chmod(path, mode)
        server.state = state
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        thread.start()
        previous = None
        while not stopped.is_set():
            frame = state.frame()
            if frame != previous:
                draw(frame)
                previous = frame
            stopped.wait(FRAME_SECONDS)
    finally:
        if thread is not None:
            server.shutdown()
            thread.join()
        server.server_close()
        path.unlink(missing_ok=True)
        draw(BLACK)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', type=Path, default=Path(SOCKET_PATH))
    parser.add_argument('--dry-run', action='store_true', help='test with a separate socket and no hardware')
    args = parser.parse_args()
    if args.dry_run and args.socket.resolve() == Path(SOCKET_PATH):
        parser.error('--dry-run requires a separate --socket path')
    if not args.dry_run and args.socket.resolve() != Path(SOCKET_PATH):
        parser.error('hardware mode uses the existing PT35 service socket')
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    if args.dry_run:
        state = LEDState(battery=lambda: (None, None), haptic=lambda _: None)
        try:
            serve(args.socket, state, lambda _: None, stopped, mode=0o600)
        finally:
            state.close()
        return
    # A second process must never start GPIO12 while the service is active.
    with os.fdopen(os.open(HARDWARE_LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'r+b') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepare_socket(args.socket)
        from rpi_ws281x import PixelStrip, Color

        strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
        strip.begin()

        def draw(frame):
            for index, color in enumerate(frame):
                strip.setPixelColor(index, Color(*color))
            strip.show()

        state = LEDState()
        try:
            state.command('boot')
            serve(args.socket, state, draw, stopped)
        finally:
            state.close()


if __name__ == '__main__':
    main()
