#!/usr/bin/env python3
"""PT35 ISO15693 / Tonie read-only archive. Uses the working nfcv_scan.py driver.

Saves UID and standard Read Single Block data, not protected secrets or authentication.
No writes to tags. The ST25R3916 does NOT emulate NFC-V Tonies.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from smbus2 import SMBus
from nfcv_scan import Chip, encode_vcd, crc15693

VERSION = '1.0'


def decode_response(raw, sizes=(7, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16)):
    """Decode variable-size NFC-V response, by CRC-tested candidate lengths.

    ST25R3916 stream mode delivers a 5-bit SOF, Manchester symbols, then EOF.
    We stop after the candidate's exact number of payload bytes, as for our
    already-proven inventory decoder. CRC decides which candidate was correct.
    """
    if not raw or (raw[0] & 0x1f) != 0x17:
        raise ValueError('invalid RF SOF')
    total_bits = len(raw) * 8
    for size in sizes:
        bits = size * 8
        if (5 + 2 * bits) > total_bits:
            continue
        data = bytearray(size)
        valid = True
        for i in range(bits):
            p = 5 + i * 2
            sym = ((raw[p // 8] >> (p % 8)) & 1) | (((raw[(p + 1) // 8] >> ((p + 1) % 8)) & 1) << 1)
            if sym not in (1, 2):
                valid = False
                break
            if sym == 2:
                data[i // 8] |= 1 << (i % 8)
        if valid and crc15693(data[:-2]) == (data[-2] | (data[-1] << 8)):
            return bytes(data[:-2])
    raise ValueError('no CRC-valid RF payload found')


class Reader(Chip):
    def exchange(self, payload, timeout=0.35, verbose=False):
        frame = encode_vcd(payload)
        ticks = min(65535, max(1, int(timeout * 13560000 / 4096)))
        self.update(0x12, setbits=0x01)
        self.wr(0x10, ticks >> 8)
        self.wr(0x11, ticks & 255)
        self.irqs()
        self.cmd(0xdb)
        self.send(0x80, *frame)
        nbits = len(frame) * 8
        self.wr(0x22, nbits >> 8)
        self.wr(0x23, nbits & 255)
        self.cmd(0xc5)
        irq_tx = self.await_irq(0x08, timeout + 0.1)
        if not (irq_tx & 0x08):
            raise TimeoutError('NFC-V transmit did not finish')
        irq_rx = self.await_irq(0x10, timeout + 0.1)
        b1, b2 = self.read(0x5e, 2)
        n = b1 | ((b2 & 0xc0) << 2)
        if n == 0:
            raise TimeoutError('Tag did not respond')
        raw = self.read(0x9f, min(n, 128))
        if verbose:
            print(f'  IRQ=0x{irq_rx:02X} RF raw={raw.hex(" ")}', flush=True)
        return decode_response(raw)

    def read_single(self, uid, block, verbose=False):
        # Addressed high-rate ISO15693 READ SINGLE BLOCK: 0x22 0x20 UID[LSB-first] block.
        # Use address flag because the PT35 itself contains a nearby ST25DV tag.
        payload = bytes((0x22, 0x20)) + bytes.fromhex(uid)[::-1] + bytes((block,))
        answer = self.exchange(payload, verbose=verbose)
        if not answer:
            raise ValueError('empty tag response')
        if answer[0] & 1:
            code = answer[1] if len(answer) > 1 else None
            raise ValueError(f'ISO15693 tag error 0x{code:02X}' if code is not None else 'ISO15693 tag error')
        return answer[1:]


def make_filename(uid):
    return f'{datetime.now().strftime("%Y%m%d-%H%M%S")}_{uid}'


def main():
    ap = argparse.ArgumentParser(description='Read and archive ISO15693 figurine UID + memory blocks')
    ap.add_argument('--bus', type=int, default=1)
    ap.add_argument('--blocks', type=int, default=8, help='maximum memory blocks to read (default: 8)')
    ap.add_argument('--out', default=str(Path.home() / 'pt35-nfc' / 'dumps'))
    ap.add_argument('--uid', help='only save a tag matching this UID')
    ap.add_argument('--all-tags', action='store_true', help='include the PT35 built-in ST25DV tag')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--tries', type=int, default=60, help='inventory attempts, default 60')
    args = ap.parse_args()
    if not 1 <= args.blocks <= 256:
        ap.error('--blocks must be between 1 and 256')
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    with SMBus(args.bus) as bus:
        chip = Reader(bus)
        try:
            chip.initialize()
            print('Place a Tonie figurine against the NFC antenna.', flush=True)
            selected = None
            dsfid = None
            for _ in range(args.tries):
                result = chip.inventory(verbose=args.verbose)
                if result:
                    uid, inventory = result
                    if args.uid and uid.upper() != args.uid.upper():
                        continue
                    if uid.startswith('E002') and not args.all_tags and not args.uid:
                        # This is usually PT35's built-in ST25DV tag; don't archive by accident.
                        if args.verbose:
                            print(f'Ignoring internal ST tag {uid}')
                        time.sleep(.15)
                        continue
                    selected = uid
                    dsfid = inventory[1]
                    break
                time.sleep(.15)
            if not selected:
                print('No matching NFC-V tag found. Try positioning a figurine closer.', flush=True)
                return 1
            print(f'FOUND UID: {selected} DSFID=0x{dsfid:02X}', flush=True)
            blocks, errors = [], []
            for idx in range(args.blocks):
                read = None
                reason = None
                for retry in range(3):
                    try:
                        read = chip.read_single(selected, idx, verbose=args.verbose)
                        if read:
                            break
                        reason = 'empty block'
                    except (TimeoutError, ValueError, OSError) as e:
                        reason = str(e)
                    time.sleep(.08)
                if read:
                    blocks.append({'index': idx, 'hex': read.hex().upper(), 'length': len(read)})
                    print(f'  Block {idx:03d}: {read.hex(" ").upper()}', flush=True)
                else:
                    errors.append({'index': idx, 'reason': reason})
                    print(f'  Block {idx:03d}: FAILED ({reason})', flush=True)
                    # Stop on first unreadable block to avoid hammering protected/out-of-range blocks.
                    break
            complete = len(blocks) == args.blocks
            archive = {
                'format': 'PT35 NFC-V read-only dump v1',
                'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'uid': selected,
                'manufacturer': 'NXP' if selected.startswith('E004') else ('ST' if selected.startswith('E002') else 'unknown'),
                'dsfid': f'{dsfid:02X}',
                'protocol': 'ISO15693 / NFC-V',
                'requested_blocks': args.blocks,
                'blocks': blocks,
                'errors': errors,
                'complete_requested_range': complete,
                'authentication_data_present': False,
                'note': 'Read-only standard memory dump; not a complete clone or Tonie authentication credential.',
            }
            basename = make_filename(selected)
            path = out / (basename + '.json')
            path.write_text(json.dumps(archive, indent=2) + '\n', encoding='utf-8')
            print(f'JSON saved: {path}', flush=True)
            if complete and len({b['length'] for b in blocks}) == 1:
                rawpath = out / (basename + '.bin')
                rawpath.write_bytes(b''.join(bytes.fromhex(b['hex']) for b in blocks))
                print(f'Binary block dump saved: {rawpath}', flush=True)
            else:
                print('Partial dump: JSON saved with error details; no incomplete .bin file written.')
            return 0 if complete else 2
        finally:
            try:
                chip.shutdown()
            except OSError:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
