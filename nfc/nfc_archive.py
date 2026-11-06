"""Local PT35 archive. JSON is authoritative; binary exports are derived from it."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from nfc_config import file_lock

UID = re.compile(r'[0-9A-F]{2,64}', re.ASCII)
MEMORY_FIELDS = (
    'blocks', 'read_errors', 'dump_status', 'geometry', 'geometry_known',
    'requested_blocks', 'requested_range', 'requested_range_complete',
    'addressable_memory_complete', 'system_info', 'verification', 'memory_binary',
    'capture_backend', 'captured_utc', 'capture_format', 'memory_start',
)


def now():
    return datetime.now(timezone.utc).isoformat()


def record_path(root, uid, protocol='ISO15693'):
    uid = uid.upper()
    if not UID.fullmatch(uid) or len(uid) % 2:
        raise ValueError('Invalid tag identifier')
    if protocol != 'ISO15693':
        if not re.fullmatch(r'[A-Z0-9-]{1,24}', protocol):
            raise ValueError('Invalid protocol')
        uid = f'{protocol}-{uid}'
    return root / uid / 'record.json'


def atomic_write(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(temporary, path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


def record_bytes(record):
    return (json.dumps(record, indent=2, sort_keys=True) + '\n').encode()


def range_bytes(record):
    """Return a complete verified range, including a valid all-zero range."""
    requested = record.get('requested_range')
    if not requested or record.get('read_errors') or record.get('capture_format') != 2:
        return None
    start, count = requested['start'], requested['count']
    blocks = record.get('blocks', [])
    if not count or [b['index'] for b in blocks] != list(range(start, start + count)):
        return None
    chunks = [bytes.fromhex(b['hex']) for b in blocks]
    if len({len(chunk) for chunk in chunks}) != 1 or not chunks[0]:
        return None
    geometry = record.get('geometry')
    if geometry and len(chunks[0]) != geometry['size']:
        return None
    return b''.join(chunks)


def set_coverage(record, count, geometry, start=0):
    record.update(capture_format=2, geometry=geometry, geometry_known=geometry is not None,
                  requested_blocks=count, requested_range={'start': start, 'count': count})
    complete = range_bytes(record) is not None
    full = bool(complete and geometry and start == 0 and count == geometry['blocks'])
    record.update(requested_range_complete=complete, addressable_memory_complete=full,
                  dump_status='addressable_memory_complete' if full else
                  'requested_range_complete' if complete else
                  'partial' if record['blocks'] else 'failed')


def _quality(record):
    blocks = record.get('blocks') or []
    indices = frozenset(b['index'] for b in blocks)
    if record.get('capture_format') == 2:
        return bool(record.get('addressable_memory_complete')), bool(range_bytes(record) is not None), indices
    # Legacy geometry and coverage flags are untrusted. Still retain good legacy data.
    return False, bool(blocks and not record.get('read_errors') and
                       record.get('dump_status') == 'requested_range_complete'), indices


def _replace_capture(old, new):
    old_full, old_complete, old_indices = _quality(old)
    full, complete, indices = _quality(new)
    if old_indices and not indices:
        return False
    if old_full or old_complete:
        if not complete or not old_indices <= indices or (old_full and not full):
            return False
    # Retain complementary or smaller partial captures instead of silently losing coverage.
    return old_indices <= indices or full


def save_record(root, record):
    path = record_path(root, record['uid'], record.get('protocol', 'ISO15693'))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(path.parent / '.lock'):
        old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(old, dict):
            raise ValueError(f'Invalid archive record at {path}')
        merged = {**old, **{k: v for k, v in record.items() if v is not None}}
        merged['first_seen_utc'] = old.get('first_seen_utc') or record.get('last_seen_utc') or now()
        merged['last_seen_utc'] = max(filter(None, (old.get('last_seen_utc'),
                                                  record.get('last_seen_utc'), merged['first_seen_utc'])))
        if old.get('labels'):
            merged['labels'] = old['labels']
        if old.get('classification_verified') and not record.get('classification_verified'):
            for key in ('classification', 'classification_verified', 'tonie_status'):
                if key in old:
                    merged[key] = old[key]
        if old and not _replace_capture(old, record):
            for key in MEMORY_FIELDS:
                merged.pop(key, None)
                if key in old:
                    merged[key] = old[key]
            merged['capture_backend'] = old.get('capture_backend', old.get('backend'))
            merged['captured_utc'] = old.get('captured_utc', old.get('last_seen_utc'))
        elif record.get('capture_format') == 2:
            for key in MEMORY_FIELDS:
                if key not in record:
                    merged.pop(key, None)
            merged.update({k: record[k] for k in MEMORY_FIELDS if k in record})
            merged['capture_backend'] = record['backend']
            merged['captured_utc'] = record['last_seen_utc']
        binary = range_bytes(merged)
        if binary is not None:
            identity = hashlib.sha256(binary).hexdigest()
            bin_path = path.parent / f'capture-{identity}.bin'
            if not bin_path.exists():
                atomic_write(bin_path, binary)
            merged['memory_binary'] = bin_path.name
        atomic_write(path, record_bytes(merged))
        for item in path.parent.glob('capture-*.bin'):
            if re.fullmatch(r'capture-[0-9a-f]{64}\.bin', item.name) and item.name != merged.get('memory_binary'):
                item.unlink()
    return path


def is_known_tonie(uid, archive):
    try:
        lines = (archive / 'known_tonies.txt').read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return False
    return any(line.partition('#')[0].strip().upper() == uid for line in lines)


def migrate_archive(source, destination):
    """Copy missing records and sidecars. Originals and conflicts stay intact."""
    if source.resolve() == destination.resolve() or not source.is_dir():
        return 0
    copies = 0
    for source_file in sorted(source.rglob('*')):
        if (not source_file.is_file() or source_file.is_symlink() or
                any(part.startswith('.') for part in source_file.relative_to(source).parts)):
            continue
        target = destination / source_file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with file_lock(target.parent / '.lock'):
            if not target.exists():
                atomic_write(target, source_file.read_bytes())
                copies += 1
    return copies
