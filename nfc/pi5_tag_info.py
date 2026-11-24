"""Safe, read-only NFC tag descriptions for the recovered PT35 GUI.

Interpret existing, CRC-verified polling metadata only. Do not infer a vendor,
payment-card application, or exact chip from an ISO14443-B PUPI/ATQB.
"""


def describe(record):
    protocol = record.get("protocol", "")
    discovery = record.get("discovery") or {}
    result = []
    if protocol == "NFC-B":
        result.append("Technology: ISO/IEC 14443-B (NFC-B)")
        atqb = discovery.get("atqb", "")
        try:
            data = bytes.fromhex(atqb)
        except (ValueError, TypeError):
            data = b""
        if len(data) == 12 and data[0] == 0x50:
            pupi = data[1:5].hex().upper()
            result.extend([
                "Identifier: PUPI " + pupi + " (may change between scans)",
                "ATQB application data: " + data[5:9].hex().upper(),
                "ATQB protocol info: " + data[9:12].hex().upper(),
                "Card family: ISO14443-B; exact chip/application not identified",
                "Memory: protocol discovery only; no generic memory-dump command",
            ])
        else:
            result.append("ATQB metadata unavailable or invalid")
    elif protocol == "NFC-A":
        result.append("Technology: ISO/IEC 14443-A (NFC-A)")
        if "atqa" in discovery:
            result.append("ATQA: " + str(discovery["atqa"]))
        if "sak" in discovery:
            try:
                sak = int(discovery["sak"])
            except (TypeError, ValueError):
                sak = None
            if sak is not None:
                result.append(f"SAK: {sak:02X}")
                if sak & 0x20:
                    result.append("ISO-DEP (ISO14443-4) support indicated by SAK")
                elif sak == 0:
                    result.append("Type 2-compatible anticollision profile (not a chip ID)")
        uid = record.get("uid", "")
        if len(uid) == 8 and uid.upper().startswith("08"):
            result.append("Identifier: possible random ID (RID); can vary between scans")
        if record.get("cc"):
            result.append("Type 2 capability container: " + str(record["cc"]))
    elif protocol == "NFC-F":
        result.append("Technology: NFC-F / FeliCa polling")
        if discovery.get("pmm"):
            result.append("PMm: " + str(discovery["pmm"]))
        if discovery.get("system_code"):
            result.append("System code: " + str(discovery["system_code"]))
        result.append("Chip model not determined by polling alone")
    elif protocol == "ISO15693":
        result.append("Technology: ISO/IEC 15693 (NFC-V)")
    return result
