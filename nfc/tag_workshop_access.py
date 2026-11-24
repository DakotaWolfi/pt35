"""Read-only access map for NXP NTAG213/215/216 (Type 2).

Unverified/unknown chip configuration is reported as UNKNOWN, never writable.
No lock bits, password, AUTH0, ACCESS or configuration are modified here.
"""
MODELS = {
    144: ("NTAG213", 40, 41, 42, 45),
    496: ("NTAG215", 130, 131, 132, 135),
    872: ("NTAG216", 226, 227, 228, 231),
}
# GET_VERSION bytes 0..5 and protocol type, as in recovered nfc_poll.py
PREFIX = bytes.fromhex("000404020100")
SIZE_CODE = {144: 0x0F, 496: 0x11, 872: 0x13}


def model_for(snapshot):
    capacity = snapshot.get("capacity")
    version = snapshot.get("version")
    if capacity not in MODELS or not isinstance(version, bytes):
        return None
    if (len(version) != 8 or version[:6] != PREFIX or
            version[6] != SIZE_CODE[capacity] or version[7] != 3):
        return None
    return MODELS[capacity][0]


def _lock_status(page, static, dynamic, model):
    if not isinstance(static, bytes) or len(static) != 2:
        return "Unknown"
    if page <= 15:
        # Static lock bits L3..L7 at first byte bits 3..7;
        # L8..L15 at second byte bits 0..7. The other 3 first-byte
        # bits are block-lock bits and don't individually lock user pages.
        bit = bool(static[0] & (1 << page)) if page <= 7 else (
            bool(static[1] & (1 << (page - 8))))
        return "Locked" if bit else "Writable*"
    if not isinstance(dynamic, bytes) or len(dynamic) != 3:
        return "Unknown"
    if model == "NTAG215":
        # NXP NTAG215 dynamic lock byte 0: 16..95 in 16-page
        # groups, 124..129 in smaller groups. Byte 2 contains
        # block-lock bits, not page lock bits.
        groups = [(16, 31), (32, 47), (48, 63), (64, 79),
                  (80, 95), (124, 125), (126, 127),
                  (128, 129)]
        for index, (first, last) in enumerate(groups):
            if first <= page <= last:
                return "Locked" if dynamic[0] & (1 << index) else "Writable*"
        # 96..123 require additional lock block interpretation. Avoid
        # reporting writable when any dynamic lock bit is set.
        return "Writable*" if dynamic == bytes((0, 0, 0)) else "Locked / check"
    # For other chips, do not guess individual dynamic bit maps.
    return "Writable*" if dynamic == bytes((0, 0, 0)) else "Locked / check"


def access_rows(snapshot):
    capacity = snapshot["capacity"]
    count = capacity // 4
    model = model_for(snapshot)
    static = snapshot.get("static_lock_bytes")
    dynamic = snapshot.get("dynamic_lock_bytes")
    cfg = snapshot.get("config_pages") or {}
    auth0 = cfg.get("auth0")
    access = cfg.get("access")
    auth_protects_read = bool(access & 0x80) if isinstance(access, int) else None
    rows = []
    for page in range(0, 4 + count):
        kind = ("Manufacturer / UID" if page <= 2 else
                "Capability Container" if page == 3 else
                "NDEF / user memory")
        if page <= 2:
            permission = "System"
        elif page == 3:
            permission = "Configuration"
        elif model is None:
            permission = "Unknown chip"
        else:
            permission = _lock_status(page, static, dynamic, model)
            if isinstance(auth0, int) and auth0 != 255 and page >= auth0:
                permission = ("Password read + write" if auth_protects_read
                              else "Password write")
            elif auth0 is None:
                permission = "Protection unknown" if permission == "Writable*" else permission
        offset = (page-4)*4
        if page < 4:
            header = snapshot.get("header")
            value = header[page*4:page*4+4].hex().upper() if isinstance(header, bytes) and len(header) == 16 else "Not read"
        else:
            value = snapshot["data"][offset:offset+4].hex().upper()
        rows.append((page, f"{page:03d} / {page:02X}", kind, value, permission))
    if model and capacity in MODELS:
        name, dyn, cfg1, cfg2, last = MODELS[capacity]
        rows.extend([
            (dyn, f"{dyn:03d} / {dyn:02X}", "Dynamic lock bytes", 
             dynamic.hex().upper() if isinstance(dynamic, bytes) else "Not read", "System"),
            (cfg1, f"{cfg1:03d} / {cfg1:02X}", "Configuration: AUTH0",
             f"{auth0:02X}" if isinstance(auth0, int) else "Not read", "System"),
            (cfg2, f"{cfg2:03d} / {cfg2:02X}", "Configuration: ACCESS",
             f"{access:02X}" if isinstance(access, int) else "Not read", "System"),
        ])
    return rows


def summarize(snapshot):
    model = model_for(snapshot)
    static = snapshot.get("static_lock_bytes")
    dynamic = snapshot.get("dynamic_lock_bytes")
    config = snapshot.get("config_pages") or {}
    return [
        f"Chip: {model or 'Unverified Type 2'}",
        f"UID: {snapshot.get('uid', '?')}  ·  NDEF user area: {snapshot['capacity']} bytes",
        f"Static locks: {static.hex().upper() if isinstance(static, bytes) else 'Unknown'}",
        f"Dynamic locks: {dynamic.hex().upper() if isinstance(dynamic, bytes) else 'Unknown'}",
        f"AUTH0: {config['auth0']:02X}" if isinstance(config.get("auth0"), int)
            else "AUTH0: Unknown",
        f"ACCESS: {config['access']:02X}" if isinstance(config.get("access"), int)
            else "ACCESS: Unknown",
        "Writable* = lock bits appear clear; this does NOT guarantee physical write access",
        "No data, password, or lock configuration was written.",
    ]
