#!/usr/bin/env python3
"""PT35 read-only NFC frontend and JSON-lines worker for the desktop app."""
import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import nfc_pm3 as pm3
from nfc_archive import is_known_tonie, migrate_archive, now, record_path, save_record
from nfc_config import DEFAULT_ARCHIVE, LEGACY_ARCHIVE, handle_sigterm, reader_lock
from nfcv_dump import Reader, failure, is_sli_l, read_memory

VERSION = '0.2.0'
INTERNAL_PROTOCOLS = ('ISO15693',)


def new_record(uid, backend, dsfid=None, protocol='ISO15693'):
    manufacturer = 'Unknown'
    if protocol == 'ISO15693':
        manufacturer = {'E004': 'NXP', 'E002': 'STMicroelectronics'}.get(uid[:4], 'Unknown')
    candidate = manufacturer == 'NXP'
    record = dict(format='PT35-NFC-archive-v2', uid=uid.upper(), protocol=protocol,
                  manufacturer=manufacturer, classification='tonie_candidate' if candidate else 'other',
                  classification_verified=False, backend=backend,
                  dsfid=f'{dsfid:02X}' if dsfid is not None else None,
                  last_seen_utc=now(), blocks=[], read_errors=[], dump_status='not_requested')
    if protocol == 'ISO15693' and is_sli_l(uid):
        record['chip'] = 'NXP ICODE SLI-L / SLIX-L (UID type 03)'
    return record


def skip_internal_uid(uid, include, exclude):
    # E002 identifies the vendor, so never use it to hide all external ST tags.
    return not include and bool(exclude) and uid == exclude.upper()


class Events:
    def __init__(self, json_lines):
        self.json_lines = json_lines

    def __call__(self, event, message, **data):
        if self.json_lines:
            print(json.dumps({'event': event, 'message': message, **data}), flush=True)
        else:
            print(message, flush=True)


def backend_choice(args, emit):
    if args.backend != 'internal':
        client = pm3.pm3_client(args.client)
        ports = pm3.usb_ports()
        if args.port:
            requested = str(Path(args.port).resolve())
            ports = [port for port in ports if str(Path(port).resolve()) == requested]
        reason = ('Iceman client missing or not executable' if not client else
                  'No matching Proxmark3 USB descriptor' if not ports else '')
        if client:
            for port in ports:
                try:
                    with reader_lock(Path(port).name):
                        reason = pm3.probe(client, port)
                except RuntimeError as exc:
                    reason = str(exc)
                if reason is None:
                    emit('backend', f'Proxmark3/Iceman connected on {port}', backend='proxmark3',
                         capabilities=['ISO15693 inventory', 'HF/LF identify logs'], port=port)
                    return 'proxmark3', client, port
        emit('fault', f'Proxmark3 unavailable: {reason}', backend='proxmark3')
        if args.backend == 'proxmark3':
            return None, None, None
    return 'internal', None, None


def tag_event(args, emit, record):
    candidate = record['classification'] == 'tonie_candidate'
    known = candidate and is_known_tonie(record['uid'], args.archive)
    record['tonie_status'] = ('known_tonie' if known else 'possible_tonie' if candidate else
                              'not_identified_as_tonie')
    if known:
        record.update(classification='known_tonie', classification_verified=True)
    uid = record['uid']
    emit('tag', f"FOUND {uid} | {record['protocol']} | {record['dump_status']}", record=record)
    if args.save or (args.auto_tonie and known) or (args.auto_candidates and candidate):
        try:
            path = save_record(args.archive, record)
        except (OSError, ValueError) as exc:
            emit('fault', f'Archive save failed: {exc}')
        else:
            emit('archived', f'Archived {uid}', path=str(path))


def internal_operation(args, emit):
    try:
        from smbus2 import SMBus
    except ImportError as exc:
        raise RuntimeError('Install python3-smbus2 for the internal reader') from exc
    # Legacy verbose hex diagnostics stay off the JSON-lines stream.
    diagnostics = contextlib.redirect_stdout(sys.stderr) if args.json_lines else contextlib.nullcontext()
    with reader_lock(f'i2c-{args.bus}'), SMBus(args.bus) as bus:
        reader = Reader(bus)
        if args.action == 'status':
            identity = reader.rd(0x3f)
            if identity >> 3 != 5:
                raise RuntimeError(f'Unexpected ST25R3916 ID 0x{identity:02X}')
            emit('backend', f'Internal ST25R3916 connected (0x{identity:02X})',
                 backend='internal', capabilities=list(INTERNAL_PROTOCOLS))
            return
        try:
            with diagnostics:
                reader.initialize(verbose=args.verbose)
            emit('backend', 'Internal ST25R3916 connected', backend='internal',
                 capabilities=list(INTERNAL_PROTOCOLS))
            last = {}
            attempts = 0
            last_error = None
            while args.watch or attempts < args.tries:
                attempts += 1
                with diagnostics:
                    result = reader.inventory(verbose=args.verbose)
                if result and not skip_internal_uid(result[0], args.include_st, args.exclude_uid):
                    uid, payload = result
                    current = time.monotonic()
                    if uid not in last or current - last[uid] >= args.repeat_after:
                        if len(last) >= 256:
                            last.pop(next(iter(last)))
                        last[uid] = current
                        record = new_record(uid, 'internal', dsfid=payload[1])
                        with diagnostics:
                            record.update(read_memory(reader, uid, args.blocks, args.verbose))
                        tag_event(args, emit, record)
                        if not args.watch:
                            return
                error = reader.inventory_error
                state = (failure(error)['kind'] if error else 'tag')
                if state != last_error and error:
                    emit('scan_state', 'Waiting for tag' if state == 'timeout' else str(error), state=state)
                last_error = state
                time.sleep(args.delay)
        finally:
            reader.shutdown()


def pm3_operation(args, emit, client, port):
    with reader_lock(Path(port).name):
        if args.action == 'identify':
            for command in ('hf search', 'lf search'):
                code, output = pm3.run_pm3(client, port, command)
                emit('log', f'{command} (exit {code})\n{output}')
            return
        if args.action == 'pm3-shell':
            subprocess.run([client, '-p', port], check=True)
            return
        last = None
        last_time = 0
        attempts = 0
        while args.watch or attempts < args.tries:
            attempts += 1
            if not Path(port).exists():
                raise OSError(f'Proxmark3 disconnected ({port})')
            uid, output, _ = pm3.pm3_inventory(client, port)
            if args.verbose:
                emit('log', output.strip())
            if uid and (uid != last or time.monotonic() - last_time >= args.repeat_after):
                last, last_time = uid, time.monotonic()
                tag_event(args, emit, new_record(uid, 'proxmark3'))
                if not args.watch:
                    return
            time.sleep(args.delay)


def main():
    p = argparse.ArgumentParser(description='PT35 NFC dual-reader and local archive')
    p.add_argument('action', choices=['status', 'scan', 'watch', 'list', 'show', 'identify', 'pm3-shell',
                                       'migrate-archive'], nargs='?', default='scan')
    p.add_argument('uid', nargs='?', help='tag identifier for show')
    p.add_argument('--backend', choices=['auto', 'internal', 'proxmark3'], default='auto')
    p.add_argument('--port', help='select a detected Proxmark3 serial port')
    p.add_argument('--client', help='path to the Iceman client executable')
    p.add_argument('--bus', type=int, default=1)
    p.add_argument('--archive', type=Path, default=DEFAULT_ARCHIVE)
    p.add_argument('--save', action='store_true', help='save all discovered tags')
    p.add_argument('--auto-tonie', action='store_true', help='save UID matches in known_tonies.txt')
    p.add_argument('--auto-candidates', action='store_true', help='also save unverified NXP candidates')
    p.add_argument('--include-st', action='store_true', help='include the configured onboard ST25DV UID')
    p.add_argument('--exclude-uid', default=os.environ.get('PT35_NFC_ONBOARD_UID'),
                   help='exact onboard ST25DV UID to omit')
    p.add_argument('--blocks', type=int, default=0, help='ISO15693 blocks (0 = geometry or conservative probe)')
    p.add_argument('--tries', type=int, default=40)
    p.add_argument('--delay', type=float, default=.25)
    p.add_argument('--repeat-after', type=float, default=30)
    p.add_argument('--json-lines', action='store_true')
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()
    args.watch = args.action == 'watch'
    args.archive = args.archive.expanduser().resolve()
    if not 0 <= args.blocks <= 256 or args.tries < 1 or not 0 <= args.delay <= 10 or args.repeat_after < 0:
        p.error('Invalid block count, retry count or scan interval')
    if args.exclude_uid and not re.fullmatch(r'E002[0-9A-F]{12}', args.exclude_uid.upper()):
        p.error('--exclude-uid must be the exact onboard 16-digit ST25DV UID')
    emit = Events(args.json_lines)
    handle_sigterm()
    try:
        if args.action == 'migrate-archive':
            print(f'Copied {migrate_archive(LEGACY_ARCHIVE, args.archive)} missing archive files.')
            return 0
        if args.action == 'list':
            for path in sorted(args.archive.glob('*/record.json')):
                try:
                    record = json.loads(path.read_text())
                    print(record['uid'], record['protocol'], record.get('dump_status', '?'))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    print(f'{path}: {exc}', file=sys.stderr)
            return 0
        if args.action == 'show':
            if not args.uid:
                p.error('show requires a UID')
            print(record_path(args.archive, args.uid).read_text(encoding='utf-8'))
            return 0
        backend, client, port = backend_choice(args, emit)
        if backend is None:
            return 2
        if backend == 'internal':
            if args.action in ('identify', 'pm3-shell'):
                raise RuntimeError('This operation requires a responsive Proxmark3/Iceman')
            internal_operation(args, emit)
        elif args.action != 'status':
            try:
                pm3_operation(args, emit, client, port)
            except (OSError, subprocess.TimeoutExpired) as exc:
                if args.backend != 'auto' or args.action not in ('scan', 'watch'):
                    raise
                emit('fault', f'Proxmark3 unavailable: {exc}. Switching to internal reader.')
                internal_operation(args, emit)
    except KeyboardInterrupt:
        emit('stopped', 'Stopped')
        return 130
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        emit('fault', str(exc))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
