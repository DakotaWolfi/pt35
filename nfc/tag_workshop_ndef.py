"""Conservative NFC Forum Type 2 NDEF editor model.

Only creates standard NDEF text/URI messages and a Type-2 TLV. No commands
for UID pages, lock bits, passwords, authentication, or configuration.
"""
from urllib.parse import urlsplit

URI_PREFIXES = ("", "http://www.", "https://www.", "http://", "https://",
                "tel:", "mailto:")


def message(kind, value):
    if kind == "Text":
        payload = b"\x02en" + value.encode("utf-8")
        record_type = b"T"
    elif kind == "URL":
        if not value or not urlsplit(value).scheme:
            raise ValueError("A URL must include a scheme, e.g. https://example.org")
        prefix = max((p for p in URI_PREFIXES if p and value.startswith(p)),
                     key=len, default="")
        payload = bytes((URI_PREFIXES.index(prefix),)) + value[len(prefix):].encode("utf-8")
        record_type = b"U"
    elif kind == "Empty":
        return b""
    else:
        raise ValueError("Only Text, URL, and Empty are supported")
    if len(payload) > 0xFFFF:
        raise ValueError("NDEF record too large")
    short = len(payload) < 256
    return bytes((0xD1 if short else 0xC1, len(record_type))) + (
        bytes((len(payload),)) if short else len(payload).to_bytes(4, "big")
    ) + record_type + payload


def tlv(kind, value, capacity):
    if not 16 <= capacity <= 144:
        raise ValueError("Workshop write support is limited to Type 2 areas of 16-144 bytes")
    payload = message(kind, value)
    # Even an empty tag keeps an empty NDEF TLV, so other NFC tools can see it.
    length_field = bytes((len(payload),)) if len(payload) < 255 else (
        b"\xFF" + len(payload).to_bytes(2, "big")
    )
    data = b"\x03" + length_field + payload + b"\xFE"
    if len(data) > capacity:
        raise ValueError(f"Content uses {len(data)} bytes, tag supports {capacity}")
    return data.ljust(capacity, b"\x00")


def parse(area):
    """Identify a single, standard NDEF TLV; do not silently replace other TLVs."""
    if not isinstance(area, bytes):
        raise ValueError("Area must be bytes")
    pos = 0
    while pos < len(area) and area[pos] == 0:
        pos += 1
    if pos == len(area) or area[pos] == 0xFE:
        return ("Empty", "")
    if area[pos] != 3 or pos + 2 > len(area):
        raise ValueError("Unsupported TLV layout: refusing automatic rewrite")
    pos += 1
    size = area[pos]
    pos += 1
    if size == 255:
        if pos + 2 > len(area):
            raise ValueError("Invalid extended NDEF length")
        size = int.from_bytes(area[pos:pos+2], "big")
        pos += 2
    end = pos + size
    if end > len(area):
        raise ValueError("Incomplete NDEF payload")
    raw = area[pos:end]
    if not raw:
        return ("Empty", "")
    if len(raw) < 4 or raw[0] not in (0xD1, 0xC1) or raw[1] != 1:
        raise ValueError("Existing NDEF contains unsupported records; backup before editing")
    short = raw[0] == 0xD1
    width = 1 if short else 4
    if len(raw) < 2 + width + 1:
        raise ValueError("Incomplete NDEF header")
    n = int.from_bytes(raw[2:2+width], "big")
    tpos = 2 + width
    payload = raw[tpos+1:]
    if len(payload) != n:
        raise ValueError("NDEF length mismatch")
    typ = raw[tpos:tpos+1]
    if typ == b"T":
        if not payload:
            raise ValueError("Invalid text payload")
        lang_len = payload[0] & 63
        if payload[0] & 0x80:
            raise ValueError("UTF-16 text editing not yet supported")
        if lang_len + 1 > len(payload):
            raise ValueError("Invalid language-code length")
        return ("Text", payload[1+lang_len:].decode("utf-8", "strict"))
    if typ == b"U":
        if not payload or payload[0] >= len(URI_PREFIXES):
            raise ValueError("Unknown URI prefix")
        return ("URL", URI_PREFIXES[payload[0]] + payload[1:].decode("utf-8", "strict"))
    raise ValueError("Unsupported NDEF record type")


def plan(old_area, kind, value):
    if len(old_area) % 4:
        raise ValueError("Memory size must be divisible by 4")
    parse(old_area)  # Fail closed on unexpected existing formats.
    new_area = tlv(kind, value, len(old_area))
    return [(4 + i // 4, new_area[i:i+4]) for i in range(0, len(new_area), 4)
            if new_area[i:i+4] != old_area[i:i+4]]
