#!/usr/bin/env python3
"""PT35 ST25R3916 NFC-V (ISO15693) inventory experiment.
Port of M5Stack's NFC-V streaming sequence to Linux smbus2 I2C, no IRQ GPIO.
Read-only RF command: INVENTORY (flags 0x26, command 0x01, mask len 0).
"""
import argparse
import time
from smbus2 import SMBus, i2c_msg

ADDRESS = 0x50


def crc15693(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return (~crc) & 0xffff


def encode_vcd(payload):
    data = bytearray(payload)
    data[0] = (data[0] | 0x02) & ~0x01  # high rate, one subcarrier
    check = crc15693(data)
    data.extend([check & 255, check >> 8])
    out = bytearray([0x21])  # SOF, 1-out-of-4 coding
    table = (0x02, 0x08, 0x20, 0x80)
    for byte in data:
        for shift in (0, 2, 4, 6):
            out.append(table[(byte >> shift) & 3])
    out.append(0x04)  # EOF
    return out


def decode_vicc(buf):
    """Decode one ISO15693 inventory reply from ST25R3916 subcarrier stream.

    Inventory response is 12 decoded bytes: flags, DSFID, UID[8], CRC[2].
    The chip's trailing EOF symbols aren't Manchester data. Stop immediately
    after exactly 96 decoded bits; verify CRC instead of parsing EOF as data.
    """
    if not buf or (buf[0] & 0x1F) != 0x17:
        raise ValueError('invalid Manchester SOF: ' + buf[:8].hex(' '))
    response_len = 12
    required_bits = response_len * 8
    decoded_bits = 0
    payload = bytearray(response_len)
    p = 5  # ST25R3916 stream SOF consumes five bits
    while decoded_bits < required_bits:
        if p + 1 >= len(buf) * 8:
            raise ValueError(f'truncated response: {decoded_bits}/96 decoded bits')
        symbol = ((buf[p // 8] >> (p % 8)) & 1) | (((buf[(p + 1) // 8] >> ((p + 1) % 8)) & 1) << 1)
        if symbol not in (1, 2):
            raise ValueError(f'Manchester collision before complete frame at bit {p}, symbol {symbol}')
        if symbol == 2:
            payload[decoded_bits // 8] |= 1 << (decoded_bits % 8)
        decoded_bits += 1
        p += 2
    # The remaining stream is the non-Manchester ISO15693 EOF; ignore it.
    expected = crc15693(payload[:10])
    received = payload[10] | (payload[11] << 8)
    if expected != received:
        raise ValueError(f'CRC mismatch: calculated {expected:04x} received {received:04x} decoded={payload.hex(" ")}')
    if payload[0] & 0x01:
        raise ValueError(f'ISO15693 inventory error response: {payload.hex(" ")}')
    return payload[:10]


class Chip:
    def __init__(self, bus):
        self.bus = bus
    def send(self, *data):
        self.bus.i2c_rdwr(i2c_msg.write(ADDRESS, list(data)))
    def read(self, operation, length=1):
        write = i2c_msg.write(ADDRESS, [operation])
        read = i2c_msg.read(ADDRESS, length)
        self.bus.i2c_rdwr(write, read)
        return bytes(read)
    def wr(self, address, value, space_b=False):
        self.send(*([0xfb] if space_b else []), address & 0x3f, value & 255)
    def rd(self, address, space_b=False):
        # space B read register mode
        if space_b:
            write = i2c_msg.write(ADDRESS, [0xfb, 0x40 | (address & 0x3f)])
            read = i2c_msg.read(ADDRESS, 1)
            self.bus.i2c_rdwr(write, read)
            return bytes(read)[0]
        return self.read(0x40 | (address & 0x3f))[0]
    def cmd(self, opcode, *extra):
        self.send(opcode, *extra)
    def update(self, reg, setbits=0, clearbits=0):
        value = (self.rd(reg) & ~clearbits) | setbits
        self.wr(reg, value)
        return value
    def irqs(self):
        return self.read(0x40 | 0x1a, 4)
    def await_irq(self, mask, duration):
        until = time.monotonic() + duration
        observed = 0
        while time.monotonic() < until:
            status = self.irqs()
            observed |= status[0]
            if observed & mask:
                return observed
            time.sleep(0.001)
        return observed
    def initialize(self, verbose=False):
        identity = self.rd(0x3f)
        if (identity >> 3) != 5:
            raise RuntimeError(f'Unexpected chip ID 0x{identity:02X}')
        print(f'ST25R3916 detected: 0x{identity:02X}', flush=True)
        self.cmd(0xc2)
        self.update(0x02, clearbits=0x48)
        time.sleep(.003)
        self.cmd(0xc1)
        time.sleep(.005)
        # Manufacturer's documented temperature-protection workaround.
        self.cmd(0xfc, 0x04, 0x10)
        self.wr(0x00, 0x00)
        self.wr(0x01, 0x84)  # sup3V, io_drv_lvl
        self.wr(0x28, 0x00)
        self.update(0x00, setbits=0x07)
        self.wr(0x2a, 0x80, True)
        self.update(0x01, setbits=0x20)
        self.wr(0x2a, 0, True)
        self.wr(0x2a, 0x13)
        self.wr(0x2b, 0x02)
        self.wr(0x08, (self.rd(0x08) & 0x0f) | 0x50)
        self.wr(0x29, 0x5f)
        self.wr(0x05, 0x40, True)
        self.wr(0x26, 0x82)
        self.wr(0x27, 0x82)
        self.update(0x02, setbits=0x03)
        self.cmd(0xdb)
        for r in (0x16,0x17,0x18,0x19):
            self.wr(r,0)
        self.irqs()
        self.update(0x02, setbits=0x80)
        time.sleep(.02)
        aux = self.rd(0x31)
        if not (aux & 0x10):
            raise RuntimeError(f'oscillator not ready: auxiliary display 0x{aux:02X}')
        self.cmd(0xd6)  # adjust regulators
        time.sleep(.006)
        self.irqs()
        # NFC-V: directly transcribed from M5Stack configure_nfc_v.
        for addr,val in [(0x0b,0x13),(0x0c,0x2d),(0x0d,0),(0x0e,0),(0x28,0x70),
                         (0x00,0x07),(0x09,0x38),(0x0a,0x02)]:
            self.wr(addr,val)
        self.update(0x01,setbits=0x20)
        self.update(0x02,setbits=0x03)
        for addr,val in [(0x05,0x40),(0x06,0x14),(0x0b,0x0c),(0x0c,0x13),
                         (0x0d,0x01),(0x0f,0),(0x15,0),(0x28,0x10),(0x29,0x7c),(0x2a,0x80)]:
            self.wr(addr,val,True)
        self.wr(0x03,0x70)
        # NFC collision avoidance, then turn TX/RX on.
        self.cmd(0xc8)
        time.sleep(.006)
        self.update(0x02,setbits=0x48)
        time.sleep(.010)
        print(f'NFC-V RF enabled; op=0x{self.rd(0x02):02X} I/O2=0x{self.rd(0x01):02X}',flush=True)
    def inventory(self, timeout=.3, verbose=False):
        frame = encode_vcd([0x26,0x01,0x00])  # single slot inventory; 1 subcarrier, high rate
        # NRT period 4096/fc: approx 13 ticks per 4ms, 995 per 300ms
        t = min(65535, max(1, int(timeout * 13560000 / 4096)))
        self.update(0x12,setbits=0x01)
        self.wr(0x10,t>>8)
        self.wr(0x11,t&255)
        self.irqs()
        self.cmd(0xdb)
        self.send(0x80,*frame)
        nbits = len(frame)*8
        self.wr(0x22,nbits>>8)
        self.wr(0x23,nbits&255)
        self.cmd(0xc5)
        irq = self.await_irq(0x08,timeout+.1)
        if not irq & 0x08:
            print(f'TX did not complete (IRQ main=0x{irq:02X})')
            return None
        irq = self.await_irq(0x10,timeout+.1)
        length1,length2 = self.read(0x5e,2)
        size = length1 | ((length2 & 0xc0)<<2)
        if not size:
            if verbose:
                print(f'No reply (IRQ main=0x{irq:02X}, FIFO=0)')
            return None
        raw = self.read(0x9f,min(size,256))
        if verbose:
            print(f'RX IRQ=0x{irq:02X}, FIFO={size}, raw={raw.hex(" ")}')
        try:
            decoded = decode_vicc(raw)
        except ValueError as e:
            if verbose:
                print('Decode error:',e)
            return None
        if len(decoded)>=10 and not (decoded[0]&1):
            uid = decoded[2:10]
            return uid[::-1].hex().upper(),decoded
        print('Received NFC-V response:',decoded.hex(' '))
        return None
    def shutdown(self):
        self.cmd(0xc2)
        self.update(0x02, clearbits=0x48)


def main():
    p = argparse.ArgumentParser(description='PT35 ISO15693 inventory scan (read-only)')
    p.add_argument('--bus',type=int,default=1)
    p.add_argument('--count',type=int,default=30)
    p.add_argument('--delay',type=float,default=.35)
    p.add_argument('--verbose',action='store_true')
    opts=p.parse_args()
    with SMBus(opts.bus) as bus:
        chip=Chip(bus)
        try:
            chip.initialize(opts.verbose)
            print('Hold a Tonie or ST25DV tag over the reader antenna. Ctrl+C to exit.',flush=True)
            last=None
            for attempt in range(opts.count):
                result=chip.inventory(verbose=opts.verbose)
                if result:
                    uid, data=result
                    if uid!=last:
                        print(f'FOUND ISO15693 UID: {uid} | DSFID=0x{data[1]:02X}',flush=True)
                        last=uid
                elif opts.verbose:
                    print(f'Attempt {attempt+1}: no valid tag')
                time.sleep(opts.delay)
            if last is None:
                print('No valid ISO15693 UID returned. Try --verbose for RF diagnostics.')
        except KeyboardInterrupt:
            print('\nStopped')
        finally:
            try: chip.shutdown()
            except OSError: pass

if __name__=='__main__':
    main()
