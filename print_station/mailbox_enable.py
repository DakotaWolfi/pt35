#!/usr/bin/env python3
"""One-time ST25DV16K FTM enable using the manufacturer's factory I2C password.

ONLY run on a tag you own and whose I2C configuration may be changed.
Does not set/change the I2C password, write NDEF, change GPO, or clear EEPROM.
Factory password is 8 zero bytes per ST AN4910. If customized, exits without
attempting any other password.
"""
import argparse
import time
from smbus2 import SMBus, i2c_msg

SYSTEM=0x57
TAG=0x53
MB_MODE=0x000D
I2C_SSO=0x2004

def read(bus,slave,register):
    w=i2c_msg.write(slave,[register>>8,register&0xff])
    r=i2c_msg.read(slave,1)
    bus.i2c_rdwr(w,r)
    return bytes(r)[0]

def write(bus,slave,register,content):
    bus.i2c_rdwr(i2c_msg.write(slave,[register>>8,register&0xff,*content]))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bus",type=int,default=0)
    ap.add_argument("--apply",action="store_true",help="Authorize and perform the single static register update")
    a=ap.parse_args()
    with SMBus(a.bus) as bus:
        old=read(bus,SYSTEM,MB_MODE)
        gpo=read(bus,SYSTEM,0x0000)
        sso=read(bus,TAG,I2C_SSO)
        print(f"Current MB_MODE=0x{old:02X}; GPO=0x{gpo:02X}; I2C_SSO_Dyn=0x{sso:02X}")
        if old & 0x01:
            print("FTM static mode already enabled. No change necessary.")
            return
        if not a.apply:
            print("Dry run: --apply will present ST factory I2C password 0000000000000000")
            print("and set ONLY MB_MODE bit 0 (0x000D), preserving other bits.")
            return
        # ST25DV I2C Present Password: 8 password bytes, 0x09 validation,
        # repeated same 8 bytes (not the password-change validation 0x07).
        zero=bytes(8)
        write(bus,SYSTEM,0x0900,zero+bytes([0x09])+zero)
        time.sleep(.005)
        sso=read(bus,TAG,I2C_SSO)
        print(f"Security session after factory password: 0x{sso:02X}")
        if not(sso&0x01):
            raise RuntimeError("Factory password did not open I2C session. "
                               "Existing password was probably changed; no configuration register was written.")
        new=old|0x01
        write(bus,SYSTEM,MB_MODE,[new])
        time.sleep(.01)
        actual=read(bus,SYSTEM,MB_MODE)
        if actual!=new:
            raise RuntimeError(f"MB_MODE readback mismatch: expected 0x{new:02X}, got 0x{actual:02X}")
        if read(bus,SYSTEM,0x0000)!=gpo:
            raise RuntimeError("GPO unexpectedly changed; inspect NFC settings")
        print(f"Success: MB_MODE 0x{old:02X} -> 0x{actual:02X}. GPO unchanged 0x{gpo:02X}.")
        print("Next: sudo python3 mailbox_inspect.py --bus 0")
        print("Then start test host: sudo python3 mailbox_host.py --bus 0")

if __name__=="__main__":
    main()
