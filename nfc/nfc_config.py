"""Shared PT35 NFC paths and cooperative reader locks."""
import fcntl
import os
import signal
from contextlib import contextmanager
from pathlib import Path

DEFAULT_ARCHIVE = Path.home() / 'pt35-nfc' / 'archive'
LEGACY_ARCHIVE = Path(__file__).resolve().parent / 'archive'


@contextmanager
def file_lock(path, *, blocking=True):
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), 'r+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise RuntimeError(f'Reader already in use ({path.name})') from exc
        yield


def reader_lock(device):
    return file_lock(Path('/tmp') / f'pt35-nfc-{os.getuid()}-{device}.lock', blocking=False)


def handle_sigterm():
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
