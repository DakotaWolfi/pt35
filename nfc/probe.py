#!/usr/bin/env python3
"""Read-only PT35 ST25R3916 identification, supply config and shared I2C checks.
No RF activation, no EEPROM writes, no kernel or service changes.
"""
from smbus2 import SMBus, i2c_msg
from time import sleep

BUS=1
ADDR=0x50

def reg(bus, addr):
    # ST25R3916 I2C register read: command address with bit 6 asserted.
    w=i2c_msg.write(ADDR, [addr | 0x40])
    r=i2c_msg.read(ADDR, 1)
    bus.i2c_rdwr(w,r)
    return list(r)[0]

with SMBus(BUS) as bus:
    for i in range(5):
        identity=reg(bus,0x3f)
        cfg=reg(bus,0x01)
        chip=(identity >> 3) & 0x1f
        rev=identity & 7
        print(f'Probe {i+1}/5: IC 0x{identity:02X} (type {chip}, revision {rev}); I/O Config 2=0x{cfg:02X}; sup3V={bool(cfg & 0x80)}')
        if chip != 5:
            raise SystemExit('Unexpected identity; stopping. No RF operations performed.')
        sleep(.2)
    print('PASS: ST25R3916 identification stable on /dev/i2c-1')
    if not (cfg & 0x80):
        print('WARNING: sup3V not set. Your earlier 0x84 write may have been reset by power cycling.')
        print('Do not enable RF until 3.3 V power settings are checked.')
    else:
        print('PASS: 3.3 V supply-selection bit is currently set.')
print('Next milestone: ISO15693 RF initialization and UID inventory; not implemented in this diagnostic.')
