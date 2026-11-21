"""Optional scan lease client. Socket I/O stays off the Tk and RF threads."""
import os
import secrets
import socket
import threading
import time

DEFAULT_SOCKET = '/run/pt35-led.sock'
HEARTBEAT = .4
UPDATE_INTERVAL = .12
RESULT_SECONDS = .6


class NFCLeds:
    def __init__(self, path=None):
        self.path = path or os.environ.get('PT35_LED_SOCKET', DEFAULT_SOCKET)
        self.token = secrets.token_hex(8)
        self.condition = threading.Condition()
        self.frame = None
        self.protocol = 'none'
        self.rssi = -1
        self.style = 'sweep'
        self.brightness = 12
        self.until = None
        self.resume = None
        self.closed = False
        self.status = ''
        self.thread = threading.Thread(target=self.run, name='nfc-led-socket', daemon=True)
        self.thread.start()

    def start(self, style, brightness):
        with self.condition:
            self.style, self.brightness = style, brightness
            self.frame = ('scan', 0, 0)
            self.protocol, self.rssi = 'none', -1
            self.until = None
            self.condition.notify()

    def detected(self, protocol, rssi=None):
        with self.condition:
            if self.frame is not None:
                self.protocol = protocol if protocol in ('ISO15693', 'NFC-A', 'NFC-B', 'NFC-F', 'LF') else 'none'
                self.rssi = rssi if isinstance(rssi, int) and 0 <= rssi <= 15 else -1
                self.condition.notify()

    def reading(self, completed, total):
        with self.condition:
            if self.frame is not None:
                self.frame = ('read', completed, total or 0)
                self.until = None
                self.condition.notify()

    def result(self, stage):
        with self.condition:
            if self.frame is not None:
                self._temporary(stage, ('scan', 0, 0))
                self.condition.notify()

    def _temporary(self, stage, resume):
        self.frame = (stage, 0, 0)
        self.until = time.monotonic() + RESULT_SECONDS
        self.resume = resume

    def stop(self, fault=False):
        with self.condition:
            if fault and self.frame is not None:
                self._temporary('error', None)
            else:
                self.frame = self.until = None
            self.condition.notify()

    def close(self):
        with self.condition:
            self.frame = self.until = None
            self.closed = True
            self.condition.notify()

    def send(self, arguments):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(.12)
            client.connect(str(self.path))
            client.sendall(f'nfc {self.token} {arguments}\n'.encode())
            return client.recv(256).decode(errors='replace').strip()

    def run(self):
        leased = False
        last_frame = None
        last_sent = 0
        while True:
            with self.condition:
                now = time.monotonic()
                if self.until is not None and now >= self.until:
                    self.frame, self.until = self.resume, None
                frame = self.frame
                closed = self.closed
                if frame is None and not leased:
                    if closed:
                        return
                    self.status = ''
                    self.condition.wait()
                    continue
                if frame is not None:
                    stage, completed, total = frame
                    message = f'{self.style} {self.brightness} {stage} {completed} {total} {self.protocol} {self.rssi}'
                    interval = HEARTBEAT if message == last_frame else UPDATE_INTERVAL
                    due = last_sent + interval - now
                    if due > 0:
                        self.condition.wait(due)
                        continue
                else:
                    message = 'release'
            try:
                reply = self.send(message)
                if message == 'release':
                    leased = False
                elif reply == 'OK':
                    leased = True
                self.status = ('' if message == 'release' or reply == 'OK' else
                               'NFC LED lease busy' if 'busy' in reply else 'NFC LED support unavailable')
            except OSError:
                self.status = '' if message == 'release' else 'NFC LED service unavailable'
                if message == 'release':
                    leased = False  # The daemon's lease expires if it missed this release.
            last_frame, last_sent = message, time.monotonic()
