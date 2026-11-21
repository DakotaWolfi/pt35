#!/usr/bin/env python3
"""Bridge custom cafe:4011 PT35 USB gamepad buttons to PocketTerm35-OS keysyms.

The RP2040's Pico SDK/TinyUSB firmware exposes a keyboard plus Linux gamepad,
not the upstream CircuitPython interface. The D-pad already produces keyboard
arrows, so ONLY face buttons and Start/Select are converted here.

Root is required by the system service for /dev/input/event* and /dev/uinput;
no network, firmware, or hardware writes are performed.
"""
import logging
import time
from evdev import InputDevice, UInput, ecodes, list_devices, categorize

LOG = logging.getLogger("pt35-gamepad-bridge")
VID, PID = 0xCAFE, 0x4011
KEYMAP = {
    ecodes.BTN_TL: ecodes.KEY_F13,        # L => close
    ecodes.BTN_TR: ecodes.KEY_F14,        # R => mode switch
    ecodes.BTN_X: ecodes.KEY_F15,         # X => tab / scroll
    ecodes.BTN_Y: ecodes.KEY_F16,         # Y => menu / scroll
    ecodes.BTN_B: ecodes.KEY_F17,         # B => escape / right click
    ecodes.BTN_A: ecodes.KEY_F18,         # A => enter / left click
    ecodes.BTN_SELECT: ecodes.KEY_F21,    # window switcher
    ecodes.BTN_START: ecodes.KEY_F22,     # launcher
}

def discover():
    for name in list_devices():
        try:
            dev = InputDevice(name)
            keys = set(dev.capabilities().get(ecodes.EV_KEY, []))
            if (dev.info.vendor,dev.info.product) == (VID,PID) and ecodes.BTN_A in keys:
                return dev
            dev.close()
        except OSError:
            pass
    return None

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    LOG.info("Starting PT35 cafe:4011 gamepad -> F13..F18,F21,F22 bridge")
    ui = UInput({ecodes.EV_KEY: list(KEYMAP.values())}, name="PT35 FMI Desktop Buttons")
    try:
        while True:
            dev=discover()
            if dev is None:
                LOG.warning("PT35 gamepad device not found, retrying")
                time.sleep(2)
                continue
            LOG.info("Input: %s (%s)", dev.path,dev.name)
            pressed=set()
            try:
                for event in dev.read_loop():
                    if event.type != ecodes.EV_KEY or event.code not in KEYMAP:
                        continue
                    if event.value not in (0,1):
                        continue
                    pressed.discard(event.code) if event.value == 0 else pressed.add(event.code)
                    ui.write(ecodes.EV_KEY, KEYMAP[event.code],event.value)
                    ui.syn()
            except OSError as exc:
                LOG.warning("Device disconnected: %s",exc)
            finally:
                for code in pressed:
                    ui.write(ecodes.EV_KEY,KEYMAP[code],0)
                ui.syn()
                dev.close()
    finally:
        ui.close()

if __name__=="__main__":
    main()
