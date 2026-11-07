"""ST25DV16K I2C NDEF user-memory access, migrated from PT35_XIAO_NFC_Controls v1.4.

No RF reader, no system-memory 0x57 writes, no GPIO. All writes require
an explicit calling UI action and are followed by I2C readback verification.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

BUS = os.environ.get('PT35_NFC_I2C_BUS', '1')
ADDR = '0x53'
MEMORY_BYTES = 2048
INSPECT_BYTES = 512
MAX_NDEF = 240
CC16 = bytes.fromhex('E2 40 00 00 00 00 00 FF')
PRESETS = {
    'CollarPet / PT35 info': os.environ.get('PT35_NFC_INFO', os.environ.get('PT35_NFC_GITHUB',
                                        'https://github.com/DakotaWolfi/collar-pet')),
    'Telegram': os.environ.get('PT35_NFC_TELEGRAM', 'https://t.me/DakotaWolfi'),
    'GitHub': os.environ.get('PT35_NFC_GITHUB', 'https://github.com/DakotaWolfi/collar-pet'),
}


def run_i2c(args, timeout=5):
    if not shutil.which('i2ctransfer'):
        raise RuntimeError('i2ctransfer is missing (install i2c-tools)')
    proc = subprocess.run(['i2ctransfer', '-y', BUS, *args], text=True, capture_output=True,
                          timeout=timeout, check=False)
    if proc.returncode:
        err = (proc.stderr or proc.stdout).strip()
        if 'Permission denied' in err or 'Could not open file' in err:
            raise PermissionError('No I²C access; verify /dev/i2c-' + BUS + ' group permissions')
        raise RuntimeError(err or f'i2ctransfer returned {proc.returncode}')
    return proc.stdout.strip()


def check_bounds(off, length):
    if not isinstance(off, int) or not isinstance(length, int) or off < 0 or length < 0 or off + length > MEMORY_BYTES:
        raise ValueError('Requested ST25DV user-memory range out of bounds')


def read_mem(off, length):
    check_bounds(off, length)
    result = bytearray()
    while length:
        size = min(length, 32)
        output = run_i2c([f'w2@{ADDR}', f'0x{off >> 8:02x}', f'0x{off & 255:02x}', f'r{size}'])
        data = [int(x, 16) for x in re.findall(r'0x[0-9a-fA-F]{2}\b', output)]
        if len(data) != size:
            raise RuntimeError(f'Short read at 0x{off:04X}: {output}')
        result.extend(data)
        off += size
        length -= size
    return bytes(result)


def write_mem(off, data):
    data = bytes(data)
    check_bounds(off, len(data))
    for start in range(0, len(data), 4):
        pass  # Writes are intentionally split below by absolute EEPROM page.
    index = 0
    while index < len(data):
        width = min(4 - off % 4, 4, len(data) - index)
        part = data[index:index + width]
        run_i2c([f'w{2 + width}@{ADDR}', f'0x{off >> 8:02x}', f'0x{off & 255:02x}',
                 *(f'0x{byte:02x}' for byte in part)])
        off += width
        index += width
        time.sleep(.007)


def ndef_uri(value):
    if value.startswith('https://'):
        payload = b'\x04' + value[8:].encode('utf-8')
    elif value.startswith('http://'):
        payload = b'\x03' + value[7:].encode('utf-8')
    else:
        payload = b'\x00' + value.encode('utf-8')
    if len(payload) > 255:
        raise ValueError('URL is too long')
    return bytes((0xD1, 1, len(payload), 0x55)) + payload


def ndef_text(value):
    payload = b'\x02en' + value.encode('utf-8')
    if len(payload) > 255:
        raise ValueError('Text is too long')
    return bytes((0xD1, 1, len(payload), 0x54)) + payload


def make_ndef(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Enter nonempty URL or text')
    msg = ndef_uri(value) if value.startswith(('http://', 'https://')) else ndef_text(value)
    if len(msg) > MAX_NDEF:
        raise ValueError(f'NDEF message is {len(msg)} bytes; maximum {MAX_NDEF}')
    return msg


def find_ndef(buf):
    # Preserve support for both ordinary 4-byte and the existing 8-byte CC.
    starts = (8,) if buf.startswith(CC16) else (4, 8)
    for start in starts:
        pos = start
        while pos < len(buf):
            kind = buf[pos]
            if kind == 0:
                pos += 1
                continue
            if kind == 0xFE:
                break
            if pos + 2 > len(buf):
                break
            length = buf[pos + 1]
            width = 2
            if length == 0xff:
                if pos + 4 > len(buf):
                    break
                length = int.from_bytes(buf[pos + 2:pos + 4], 'big')
                width = 4
            if pos + width + length > len(buf):
                break
            if kind == 3:
                return pos, width, length
            pos += width + length
    return None


def inspect():
    buf = read_mem(0, INSPECT_BYTES)
    tlv = find_ndef(buf)
    if tlv is None:
        blank = all(value in (0, 255) for value in buf[:32])
        return {'state': 'blank' if blank else 'unrecognized', 'buffer': buf,
                'message': b'', 'tlv': None}
    off, width, length = tlv
    return {'state': 'ndef', 'buffer': buf, 'tlv': tlv,
            'message': buf[off + width:off + width + length]}


def format_blank_tag():
    # Matches v1.4 formatting, but explicitly checks the full formatted region.
    head = read_mem(0, 32)
    if not all(byte in (0, 255) for byte in head):
        raise RuntimeError('Refusing to format: first 32 bytes are not blank')
    write_mem(0, CC16)
    write_mem(8, b'\x03\x00\xfe')
    expected = CC16 + b'\x03\x00\xfe'
    if read_mem(0, len(expected)) != expected:
        raise RuntimeError('Format readback verification failed')
    return expected


def write_payload(value):
    msg = make_ndef(value)
    tag = inspect()
    if tag['state'] != 'ndef':
        raise RuntimeError('NDEF TLV missing; format the blank tag first')
    buf = tag['buffer']
    off, width, old_length = tag['tlv']
    if width != 2:
        raise RuntimeError('Extended-length TLV: automatic rewrite not supported')
    start = off + 2
    end = start + len(msg) + 1
    if end > INSPECT_BYTES:
        raise RuntimeError('New NDEF payload exceeds the inspected memory region')
    # Do not overwrite any different TLV, unknown data, or an occupied tail.
    previous_end = start + old_length
    if buf[previous_end] not in (0, 0xfe):
        raise RuntimeError('Unexpected data after existing NDEF')
    extension = buf[previous_end + 1:end]
    if any(byte not in (0, 0xff) for byte in extension):
        raise RuntimeError('New NDEF would overwrite occupied memory')
    # Commit length last; failure leaves TLV unpublished rather than claiming success.
    write_mem(off + 1, b'\x00')
    write_mem(start, msg + b'\xfe')
    if read_mem(start, len(msg) + 1) != msg + b'\xfe':
        raise RuntimeError('NDEF write verification failed; TLV remains unpublished')
    write_mem(off + 1, bytes((len(msg),)))
    verified = inspect()
    if verified['message'] != msg:
        raise RuntimeError('Final NDEF readback verification failed')
    return len(msg)
