"""Local, privacy-conscious Tonie candidates derived from PT35 NFC archives.

A UID / manufacturer prefix is NOT proof that the object is a Tonie, nor is
it an audio ID or a TeddyCloud model. Never export RF dumps or authentication
material through these catalog functions.
"""
import json
import re
from pathlib import Path

from nfc_archive import atomic_write, is_known_tonie
from nfc_config import file_lock

FILENAME = 'possible_tonies.json'
UID = re.compile(r'E004[0-9A-F]{12}\Z')
AUDIO_ID = re.compile(r'[0-9]{1,12}\Z')
HASH = re.compile(r'[0-9a-fA-F]{40}\Z')
MODEL = re.compile(r'[0-9A-Za-z_-]{1,64}\Z')
METADATA_KEYS = ('title', 'series', 'episodes', 'tracks', 'release', 'language', 'category', 'pic')


def eligibility(record, root):
    """Return independent evidence. NXP manufacturer alone = candidate only."""
    if not isinstance(record, dict):
        return None
    uid = str(record.get('uid', '')).upper()
    if record.get('protocol') != 'ISO15693' or not UID.fullmatch(uid):
        return None
    if record.get('classification_verified') and record.get('classification') in (
            'ndef_link', 'ndef_text', 'business_card'):
        return None
    if record.get('content_preview') and record.get('classification') in (
            'ndef_link', 'ndef_text', 'business_card'):
        return None
    known = is_known_tonie(uid, root)
    return dict(uid=uid, protocol='ISO15693', manufacturer='NXP',
                status='known_tonie' if known else 'possible_tonie',
                evidence='local_known_uid_list' if known else 'nxp_manufacturer_prefix_only',
                verified=bool(known))


def catalog_path(root):
    return Path(root) / FILENAME


def _read(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    if not isinstance(data, list):
        raise ValueError('Possible Tonies catalog must be a JSON array')
    result = []
    for item in data:
        if not isinstance(item, dict) or not UID.fullmatch(str(item.get('uid', ''))):
            raise ValueError('Invalid candidate entry in catalog; refusing to overwrite it')
        result.append(item)
    return result


def _merge(items, record, root):
    evidence = eligibility(record, root)
    if evidence is None:
        # A later verified ordinary NDEF capture can disprove an earlier
        # vendor-prefix-only candidate. Do not keep exporting that false
        # positive. Preserve user-enriched entries but mark them excluded.
        uid = str(record.get('uid', '')).upper()
        excluded = (record.get('protocol') == 'ISO15693' and UID.fullmatch(uid) and
                    record.get('classification') in ('ndef_link', 'ndef_text', 'business_card') and
                    record.get('classification_verified') is True)
        if excluded:
            old = next((item for item in items if item.get('uid') == uid), None)
            if old is not None:
                if old.get('teddycloud'):
                    old.update(status='excluded_non_tonie',
                               evidence='verified_non_tonie_ndef', verified=False)
                else:
                    items.remove(old)
                return True
        return False
    previous = next((item for item in items if item['uid'] == evidence['uid']), None)
    if previous is None:
        item = dict(evidence)
        item['first_seen_utc'] = record.get('first_seen_utc') or record.get('last_seen_utc') or ''
        item['last_seen_utc'] = record.get('last_seen_utc') or ''
        # Deliberately do not store raw tag blocks, keys, NDEF or logs.
        items.append(item)
        return True
    updated = False
    for key, value in evidence.items():
        if previous.get(key) != value:
            previous[key] = value
            updated = True
    seen = record.get('last_seen_utc') or ''
    if seen and seen > previous.get('last_seen_utc', ''):
        previous['last_seen_utc'] = seen
        updated = True
    return updated


def _save(path, items):
    # Preserve any user-enriched TeddyCloud metadata on retained entries.
    payload = json.dumps(sorted(items, key=lambda entry: entry['uid']), indent=2,
                         ensure_ascii=False) + '\n'
    atomic_write(path, payload.encode('utf-8'))


def add_scan(root, record):
    """Add/upsert one scan; the existing archive is never modified."""
    root = Path(root)
    if eligibility(record, root) is None and not (
            isinstance(record, dict) and record.get('protocol') == 'ISO15693' and
            UID.fullmatch(str(record.get('uid', '')).upper()) and
            record.get('classification_verified') is True and
            record.get('classification') in ('ndef_link', 'ndef_text', 'business_card')):
        return False
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(root / '.possible_tonies.lock'):
        path = catalog_path(root)
        items = _read(path)
        changed = _merge(items, record, root)
        if changed:
            _save(path, items)
        return changed


def scan_archive(root):
    """Incrementally index all saved NFC archives, without deleting candidates."""
    root = Path(root)
    records = []
    invalid = 0
    for path in sorted(root.glob('*/record.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(record, dict):
                records.append(record)
            else:
                invalid += 1
        except (OSError, ValueError):
            invalid += 1
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(root / '.possible_tonies.lock'):
        path = catalog_path(root)
        items = _read(path)
        changed = sum(bool(_merge(items, record, root)) for record in records)
        if changed or not path.exists():
            _save(path, items)
        return {'scanned': len(records), 'changed': changed, 'candidates': len(items),
                'invalid': invalid, 'path': str(path)}


def shareable_catalog(root, destination):
    """Explicit sharing action: export only safe catalog evidence and UID.

    UIDs may still act as access tokens on simple tag-based systems. Warn
    the user before invoking this for public sharing.
    """
    root = Path(root)
    with file_lock(root / '.possible_tonies.lock'):
        items = _read(catalog_path(root))
    public = [{key: item[key] for key in (
        'uid', 'protocol', 'manufacturer', 'status', 'evidence', 'verified') if key in item}
        for item in items if item.get('status') in ('possible_tonie', 'known_tonie')]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(destination, (json.dumps(public, indent=2, ensure_ascii=False) + '\n').encode())
    return destination, len(public)


def teddy_custom_entries(root):
    """Only emit real, user-enriched TeddyCloud fields, never invent IDs/hashes.

    Expected optional per-entry field 'teddycloud' is a dict obtained from
    independent audio/TAF metadata, not from an NFC tag UID.
    """
    with file_lock(Path(root) / '.possible_tonies.lock'):
        items = _read(catalog_path(root))
    entries = []
    for item in items:
        if item.get('status') == 'excluded_non_tonie':
            continue
        meta = item.get('teddycloud')
        if not isinstance(meta, dict):
            continue
        model = str(meta.get('model', ''))
        ids = meta.get('audio_id')
        hashes = meta.get('hash')
        if not (MODEL.fullmatch(model) and isinstance(ids, list) and
                isinstance(hashes, list) and len(ids) == len(hashes) and ids and
                all(isinstance(value, str) and AUDIO_ID.fullmatch(value) for value in ids) and
                all(isinstance(value, str) and HASH.fullmatch(value) for value in hashes)):
            continue
        output = {'no': str(len(entries)), 'model': model, 'audio_id': ids, 'hash': hashes}
        for key in METADATA_KEYS:
            value = meta.get(key)
            if isinstance(value, str) or (key == 'tracks' and isinstance(value, list) and
                                          all(isinstance(part, str) for part in value)):
                output[key] = value
        entries.append(output)
    return entries


def export_teddy_custom(root, destination):
    entries = teddy_custom_entries(root)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(destination, (json.dumps(entries, ensure_ascii=False, indent=2) + '\n').encode())
    return destination, len(entries)
