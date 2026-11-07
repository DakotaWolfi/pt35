"""Read-only Iceman transport and opt-in ISO15693 simulation."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from nfc_archive import range_bytes
from nfc_config import reader_lock
from nfcv_dump import Reader
from nfcv_scan import FrameError, crc15693

CONTROL = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
DESCRIPTOR = re.compile(r'proxmark(?:[ _.-]*3|\.org)|\bpm3(?:[ _-]rdv4)?\b', re.I)
USB_IDS = {('9ac4', '4b8f'), ('502d', '502d'), ('2d2d', '504d')}
PM3_MODES = ('HF', 'LF', 'ISO15693')
SIM_SECONDS = 10


def usb_ports(dev=Path('/dev'), sys_tty=Path('/sys/class/tty')):
    def read(path):
        try:
            return path.read_text(errors='replace').strip()
        except OSError:
            return ''

    ports = set()
    for item in (*dev.glob('ttyACM*'), *dev.glob('ttyUSB*')):
        node = (sys_tty / item.name / 'device').resolve()
        description = []
        for parent in (node, *node.parents):
            description.extend((read(parent / 'product'), read(parent / 'manufacturer'),
                                read(parent / 'interface')))
            vendor = read(parent / 'idVendor').lower()
            if vendor:
                ids = vendor, read(parent / 'idProduct').lower()
                if ids in USB_IDS or any(DESCRIPTOR.search(value) for value in description):
                    ports.add(str(item.resolve()))
                break
    # Some kernel/udev setups only expose the explicit Proxmark model in by-id.
    for link in (dev / 'serial/by-id').glob('*'):
        if (link.is_symlink() and link.exists() and
                re.search(r'^usb-(?:proxmark[._]org|proxmark[_-]?3)', link.name, re.I)):
            target = link.resolve()
            if target.parent == dev.resolve() and re.fullmatch(r'tty(?:ACM|USB)\d+', target.name):
                ports.add(str(target))
    return sorted(ports)


def pm3_client(configured=None):
    override = configured or os.environ.get('PT35_PM3_CLIENT')
    paths = [Path.home() / '.local/lib/pt35-iceman/current/client/proxmark3',
             Path.home() / 'proxmark3/client/proxmark3',
             Path.home() / 'proxmark3/client/build/proxmark3',
             Path.home() / 'proxmark3-iceman/client/proxmark3', '/usr/local/bin/proxmark3',
             Path.home() / '.local/bin/proxmark3', shutil.which('proxmark3')]
    for value in ([override] if override else paths):
        if value:
            path = Path(value).expanduser().resolve()
            candidates = [path]
            if path.name == 'pm3':
                # The upstream shell launcher forks the binary, which can
                # otherwise keep a serial port and the child's pipes open.
                candidates = [path.parent / relative for relative in (
                    'client/proxmark3', 'client/build/proxmark3', 'proxmark3')] + candidates
            for candidate in candidates:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate.resolve())
    return None


def run_pm3(client, port, command, timeout=20, cwd=None, cancel=None):
    # Iceman commands are fixed strings or validated hex; shell=False.
    args = [client, '-p', port, '--incognito', '-c', command]
    deadline = time.monotonic() + timeout
    with subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, errors='replace',
                          env={**os.environ, 'NO_COLOR': '1'}) as proc:
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('Iceman probe cancelled')
                if not Path(port).exists():
                    raise OSError(f'Iceman disconnected on {port}')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    out, err = proc.communicate(timeout=min(remaining, .2))
                    return proc.returncode, CONTROL.sub('', out + '\n' + err)
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            proc.kill()
            raise


def revisions(output):
    client = re.search(r'^\s*(?:\[.\]\s*)?(?:Client(?:\.{2,}|:)\s+)?Iceman/(\S+)', output, re.M | re.I)
    firmware = re.search(r'^\s*(?:\[.\]\s*)?OS(?:\.{2,}|:)\s+Iceman/(\S+)', output, re.M | re.I)
    return tuple(match[1].split('/')[-1] if match else '' for match in (client, firmware))


def version_fault(code, output):
    """Reject broken communications, not merely different source revisions.

    Custom PM3 firmware commonly has a deliberately different revision from
    its userspace client. A working hardware ping is the connection gate.
    """
    if (code or not re.search(r'Ping response received\b', output, re.I) or
            re.search(r'content\s*\(\s*fail', output, re.I)):
        return 'Iceman did not receive a valid hardware ping'
    return None


def revision_warning(output):
    """Advisory warning, never silently claim custom firmware is identical."""
    client, firmware = revisions(output)
    if not client or not firmware:
        return 'firmware revision unknown'
    if client == firmware:
        return ''
    hashes = [re.search(r'(?:^|-g)([a-f0-9]{7,40})(?:-suspect)?$', value, re.I)
              for value in (client, firmware)]
    if all(hashes):
        a, b = (item[1].lower() for item in hashes)
        if a.startswith(b) or b.startswith(a):
            return ''
    return f'client/firmware revisions differ ({client} / {firmware})'


@dataclass(frozen=True)
class Link:
    state: str
    message: str
    client: str = ''
    port: str = ''
    firmware: str = ''
    actions: tuple = ()


def connect(client_override=None, port_override=None, cancel=None, *, allow_simulation_mismatch=False):
    ports = usb_ports()
    if port_override:
        requested = str(Path(port_override).expanduser().resolve())
        ports = [port for port in ports if port == requested]
    if not ports:
        return Link('absent', 'No Proxmark3 USB serial device detected')
    client = pm3_client(client_override)
    if not client:
        return Link('no_client', 'Proxmark3 found · install its matching Iceman client')
    link = None
    for port in ports:
        if cancel is not None and cancel.is_set():
            break
        if not os.access(port, os.R_OK | os.W_OK):
            link = Link('inaccessible', f'{Path(port).name} inaccessible · check Debian dialout access')
            continue
        try:
            with reader_lock(Path(port).name):
                code, output = run_pm3(client, port, 'hw ping; hw version', timeout=5, cancel=cancel)
                fault = version_fault(code, output)
                if fault is None:
                    firmware = revisions(output)[1]
                    warning = revision_warning(output)
                    # Discovery is read-only; an advertised raw reader can be
                    # tested independently. Never offer emulation with an
                    # unverified custom/client combination.
                    actions = tuple(action for action in iso15693_actions(client, port, cancel)
                                    if not warning or allow_simulation_mismatch or action != 'pm3-simulate')
                    if Path(port).exists():
                        message = f'Proxmark3 connected · {Path(port).name} · {firmware}'
                        if warning:
                            message += (f' · Caution: {warning}; ' +
                                        ('experimental emulation override enabled'
                                         if allow_simulation_mismatch else 'simulation disabled'))
                        return Link('connected', message, client, port, firmware, actions)
                    link = Link('unresponsive', 'Proxmark3 disconnected during setup')
                elif re.search(r'permission denied|could not open.*permission', output, re.I):
                    link = Link('inaccessible', f'{Path(port).name} inaccessible · check Debian dialout access')
                else:
                    link = Link('unresponsive', f'{fault} · check USB and port availability')
        except PermissionError:
            link = Link('inaccessible', f'{Path(port).name} inaccessible · check Debian dialout access')
        except RuntimeError:
            link = Link('busy', f'{Path(port).name} in use · close the other reader')
        except (OSError, subprocess.TimeoutExpired):
            link = Link('unresponsive', f'{Path(port).name} did not respond · check USB and serial access')
    return link or Link('absent', 'No responsive Proxmark3 USB serial device')


def iso15693_actions(client, port, cancel=None):
    try:
        code, output = run_pm3(client, port, 'hf 15 help', timeout=2, cancel=cancel)
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


def simulation_eligibility(record):
    """Explain whether a saved ISO15693 capture has enough verified data."""
    try:
        image = simulation_image(record)
    except (ValueError, KeyError, TypeError) as exc:
        return False, str(exc)
    return True, f"ISO15693 · {image['Card']['pagescount']} blocks × 4 bytes · 10 s maximum"


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
