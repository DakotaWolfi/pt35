#!/usr/bin/env python3
"""PT35 ST25R3916 NFC-V (ISO15693) inventory experiment.
Port of M5Stack's NFC-V streaming sequence to Linux smbus2 I2C, no IRQ GPIO.
Read-only RF command: INVENTORY (flags 0x26, command 0x01, mask len 0).
"""
import argparse
import time
from nfc_config import handle_sigterm, reader_lock

VERSION = '1.1'
MAX_V_FIFO = 128


class FrameError(ValueError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind

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


def decode_response(raw):
    """Decode exactly one bounded VICC frame, including its stream EOF and CRC.

    Each payload byte uses 16 stream bits. M5Stack documents the FIFO SOF
    in the low five bits and the byte-aligned EOF as 0b101 followed by 0x03.
    """
    if not raw or raw[0] & 0x1f != 0x17:
        raise FrameError('framing', 'Invalid NFC-V SOF')
    if len(raw) > MAX_V_FIFO:
        raise FrameError('framing', 'Oversize NFC-V response')
    stream = int.from_bytes(raw, 'little') >> 5
    frame = bytearray()
    for offset in range(0, len(raw) - 1, 2):
        if raw[offset] & 0xe0 == 0xa0 and raw[offset + 1] == 0x03:
            if len(frame) < 3 or any(raw[offset + 2:]):
                raise FrameError('framing', 'Invalid NFC-V frame boundary')
            if crc15693(frame[:-2]) != int.from_bytes(frame[-2:], 'little'):
                raise FrameError('crc', 'NFC-V CRC mismatch')
            return bytes(frame[:-2])
        if offset + 2 >= len(raw):
            break
        byte = 0
        for bit in range(8):
            symbol = stream & 3
            if symbol not in (1, 2):
                raise FrameError('manchester', 'Invalid NFC-V Manchester symbol')
            byte |= (symbol == 2) << bit
            stream >>= 2
        frame.append(byte)
    raise FrameError('framing', 'Truncated NFC-V response or missing EOF')


def decode_vicc(buf):
    payload = decode_response(buf)
    if len(payload) != 10 or payload[0] & 1:
        raise FrameError('framing', 'Unexpected ISO15693 inventory response')
    return payload


class Chip:
    def __init__(self, bus):
        self.bus = bus
        self.identified = False
    def send(self, *data):
        from smbus2 import i2c_msg
        self.bus.i2c_rdwr(i2c_msg.write(ADDRESS, list(data)))
    def read(self, operation, length=1):
        from smbus2 import i2c_msg
        write = i2c_msg.write(ADDRESS, [operation])
        read = i2c_msg.read(ADDRESS, length)
        self.bus.i2c_rdwr(write, read)
        return bytes(read)
    def wr(self, address, value, space_b=False):
        self.send(*([0xfb] if space_b else []), address & 0x3f, value & 255)
    def rd(self, address, space_b=False):
        # space B read register mode
        if space_b:
            from smbus2 import i2c_msg
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
    def initialize(self, verbose=False):
        identity = self.rd(0x3f)
        if identity >> 3 != 5:
            raise RuntimeError(f'Unexpected chip ID 0x{identity:02X}')
        self.identified = True
        if verbose:
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
        if verbose:
            print(f'NFC-V RF enabled; op=0x{self.rd(0x02):02X} I/O2=0x{self.rd(0x01):02X}', flush=True)
    def transceive(self, frame, timeout, *, tx_command=0xc5, extra_bits=0, max_rx=MAX_V_FIFO):
        """Poll latched IRQs together because every IRQ read clears the registers."""
        ticks = min(65535, max(1, int(timeout * 13560000 / 4096)))
        self.update(0x12, setbits=0x01)
        self.wr(0x10, ticks >> 8)
        self.wr(0x11, ticks & 255)
        try:
            self.cmd(0xdb)
            self.irqs()
            if frame:
                self.send(0x80, *frame)
            nbits = len(frame) * 8 + extra_bits
            self.wr(0x22, nbits >> 8)
            self.wr(0x23, nbits & 255)
            self.cmd(tx_command)
            deadline = time.monotonic() + timeout + .025
            main = timer = errors = 0
            while time.monotonic() < deadline:
                irq_main, irq_timer, irq_error, _ = self.irqs()
                main |= irq_main
                timer |= irq_timer
                errors |= irq_error
                if main & 0x18 == 0x18:
                    low, high = self.read(0x5e, 2)
                    size = low | ((high & 0xc0) << 2)
                    if not size or size > max_rx or high & 0x30:
                        raise FrameError('fifo', f'Invalid RX FIFO (size {size}, status 0x{high:02X})')
                    return self.read(0x9f, size), high, errors
                if timer & 0x40 and not main & 0x20:
                    break
                time.sleep(.001)
            raise TimeoutError('Tag did not respond' if main & 0x08 else 'NFC transmit did not finish')
        finally:
            # STOP terminates the exchange without switching off the RF field.
            # Clear stale RX/IRQ state so the next inventory can start cleanly.
            self.cmd(0xc2)
            self.cmd(0xdb)
            self.irqs()

    def exchange(self, payload, timeout=.12, verbose=False):
        raw, _, _ = self.transceive(encode_vcd(payload), timeout)
        if verbose:
            print(f'  RF raw={raw.hex(" ")}', flush=True)
        return decode_response(raw)

    def inventory(self, timeout=.12, verbose=False):
        try:
            decoded = self.exchange((0x26, 0x01, 0x00), timeout, verbose)
            if len(decoded) != 10 or decoded[0] & 1:
                raise FrameError('framing', 'Unexpected ISO15693 inventory response')
        except (FrameError, TimeoutError) as exc:
            self.inventory_error = exc
            if verbose:
                print(f'Inventory: {exc}', flush=True)
            return None
        self.inventory_error = None
        return decoded[2:10][::-1].hex().upper(), decoded

    def shutdown(self):
        if self.identified:
            try:
                self.cmd(0xc2)
            finally:
                self.update(0x02, clearbits=0x48)


def main():
    p = argparse.ArgumentParser(description='PT35 ISO15693 inventory scan (read-only)')
    p.add_argument('--bus',type=int,default=1)
    p.add_argument('--count',type=int,default=30)
    p.add_argument('--delay',type=float,default=.35)
    p.add_argument('--verbose',action='store_true')
    opts=p.parse_args()
    from smbus2 import SMBus

    handle_sigterm()
    with reader_lock(f'i2c-{opts.bus}'), SMBus(opts.bus) as bus:
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
