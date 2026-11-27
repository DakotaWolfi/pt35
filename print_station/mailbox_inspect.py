#!/usr/bin/env python3
"""Read-only ST25DV16K FTM readiness check on Print Station I2C bus 0.

Does not change tag EEPROM, MB_MODE, mailbox or GPO.
"""
import argparse
from smbus2 import SMBus
from mailbox_host import read, TAG, SYSTEM, MB_MODE, CTRL, LENGTH

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--bus",type=int,default=0)
    a=ap.parse_args()
    with SMBus(a.bus) as bus:
        static=read(bus,SYSTEM,MB_MODE)[0]
        dynamic=read(bus,TAG,CTRL)[0]
        length=read(bus,TAG,LENGTH)[0]
        gpo=read(bus,SYSTEM,0x0000)[0]
        print(f"MB_MODE (static 0x57:000D): 0x{static:02X}  FTM allowed={bool(static&1)}")
        print(f"MB_CTRL (dyn 0x53:2006):   0x{dynamic:02X}  enabled={bool(dynamic&1)} RF_PUT={bool(dynamic&4)} HOST_PUT={bool(dynamic&2)}")
        print(f"MB_LEN (dyn 0x53:2007):    0x{length:02X}  stored length-minus-one")
        print(f"GPO (static 0x57:0000):    0x{gpo:02X}  field-change={bool(gpo&8)} RF_PUT IRQ={bool(gpo&0x10)} RF_GET IRQ={bool(gpo&0x20)}")
        if not static&1:
            print("FTM is NOT enabled in static system configuration. The host service will refuse to start.")
            print("Changing MB_MODE requires an authorized I2C security session; no password handling is included.")
        elif not dynamic&1:
            print("FTM allowed; start mailbox_host.py to enable dynamic MB_CTRL_Dyn.")
        else:
            print("FTM enabled; host can listen and PT35 can exchange frames.")

if __name__=="__main__":main()
