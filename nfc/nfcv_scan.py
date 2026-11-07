#!/usr/bin/env python3
"""PT35 ST25R3916 NFC-V (ISO15693) inventory experiment.
Port of M5Stack's NFC-V streaming sequence to Linux smbus2 I2C, no IRQ GPIO.
Read-only RF command: INVENTORY (flags 0x26, command 0x01, mask len 0).
"""
import argparse
import time
from collections import deque
from nfc_config import handle_sigterm, reader_lock

VERSION = '1.3'
INVENTORY_TIMEOUT = .30
ADDRESSED_TIMEOUT = .35
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


def decode_response(raw, *, recover_end=False, last_bits=0, details=None):
    """Decode exactly one bounded VICC frame, including its stream EOF and CRC.

    Each payload byte uses 16 stream bits. M5Stack documents the FIFO SOF
    in the low five bits and the byte-aligned EOF as 0b101 followed by 0x03.
    """
    if not raw or raw[0] & 0x1f != 0x17:
        raise FrameError('framing', 'Invalid NFC-V SOF')
    if len(raw) > MAX_V_FIFO:
        raise FrameError('framing', 'Oversize NFC-V response')
    valid_bits = (len(raw) - 1) * 8 + (last_bits or 8)
    stream = int.from_bytes(raw, 'little') >> 5
    frame = bytearray()
    # At most eleven stream bits can follow the last complete encoded byte.
    # The original scanner ignored those terminal symbols after the CRC.
    boundary = (valid_bits - 5) // 16
    for offset in range(0, len(raw), 2):
        if valid_bits >= offset * 8 + 10 and raw[offset] & 0xe0 == 0xa0 and raw[offset + 1] == 0x03:
            if len(frame) < 3 or any(raw[offset + 2:]):
                raise FrameError('framing', 'Invalid NFC-V frame boundary')
            if crc15693(frame[:-2]) != int.from_bytes(frame[-2:], 'little'):
                raise FrameError('crc', 'NFC-V CRC mismatch')
            return bytes(frame[:-2])
        tail_bits = valid_bits - 5 - 16 * len(frame)
        if recover_end and len(frame) == boundary and len(frame) >= 3 and tail_bits <= 11:
            if crc15693(frame[:-2]) != int.from_bytes(frame[-2:], 'little'):
                raise FrameError('crc', 'NFC-V CRC mismatch')
            if details is not None:
                details['end_recovered'] = True
            return bytes(frame[:-2])
        if valid_bits < offset * 8 + 21:
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
    payload = decode_response(buf, recover_end=True)
    if len(payload) != 10 or payload[0] & 1:
        raise FrameError('framing', 'Unexpected ISO15693 inventory response')
    return payload


class Chip:
    def __init__(self, bus):
        self.bus = bus
        self.identified = False
        self.rf_state = {}
        self.diagnostic = None
        self.trace_context = {}

    def trace(self, stage, result, **details):
        if self.diagnostic is not None:
            self.diagnostic(stage, result, **details)

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
    def initialize(self, verbose=False, configure=None):
        try:
            self._initialize(verbose, configure)
            if self.diagnostic is not None:
                self.trace('configure', 'ok', identity=self.rd(0x3f), op=self.rd(0x02),
                           io2=self.rd(0x01), mode=self.rd(0x03), bitrate=self.rd(0x04),
                           stream=self.rd(0x09))
        except (OSError, RuntimeError):
            self.trace('configure', 'io')
            raise

    def _initialize(self, verbose, configure):
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
        if configure is None:
            self.configure_nfc_v()
        else:
            configure(self)
        self.field_on()
        if verbose:
            print(f'RF enabled; op=0x{self.rd(0x02):02X} I/O2=0x{self.rd(0x01):02X}', flush=True)

    def configure_nfc_v(self):
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
    def field_on(self):
        # NFC collision avoidance, then turn TX/RX on.
        self.cmd(0xc8)
        time.sleep(.006)
        self.update(0x02,setbits=0x48)
        time.sleep(.010)
    def transceive(self, frame, timeout, *, tx_command=0xc5, max_rx=MAX_V_FIFO, check_errors=False,
                   recover_fifo=False):
        """Latch clear-on-read IRQs and retain the original NFC-V FIFO fallback."""
        started = time.monotonic()
        state = self.rf_state = {}
        ticks = min(65535, max(1, int(timeout * 13560000 / 4096)))
        complete = False

        def fifo():
            low, high = self.read(0x5e, 2)
            size = low | ((high & 0xc0) << 2)
            state.update(fifo_size=size, fifo_status=high)
            if size > max_rx or high & 0x30:
                raise FrameError('fifo', f'Invalid RX FIFO (size {size}, status 0x{high:02X})')
            return size, high

        try:
            self.update(0x12, setbits=0x01)
            self.wr(0x10, ticks >> 8)
            self.wr(0x11, ticks & 255)
            self.irqs()
            self.cmd(0xdb)
            if frame:
                self.send(0x80, *frame)
            nbits = len(frame) * 8
            self.wr(0x22, nbits >> 8)
            self.wr(0x23, nbits & 255)
            self.cmd(tx_command)
            sent = time.monotonic()
            deadline = sent + timeout + (.10 if recover_fifo and timeout >= .10 else .025)
            main = timer = errors = 0
            quiet_sample = None
            while time.monotonic() < deadline:
                irq_main, irq_timer, irq_error, _ = self.irqs()
                main |= irq_main
                timer |= irq_timer
                errors |= irq_error
                state.update(irq_main=main, irq_timer=timer, irq_error=errors)
                if check_errors and main & 0x04:
                    raise FrameError('collision', 'RF bit collision')
                if check_errors and errors & 0xf0:
                    raise FrameError('crc' if errors & 0x80 else 'framing',
                                     f'RF receive error 0x{errors:02X}')
                if main & 0x18 == 0x18:
                    size, high = fifo()
                    if not size:
                        raise FrameError('fifo', 'RX ended with empty FIFO')
                    raw = self.read(0x9f, size)
                    complete = True
                    return raw, high, errors
                if timer & 0x40 and not main & 0x20:
                    break
                if recover_fifo and main & 0x08:
                    now = time.monotonic()
                    # A high-rate reply small enough for this FIFO window
                    # finishes in under 20 ms. Recover a stable FIFO even if
                    # RXE never arrives, then still validate the whole frame.
                    if now - sent >= .020:
                        size, high = fifo()
                        if quiet_sample and (size, high) == quiet_sample[:2]:
                            if size and now - quiet_sample[2] >= .004:
                                state['fifo_recovered'] = True
                                return self.read(0x9f, size), high, errors
                        else:
                            quiet_sample = (size, high, now)
                time.sleep(.001)
            if not main & 0x08:
                raise FrameError('tx_timeout', 'NFC transmit did not finish')
            if recover_fifo:
                size, high = fifo()
                if size:
                    raw = self.read(0x9f, size)
                    state['fifo_recovered'] = True
                    return raw, high, errors
            raise TimeoutError('Tag did not respond')
        finally:
            state['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            if not complete:
                self.recover_exchange()

    def recover_exchange(self):
        # STOP is reserved for interrupted or failed exchanges. A successful
        # RXE returns to the original scanner's clear-before-transmit sequence.
        self.cmd(0xc2)
        self.cmd(0xdb)
        self.irqs()

    def exchange(self, payload, timeout=ADDRESSED_TIMEOUT, verbose=False):
        raw, fifo_status, _ = self.transceive(encode_vcd(payload), timeout, recover_fifo=True)
        if verbose:
            print(f'  RF raw={raw.hex(" ")}', flush=True)
        try:
            return decode_response(raw, recover_end=True, last_bits=(fifo_status >> 1) & 7, details=self.rf_state)
        except FrameError:
            if not self.rf_state.get('fifo_recovered'):
                self.recover_exchange()
            raise

    def inventory(self, timeout=INVENTORY_TIMEOUT, verbose=False, *, mask_bits=0, mask=0):
        mask_bytes = mask.to_bytes((mask_bits + 7) // 8, 'little')
        try:
            decoded = self.exchange(bytes((0x26, 0x01, mask_bits)) + mask_bytes, timeout, verbose)
            if len(decoded) != 10 or decoded[0] & 1:
                self.recover_exchange()
                raise FrameError('framing', 'Unexpected ISO15693 inventory response')
            if int.from_bytes(decoded[2:10], 'little') & ((1 << mask_bits) - 1) != mask:
                raise FrameError('framing', 'Inventory response outside requested mask')
        except (FrameError, TimeoutError, OSError) as exc:
            kind = getattr(exc, 'kind', 'timeout' if isinstance(exc, TimeoutError) else 'io')
            self.trace('inventory', kind, mask_bits=mask_bits, **self.rf_state)
            if kind == 'io':
                raise
            self.inventory_error = exc
            if verbose:
                print(f'Inventory: {exc}', flush=True)
            return None
        self.trace('inventory', 'ok', mask_bits=mask_bits, **self.rf_state)
        self.inventory_error = None
        return decoded[2:10][::-1].hex().upper(), decoded

    def shutdown(self):
        if not self.identified:
            self.trace('shutdown', 'not_configured')
            return
        try:
            try:
                self.cmd(0xc2)
            finally:
                self.update(0x02, clearbits=0x48)
            op = self.rd(0x02)
            self.trace('shutdown', 'rf_on' if op & 0x48 else 'ok', op=op, rf_bits=op & 0x48)
            if op & 0x48:
                raise RuntimeError(f'RF shutdown failed (RF bits 0x{op & 0x48:02X})')
        except OSError:
            self.trace('shutdown', 'io')
            raise


class InventorySearch:
    """Split single-slot inventory by LSB-first UID masks after a collision.

    Process one mask per poll. Budget the tree and return to unmasked discovery
    so moving/removing tags cannot leave the scanner stuck in an old search.
    """
    def __init__(self, onboard_uid=None, include_onboard=False):
        self.onboard = int(onboard_uid, 16) if onboard_uid else None
        self.include_onboard = include_onboard
        self.pending = deque()
        self.remaining = 0

    def poll(self, reader, verbose=False, timeout=INVENTORY_TIMEOUT):
        if self.pending and self.remaining:
            bits, mask = self.pending.popleft()
            self.remaining -= 1
            reader.trace('collision_probe', 'ok', mask_bits=bits)
        else:
            self.pending.clear()
            self.remaining = 24
            bits, mask = 0, 0
        result = reader.inventory(timeout=min(timeout, .075) if bits else timeout, verbose=verbose,
                                  mask_bits=bits, mask=mask)
        if result and self.onboard == int(result[0], 16):
            if bits < 64:
                # The onboard tag may have won the unmasked exchange. Search
                # each sibling from this prefix without waking or muting it.
                for index in range(bits, 64):
                    sibling = (self.onboard ^ (1 << index)) & ((1 << (index + 1)) - 1)
                    self.pending.append((index + 1, sibling))
                while len(self.pending) > self.remaining:
                    self.pending.pop()
            return result if self.include_onboard else None
        if not result and getattr(reader.inventory_error, 'kind', None) in (
                'crc', 'manchester', 'framing', 'fifo') and bits < 64:
            self.pending.extendleft(((bits + 1, mask | (1 << bits)), (bits + 1, mask)))
        return result


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
