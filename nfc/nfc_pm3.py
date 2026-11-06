"""Read-only Iceman transport and opt-in ISO15693 simulation."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from nfc_archive import range_bytes
from nfcv_dump import Reader
from nfcv_scan import FrameError, crc15693

CONTROL = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
DESCRIPTOR = re.compile(r'proxmark3?|\bpm3\b', re.I)
PM3_MODES = ('HF', 'LF', 'ISO15693')
SIM_SECONDS = 10


def usb_ports():
    ports = set()
    for item in Path('/dev/serial/by-id').glob('*'):
        if item.exists() and DESCRIPTOR.search(item.name):
            ports.add(str(item.resolve()))
    for item in (*Path('/dev').glob('ttyACM*'), *Path('/dev').glob('ttyUSB*')):
        if str(item) in ports:
            continue
        node = (Path('/sys/class/tty') / item.name / 'device').resolve()
        for parent in (node, *node.parents):
            try:
                product = (parent / 'product').read_text(errors='replace')
            except OSError:
                continue
            if DESCRIPTOR.search(product):
                ports.add(str(item))
            break
    return sorted(ports)


def pm3_client(configured=None):
    override = configured or os.environ.get('PT35_PM3_CLIENT')
    paths = [Path.home() / '.local/lib/pt35-iceman/current/client/proxmark3',
             Path.home() / 'proxmark3/client/proxmark3',
             Path.home() / 'proxmark3/pm3', '/usr/local/bin/proxmark3',
             shutil.which('proxmark3')]
    for value in ([override] if override else paths):
        if value:
            path = Path(value).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path.resolve())
    return None


def run_pm3(client, port, command, timeout=20, cwd=None):
    # Iceman commands are fixed strings or validated hex; shell=False.
    proc = subprocess.run([client, '-p', port, '--incognito', '-c', command], cwd=cwd, stdin=subprocess.DEVNULL,
                          text=True, errors='replace', capture_output=True, timeout=timeout,
                          env={**os.environ, 'NO_COLOR': '1'})
    return proc.returncode, CONTROL.sub('', proc.stdout + '\n' + proc.stderr)


def version_fault(code, output):
    if re.search(r'mismatch|firmware does not match', output, re.I):
        return 'Iceman client and firmware mismatch'
    client = re.search(r'^\s*(?:\[.\]\s*)?(?:Client\.{2,}\s+)?Iceman/(\S+)', output, re.M)
    firmware = re.search(r'^\s*(?:\[.\]\s*)?OS\.{2,}\s+Iceman/(\S+)', output, re.M)
    if code or not re.search(r'Ping response received[^\n]+content\s*\(\s*ok\s*\)', output):
        return 'Iceman did not receive a valid hardware ping'
    if (not client or not firmware or client[1].split('/')[-1] != firmware[1].split('/')[-1] or
            '...' in client[1] or 'dirty' in client[1] or client[1].endswith('/release')):
        return 'No verified matching Iceman client and firmware revision'
    return None


def probe(client, port):
    try:
        code, output = run_pm3(client, port, 'hw ping; hw version', timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return version_fault(code, output)


def iso15693_actions(client, port):
    try:
        code, output = run_pm3(client, port, 'hf 15 help', timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if code:
        return []
    commands = set(re.findall(r'^\s*(?:\[.\]\s*)?(raw|eload|sim)\s{2,}', output, re.M))
    actions = []
    if 'raw' in commands:
        actions.append('pm3-dump')
    if {'eload', 'sim'} <= commands:
        actions.append('pm3-simulate')
    return actions


HF_PROTOCOLS = {
    'ISO 14443-A': ('NFC-A', 'UID', (4, 7, 10)),
    'ISO 14443-B': ('NFC-B', 'PUPI|UID', (4,)),
    'ISO 15693': ('ISO15693', 'UID', (8,)),
    'ISO 18092 / FeliCa': ('NFC-F', 'IDm', (8,)),
}


def identifier(output, label, widths):
    matches = re.finditer(rf'\b(?:{label})\s*[:.]*\s+([0-9A-F]+(?: +[0-9A-F]{{2}}\b)*)',
                          output, re.I)
    for match in matches:
        value = match[1].replace(' ', '').upper()
        if len(value) in {2 * width for width in widths}:
            return value
    return None


def discoveries(mode, output):
    if mode == 'ISO15693':
        uid = identifier(output, 'UID', (8,))
        return [('ISO15693', uid)] if uid and uid.startswith('E0') else []
    if mode == 'LF':
        uid = identifier(output, 'EM 410x ID', (5,))
        return [('EM410X', uid)] if uid and 'Valid EM410x ID found' in output else []
    tags = []
    # Anchor the UID to the matching Iceman success section. Keep unparsed formats in the log.
    for section in re.split(r'Searching for [^\n]*?\.\.\.', output):
        for name, (protocol, label, widths) in HF_PROTOCOLS.items():
            if f'Valid {name} tag found' in section:
                uid = identifier(section, label, widths)
                if uid and (protocol != 'ISO15693' or uid.startswith('E0')):
                    tags.append((protocol, uid))
    return tags


def require_link(port, output):
    if not Path(port).exists() or re.search(
            r'failed to open|could not open|no proxmark|not connected|permission denied|offline mode',
            output, re.I):
        raise OSError(f'Iceman lost connection on {port}')


def scan(client, port, mode):
    command = {'HF': 'hf search', 'LF': 'lf search', 'ISO15693': 'hf 15 reader'}[mode]
    code, output = run_pm3(client, port, command)
    require_link(port, output)
    return discoveries(mode, output), code, output


class PM3Reader(Reader):
    """Reuse the ISO15693 addressed reader, checking Iceman's raw reply in Python."""
    def __init__(self, client, port):
        super().__init__(None)
        self.client, self.port = client, port

    def exchange(self, payload, timeout=.12, verbose=False):
        code, output = run_pm3(self.client, self.port, f'hf 15 raw -ac -d {bytes(payload).hex()}', timeout=8)
        require_link(self.port, output)
        match = re.search(r'^\s*(?:\[.\]\s*)?\((\d+)\)\s+((?:[0-9a-f]{2} *)+)\s*$',
                          output, re.M | re.I)
        if code or not match:
            raise TimeoutError('No ISO15693 reply from Iceman')
        reply = bytes.fromhex(match[2])
        if not 3 <= len(reply) <= 64 or len(reply) != int(match[1]):
            raise FrameError('framing', 'Iceman raw response length mismatch')
        if crc15693(reply[:-2]) != int.from_bytes(reply[-2:], 'little'):
            raise FrameError('crc', 'ISO15693 CRC mismatch in Iceman response')
        return reply[:-2]


def simulation_image(record):
    geometry = record.get('geometry') or {}
    uid = record.get('uid', '')
    if (record.get('protocol') != 'ISO15693' or not record.get('addressable_memory_complete') or
            not re.fullmatch(r'E0[0-9A-F]{14}', uid) or geometry.get('size') != 4 or
            not 1 <= geometry.get('blocks', 0) <= 128 or
            record.get('requested_range') != {'start': 0, 'count': geometry['blocks']} or
            range_bytes(record) is None):
        raise ValueError('Simulation requires a verified complete ISO15693 capture of 1–128 four-byte blocks')
    card = {'uid': bytes.fromhex(uid)[::-1].hex().upper(), 'bytesperpage': '04',
            'pagescount': f"{geometry['blocks']:02X}"}
    if re.fullmatch(r'[0-9A-F]{2}', record.get('dsfid') or ''):
        card['dsfid'] = record['dsfid']
    info = record.get('system_info') or {}
    for field, key in (('afi', 'afi'), ('ic', 'ic_reference')):
        if isinstance(info.get(key), int) and 0 <= info[key] <= 255:
            card[field] = f'{info[key]:02X}'
    return {'FileType': '15693 v4', 'Card': card,
            'blocks': {str(block['index']): block['hex'] for block in record['blocks']}}


def simulate(client, port, record, emit):
    image = simulation_image(record)
    for command, flag in (('hf 15 eload -h', '--file'), ('hf 15 sim -h', '--timeout')):
        code, output = run_pm3(client, port, command, timeout=8)
        if code or flag not in output:
            raise RuntimeError(f'Connected Iceman did not advertise {command} with {flag}')
    with tempfile.TemporaryDirectory(prefix='pt35-nfc-emulate-') as directory:
        path = Path(directory) / 'pt35-image.json'
        path.write_text(json.dumps(image))
        # The argument contains no user-supplied path or command characters.
        code, output = run_pm3(client, port, 'hf 15 eload -f pt35-image.json', cwd=directory)
        emit('log', output.strip())
        if code or not re.search(r'uploaded \d+ bytes to emulator memory', output, re.I):
            raise RuntimeError('Iceman did not confirm emulator memory upload')
    emit('scan_state', f'ISO15693 simulation requested for {SIM_SECONDS} seconds')
    try:
        code, output = run_pm3(client, port, f'hf 15 sim --timeout {SIM_SECONDS * 1000}',
                               timeout=SIM_SECONDS + 6)
        emit('log', output.strip())
        if code or 'Press pm3 button to abort simulation' not in output or 'Done!' not in output:
            raise RuntimeError('Iceman did not confirm the bounded simulation')
    finally:
        stop_rf(client, port, emit)


def stop_rf(client, port, emit):
    if Path(port).exists():
        try:
            code, output = run_pm3(client, port, 'hw break', timeout=2)
            if code or re.search(r'not connected|offline mode|no proxmark', output, re.I):
                emit('fault', 'Could not confirm Iceman stop. Use the Proxmark3 button.')
        except (OSError, subprocess.TimeoutExpired):
            emit('fault', 'Could not confirm Iceman stop. Use the Proxmark3 button.')
