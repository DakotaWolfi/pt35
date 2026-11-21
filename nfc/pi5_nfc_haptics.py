"""Optional DRV2605L haptic notifications from Pi5 NFC GUI.

Uses the existing lra_ctl utility. Avoids I2C access and subprocess waits on Tk.
"""
import shutil
import subprocess
import threading
import time

_lock = threading.Lock()
_last_time = 0.0
_last_uid = None
_effects = {"1": "Strong click", "10": "Sharp click", "47": "Soft pulse"}


def new_scan():
    global _last_uid
    with _lock:
        _last_uid = None


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
    if not __import__("os").path.isfile(ctl):
        return False

    def work():
        try:
            subprocess.run([ctl, "play", effect], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=2, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

    threading.Thread(target=work, daemon=True, name="pt35-nfc-haptic").start()
    return True
