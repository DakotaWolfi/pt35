"""Optional DRV2605L haptic notifications from Pi5 NFC GUI.

Uses the existing lra_ctl utility. Avoids I2C access and subprocess waits on Tk.
"""
import os
import shutil
import logging
import json
from pathlib import Path
import subprocess
import threading
import time

_lock = threading.Lock()
_playback_lock = threading.Lock()
_last_time = 0.0
_last_uid = None
_effects = {"1": "Strong click", "10": "Sharp click", "47": "Soft pulse"}
_log = logging.getLogger("pt35.nfc.haptics")
CONFIG_PATH = Path.home() / ".config/pt35/nfc-haptics.json"
DEFAULT_EVENTS = {
    # UI Start/Stop button clicks are optional, OFF by default.
    "scan_start": {"enabled": False, "effect": 47},
    "read_start": {"enabled": True, "effect": 47},
    "tag": {"enabled": True, "effect": 10},
    "scan_stop": {"enabled": False, "effect": 1},
    "error": {"enabled": True, "effect": 1},
}
EFFECT_LABELS = {1: "Strong click", 10: "Sharp click", 47: "Soft pulse"}


def load_settings():
    """Load only recognized event fields, preserving defaults for old installs."""
    data = {}
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data = raw
    except (FileNotFoundError, OSError, ValueError):
        pass
    result = {}
    for event, defaults in DEFAULT_EVENTS.items():
        candidate = data.get(event, {})
        if not isinstance(candidate, dict):
            candidate = {}
        value = candidate.get("effect", defaults["effect"])
        try:
            effect = int(value)
        except (ValueError, TypeError):
            effect = defaults["effect"]
        if not 1 <= effect <= 123:
            effect = defaults["effect"]
        result[event] = {
            "enabled": candidate.get("enabled", defaults["enabled"]) is True,
            "effect": effect,
        }
    return result


def save_settings(data):
    """Validate and atomically replace the separate NFC haptic configuration."""
    sanitized = {}
    for event in DEFAULT_EVENTS:
        item = data.get(event, {})
        if not isinstance(item, dict):
            raise ValueError(f"Invalid settings for {event}")
        effect = int(item["effect"])
        if not 1 <= effect <= 123:
            raise ValueError(f"{event}: effect must be between 1 and 123")
        sanitized[event] = {"enabled": bool(item["enabled"]), "effect": effect}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def _play(event, effect):
    """Serialize DRV2605L effects, including the time the motor is active.

    lra_ctl play returns immediately after writing GO=1. Launching another
    lra_ctl before GO clears can reconfigure an effect mid-playback.
    """
    ctl = shutil.which("lra_ctl") or "/usr/local/bin/lra_ctl"
    if not os.path.isfile(ctl) or not os.access(ctl, os.X_OK):
        _log.warning("NFC haptic unavailable: %s missing or not executable", ctl)
        return False

    # Prevent a queue of old notifications from vibrating long after a scan.
    if not _playback_lock.acquire(blocking=False):
        _log.debug("NFC haptic %s skipped: another effect is playing", event)
        return False

    def work():
        try:
            result = subprocess.run(
                [ctl, "play", str(effect)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=2, check=False,
            )
            if result.returncode:
                _log.warning("NFC haptic %s failed (%s): %s", event,
                             result.returncode,
                             (result.stderr or result.stdout).strip()[-250:])
                return

            # Poll the controller's GO bit, which clears when effect playback
            # finishes. It is read-only; no further motor configuration writes.
            try:
                from smbus2 import SMBus
                with SMBus(1) as bus:
                    deadline = time.monotonic() + 1.0
                    while time.monotonic() < deadline:
                        if not bus.read_byte_data(0x5A, 0x0C) & 1:
                            break
                        time.sleep(0.015)
            except (OSError, ImportError) as exc:
                _log.debug("DRV2605L GO polling unavailable: %s", exc)
                time.sleep(0.45)
            # Allow the LRA to settle so adjacent effects do not blend.
            time.sleep(0.06)
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log.warning("NFC haptic %s failed: %s", event, exc)
        finally:
            _playback_lock.release()

    threading.Thread(target=work, daemon=True,
                     name="pt35-nfc-haptic-" + event).start()
    return True


def test_effect(effect):
    """Play a selected effect without changing stored settings."""
    effect = int(effect)
    if not 1 <= effect <= 123:
        raise ValueError("DRV2605L effect must be 1..123")
    return _play("test", effect)


def new_scan():
    global _last_uid
    with _lock:
        _last_uid = None


def signal(event):
    """Play the configured lifecycle cue when enabled (never block the GUI)."""
    selected = load_settings().get(event)
    if selected is None or not selected["enabled"]:
        return False
    return _play(event, selected["effect"])


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
