#!/usr/bin/env python3
"""Read-only PT35 Tag Workshop diagnostic. No GUI or tag writes."""
import inspect
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nfc"))

import tag_workshop_rf as rf


def main():
    print("PT35 Workshop RF diagnostic", flush=True)
    print("Reader module:", inspect.getfile(rf), flush=True)
    print("Stage-aware reader:", "NFC-A anticollision/selection" in inspect.getsource(rf.read_all), flush=True)
    print("Close both NFC GUI windows and hold one NFC-A Type 2 sticker on the antenna.", flush=True)
    try:
        from smbus2 import SMBus
        configure, poll_a, crc_a, receive, Reader, reader_lock, FrameError = rf.driver()
        print("Recovered driver:", inspect.getfile(poll_a), flush=True)
        with reader_lock("i2c-1"), SMBus(1) as bus:
            chip = Reader(bus)
            try:
                print("Stage: initialize NFC-A RF", flush=True)
                chip.initialize(configure=lambda dev: configure(dev, "NFC-A"))
                print("Stage: select and read user memory", flush=True)
                result = rf.read_all(chip, poll_a, receive, crc_a, FrameError)
                print("SUCCESS UID:", result["uid"], flush=True)
                print("SUCCESS CC:", result["cc"], "capacity:", result["capacity"], flush=True)
            finally:
                try:
                    chip.shutdown()
                except OSError as exc:
                    print("Shutdown warning:", exc, flush=True)
    except Exception as exc:
        print("FAILED:", type(exc).__name__, str(exc), flush=True)
        traceback.print_exc(limit=5, file=sys.stdout)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
