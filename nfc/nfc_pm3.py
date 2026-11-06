"""Proxmark3 descriptor detection and Iceman client transport."""
import os
import re
import shutil
import subprocess
from pathlib import Path

UID_RE = re.compile(r'(?<![0-9a-fA-F])E0[0-9a-fA-F]{14}(?![0-9a-fA-F])', re.I)
COLOR_RE = re.compile(r'\x1b\[[0-9;]*m')

def usb_ports():
    # Never select arbitrary USB serial adapters; check sysfs ancestry for PM3 descriptors.
    found = []
    for base in ('/dev/serial/by-id',):
        folder = Path(base)
        if folder.is_dir():
            for item in folder.iterdir():
                if item.exists() and re.search(r'proxmark|pm3', item.name, re.I):
                    found.append(str(item.resolve()))
    for item in list(Path('/dev').glob('ttyACM*')) + list(Path('/dev').glob('ttyUSB*')):
        if str(item) in found:
            continue
        sysdev = Path('/sys/class/tty') / item.name / 'device'
        desc = []
        try:
            p = sysdev.resolve()
            for parent in [p, *p.parents]:
                for f in ('product', 'manufacturer', 'interface'):
                    fp = parent / f
                    if fp.is_file():
                        desc.append(fp.read_text(errors='replace').strip())
        except OSError:
            pass
        if re.search(r'proxmark|pm3', ' '.join(desc), re.I):
            found.append(str(item))
    return sorted(set(found))


def pm3_client(configured=None):
    override = configured or os.environ.get('PT35_PM3_CLIENT')
    paths = [
             str(Path.home() / 'proxmark3' / 'client' / 'proxmark3'),
             str(Path.home() / 'proxmark3' / 'pm3'),
             '/usr/local/bin/proxmark3', shutil.which('proxmark3') or '']
    for v in ([override] if override else paths):
        if v and Path(v).is_file() and os.access(v, os.X_OK):
            return str(Path(v).expanduser().resolve())
    return None


def run_pm3(client, port, command, timeout=35, cwd=None):
    # -c is the Proxmark3 client command-string flag; no shell interpolation.
    proc = subprocess.run([client, '-p', port, '-c', command], cwd=cwd,
                          text=True, capture_output=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, errors='replace',
                          env={**os.environ, 'NO_COLOR': '1'})
    return proc.returncode, COLOR_RE.sub('', (proc.stdout or '') + '\n' + (proc.stderr or ''))


def pm3_inventory(client, port):
    code, output = run_pm3(client, port, 'hf 15 reader', timeout=8)
    # Different Iceman versions print UID differently; accept explicitly labeled UID only.
    uid = None
    for line in output.splitlines():
        if re.search(r'\bUID\b', line, re.I):
            match = UID_RE.search(line.replace(' ', ''))
            if match:
                uid = match.group(0).upper()
                break
            # Common spaced hex UID format on a 'UID:' line.
            if ':' in line:
                tail = line.split(':', 1)[1]
                chunks = re.findall(r'\b[0-9a-fA-F]{2}\b', tail)
                if len(chunks) >= 8:
                    candidate = ''.join(chunks[:8]).upper()
                    if candidate.startswith('E0'):
                        uid = candidate
                        break
    return uid, output, code



def probe(client, port):
    try:
        code, output = run_pm3(client, port, 'hw ping; hw version', timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if re.search(r'mismatch|firmware does not match', output, re.I):
        return 'Iceman client and firmware mismatch'
    client_line = re.search(r'^\s*(?:\[.\]\s*)?Client\.{2,}\s+(.+)$', output, re.M)
    firmware = re.search(r'^\s*(?:\[.\]\s*)?OS\.{2,}\s+(.+)$', output, re.M)
    if (code or 'Ping response received' not in output or not client_line or not firmware or
            'Iceman' not in client_line[1] or client_line[1].strip() != firmware[1].strip()):
        return 'No verified Iceman response or matching firmware version'
    return None
