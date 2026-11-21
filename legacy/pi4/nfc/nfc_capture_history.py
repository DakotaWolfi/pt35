"""Immutable local NFC scan snapshots and conservative rescan comparison.

A snapshot is evidence from one read attempt, not a claim that the tag's
memory was fully validated. Identical observations share a snapshot file.
"""
import hashlib
import json

from nfc_archive import atomic_write, record_bytes, range_bytes

CAPTURE_KEYS = ('uid', 'protocol', 'backend', 'last_seen_utc', 'classification',
                'classification_verified', 'chip', 'manufacturer', 'blocks',
                'read_errors', 'dump_status', 'requested_range', 'geometry',
                'geometry_known', 'capture_format', 'requested_blocks',
                'requested_range_complete', 'addressable_memory_complete',
                'system_info', 'verification', 'memory_start', 'cc', 'dsfid',
                'read_capability', 'discovery', 'tonie_status', 'content_preview')


def evidence(record):
    """Keep only ordinary serializable capture fields, never PM3 console logs."""
    return {key: record[key] for key in CAPTURE_KEYS if key in record}


def comparable_blocks(record):
    if record.get('capture_format') != 2:
        return {}
    result = {}
    for block in record.get('blocks') or []:
        try:
            index = block['index']
            value = bytes.fromhex(block['hex'])
            if not isinstance(index, int) or not value:
                continue
            result[index] = value
        except (TypeError, ValueError, KeyError):
            continue
    return result


def compare(previous, current):
    """Conservative state for user feedback. Absence of bytes != disagreement."""
    if not previous:
        return 'new'
    before, after = comparable_blocks(previous), comparable_blocks(current)
    shared = before.keys() & after.keys()
    different = any(before[index] != after[index] for index in shared)
    complete_before = range_bytes(previous) is not None
    complete_after = range_bytes(current) is not None
    if different:
        return 'changed_verified' if complete_before and complete_after else 'different_partial'
    if before and after and after.keys() > before.keys():
        return 'improved'
    if before and after and before.keys() == after.keys() and all(
            before[index] == after[index] for index in before):
        return 'same'
    if after and not before:
        return 'improved'
    if not before and not after:
        return 'seen_again'
    return 'incomplete'


def snapshot(folder, record):
    """Create a unique immutable capture file; reuse exact duplicates.

    Storage stays within a single tag's private archive directory. We omit
    unbounded PM3 log output and do not publish copies to GitHub.
    """
    capture = evidence(record)
    # Identity excludes observation time so identical rescans do not multiply files.
    identity = {key: value for key, value in capture.items() if key != 'last_seen_utc'}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    directory = folder / 'captures'
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / (digest + '.json')
    if not target.exists():
        atomic_write(target, record_bytes(capture))
    return digest, capture


def summary(digest, capture, comparison):
    return {'id': digest, 'at': capture.get('last_seen_utc'), 'backend': capture.get('backend'),
            'status': capture.get('dump_status', 'not_requested'), 'comparison': comparison,
            'blocks': len(capture.get('blocks') or []),
            'classification': capture.get('classification', 'unknown')}
