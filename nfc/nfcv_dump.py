#!/usr/bin/env python3
"""Addressed ISO15693 reads and the standalone PT35 NFC-V dump command."""
import argparse
import time
from pathlib import Path

from nfc_archive import atomic_write, now, range_bytes, record_bytes, record_path, set_coverage
from nfc_config import DEFAULT_ARCHIVE, handle_sigterm, reader_lock
from nfcv_scan import Chip, FrameError, decode_response

VERSION = '1.1'
# SLIX-L datasheet: UID tag type 03h (also used by SLI-L), 8 x 4 user blocks.
SLI_L_GEOMETRY = {'blocks': 8, 'size': 4, 'source': 'NXP UID type 03'}
TAG_ERRORS = {0x01: 'unsupported_command', 0x02: 'unrecognized_command',
              0x03: 'unsupported_option', 0x10: 'block_unavailable',
              0x12: 'block_locked', 0x15: 'read_protected'}


class TagError(ValueError):
    def __init__(self, code):
        self.code = code
        self.kind = TAG_ERRORS.get(code, 'tag_error')
        super().__init__(f'ISO15693 error 0x{code:02X} ({self.kind})')


def checked_reply(reply):
    if not reply:
        raise FrameError('framing', 'Empty ISO15693 response')
    if reply[0] & 1:
        if len(reply) != 2:
            raise FrameError('framing', 'Invalid ISO15693 error response')
        raise TagError(reply[1])
    return reply


def failure(exc):
    kind = getattr(exc, 'kind', 'timeout' if isinstance(exc, TimeoutError) else 'io')
    result = {'kind': kind, 'error': str(exc)}
    if isinstance(exc, TagError):
        result['code'] = exc.code
    return result


def is_sli_l(uid):
    return uid.startswith('E00403')


class Reader(Chip):
    def read_single(self, uid, block, verbose=False, expected_size=None):
        extended = block >= 256
        payload = (bytes((0x22, 0x30 if extended else 0x20)) + bytes.fromhex(uid)[::-1] +
                   block.to_bytes(2 if extended else 1, 'little'))
        data = checked_reply(self.exchange(payload, verbose=verbose))[1:]
        if not 1 <= len(data) <= 32 or (expected_size is not None and len(data) != expected_size):
            raise FrameError('size', f'Block {block} has unexpected length {len(data)}')
        return data

    def system_info(self, uid, verbose=False):
        air_uid = bytes.fromhex(uid)[::-1]
        reply = checked_reply(self.exchange(b'\x22\x2b' + air_uid, verbose=verbose))
        if len(reply) < 10 or reply[2:10] != air_uid:
            raise FrameError('framing', 'System Information UID mismatch or truncated reply')
        flags = reply[1]
        size = 10 + bool(flags & 1) + bool(flags & 2) + 2 * bool(flags & 4) + bool(flags & 8)
        if flags & 0xf0 or len(reply) != size:
            raise FrameError('framing', 'Invalid System Information fields')
        geometry = None
        if flags & 4:
            pos = 10 + bool(flags & 1) + bool(flags & 2)
            if reply[pos + 1] & 0xe0:
                raise FrameError('framing', 'Invalid System Information block size')
            geometry = {'blocks': reply[pos] + 1, 'size': reply[pos + 1] + 1,
                        'source': 'ISO15693 Get System Information'}
        ic_reference = reply[-1] if flags & 8 else None
        if geometry is None and uid.startswith('E002') and ic_reference == 0x26:
            # ST25DV16K/64K omit geometry from standard System Information.
            ext = checked_reply(self.exchange(b'\x22\x3b\x14' + air_uid, verbose=verbose))
            if (len(ext) != 13 or ext[1] != 0x14 or ext[2:10] != air_uid or
                    ext[12] != 3 or int.from_bytes(ext[10:12], 'little') not in (511, 2047)):
                raise FrameError('framing', 'Invalid ST25DV extended geometry response')
            geometry = {'blocks': int.from_bytes(ext[10:12], 'little') + 1, 'size': 4,
                        'source': 'ST25DV Extended Get System Information'}
        return {'flags': flags, 'ic_reference': ic_reference, 'geometry': geometry}


def read_memory(reader, uid, limit=0, verbose=False):
    try:
        info = reader.system_info(uid, verbose)
    except (FrameError, TagError, TimeoutError) as exc:
        info = {'error': failure(exc)}
    geometry = info.get('geometry')
    if geometry is None and is_sli_l(uid):
        geometry = dict(SLI_L_GEOMETRY)
    # Eight is a conservative probe limit for unknown tags, never a geometry claim.
    count = (min(limit or 256, geometry['blocks']) if geometry else min(limit or 8, 256))
    width = geometry['size'] if geometry else None
    blocks, errors = [], []
    for index in range(count):
        for attempt in range(3):
            try:
                data = reader.read_single(uid, index, verbose, width)
            except (FrameError, TagError, TimeoutError) as exc:
                if isinstance(exc, TagError) or attempt == 2:
                    errors.append({'index': index, **failure(exc)})
                    break
                time.sleep(.02)
            else:
                blocks.append({'index': index, 'hex': data.hex().upper(), 'size': len(data)})
                width = len(data)
                break
        if errors:
            # A missing block is evidence about this attempt only. Never infer size from silence.
            break
    record = dict(blocks=blocks, read_errors=errors, system_info=info, memory_start=0,
                  verification='CRC-checked successful RF replies')
    set_coverage(record, count, geometry)
    return record


def main():
    ap = argparse.ArgumentParser(description='Read and archive ISO15693 UID and memory blocks')
    ap.add_argument('--bus', type=int, default=1)
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--out', type=Path, default=DEFAULT_ARCHIVE.parent / 'dumps')
    ap.add_argument('--uid', help='only save a tag matching this UID')
    ap.add_argument('--all-tags', action='store_true', help='include configured onboard ST25DV UID')
    ap.add_argument('--exclude-uid', help='onboard ST25DV UID to omit')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--tries', type=int, default=60)
    args = ap.parse_args()
    if not 1 <= args.blocks <= 2048 or args.tries < 1:
        ap.error('--blocks must be 1..2048 and --tries must be positive')
    from smbus2 import SMBus
    from pt35_nfc import new_record, skip_internal_uid
    handle_sigterm()
    with reader_lock(f'i2c-{args.bus}'), SMBus(args.bus) as bus:
        reader = Reader(bus)
        try:
            reader.initialize(args.verbose)
            print('Present an ISO15693 tag.', flush=True)
            for _ in range(args.tries):
                result = reader.inventory(verbose=args.verbose)
                if result:
                    uid, inventory = result
                    if (args.uid and uid == args.uid.upper()) or (not args.uid and not
                            skip_internal_uid(uid, args.all_tags, args.exclude_uid)):
                        record = new_record(uid, 'internal', dsfid=inventory[1])
                        record.update(read_memory(reader, uid, args.blocks, args.verbose))
                        break
                time.sleep(.15)
            else:
                print('No matching NFC-V tag found.')
                return 1
        except KeyboardInterrupt:
            return 130
        finally:
            reader.shutdown()
    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    stem = f"{now().replace(':', '-')}_{record['uid']}"
    path = out / (stem + '.json')
    binary = range_bytes(record)
    if binary is not None:
        record['memory_binary'] = stem + '.bin'
        atomic_write(out / record['memory_binary'], binary)
    atomic_write(path, record_bytes(record))
    print(f"{record['dump_status']}: {path}")
    return 0 if binary is not None else 2


if __name__ == '__main__':
    raise SystemExit(main())
