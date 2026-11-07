#!/usr/bin/env python3
"""PT35 read-only NFC frontend and JSON-lines worker for the desktop app."""
import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import nfc_pm3 as pm3
from nfc_archive import atomic_write, record_bytes, is_known_tonie, migrate_archive, now, record_path, save_record
from nfc_capture_history import compare
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


def announce_pm3(link, emit):
    emit('pm3_status', link.message, state=link.state, firmware=link.firmware)
    if link.state == 'connected':
        capabilities = ['HF discovery', 'explicit LF search']
        if 'pm3-dump' in link.actions:
            capabilities.append('ISO15693 addressed reads')
        if 'pm3-simulate' in link.actions:
            capabilities.append('Experimental manual ISO15693 simulation')
        emit('backend', 'Proxmark3 · Iceman', backend='proxmark3', capabilities=capabilities,
             port=link.port, pm3_actions=list(link.actions))


def backend_choice(args, emit):
    pm3_action = args.action in ('identify', 'pm3-shell', 'pm3-dump', 'pm3-simulate')
    if args.backend == 'internal' and pm3_action:
        raise RuntimeError('This operation requires Proxmark3/Iceman')
    if args.backend != 'internal':
        link = pm3.connect(args.client, args.port)
        announce_pm3(link, emit)
        if link.state == 'connected':
            if args.action in ('pm3-dump', 'pm3-simulate') and args.action not in link.actions:
                raise RuntimeError('Connected firmware does not advertise the requested ISO15693 operation')
            return 'proxmark3', link.client, link.port
        if args.backend == 'proxmark3' or pm3_action:
            return None, None, None
    return 'internal', None, None


class PM3Monitor:
    """Probe one USB candidate in parallel with internal RF scans."""
    def __init__(self, args, emit):
        self.args = args
        self.emit = emit
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pm3-probe')
        self.cancel = threading.Event()
        self.future = None
        self.next_probe = 0
        self.reported = None

    def poll(self):
        now = time.monotonic()
        if self.future is not None and self.future.done():
            link = self.future.result()
            self.future = None
            self.next_probe = now + (1 if link.state == 'absent' else 3)
            if link.state == 'connected':
                return link
            if link != self.reported:
                self.emit('pm3_status', link.message, state=link.state)
                self.reported = link
        if self.future is None and now >= self.next_probe:
            self.future = self.pool.submit(pm3.connect, self.args.client, self.args.port, self.cancel)
        return None

    def close(self):
        self.cancel.set()
        self.pool.shutdown(cancel_futures=True)


def auto_watch(args, emit):
    monitor = PM3Monitor(args, emit)
    try:
        while True:
            try:
                link = internal_operation(args, emit, monitor.poll)
            except OSError as exc:
                emit('fault', f'Internal reader unavailable: {exc}. Retrying reader selection.')
                time.sleep(.5)
                link = monitor.poll()
                if not link:
                    continue
            if not link:
                return 0
            # internal_operation has already cleared TX/RX and released I2C.
            announce_pm3(link, emit)
            try:
                pm3_operation(args, emit, link.client, link.port, link.actions)
                return 0
            except (OSError, subprocess.TimeoutExpired):
                emit('pm3_status', 'Proxmark3 connection lost · using internal reader', state='unresponsive')
                monitor.reported = None
    finally:
        monitor.close()


def tag_event(args, emit, record):
    candidate = record['classification'] == 'tonie_candidate'
    known = record['protocol'] == 'ISO15693' and is_known_tonie(record['uid'], args.archive)
    record['tonie_status'] = ('known_tonie' if known else 'possible_tonie' if candidate else
                              'not_identified_as_tonie')
    if known:
        record.update(classification='known_tonie', classification_verified=True)
    uid = record['uid']
    # All scans, even partial/discovery-only ones, are saved LOCALLY. Invalid
    # frames are never silently passed off as verified blocks.
    try:
        path = record_path(args.archive, uid, record['protocol'])
        previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        comparison = compare(previous, record)
    except (OSError, ValueError, TypeError):
        comparison = 'unknown'
    record['rescan_comparison'] = comparison
    emit('tag', f"FOUND {uid} | {record['protocol']} | {record['dump_status']}",
         record=record, comparison=comparison)
    try:
        path = save_record(args.archive, record)
    except (OSError, ValueError) as exc:
        emit('fault', f'Archive save failed: {exc}')
    else:
        emit('archived', f'Archived {uid}', path=str(path), comparison=comparison)


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
                rssi = reader.rf_state.get('rssi_am') if result else None
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
                        emit('tag_detected', 'Tag detected', protocol=protocol,
                             rssi_am=rssi if isinstance(rssi, int) and 0 <= rssi <= 15 else None)
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


def pm3_operation(args, emit, client, port, actions=()):
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
                        previous_seen, previous_read = last.get(key, (0.0, -1e9))
                        # Presenting the tag again after absence rereads it;
                        # an unchanged held tag is retried only periodically.
                        re_presented = current - previous_seen >= 1.5
                        retry_due = current - previous_read >= min(args.repeat_after, 5.0)
                        if re_presented or retry_due:
                            if len(last) >= 256 and key not in last:
                                last.pop(next(iter(last)))
                            record = new_record(uid, 'proxmark3', protocol=protocol)
                            record['pm3_log'] = output.strip()[-12000:]
                            if protocol == 'ISO15693' and 'pm3-dump' in actions:
                                # Read-only addressed ISO15693, capped so the PM3
                                # scanner is not blocked by a huge requested range.
                                progress = progress_events(emit, protocol, 'proxmark3')
                                progress(0, None)
                                try:
                                    record.update(read_memory(
                                        pm3.PM3Reader(client, port), uid, args.blocks,
                                        args.verbose, cap=32, progress=progress))
                                except (FrameError, TimeoutError, ValueError) as exc:
                                    record['read_errors'].append(failure(exc))
                                    record['dump_status'] = 'failed'
                            else:
                                record['read_capability'] = 'discovery_only'
                            tag_event(args, emit, record)
                            previous_read = time.monotonic()
                        last[key] = (time.monotonic(), previous_read)
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
    if args.watch and args.backend == 'auto':
        return auto_watch(args, emit)
    while True:
        backend, client, port = backend_choice(args, emit)
        if backend is None:
            if not args.watch:
                return 2
            time.sleep(1)
            continue
        if backend == 'internal':
            internal_operation(args, emit)
            return 0
        try:
            if args.action != 'status':
                pm3_operation(args, emit, client, port)
            return 0
        except (OSError, subprocess.TimeoutExpired):
            if args.action == 'scan' and args.backend == 'auto':
                emit('pm3_status', 'Proxmark3 connection lost · using internal reader', state='unresponsive')
                internal_operation(args, emit)
                return 0
            if not args.watch:
                raise
            emit('pm3_status', 'Proxmark3 connection lost · waiting for USB', state='unresponsive')
            time.sleep(1)


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
