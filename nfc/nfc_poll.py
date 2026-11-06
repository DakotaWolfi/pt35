"""Single-tag polling for the ST25R3916 hardware framing modes.

Register profiles are based on M5Stack's U216 reader sequences. Keep the
PT35 3.3 V supply settings from the common initializer.
"""
from nfc_archive import set_coverage
from nfcv_dump import failure
from nfcv_scan import FrameError, crc15693

MODES = ('NFC-A', 'NFC-B', 'NFC-F')
NTAG = {0x0f: ('NTAG213', 36), 0x11: ('NTAG215', 126), 0x13: ('NTAG216', 222)}


def configure(chip, protocol):
    mode, rate, rx, correlator = {
        'NFC-A': (0x09, 0x00, (0x08, 0x2d, 0xd8, 0x22), 0x47),
        'NFC-B': (0x14, 0x00, (0x04, 0x2d, 0, 0), 0x1b),
        'NFC-F': (0x1c, 0x11, (0x13, 0x3d, 0, 0), 0x54),
    }[protocol]
    for addr, value in ((0x03, mode), (0x04, rate), (0x05, 0), (0x06, 0),
                        (0x07, 0), (0x0a, 0), (0x0f, 0), (0x12, 0), (0x28, 0x70)):
        chip.wr(addr, value)
    for addr, value in enumerate(rx, start=0x0b):
        chip.wr(addr, value)
    chip.wr(0x0c, correlator, True)
    chip.wr(0x0d, 0, True)
    if protocol == 'NFC-A':
        for addr, value in enumerate((0x40, 0x03, 0x40, 0x03), start=0x30):
            chip.wr(addr, value, True)
    elif protocol == 'NFC-B':
        for addr, value in ((0x08, 0x5d), (0x09, 0x38), (0x0f, 0x07), (0x12, 0x22)):
            chip.wr(addr, value)
        for addr, value in ((0x05, 0xc4), (0x06, 0x14), (0x0b, 0x0c),
                            (0x28, 0x10), (0x29, 0x7c), (0x2a, 0x80)):
            chip.wr(addr, value, True)
    chip.cmd(0xd5)  # Reset RX gain


def crc_a(data):
    crc = 0x6363
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc


def receive(chip, data, *, cmd=0xc4, checksum=None):
    reply, status, _ = chip.transceive(data, .035, tx_command=cmd, check_errors=True, max_rx=64)
    if status & 0x0f:
        raise FrameError('framing', 'Incomplete byte or missing parity in NFC response')
    if checksum is not None:
        if len(reply) < 3 or checksum(reply[:-2]) != int.from_bytes(reply[-2:], 'little'):
            raise FrameError('crc', 'NFC CRC mismatch')
        return reply[:-2]
    return reply


def poll_a(chip):
    # WUPA reactivates a tag left selected by a previous sweep. Reject
    # collisions rather than assigning a UID from a corrupt cascade frame.
    chip.wr(0x05, 0x01)
    chip.wr(0x0a, 0x80)
    atqa = receive(chip, b'', cmd=0xc7)
    if len(atqa) != 2:
        raise FrameError('framing', 'Invalid NFC-A ATQA length')
    uid = bytearray()
    for level, select in enumerate((0x93, 0x95, 0x97)):
        chip.wr(0x05, 0x01)
        chip.wr(0x0a, 0x80)
        serial = receive(chip, bytes((select, 0x20)), cmd=0xc5)
        if len(serial) != 5 or serial[4] != serial[0] ^ serial[1] ^ serial[2] ^ serial[3]:
            raise FrameError('framing', 'Invalid NFC-A anticollision BCC')
        chip.wr(0x05, 0x00)
        chip.wr(0x0a, 0x00)
        sak = receive(chip, bytes((select, 0x70)) + serial, checksum=crc_a)
        if len(sak) != 1:
            raise FrameError('framing', 'Invalid NFC-A SAK length')
        if not sak[0] & 0x04:
            uid.extend(serial[:4])
            return uid.hex().upper(), {'atqa': atqa.hex().upper(), 'sak': sak[0]}
        if level == 2 or serial[0] != 0x88:
            break
        uid.extend(serial[1:4])
    raise FrameError('framing', 'Invalid NFC-A cascade')


def poll_b(chip):
    reply = receive(chip, b'\x05\x00\x00', checksum=crc15693)
    if len(reply) != 12 or reply[0] != 0x50:
        raise FrameError('framing', 'Invalid NFC-B ATQB')
    return reply[1:5].hex().upper(), {'atqb': reply.hex().upper(), 'identifier_type': 'PUPI'}


def poll_f(chip):
    # The ST25R3916 adds the FeliCa length byte and TX CRC.
    reply = receive(chip, b'\x00\xff\xff\x01\x00')
    if len(reply) not in (20, 22) or reply[0] != len(reply) - 2 or reply[1] != 0x01:
        raise FrameError('framing', 'Invalid NFC-F polling response')
    details = {'pmm': reply[10:18].hex().upper(), 'identifier_type': 'IDm'}
    if len(reply) == 22:
        details['system_code'] = reply[18:20].hex().upper()
    return reply[2:10].hex().upper(), details


POLL = {'NFC-A': poll_a, 'NFC-B': poll_b, 'NFC-F': poll_f}


def read_ntag(chip, uid, details):
    """Read only the user pages on known NTAG21x, using read-only commands."""
    if len(uid) != 14 or details['sak'] != 0:
        return {}
    try:
        version = receive(chip, b'\x60', checksum=crc_a)
    except (FrameError, TimeoutError):
        return {}
    if len(version) != 8 or version[:6] != bytes.fromhex('000404020100') or version[7] != 3:
        return {}
    model = NTAG.get(version[6])
    if model is None:
        return {}
    name, count = model
    capture = dict(chip=f'{name} (GET_VERSION)', manufacturer='NXP', blocks=[], read_errors=[],
                   verification='CRC-A checked READ responses', memory_start=4)
    try:
        page0 = receive(chip, b'\x30\x00', checksum=crc_a)
        if len(page0) != 16 or (page0[:3] + page0[4:8]).hex().upper() != uid:
            raise FrameError('framing', 'NTAG header size or UID changed')
        capture['cc'] = page0[12:16].hex().upper()
    except (FrameError, TimeoutError) as exc:
        capture['read_errors'].append({'index': 4, **failure(exc)})
    else:
        for page in range(4, count + 4, 4):
            first = min(page, count)
            try:
                data = receive(chip, bytes((0x30, first)), checksum=crc_a)
                if len(data) != 16:
                    raise FrameError('size', 'NTAG READ did not return four pages')
            except (FrameError, TimeoutError) as exc:
                capture['read_errors'].append({'index': page, **failure(exc)})
                break
            for index in range(page, min(page + 4, count + 4)):
                offset = (index - first) * 4
                capture['blocks'].append({'index': index, 'hex': data[offset:offset + 4].hex().upper(),
                                          'size': 4})
    geometry = {'start': 4, 'blocks': count, 'size': 4, 'source': f'NXP {name} user pages'}
    set_coverage(capture, count, geometry, start=4)
    return capture
