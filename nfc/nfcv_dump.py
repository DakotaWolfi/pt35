#!/usr/bin/env python3
"""Addressed ISO15693 reads and the standalone PT35 NFC-V dump command."""
import argparse
import time
from contextlib import contextmanager
from pathlib import Path

from nfc_archive import atomic_write, now, range_bytes, record_bytes, record_path, set_coverage
from nfc_config import DEFAULT_ARCHIVE, handle_sigterm, reader_lock
from nfcv_scan import Chip, FrameError, decode_response

VERSION = '1.2'
AUTO_BLOCKS = 32
ALL_KNOWN = -1
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
    @contextmanager
    def transaction(self, stage, **details):
        self.rf_state = {}
        try:
            yield
        except KeyboardInterrupt:
            self.trace(stage, 'interrupted', **details, **self.rf_state)
            raise
        except (FrameError, TagError, TimeoutError, OSError) as exc:
            info = failure(exc)
            if 'code' in info:
                details['tag_error'] = info['code']
            self.trace(stage, info['kind'], **details, **self.rf_state)
            raise
        else:
            self.trace(stage, 'ok', **details, **self.rf_state)

    def read_single(self, uid, block, verbose=False, expected_size=None):
        extended = block >= 256
        payload = (bytes((0x22, 0x30 if extended else 0x20)) + bytes.fromhex(uid)[::-1] +
                   block.to_bytes(2 if extended else 1, 'little'))
        with self.transaction('read_block', block=block, **self.trace_context):
            data = checked_reply(self.exchange(payload, verbose=verbose))[1:]
            if not 1 <= len(data) <= 32 or (expected_size is not None and len(data) != expected_size):
                raise FrameError('size', f'Block {block} has unexpected length {len(data)}')
        return data

    def system_info(self, uid, verbose=False):
        air_uid = bytes.fromhex(uid)[::-1]
        with self.transaction('system_info'):
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
        info = {'flags': flags, 'dsfid': reply[10] if flags & 1 else None,
                'afi': reply[10 + bool(flags & 1)] if flags & 2 else None,
                'ic_reference': ic_reference, 'geometry': geometry}
        if geometry is None and uid.startswith('E002') and ic_reference == 0x26:
            # Standard System Information omits ST25DV16K/64K geometry.
            info['block_size_hint'] = 4
            try:
                with self.transaction('extended_info'):
                    ext = checked_reply(self.exchange(b'\x22\x3b\x14' + air_uid, verbose=verbose))
                    if (len(ext) != 13 or ext[1] != 0x14 or ext[2:10] != air_uid or
                            ext[12] != 3 or int.from_bytes(ext[10:12], 'little') not in (511, 2047)):
                        raise FrameError('framing', 'Invalid ST25DV extended geometry response')
                    info['geometry'] = {'blocks': int.from_bytes(ext[10:12], 'little') + 1, 'size': 4,
                                        'source': 'ST25DV Extended Get System Information'}
            except (FrameError, TagError, TimeoutError) as exc:
                info['extended_error'] = failure(exc)
        return info


def read_memory(reader, uid, limit=0, verbose=False, cap=2048):
    st_tag = uid.startswith('E002')
    for attempt in range(2):
        try:
            info = reader.system_info(uid, verbose)
            break
        except (FrameError, TagError, TimeoutError) as exc:
            info = {'error': failure(exc)}
            if attempt or not (st_tag and isinstance(exc, TagError) and exc.code == 0x0f):
                break
            # ST25DV can return 0Fh during I²C activity. It can also mean an
            # unspecified tag error, so keep the original code in diagnostics.
            time.sleep(.04)
    geometry = info.get('geometry')
    if geometry is None and is_sli_l(uid):
        geometry = dict(SLI_L_GEOMETRY)
    # Eight is a conservative probe limit for unknown tags, never a geometry claim.
    if geometry:
        count = min(cap, geometry['blocks'], geometry['blocks'] if limit == ALL_KNOWN else limit or AUTO_BLOCKS)
    else:
        count = min(cap, 256, limit if limit > 0 else 8)
    width = geometry['size'] if geometry else info.get('block_size_hint')
    blocks, errors = [], []
    missed = 0
    for index in range(count):
        for attempt in range(1, 4):
            reader.trace_context['attempt'] = attempt
            try:
                data = reader.read_single(uid, index, verbose, width)
            except (FrameError, TagError, TimeoutError) as exc:
                ambiguous_st_error = st_tag and isinstance(exc, TagError) and exc.code == 0x0f
                if attempt == 3 or (isinstance(exc, TagError) and not ambiguous_st_error):
                    errors.append({'index': index, **failure(exc)})
                    break
                time.sleep(.04 * attempt if ambiguous_st_error else .02)
            else:
                blocks.append({'index': index, 'hex': data.hex().upper(), 'size': len(data)})
                width = len(data)
                missed = 0
                break
            finally:
                reader.trace_context.clear()
        if errors and errors[-1]['index'] == index:
            kind = errors[-1]['kind']
            if geometry and kind == 'read_protected':
                continue
            missed += 1
            if not geometry or kind in (*TAG_ERRORS.values(), 'tag_error') or missed >= 2:
                break
    record = dict(blocks=blocks, read_errors=errors, system_info=info, memory_start=0,
                  verification='CRC-checked successful RF replies')
    set_coverage(record, count, geometry)
    sizes = {'geometry_blocks': geometry['blocks'], 'geometry_size': geometry['size']} if geometry else {}
    reader.trace('geometry', 'ok' if geometry else 'unknown_geometry', **sizes)
    reader.trace('coverage', record['dump_status'], requested=count, readable=len(blocks), **sizes)
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
