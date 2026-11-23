"""Read-only generic NFC Forum Type 2 memory reader for recovered Pi4 scanner.

Accepts any selected NFC-A 7-byte UID/SAK=00 tag whose page-3 Capability
Container advertises NFC Forum Type 2 data memory. No writes/authentication.
The recovered scanner owns RF setup and passes its CRC-checked receive helper.
"""


def read_type2(chip, uid, details, *, progress, receive, crc_a,
               set_coverage, failure, frame_error):
    # ISO14443-4 bank cards and other non-Type-2 targets are discovery-only.
    if len(uid) != 14 or details.get("sak") != 0:
        return {"read_capability": "discovery_only"}

    capture = {
        "chip": "NFC Forum Type 2 (CC-identified)",
        "blocks": [],
        "read_errors": [],
        "read_capability": "type2_read_attempted",
        "verification": "CRC-A checked NFC-A READ responses",
        "memory_start": 4,
    }

    def read_four(start):
        response = receive(chip, bytes((0x30, start)), checksum=crc_a)
        if len(response) != 16:
            raise frame_error("size", "NFC Type 2 READ must return 16 data bytes")
        return response

    # Standard Type 2 tag READ page 0 returns pages 0 through 3.
    # Validate UID stored in manufacturer pages and the Capability Container.
    try:
        first = read_four(0)
    except (OSError, TimeoutError, ValueError, frame_error) as exc:
        capture["read_errors"].append({"index": 0, **failure(exc)})
        capture["dump_status"] = "failed"
        return capture

    if (first[:3] + first[4:8]).hex().upper() != uid:
        capture["read_errors"].append({
            "index": 0, "kind": "uid_mismatch",
            "message": "Tag header does not match the selected UID",
        })
        capture["dump_status"] = "failed"
        return capture

    cc = first[12:16]
    capture["cc"] = cc.hex().upper()
    # E1 = NFC Forum Type 2 CC; upper version nibble must be version 1.
    if cc[0] != 0xE1 or cc[1] >> 4 != 1 or cc[2] == 0:
        capture["read_capability"] = "type2_cc_missing_or_unsupported"
        capture["dump_status"] = "not_requested"
        return capture

    count = cc[2] * 2  # CC memory-size field: 8-byte units, two 4-byte pages.
    # Limit one pass; larger cards get a bounded partial capture.
    limit = min(count, 256)
    if limit < 4:
        capture["read_capability"] = "unsupported_small_type2_area"
        capture["dump_status"] = "not_requested"
        return capture
    capture["read_capability"] = "nfc_forum_type2_user_memory"
    geometry = {
        "start": 4, "blocks": count, "size": 4,
        "source": "NFC Forum Type 2 capability container (user area only)",
    }
    capture["geometry"] = geometry
    capture["requested_blocks"] = limit
    capture["cc_access"] = cc[3]
    if progress:
        progress(0, limit)

    end = 4 + limit
    seen = set()
    for page in range(4, end, 4):
        # On memories not divisible by 4, align the last READ backwards
        # so its four pages don't go beyond the declared user-memory area.
        first_page = max(4, min(page, end - 4))
        last_error = None
        for _ in range(2):
            try:
                chunk = read_four(first_page)
                last_error = None
                break
            except (OSError, TimeoutError, ValueError) as exc:
                last_error = exc
        if last_error is not None:
            capture["read_errors"].append({"index": first_page, **failure(last_error)})
            break
        for offset in range(4):
            index = first_page + offset
            if index >= end or index in seen:
                continue
            seen.add(index)
            data = chunk[offset * 4:(offset + 1) * 4]
            capture["blocks"].append({
                "index": index, "hex": data.hex().upper(), "size": 4,
            })
        if progress:
            progress(len(capture["blocks"]), limit)

    capture["blocks"].sort(key=lambda item: item["index"])
    # Count is the attempted range; known geometry is the CC-advertised area.
    set_coverage(capture, limit, geometry, start=4)
    return capture
