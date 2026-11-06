#!/usr/bin/env python3
"""PT35 NFC archive and dual-reader frontend.

Backends: Proxmark3/Iceman USB when genuinely available, otherwise existing
ST25R3916 on /dev/i2c-1. Internal driver currently implements ISO15693/NFC-V.
All automatic operations are read-only. Simulation is explicit via Iceman shell.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ARCHIVE = HERE / 'archive'
VERSION = '0.1.0'
UID_RE = re.compile(r'(?<![0-9a-fA-F])(?:E0[0-9a-fA-F]{14})(?![0-9a-fA-F])', re.I)
COLOR_RE = re.compile(r'\x1b\[[0-9;]*m')


def now():
    return datetime.now(timezone.utc).isoformat()


def classify(uid):
    uid = uid.upper()
    if uid.startswith('E004'):
        return 'NXP ISO15693', 'tonie_candidate'
    if uid.startswith('E002'):
        return 'STMicroelectronics ISO15693', 'other'
    return 'ISO15693', 'other'


def is_known_tonie(uid, archive):
    known_file = archive / 'known_tonies.txt'
    if not known_file.is_file():
        return False
    return uid.upper() in {line.strip().upper() for line in known_file.read_text().splitlines()
                           if line.strip() and not line.startswith('#')}


def record_path(root, uid):
    return root / uid.upper() / 'record.json'


def save_record(root, record):
    path = record_path(root, record['uid'])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        record['first_seen_utc'] = old.get('first_seen_utc', now())
        record['labels'] = old.get('labels', record.get('labels', []))
        if old.get('blocks') and not record.get('blocks'):
            record['blocks'] = old['blocks']
            record['read_errors'] = old.get('read_errors', [])
            record['dump_status'] = old.get('dump_status')
        if old.get('pm3') and not record.get('pm3'):
            record['pm3'] = old['pm3']
    else:
        record['first_seen_utc'] = now()
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return path


def new_record(uid, backend, dsfid=None):
    manufacturer, kind = classify(uid)
    return dict(format='PT35-NFC-archive-v1', uid=uid.upper(), protocol='ISO15693',
                manufacturer=manufacturer, classification=kind,
                classification_verified=False, backend=backend,
                dsfid=f'{dsfid:02X}' if dsfid is not None else None,
                last_seen_utc=now(), blocks=[], read_errors=[], dump_status='not_requested',
                notes='Ordinary read-only tag data. No Tonie authentication keys are recovered.')


def usb_ports():
    # Never select arbitrary USB serial adapters; check sysfs ancestry for PM3 descriptors.
    found = []
    for base in ('/dev/serial/by-id',):
        folder = Path(base)
        if folder.is_dir():
            for item in folder.iterdir():
                if re.search(r'proxmark|pm3|iceman', item.name, re.I):
                    found.append(str(item.resolve()))
    for item in list(Path('/dev').glob('ttyACM*')) + list(Path('/dev').glob('ttyUSB*')):
        if str(item) in found:
            continue
        sysdev = Path('/sys/class/tty') / item.name / 'device'
        desc = []
        try:
            p = sysdev.resolve()
            for parent in [p, *p.parents]:
                for f in ('product', 'manufacturer', 'interface'):
                    fp = parent / f
                    if fp.is_file():
                        desc.append(fp.read_text(errors='replace').strip())
        except OSError:
            pass
        if re.search(r'proxmark|pm3', ' '.join(desc), re.I):
            found.append(str(item))
    return sorted(set(found))


def pm3_client():
    paths = [os.environ.get('PT35_PM3_CLIENT', ''),
             str(Path.home() / 'proxmark3' / 'client' / 'proxmark3'),
             str(Path.home() / 'proxmark3' / 'pm3'),
             '/usr/local/bin/proxmark3', shutil.which('proxmark3') or '']
    for v in paths:
        if v and Path(v).is_file() and os.access(v, os.X_OK):
            return v
    return None


def run_pm3(client, port, command, timeout=35, cwd=None):
    # -c is the Proxmark3 client command-string flag; no shell interpolation.
    proc = subprocess.run([client, '-p', port, '-c', command], cwd=cwd,
                          text=True, capture_output=True, timeout=timeout,
                          env={**os.environ, 'NO_COLOR': '1'})
    return proc.returncode, COLOR_RE.sub('', (proc.stdout or '') + '\n' + (proc.stderr or ''))


def pm3_online(client, port):
    try:
        code, out = run_pm3(client, port, 'hw version', timeout=12)
        return code == 0 and bool(re.search(r'proxmark|firmware|bootrom|fpga', out, re.I))
    except (OSError, subprocess.TimeoutExpired):
        return False


def choose_backend(mode, port=None):
    if mode == 'internal':
        return 'internal', None, None
    client = pm3_client()
    candidates = [port] if port else usb_ports()
    if client:
        for p in candidates:
            if p and pm3_online(client, p):
                return 'proxmark3', client, p
    if mode == 'proxmark3':
        raise RuntimeError('No reachable Proxmark3/Iceman client/device. Run status or choose --backend internal.')
    return 'internal', None, None


def pm3_inventory(client, port):
    code, output = run_pm3(client, port, 'hf 15 reader', timeout=20)
    # Different Iceman versions print UID differently; accept explicitly labeled UID only.
    uid = None
    for line in output.splitlines():
        if re.search(r'\bUID\b', line, re.I):
            match = UID_RE.search(line.replace(' ', ''))
            if match:
                uid = match.group(0).upper()
                break
            # Common spaced hex UID format on a 'UID:' line.
            if ':' in line:
                tail = line.split(':', 1)[1]
                chunks = re.findall(r'\b[0-9a-fA-F]{2}\b', tail)
                if len(chunks) >= 8:
                    candidate = ''.join(chunks[:8]).upper()
                    if candidate.startswith('E0'):
                        uid = candidate
                        break
    return uid, output, code


def pm3_dump(client, port, uid, root):
    dest = record_path(root, uid).parent / 'proxmark3'
    dest.mkdir(parents=True, exist_ok=True)
    try:
        code, output = run_pm3(client, port, 'hf 15 dump', timeout=100, cwd=dest)
    except subprocess.TimeoutExpired:
        code, output = 124, 'Timeout while executing hf 15 dump'
    (dest / 'iceman_dump.log').write_text(output, encoding='utf-8')
    return dict(command='hf 15 dump', exit_status=code, log='proxmark3/iceman_dump.log',
                files=[str(x.relative_to(record_path(root, uid).parent)) for x in dest.iterdir() if x.is_file()])


def internal_driver():
    try:
        from smbus2 import SMBus
        from nfcv_dump import Reader
    except ImportError as exc:
        raise RuntimeError(f'Install smbus2 and place nfcv_scan.py + nfcv_dump.py beside pt35_nfc.py: {exc}') from exc
    return SMBus, Reader


def get_v_memory_size(reader, uid, verbose=False):
    # ISO15693 GET SYSTEM INFORMATION (addressed, high data rate).
    # Response: flags, infoflags, UID[8], optionally DSFID/AFI/memory geometry/IC ref.
    try:
        reply = reader.exchange(bytes([0x22, 0x2B]) + bytes.fromhex(uid)[::-1],
                                timeout=.5, verbose=verbose)
        if not reply or (reply[0] & 1) or len(reply) < 10:
            return None
        mask, index = reply[1], 10
        if mask & 0x01: index += 1  # DSFID
        if mask & 0x02: index += 1  # AFI
        if mask & 0x04:
            if len(reply) < index + 2:
                return None
            return dict(blocks=reply[index] + 1,
                        size=(reply[index + 1] & 0x1f) + 1)
    except (OSError, TimeoutError, ValueError) as exc:
        if verbose:
            print(f'  System info not available: {exc}')
    return None


def internal_dump(reader, uid, blocks, verbose):
    got, errors = [], []
    for i in range(blocks):
        try:
            block = reader.read_single(uid, i, verbose=verbose)
            if not block:
                raise ValueError('empty response')
            got.append(dict(index=i, hex=block.hex().upper(), size=len(block)))
            print(f'  Block {i:03}: {block.hex(" ").upper()}', flush=True)
        except (OSError, TimeoutError, ValueError) as exc:
            print(f'  Block {i:03}: {exc}', flush=True)
            errors.append(dict(index=i, error=str(exc)))
            break
    return got, errors


def save_binary(root, record):
    blocks = record.get('blocks', [])
    if not blocks or record.get('read_errors'):
        return
    if len({len(bytes.fromhex(block['hex'])) for block in blocks}) != 1:
        return
    file = record_path(root, record['uid']).parent / 'memory.bin'
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b''.join(bytes.fromhex(x['hex']) for x in blocks))
    record['memory_binary'] = 'memory.bin'


def handle_tag(root, uid, backend, dsfid, save, auto_tonie, blocks, verbose, reader=None,
               pm3_client_path=None, pm3_port=None):
    candidate = uid.startswith('E004')
    known = is_known_tonie(uid, root)
    manufacturer, tagclass = classify(uid)
    print(f'FOUND {uid}  ({manufacturer})  via {backend}', flush=True)
    should_save = save or (auto_tonie and (known or candidate))
    if not should_save:
        print('  Not archived. Use --save or --auto-tonie to store it.', flush=True)
        return False
    existing = record_path(root, uid)
    if auto_tonie and not save and existing.is_file():
        try:
            old = json.loads(existing.read_text(encoding='utf-8'))
            if old.get('dump_status') in ('requested_range_complete', 'see_pm3_log'):
                print('  Already archived; skipping repeated dump.', flush=True)
                return False
        except (OSError, ValueError):
            pass
    rec = new_record(uid, backend, dsfid)
    rec['tonie_status'] = 'known_tonie' if known else ('possible_tonie' if candidate else 'not_identified_as_tonie')
    if known:
        rec['classification_verified'] = True
    if backend == 'internal':
        geometry = get_v_memory_size(reader, uid, verbose)
        rec['geometry'] = geometry
        count = (geometry['blocks'] if geometry else 8) if blocks == 0 else blocks
        print(f'  Reading {count} block(s)' + (f" of {geometry['blocks']} x {geometry['size']} bytes" if geometry else ' (geometry unavailable)'), flush=True)
        rec['requested_blocks'] = count
        rec['blocks'], rec['read_errors'] = internal_dump(reader, uid, count, verbose)
        rec['dump_status'] = ('requested_range_complete' if len(rec['blocks']) == count
                              else 'partial' if rec['blocks'] else 'failed')
        save_binary(root, rec)
    else:
        rec['pm3'] = pm3_dump(pm3_client_path, pm3_port, uid, root)
        rec['dump_status'] = 'see_pm3_log'
    loc = save_record(root, rec)
    print(f'  Archived: {loc}', flush=True)
    return True


def internal_scan(args):
    SMBus, Reader = internal_driver()
    last, last_time = None, 0.0
    with SMBus(args.bus) as bus:
        reader = Reader(bus)
        try:
            reader.initialize(verbose=args.verbose)
            print('Internal NFC-V reader. Present a tag; Ctrl+C to stop.', flush=True)
            attempts = 0
            while args.watch or attempts < args.tries:
                attempts += 1
                result = reader.inventory(verbose=args.verbose)
                if result:
                    uid, payload = result
                    if uid.startswith('E002') and not args.include_st:
                        if args.verbose:
                            print(f'  Ignored ST tag {uid}; use --include-st to include it.')
                        time.sleep(args.delay)
                        continue
                    if uid != last or time.monotonic() - last_time > args.repeat_after:
                        last, last_time = uid, time.monotonic()
                        handle_tag(args.archive, uid, 'internal', payload[1], args.save,
                                   args.auto_tonie, args.blocks, args.verbose, reader=reader)
                elif args.verbose:
                    print('  No tag')
                time.sleep(args.delay)
        except KeyboardInterrupt:
            print('\nStopped.')
        finally:
            try: reader.shutdown()
            except OSError: pass


def pm3_scan(args, client, port):
    print(f'Proxmark3/Iceman active: {port} ({client})', flush=True)
    attempts = 0
    last, last_time = None, 0.0
    while args.watch or attempts < args.tries:
        attempts += 1
        try:
            uid, output, code = pm3_inventory(client, port)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f'Proxmark3 connection failed: {exc}', flush=True)
            if args.backend == 'auto':
                print('Falling back to internal NFC-V reader...', flush=True)
                return internal_scan(args)
            raise
        if uid and (uid != last or time.monotonic() - last_time > args.repeat_after):
            last, last_time = uid, time.monotonic()
            handle_tag(args.archive, uid, 'proxmark3', None, args.save,
                       args.auto_tonie, args.blocks, args.verbose,
                       pm3_client_path=client, pm3_port=port)
        elif args.verbose:
            print(output.strip()[-1500:] or '(no output)')
        if not args.watch and attempts >= args.tries:
            break
        time.sleep(args.delay)


def list_archive(root):
    if not root.exists():
        print('No archive yet.')
        return
    for p in sorted(root.glob('*/record.json')):
        try:
            r = json.loads(p.read_text(encoding='utf-8'))
            print(f"{r['uid']} | {r.get('tonie_status','unknown'):22} | {r.get('dump_status','?'):24} | {r.get('backend','?')}")
        except (ValueError, KeyError):
            print(f'Invalid record: {p}')


def main():
    p = argparse.ArgumentParser(description='PT35 NFC dual-backend reader/archive')
    p.add_argument('action', choices=['status', 'scan', 'watch', 'list', 'show', 'identify', 'pm3-shell'], nargs='?', default='scan')
    p.add_argument('uid', nargs='?', help='UID for show action')
    p.add_argument('--backend', choices=['auto', 'internal', 'proxmark3'], default='auto')
    p.add_argument('--port', help='Proxmark3 serial device, e.g. /dev/ttyACM0')
    p.add_argument('--bus', type=int, default=1)
    p.add_argument('--archive', type=Path, default=DEFAULT_ARCHIVE)
    p.add_argument('--save', action='store_true', help='save every scanned tag')
    p.add_argument('--auto-tonie', action='store_true', help='archive NXP NFC-V Tonie candidates')
    p.add_argument('--include-st', action='store_true', help='also detect internal ST25DV tags')
    p.add_argument('--blocks', type=int, default=0, help='ISO15693 block count; 0=auto from system info, fallback 8')
    p.add_argument('--tries', type=int, default=40)
    p.add_argument('--delay', type=float, default=.25)
    p.add_argument('--repeat-after', type=float, default=30)
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()
    args.watch = args.action == 'watch'
    args.archive = args.archive.expanduser().resolve()
    if not 0 <= args.blocks <= 256:
        p.error('--blocks must be 0..256')
    if args.action == 'list':
        list_archive(args.archive)
        return
    if args.action == 'show':
        if not args.uid:
            p.error('show requires UID')
        file = record_path(args.archive, args.uid)
        if not file.exists():
            p.error(f'Not archived: {args.uid}')
        print(file.read_text(encoding='utf-8'))
        return
    backend, client, port = choose_backend(args.backend, args.port)
    if args.action == 'status':
        print(f'PT35 NFC v{VERSION}')
        print(f'Selected backend: {backend}')
        print(f'Iceman client: {client or "not found"}')
        print(f'Proxmark3 USB ports: {", ".join(usb_ports()) or "none detected"}')
        print(f'Archive: {args.archive}')
        print('Internal implemented protocol: ISO15693/NFC-V (UID + readable blocks)')
        print('Internal NFC-A/B/F and card emulation: not implemented in this build')
        return
    if args.action == 'identify':
        if backend != 'proxmark3':
            print('Generic HF/LF identification requires Proxmark3. Internal backend supports NFC-V only.')
            return
        for command in ('hf search', 'lf search'):
            try:
                code, output = run_pm3(client, port, command, timeout=35)
                print(f'===== {command} (exit {code}) =====\n{output}')
            except subprocess.TimeoutExpired:
                print(f'{command}: timeout')
        return
    if args.action == 'pm3-shell':
        if backend != 'proxmark3':
            p.error('PM3 not available. Plug it in or specify --port.')
        print('Opening Iceman interactive console; use hf 15 help / hf 15 sim etc.')
        os.execv(client, [client, '-p', port])
    try:
        if backend == 'proxmark3':
            pm3_scan(args, client, port)
        else:
            internal_scan(args)
    except KeyboardInterrupt:
        print('\nStopped.')
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == '__main__':
    main()
