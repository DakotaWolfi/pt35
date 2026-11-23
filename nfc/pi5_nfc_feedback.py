"""Pi5-compatible NFC LED feedback, using the PT35 user LED daemon socket.

Only IPC here: never access NeoPixel GPIO or I2C from the GUI process.
"""
import os
import queue
import socket
import threading
import time


class NFCLeds:
    """Implements the original GUI's NFCLeds interface via Pi5 LED IPC."""

    def __init__(self):
        self.path = os.environ.get("PT35_LED_SOCKET", f"/run/user/{os.getuid()}/pt35-led.sock")
        self.status = "LED effects available when pt35-leds-pi5 is running"
        self.commands = queue.Queue(maxsize=32)
        self.closed = False
        self.active = False
        self.previous_mode = None
        self.brightness = 12
        self.thread = threading.Thread(target=self.run, daemon=True, name="pt35-nfc-pi5-led")
        self.thread.start()

    def _send(self, command):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2)
            sock.connect(self.path)
            sock.sendall((command + "\n").encode("ascii"))
            return sock.recv(256).decode(errors="replace").strip()

    def _queue(self, command):
        if self.closed:
            return
        try:
            self.commands.put_nowait(command)
        except queue.Full:
            pass

    def start(self, style, brightness):
        self.active = True
        self._queue(("start", style, brightness))

    def detected(self, protocol, rssi=None):
        # Detection may fire many times in one scan; don't flash on every poll.
        pass

    def reading(self, completed, total):
        # The daemon animates continuously while scanning/reading; leave the
        # moving bar running rather than flashing after every block.
        pass

    def result(self, stage):
        if self.active:
            self._queue(("result", stage))

    def stop(self, fault=False):
        if self.active:
            self.active = False
            self._queue(("result", "error") if fault else ("restore",))

    def close(self):
        self.closed = True
        self.active = False
        self._queue_force(("restore",))
        self._queue_force(("quit",))

    def _queue_force(self, command):
        try:
            self.commands.put_nowait(command)
        except queue.Full:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                pass
            self.commands.put_nowait(command)

    def _restore(self):
        mode = self.previous_mode
        self.previous_mode = None
        if mode in ("idle", "rainbow", "off", "nfc"):
            self._send(mode)
        # Unknown/solid modes cannot be reconstructed safely: leave LED off.
        elif mode is None:
            pass
        else:
            self._send("off")

    def run(self):
        while True:
            operation = self.commands.get()
            try:
                if operation[0] == "quit":
                    return
                if operation[0] == "start":
                    status = self._send("status")
                    if status.startswith("OK mode="):
                        self.previous_mode = status.split("mode=", 1)[1].split()[0]
                    style, brightness = operation[1], operation[2]
                    self.brightness = max(1, min(32, int(brightness)))
                    self._send({"sweep": "nfc", "pulse": "idle", "minimal": "off"}.get(style, "nfc"))
                    self.status = "NFC scan LED active"
                elif operation[0] == "result":
                    rgb = {
                        "success": "0 100 20", "same": "0 60 100",
                        "improved": "0 100 60", "changed": "70 50 120",
                        "uncertain": "100 65 0", "partial": "100 65 0",
                        "error": "100 0 0", "hold": "0 40 80",
                    }.get(operation[1], "0 40 80")
                    levels = [max(0, min(255, round(int(n) * self.brightness / 32))) for n in rgb.split()]
                    self._send("flash " + " ".join(map(str, levels)))
                elif operation[0] == "restore":
                    self._restore()
                    self.status = ""
            except (OSError, TimeoutError) as exc:
                self.status = f"LED service unavailable: {exc}"
