#!/usr/bin/env python3
"""FMI ST25DV16K guest URL tag writer. Read-only by default; explicit write."""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

ADDR = 0x53  # ST25DV EEPROM user area; system address is 0x57.

def read_data(bus, address, n):
    from smbus2 import i2c_msg
    write = i2c_msg.write(ADDR, [address >> 8, address & 255])
    read = i2c_msg.read(ADDR, n)
    bus.i2c_rdwr(write, read)
    return bytes(read)

def write_data(bus, address, payload):
    from smbus2 import i2c_msg
    # Four bytes per RF block; deliberately small EEPROM writes.
    for offset in range(0, len(payload)):
        a = address + offset
        msg = i2c_msg.write(ADDR, [a >> 8, a & 255, payload[offset]])
        bus.i2c_rdwr(msg)
        time.sleep(0.006)

def format_ndef(url):
    p = urlsplit(url)
    if p.scheme != "http" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("Guest NFC must use a plain HTTP guest URL, no credentials or fragment")
    if any(ord(ch) > 127 for ch in url):
        raise ValueError("URL must be ASCII")
    raw = url.encode("ascii")
    if len(raw) > 100:
        raise ValueError("URL too long for this conservative writer")
    # NDEF short well-known URI record; no prefix compression.
    payload = bytes([0xD1, 0x01, len(raw)+1, 0x55, 0x00]) + raw
    return bytes([0x03, len(payload)]) + payload + bytes([0xFE])

def sync(bus_number, url, allow_write=False):
    from smbus2 import SMBus
    with SMBus(bus_number) as bus:
        cc = read_data(bus,0,8)
        if cc[0] == 0xE1:
            start = 4
        elif cc[0] == 0xE2:
            start = 8
        else:
            raise RuntimeError("Tag not NFC Type 5 NDEF formatted (CC missing); refusing writes")
        if cc[1] & 0x0F != 0x00:
            raise RuntimeError("Unexpected CC version/access bits; refusing writes")
        existing = read_data(bus,start,128)
        if existing[0] not in (0x03, 0x00):
            raise RuntimeError("Unknown NDEF/TLV layout; refusing to overwrite")
        new = format_ndef(url)
        if existing[:len(new)] == new:
            print("NFC NDEF already current; no EEPROM write")
            return False
        if not allow_write:
            print("ST25DV at 0x53, NDEF CC:",cc.hex(" "))
            print("Existing user data:",existing[:32].hex(" "))
            print("Proposed guest URL:",url)
            print("Dry run. Rerun with --write to program.")
            return False
        backup=Path(f"/tmp/fmi-nfc-backup-bus{bus_number}-{int(time.time())}.bin")
        backup.write_bytes(cc+existing)
        backup.chmod(0o600)
        # Commit marker: empty NDEF while payload is being changed.
        write_data(bus,start,bytes([0x03,0x00]))
        write_data(bus,start+2,new[2:])
        write_data(bus,start+1,bytes([new[1]]))
        if read_data(bus,start,len(new)) != new:
            raise RuntimeError("NDEF read-back mismatch: check wiring; backup at "+str(backup))
        print("NFC tag updated:",url,"backup:",backup)
        return True

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--bus",type=int,required=True)
    p.add_argument("--url",required=True)
    p.add_argument("--write",action="store_true")
    a=p.parse_args()
    sync(a.bus,a.url,a.write)

if __name__=="__main__": main()
