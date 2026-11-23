"""Optional DRV2605L haptic notifications from Pi5 NFC GUI.

Uses the existing lra_ctl utility. Avoids I2C access and subprocess waits on Tk.
"""
import os
import shutil
import logging
import subprocess
import threading
import time

_lock = threading.Lock()
_last_time = 0.0
_last_uid = None
_effects = {"1": "Strong click", "10": "Sharp click", "47": "Soft pulse"}
_log = logging.getLogger("pt35.nfc.haptics")


def new_scan():
    global _last_uid
    with _lock:
        _last_uid = None


def signal(event):
    """One non-blocking tactile cue for each scanner lifecycle event."""
    ctl = shutil.which("lra_ctl") or "/usr/local/bin/lra_ctl"
    if not os.path.isfile(ctl) or not os.access(ctl, os.X_OK):
        _log.warning("NFC haptic unavailable: %s missing", ctl)
        return False
    effect = {"start": "47", "tag": "10", "interrupted": "1", "error": "1"}.get(event)
    if effect is None:
        return False

    def work():
        try:
            result = subprocess.run(
                [ctl, "play", effect], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=2, check=False
            )
            if result.returncode:
                _log.warning("NFC haptic %s failed (%s): %s",
                             event, result.returncode,
                             (result.stderr or result.stdout).strip()[-250:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log.warning("NFC haptic %s failed: %s", event, exc)

    threading.Thread(target=work, daemon=True, name="pt35-nfc-haptic-" + event).start()
    return True


def notify(uid, enabled=False, effect="47"):
    global _last_time, _last_uid
    if not enabled or effect not in _effects or not uid:
        return False
    now = time.monotonic()
    uid = str(uid).upper()
    with _lock:
        if uid == _last_uid or now - _last_time < 0.7:
            return False
        _last_time, _last_uid = now, uid
    ctl = shutil.which("lra_ctl") or "/usr/local/bin/lra_ctl"
    if not os.path.isfile(ctl) or not os.access(ctl, os.X_OK):
        _log.warning("NFC haptic unavailable: %s is missing or not executable", ctl)
        return False

    def work():
        try:
            result = subprocess.run(
                [ctl, "play", effect], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=2, check=False
            )
            if result.returncode:
                _log.warning("NFC haptic failed (exit %s): %s",
                             result.returncode, (result.stderr or result.stdout).strip()[-250:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log.warning("NFC haptic failed: %s", exc)

    threading.Thread(target=work, daemon=True, name="pt35-nfc-haptic").start()
    return True
