#!/usr/bin/env python3
import os
import shutil
import subprocess
import time
from pathlib import Path
from evdev import InputDevice, list_devices, ecodes

TRAINER_CMD = os.environ.get("PT35_TRAINER_CMD", "/home/jenna/.local/bin/cp-petmind-training").strip()
NORMAL_UI_CMD = os.environ.get("PT35_NORMAL_CMD", "/home/jenna/.local/bin/cp-dashboard").strip()
EYE_CMD = os.environ.get("PT35_EYE_CMD", "/home/jenna/.local/bin/pt35-eye-control --button").strip()
NFC_CMD = os.environ.get("PT35_NFC_CMD", "/home/jenna/.local/bin/pt35-nfc-menu").strip()
SELECT_LONG_SECONDS = float(os.environ.get("PT35_SELECT_LONG", "1.5"))

BTN_A = 304
BTN_B = 305
BTN_X = 307
BTN_Y = 308
BTN_L = 310
BTN_R = 311
BTN_SELECT = 314
BTN_START = 315

BUTTON_LABELS = {
    BTN_A: "A", BTN_B: "B", BTN_X: "X", BTN_Y: "Y",
    BTN_L: "L", BTN_R: "R", BTN_SELECT: "SELECT", BTN_START: "START",
}


def log(msg):
    print(f"[pt35-buttons] {msg}", flush=True)


def get_gui_env():
    env = os.environ.copy()
    wanted = {
        "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
    }
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return env
    uid = os.getuid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            raw = (proc / "environ").read_bytes()
            penv = {}
            for item in raw.split(b"\0"):
                if b"=" not in item:
                    continue
                k, v = item.split(b"=", 1)
                penv[k.decode(errors="ignore")] = v.decode(errors="ignore")
            if not (penv.get("DISPLAY") or penv.get("WAYLAND_DISPLAY")):
                continue
            for k in wanted:
                if penv.get(k):
                    env[k] = penv[k]
            return env
        except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
            pass
    return env


def run_command(cmd):
    if not cmd:
        return
    env = get_gui_env()
    log(f"run: {cmd}")
    subprocess.Popen(["bash", "-lc", cmd], env=env, start_new_session=True)


def inject_key(key):
    env = get_gui_env()
    wmap = {
        "enter": "Return",
        "esc": "Escape",
        "pageup": "Page_Up",
        "pagedown": "Page_Down",
        "print": "Print",
    }
    xmap = {
        "enter": "Return",
        "esc": "Escape",
        "pageup": "Page_Up",
        "pagedown": "Page_Down",
        "print": "Print",
    }

    if shutil.which("wtype"):
        try:
            r = subprocess.run(
                ["wtype", "-k", wmap.get(key, key)], env=env,
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                log(f"key: {key} via wtype")
                return True
            log(f"wtype rejected {wmap.get(key, key)!r}: {(r.stderr or r.stdout).strip()}")
        except Exception as exc:
            log(f"wtype failed for {key}: {exc}")

    if shutil.which("xdotool"):
        try:
            r = subprocess.run(
                ["xdotool", "key", xmap.get(key, key)], env=env,
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                log(f"key: {key} via xdotool")
                return True
            log(f"xdotool rejected {xmap.get(key, key)!r}: {(r.stderr or r.stdout).strip()}")
        except Exception as exc:
            log(f"xdotool failed for {key}: {exc}")
    return False


def screenshot():
    if inject_key("print"):
        log("Print Screen triggered")
        return
    for cmd in (["gnome-screenshot", "-i"], ["grim"]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, env=get_gui_env(), start_new_session=True)
            log(f"screenshot via {cmd[0]}")
            return
    log("No screenshot tool found; install wtype or xdotool.")


def find_gamepad():
    candidates = []
    for path in list_devices():
        dev = InputDevice(path)
        name = (dev.name or "").lower()
        info = dev.info
        keycodes = set(dev.capabilities().get(ecodes.EV_KEY, []))
        if "pocketterm35" in name and BTN_A in keycodes:
            return dev
        if info.vendor == 0xCAFE and info.product == 0x4011 and BTN_A in keycodes:
            candidates.append(dev)
    return candidates[0] if candidates else None


def main():
    dev = find_gamepad()
    if not dev:
        raise SystemExit("PT35 gamepad input device not found.")

    log(f"using {dev.path}: {dev.name}")
    log("map: L=Remote Eye  R=NFC  X=PgUp  B=PgDn  Y=Esc  A=Enter")

    pressed_at = {}
    combo_suppressed = set()

    for event in dev.read_loop():
        if event.type != ecodes.EV_KEY or event.code not in BUTTON_LABELS:
            continue
        if event.value not in (0, 1):
            continue

        code = event.code
        label = BUTTON_LABELS[code]

        if event.value == 1:
            pressed_at[code] = time.monotonic()
            if BTN_SELECT in pressed_at and BTN_START in pressed_at:
                combo_suppressed.update((BTN_SELECT, BTN_START))
                log("Select+Start combo: local launch actions suppressed")
            continue

        started = pressed_at.pop(code, None)
        held = time.monotonic() - started if started is not None else 0.0

        if code in combo_suppressed:
            combo_suppressed.discard(code)
            continue

        if code == BTN_SELECT:
            if held >= SELECT_LONG_SECONDS:
                screenshot()
            else:
                run_command(TRAINER_CMD)
            continue
        if code == BTN_START:
            run_command(NORMAL_UI_CMD)
            continue

        if code == BTN_L:
            run_command(EYE_CMD)
            continue
        if code == BTN_R:
            run_command(NFC_CMD)
            continue

        simple = {
            BTN_X: "pageup",
            BTN_B: "pagedown",
            BTN_Y: "esc",
            BTN_A: "enter",
        }
        if code in simple and not inject_key(simple[code]):
            log(f"{label} -> {simple[code]} (no key injector available)")


if __name__ == "__main__":
    main()
