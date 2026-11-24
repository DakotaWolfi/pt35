"""Offline PT35 Tag Workshop presets and verified archive NDEF imports.

Presets are editable content only (no UID, passwords, or RF commands).
Archive files are read-only; unknown/incomplete captures are not presented as
decoded data. Importing never changes the currently selected destination UID.
"""
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from tag_workshop_ndef import parse

PRESETS = Path.home() / "pt35-nfc" / "workshop-presets"
ARCHIVE = Path.home() / "pt35-nfc" / "archive"
ALLOWED = ("Text", "URL", "Empty")
NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _validate(kind, content):
    if kind not in ALLOWED or not isinstance(content, str):
        raise ValueError("Only editable Text, URL or Empty presets are supported")
    if len(content.encode("utf-8")) > 8192:
        raise ValueError("Preset content exceeds 8192 bytes")
    return kind, content


def save_preset(name, kind, content, root=None):
    kind, content = _validate(kind, content)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Enter a preset name")
    slug = NAME.sub("_", name.strip()).strip("._")[:64]
    if not slug:
        raise ValueError("Preset name must contain letters or numbers")
    folder = Path(root) if root is not None else PRESETS
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / (slug + ".json")
    if path.exists():
        raise FileExistsError(f"Preset already exists: {slug}. Choose another name.")
    payload = json.dumps({
        "format": "pt35-workshop-preset-v1",
        "name": name.strip()[:100],
        "kind": kind,
        "content": content,
        "created_utc": datetime.now(timezone.utc).isoformat()
    }, indent=2, ensure_ascii=False).encode("utf-8")
    # Creation is exclusive; never overwrite a stored preset by accident.
    with path.open("xb") as fh:
        os.chmod(path, 0o600)
        fh.write(payload)
    return path


def list_presets(root=None):
    folder = Path(root) if root is not None else PRESETS
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.glob("*.json") if p.is_file()), key=lambda p: p.name.lower())


def load_preset(path, root=None):
    folder = (Path(root) if root is not None else PRESETS).resolve()
    p = Path(path).resolve()
    if p.parent != folder or p.suffix != ".json":
        raise ValueError("Preset must be selected from the Workshop library")
    if p.stat().st_size > 20000:
        raise ValueError("Preset file is too large")
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("format") != "pt35-workshop-preset-v1":
        raise ValueError("Unsupported preset format")
    kind, content = _validate(obj.get("kind"), obj.get("content"))
    return kind, content


def list_archive(root=None):
    folder = Path(root) if root is not None else ARCHIVE
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*/record.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def archive_entry(path):
    """Return browseable title even for discovery-only captures."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        protocol, uid = obj.get("protocol", "?"), obj.get("uid", "?")
        status = obj.get("dump_status", "unknown")
        return f"{protocol}  {uid}  · {status}"
    except (OSError, ValueError, AttributeError):
        return "(unreadable archive record)"


def _verified_range(obj):
    requested = obj.get("requested_range") or {}
    if obj.get("capture_format") != 2 or obj.get("read_errors") or not obj.get("requested_range_complete"):
        raise ValueError("No verified complete memory range in this capture")
    start, count = requested.get("start"), requested.get("count")
    blocks = obj.get("blocks") or []
    if not isinstance(start, int) or not isinstance(count, int) or count <= 0 or count > 2048:
        raise ValueError("Invalid archive memory range")
    if not isinstance(blocks, list) or len(blocks) != count:
        raise ValueError("Archive contains missing memory blocks")
    if [b.get("index") for b in blocks] != list(range(start, start + count)):
        raise ValueError("Archived blocks are not contiguous")
    data = b"".join(bytes.fromhex(b["hex"]) for b in blocks)
    geometry = obj.get("geometry") or {}
    if geometry and len(data) != count * geometry.get("size", 0):
        raise ValueError("Archive memory geometry does not match")
    return data, start


def load_archive_ndef(path, root=None):
    """Import verified NDEF content, never UID/lock data or memory dumps."""
    folder = (Path(root) if root is not None else ARCHIVE).resolve()
    p = Path(path).resolve()
    if p.parent.parent != folder or p.name != "record.json":
        raise ValueError("Archive record must be selected from the NFC archive")
    if p.stat().st_size > 250000:
        raise ValueError("Archive record too large")
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Invalid archive record")
    protocol = obj.get("protocol")
    area, start = _verified_range(obj)
    if protocol == "NFC-A":
        cc = bytes.fromhex(obj.get("cc") or "")
        if start != 4 or len(cc) != 4 or cc[0] != 0xE1:
            raise ValueError("NFC-A record lacks a verified Type 2 user area")
        if cc[2] * 8 > len(area):
            raise ValueError("NFC-A capture doesn't cover full CC user area")
        return parse(area[:cc[2] * 8])
    if protocol == "ISO15693":
        if start != 0 or len(area) < 4:
            raise ValueError("NFC-V capture lacks NDEF header")
        if area[0] == 0xE1 and area[2] and area[1] >> 6 == 1:
            offset, count = 4, area[2] * 8
        elif len(area) >= 8 and area[0] == 0xE2 and area[2] == 0 and area[1] >> 6 == 1:
            offset, count = 8, int.from_bytes(area[6:8], "big") * 8
        else:
            raise ValueError("No recognized NFC-V NDEF header")
        if offset + count > len(area):
            raise ValueError("Archived NFC-V NDEF area incomplete")
        return parse(area[offset:offset+count])
    raise ValueError(f"{protocol} is discovery-only or has no supported editable NDEF memory")


def load_archive_raw(path, root=None):
    """Return a verified Type 2 *user-area* image, never manufacturer pages.

    Other protocols cannot be byte-for-byte mapped to Type 2 page addresses.
    """
    folder = (Path(root) if root is not None else ARCHIVE).resolve()
    p = Path(path).resolve()
    if p.parent.parent != folder or p.name != "record.json":
        raise ValueError("Select a record inside the NFC archive")
    if p.stat().st_size > 250000:
        raise ValueError("Archive record is too large")
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("protocol") != "NFC-A":
        raise ValueError("Raw copy currently supports only verified NFC-A Type 2 user memory")
    from tag_workshop_raw import checked_image
    data, start = _verified_range(obj)
    cc = bytes.fromhex(obj.get("cc") or "")
    capacity = cc[2] * 8 if len(cc) == 4 and cc[0] == 0xE1 and cc[1] >> 4 == 1 else None
    if start != 4 or capacity is None or len(data) != capacity:
        raise ValueError("Archive does not contain the full verified Type 2 user area")
    checked_image(data, capacity)
    return {"uid": str(obj.get("uid", "")), "capacity": capacity,
            "data": data, "cc": cc.hex().upper(), "source": "archive"}
