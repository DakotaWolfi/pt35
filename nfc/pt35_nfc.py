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
from functools import partial
from pathlib import Path

import nfc_pm3 as pm3
from nfc_archive import atomic_write, record_bytes, is_known_tonie, migrate_archive, now, record_path, save_record
from nfc_diagnostics import Diagnostics, safe_event
from nfc_poll import MODES, POLL, configure, read_ntag
from nfc_config import DEFAULT_ARCHIVE, LEGACY_ARCHIVE, handle_sigterm, reader_lock
from nfcv_dump import ALL_KNOWN, Reader, failure, is_sli_l, read_memory
from nfcv_scan import FrameError, InventorySearch

VERSION = '0.6.0'
INTERNAL_PROTOCOLS = ('ISO15693', *MODES)
AUTO_INVENTORY_TIMEOUT = .035


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
    def __init__(self, json_lines, collect=False):
        self.json_lines = json_lines
        self.rf = Diagnostics() if collect else None

    def diagnostic(self, stage, result, **details):
        if self.rf is not None:
            self.rf.add(stage, result, **details)
        if self.json_lines:
            event = safe_event(stage, result, **details)
            if event is not None:
                self('diagnostic', '', **event)

    def __call__(self, event, message, **data):
        if self.json_lines:
            print(json.dumps({'event': event, 'message': message, **data}), flush=True)
        elif message:
            print(message, flush=True)


def backend_choice(args, emit, *, quiet=False):
    if args.action in ('identify', 'pm3-shell', 'pm3-dump', 'pm3-simulate') and args.backend == 'auto':
        args.backend = 'proxmark3'
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
                actions = []
                try:
                    with reader_lock(Path(port).name):
                        reason = pm3.probe(client, port)
                        if reason is None:
                            actions = pm3.iso15693_actions(client, port)
                except RuntimeError as exc:
                    reason = str(exc)
                if reason is None:
                    if args.action in ('pm3-dump', 'pm3-simulate') and args.action not in actions:
                        reason = 'Connected firmware does not advertise the requested ISO15693 operation'
                        continue
                    capabilities = ['HF/LF search']
                    if 'pm3-dump' in actions:
                        capabilities.append('ISO15693 addressed reads')
                    if 'pm3-simulate' in actions:
                        capabilities.append('Experimental manual ISO15693 simulation')
                    emit('backend', f'Proxmark3/Iceman connected on {port}', backend='proxmark3',
                         capabilities=capabilities, port=port, pm3_actions=actions)
                    return 'proxmark3', client, port
        if not quiet:
            emit('fault', f'Proxmark3 unavailable: {reason}', backend='proxmark3')
        if args.backend == 'proxmark3':
            return None, None, None
    return 'internal', None, None


def tag_event(args, emit, record):
    candidate = record['classification'] == 'tonie_candidate'
    known = record['protocol'] == 'ISO15693' and is_known_tonie(record['uid'], args.archive)
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


class InternalPoller:
    """Keep the discovered mode active for its read, then continue the sweep."""
    def __init__(self, reader, protocols, inventory, *, bench=False, verbose=False):
        self.reader = reader
        self.protocols = protocols
        self.inventory = inventory
        self.bench = bench
        self.verbose = verbose
        self.current = None
        self.index = 0

    def poll(self):
        protocol = self.protocols[self.index]
        self.index = (self.index + 1) % len(self.protocols)
        if protocol != self.current:
            # Use the same known reset/config/field-on sequence as manual mode.
            # Full reset clears any stale mode-specific RX settings and IRQs.
            profile = None if protocol == 'ISO15693' else partial(configure, protocol=protocol)
            self.reader.initialize(verbose=self.verbose, configure=profile)
            self.current = protocol
        if protocol == 'ISO15693':
            if self.bench:
                result = self.reader.inventory(verbose=self.verbose)
            elif len(self.protocols) > 1:
                result = self.inventory.poll(self.reader, self.verbose, timeout=AUTO_INVENTORY_TIMEOUT)
            else:
                result = self.inventory.poll(self.reader, self.verbose)
            error = self.reader.inventory_error
        else:
            try:
                result, error = POLL[protocol](self.reader), None
            except (FrameError, TimeoutError) as exc:
                result, error = None, exc
        return protocol, result, error


def progress_events(emit, protocol, backend):
    def report(completed, total):
        emit('read_progress', '', protocol=protocol, backend=backend, completed=completed, total=total)

    return report


def internal_operation(args, emit, reselect=None):
    try:
        from smbus2 import SMBus
    except ImportError as exc:
        raise RuntimeError('Install python3-smbus2 for the internal reader') from exc
    # Legacy verbose hex diagnostics stay off the JSON-lines stream.
    diagnostics = contextlib.redirect_stdout(sys.stderr) if args.json_lines else contextlib.nullcontext()
    with reader_lock(f'i2c-{args.bus}'), SMBus(args.bus) as bus:
        reader = Reader(bus)
        reader.diagnostic = emit.diagnostic if emit.json_lines or emit.rf is not None else None
        bench = args.action == 'rf-bench'
        inventory_search = InventorySearch(args.exclude_uid, args.include_st)
        if args.action == 'status':
            identity = reader.rd(0x3f)
            if identity >> 3 != 5:
                raise RuntimeError(f'Unexpected ST25R3916 ID 0x{identity:02X}')
            emit('backend', f'Internal ST25R3916 connected (0x{identity:02X})',
                 backend='internal', capabilities=list(INTERNAL_PROTOCOLS))
            return
        try:
            automatic = args.protocol == 'auto'
            order = args.poll_order if automatic else (args.protocol,)
            poller = InternalPoller(reader, order, inventory_search, bench=bench, verbose=args.verbose)
            emit('backend', f'Internal ST25R3916 · {"Auto NFC" if automatic else args.protocol}',
                 backend='internal', capabilities=list(INTERNAL_PROTOCOLS))
            last = {}
            attempts = 0
            last_error = None
            while args.watch or attempts < args.tries:
                if reselect:
                    selected = reselect()
                    if selected:
                        return selected
                attempts += 1
                with diagnostics:
                    protocol, result, error = poller.poll()
                if result and protocol == 'ISO15693' and skip_internal_uid(result[0], args.include_st, args.exclude_uid):
                    result = None
                if bench:
                    if result and not args.inventory_only:
                        read_memory(reader, result[0], args.blocks, batch=not args.single_block)
                    if attempts < args.tries:
                        time.sleep(args.delay)
                    continue
                if result:
                    uid, details = result
                    key = (protocol, uid)
                    current = time.monotonic()
                    seen, next_read = last.get(key, (0, 0))
                    if current >= next_read or current - seen >= 1.5:
                        if len(last) >= 256 and key not in last:
                            last.pop(next(iter(last)))
                        record = new_record(uid, 'internal', dsfid=details[1] if protocol == 'ISO15693' else None,
                                            protocol=protocol)
                        progress = progress_events(emit, protocol, 'internal')
                        if protocol in ('ISO15693', 'NFC-A'):
                            progress(0, None)
                        with diagnostics:
                            if protocol == 'ISO15693':
                                record.update(read_memory(reader, uid, args.blocks, args.verbose,
                                                          progress=progress, batch=not args.single_block))
                            else:
                                record['discovery'] = details
                                if protocol == 'NFC-A':
                                    record.update(read_ntag(reader, uid, details, progress=progress))
                                else:
                                    record['read_capability'] = 'discovery_only'
                        tag_event(args, emit, record)
                        if not args.watch:
                            return
                        interval = args.repeat_after
                        if record.get('dump_status') in ('partial', 'failed'):
                            interval = min(interval, 2)
                        current = time.monotonic()
                        next_read = current + interval
                    last[key] = current, next_read
                state = failure(error)['kind'] if error else 'waiting'
                if not result and state != last_error:
                    if state in ('timeout', 'waiting'):
                        if not automatic or last_error is None:
                            emit('scan_state', 'Waiting for tag', state='waiting')
                    else:
                        emit('scan_state', str(error), state=state, protocol=protocol)
                last_error = state
                if not automatic:
                    time.sleep(min(args.delay, .035) if inventory_search.pending else args.delay)
        finally:
            reader.shutdown()


def pm3_operation(args, emit, client, port):
    with reader_lock(Path(port).name):
        if args.action == 'pm3-shell':
            subprocess.run([client, '-p', port], check=True)
            return
        if args.action == 'pm3-simulate':
            record = json.loads(record_path(args.archive, args.uid).read_text(encoding='utf-8'))
            if record['uid'] != args.uid:
                raise ValueError('Archive UID does not match selected tag')
            pm3.simulate(client, port, record, emit)
            return
        try:
            if args.action == 'pm3-dump':
                record = new_record(args.uid, 'proxmark3')
                progress = progress_events(emit, 'ISO15693', 'proxmark3')
                progress(0, None)
                record.update(read_memory(pm3.PM3Reader(client, port), args.uid, args.blocks,
                                          args.verbose, cap=32, progress=progress))
                dsfid = record.get('system_info', {}).get('dsfid')
                if dsfid is not None:
                    record['dsfid'] = f'{dsfid:02X}'
                tag_event(args, emit, record)
                return
            modes = ('HF', 'LF') if args.action == 'identify' else (args.pm3_mode,)
            last = {}
            attempts = 0
            waiting = False
            while args.watch or attempts < args.tries:
                attempts += 1
                if not Path(port).exists():
                    raise OSError(f'Proxmark3 disconnected ({port})')
                found = False
                for mode in modes:
                    tags, code, output = pm3.scan(client, port, mode)
                    if args.action == 'identify' or args.verbose:
                        emit('log', f'{mode} search (exit {code})\n{output.strip()}')
                    for protocol, uid in tags:
                        key = (protocol, uid)
                        current = time.monotonic()
                        if current - last.get(key, float('-inf')) >= args.repeat_after:
                            if len(last) >= 256 and key not in last:
                                last.pop(next(iter(last)))
                            last[key] = current
                            record = new_record(uid, 'proxmark3', protocol=protocol)
                            record['pm3_log'] = output.strip()[-12000:]
                            tag_event(args, emit, record)
                        found = True
                    if not tags and 'Valid ' in output and args.action != 'identify' and not args.verbose:
                        emit('log', f'{mode} result has no supported structured identifier:\n{output.strip()}')
                if args.action == 'identify' or found and not args.watch:
                    return
                if not found and not waiting:
                    emit('scan_state', 'Iceman waiting for a recognized tag', state='waiting')
                waiting = not found
                time.sleep(args.delay)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            pm3.stop_rf(client, port, emit)
            raise


def run_reader(args, emit):
    selected = backend_choice(args, emit)
    next_probe = time.monotonic() + 4

    def reselect():
        nonlocal next_probe
        if time.monotonic() >= next_probe:
            next_probe = time.monotonic() + 4
            candidate = backend_choice(args, emit, quiet=True)
            if candidate[0] == 'proxmark3':
                return candidate
        return None

    while True:
        backend, client, port = selected
        if backend is None:
            if not args.watch:
                return 2
            time.sleep(2)
            selected = backend_choice(args, emit)
            continue
        if backend == 'internal':
            if args.action in ('identify', 'pm3-shell', 'pm3-dump', 'pm3-simulate'):
                raise RuntimeError('This operation requires a responsive Proxmark3/Iceman')
            try:
                selected = internal_operation(args, emit, reselect if args.watch and args.backend == 'auto' else None)
            except OSError as exc:
                if not args.watch or args.backend != 'auto':
                    raise
                emit('fault', f'Internal reader unavailable: {exc}. Retrying reader selection.')
                time.sleep(2)
                selected = backend_choice(args, emit)
            if not selected:
                return 0
        else:
            try:
                if args.action != 'status':
                    pm3_operation(args, emit, client, port)
                return 0
            except (OSError, subprocess.TimeoutExpired) as exc:
                if args.action not in ('scan', 'watch'):
                    raise
                emit('fault', f'Proxmark3 unavailable: {exc}', backend='proxmark3')
                if args.backend == 'auto':
                    next_probe = time.monotonic() + 4
                    selected = ('internal', None, None)
                elif args.watch:
                    time.sleep(2)
                    selected = backend_choice(args, emit)
                else:
                    raise


def main():
    p = argparse.ArgumentParser(description='PT35 NFC dual-reader and local archive')
    p.add_argument('--version', action='version', version=f'PT35 NFC {VERSION}')
    p.add_argument('action', choices=['status', 'scan', 'watch', 'list', 'show', 'identify', 'pm3-shell',
                                       'migrate-archive', 'pm3-dump', 'pm3-simulate', 'rf-bench'], nargs='?', default='scan')
    p.add_argument('uid', nargs='?', help='tag identifier for show, pm3-dump or pm3-simulate')
    p.add_argument('--backend', choices=['auto', 'internal', 'proxmark3'], default='auto')
    p.add_argument('--pm3-mode', choices=pm3.PM3_MODES, default='HF')
    p.add_argument('--confirm-emulation', action='store_true', help='explicitly authorize a 10-second simulation')
    p.add_argument('--port', help='select a detected Proxmark3 serial port')
    p.add_argument('--client', help='path to the Iceman client executable')
    p.add_argument('--protocol', choices=('auto', *INTERNAL_PROTOCOLS), default='auto',
                   help='internal HF technology (Auto sweeps NFC-V/A/B/F)')
    p.add_argument('--poll-order', default=','.join(INTERNAL_PROTOCOLS),
                   help='comma-separated Auto sweep order')
    p.add_argument('--single-block', action='store_true', help='skip NFC-V multi-block commands')
    p.add_argument('--bus', type=int, default=1)
    p.add_argument('--archive', type=Path, default=DEFAULT_ARCHIVE)
    p.add_argument('--save', action='store_true', help='save all discovered tags')
    p.add_argument('--auto-tonie', action='store_true', help='save UID matches in known_tonies.txt')
    p.add_argument('--auto-candidates', action='store_true', help='also save unverified NXP candidates')
    p.add_argument('--include-st', action='store_true', help='include the configured onboard ST25DV UID')
    p.add_argument('--exclude-uid', default=os.environ.get('PT35_NFC_ONBOARD_UID'),
                   help='exact onboard ST25DV UID to omit')
    p.add_argument('--blocks', type=int, default=0, help='ISO15693 blocks (0 = auto, -1 = all known blocks)')
    p.add_argument('--tries', type=int, default=40)
    p.add_argument('--delay', type=float, default=.25)
    p.add_argument('--repeat-after', type=float, default=30)
    p.add_argument('--json-lines', action='store_true')
    p.add_argument('--verbose', action='store_true', help='include private raw output locally')
    p.add_argument('--inventory-only', action='store_true', help='rf-bench: compare unmasked inventory only')
    p.add_argument('--diagnostics', type=Path, help='write a redacted NFC-V diagnostics JSON file')
    args = p.parse_args()
    args.poll_order = tuple(args.poll_order.split(','))
    if len(args.poll_order) != len(INTERNAL_PROTOCOLS) or set(args.poll_order) != set(INTERNAL_PROTOCOLS):
        p.error('--poll-order must list ISO15693,NFC-A,NFC-B,NFC-F once each')
    args.watch = args.action == 'watch'
    bench = args.action == 'rf-bench'
    if bench:
        args.backend, args.protocol, args.verbose = 'internal', 'ISO15693', False
    args.archive = args.archive.expanduser().resolve()
    if not ALL_KNOWN <= args.blocks <= 2048 or args.tries < 1 or not 0 <= args.delay <= 10 or args.repeat_after < 0:
        p.error('Invalid block count, retry count or scan interval')
    if args.exclude_uid and not re.fullmatch(r'E002[0-9A-F]{12}', args.exclude_uid.upper()):
        p.error('--exclude-uid must be the exact onboard 16-digit ST25DV UID')
    if args.action in ('pm3-dump', 'pm3-simulate'):
        args.uid = (args.uid or '').upper()
        if not re.fullmatch(r'E0[0-9A-F]{14}', args.uid):
            p.error('This operation requires a 16-digit ISO15693 UID')
    if args.action == 'pm3-simulate' and not args.confirm_emulation:
        p.error('Simulation requires --confirm-emulation after selecting an authorized bench tag')
    emit = Events(args.json_lines, collect=bench or args.diagnostics is not None)
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
            print(record_path(args.archive, args.uid, 'ISO15693' if args.protocol == 'auto' else args.protocol).read_text(encoding='utf-8'))
            return 0
        return run_reader(args, emit)
    except KeyboardInterrupt:
        emit('stopped', 'Stopped')
        return 130
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        emit('fault', str(exc))
        return 2
    finally:
        if emit.rf is not None:
            report = emit.rf.export()
            if bench:
                emit('summary', json.dumps(report['counts'], sort_keys=True), counts=report['counts'])
            if args.diagnostics:
                try:
                    atomic_write(args.diagnostics.expanduser(), record_bytes(report))
                except OSError as exc:
                    emit('fault', f'Could not export diagnostics: {exc}')
                    return 2


if __name__ == '__main__':
    raise SystemExit(main())
