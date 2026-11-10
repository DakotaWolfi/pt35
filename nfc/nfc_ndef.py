"""Conservative NDEF preview from a verified contiguous tag capture."""

URI_PREFIXES = ('', 'http://www.', 'https://www.', 'http://', 'https://', 'tel:', 'mailto:')


def ndef_area(record, data):
    if record['protocol'] == 'NFC-A':
        cc = bytes.fromhex(record.get('cc', ''))
        if len(cc) == 4 and cc[0] == 0xe1 and cc[1] >> 4 == 1 and not cc[3] & 0xf0:
            return data[:cc[2] * 8]
    if record['protocol'] == 'ISO15693' and len(data) >= 4:
        if data[0] == 0xe1 and data[1] >> 6 == 1 and not data[1] & 0x0c and data[2]:
            return data[4:4 + data[2] * 8]
        if (len(data) >= 8 and data[0] == 0xe2 and data[1] >> 6 == 1 and
                not data[1] & 0x0c and data[2] == 0):
            return data[8:8 + int.from_bytes(data[6:8], 'big') * 8]
    return b''


def extract_message(area):
    pos = 0
    while pos < len(area):
        kind = area[pos]
        pos += 1
        if kind == 0:
            continue
        if kind == 0xfe or pos == len(area):
            return None
        length = area[pos]
        pos += 1
        if length == 0xff:
            if pos + 2 > len(area):
                return None
            length = int.from_bytes(area[pos:pos + 2], 'big')
            pos += 2
        end = pos + length
        if end > len(area):
            return None
        if kind == 3:
            return area[pos:end]
        pos = end
    return None


def decode_vcard(payload):
    """Small, read-only vCard preview. Do not execute URLs or import contacts."""
    text = payload.decode('utf-8-sig', errors='replace')
    # vCard folding uses one leading whitespace on continuation lines.
    lines = []
    for line in text.replace('\r\n', '\n').split('\n'):
        if line.startswith((' ', '\t')) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    output = []
    names = {'FN': 'Name', 'N': 'Name components', 'ORG': 'Organization',
             'TITLE': 'Title', 'TEL': 'Phone', 'EMAIL': 'Email',
             'URL': 'Website', 'ADR': 'Address', 'NOTE': 'Note'}
    for line in lines:
        field, sep, value = line.partition(':')
        key = field.split(';', 1)[0].upper()
        if not sep or key not in names:
            continue
        value = value.replace('\\n', ' · ').replace('\\N', ' · ').replace('\\,', ',')
        value = value.replace('\\;', ';').replace('\\\\', '\\')
        # Limit very large cards and avoid rendering embedded controls.
        value = ''.join(char if char.isprintable() else ' ' for char in value)[:240].strip()
        if value:
            output.append(f'{names[key]}: {value}')
        if len(output) == 16:
            break
    return output


def decode_message(message):
    pos = 0
    result = []
    while pos + 2 <= len(message):
        flags, type_len = message[pos:pos + 2]
        if bool(flags & 0x80) != (pos == 0) or flags & 0x20:
            return []
        pos += 2
        width = 1 if flags & 0x10 else 4
        header_end = pos + width + bool(flags & 0x08)
        if header_end > len(message):
            return []
        length = int.from_bytes(message[pos:pos + width], 'big')
        id_len = message[header_end - 1] if flags & 0x08 else 0
        content = header_end + type_len + id_len
        end = content + length
        if end > len(message):
            return []
        tag_type = message[header_end:header_end + type_len]
        payload = message[content:end]
        if flags & 7 == 1 and tag_type == b'T' and payload and 1 + (payload[0] & 0x3f) <= len(payload):
            encoding = 'utf-16' if payload[0] & 0x80 else 'utf-8'
            result.append('Text: ' + payload[1 + (payload[0] & 0x3f):].decode(encoding, errors='replace'))
        elif flags & 7 == 2 and tag_type.lower().split(b';', 1)[0] in (b'text/vcard', b'text/x-vcard'):
            details = decode_vcard(payload)
            result.extend(['Business card (vCard)', *details] if details else ['vCard data present'])
        elif flags & 7 == 1 and tag_type == b'U' and payload:
            prefix = URI_PREFIXES[payload[0]] if payload[0] < len(URI_PREFIXES) else f'[prefix {payload[0]:02X}]'
            result.append('URI: ' + prefix + payload[1:].decode('utf-8', errors='replace'))
        else:
            result.append(f'NDEF type {tag_type.decode("ascii", "replace")} ({length} bytes)')
        if flags & 0x40:
            return result if end == len(message) else []
        pos = end
    return []
