"""Local physical-presence challenge and admin-issued short-lived passes."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time

KEY_PATH=Path("/home/jenna/.local/state/fmi-print-station/challenge.key")
PERIOD=600  # ten-minute codes; one prior period accepted for slow e-paper updates
PASS_PERIOD=300
CODE_STATE_PATH=KEY_PATH.with_name("guest-code.json")

def get_key(create=False, path=KEY_PATH):
    if create:
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        try:
            fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,"w") as f:
                f.write(secrets.token_hex(32)+"\n")
    secret=path.read_text(encoding="ascii").strip()
    if len(secret)!=64:
        raise ValueError("Invalid challenge secret")
    return bytes.fromhex(secret)

def _digest(secret, context, bucket):
    return hmac.new(secret,(context+":"+str(bucket)).encode(),hashlib.sha256).digest()

def current_code(secret, now=None):
    t=time.time() if now is None else now
    return f"{int.from_bytes(_digest(secret,'guest',int(t//PERIOD))[:4],'big')%1000000:06d}"

def check_code(secret, candidate, now=None):
    t=time.time() if now is None else now
    if not isinstance(candidate,str) or len(candidate)!=6 or not candidate.isascii() or not candidate.isdecimal():
        return False
    return any(hmac.compare_digest(candidate,current_code(secret,(int(t//PERIOD)-d)*PERIOD)) for d in (0,1))

def pass_token(secret,now=None):
    t=time.time() if now is None else now
    raw=_digest(secret,'owner',int(t//PASS_PERIOD))
    return base64.b32encode(raw[:7]).decode('ascii').rstrip('=')[:10]

def check_pass(secret,candidate,now=None):
    t=time.time() if now is None else now
    if not isinstance(candidate,str) or len(candidate)!=10:
        return False
    return any(hmac.compare_digest(candidate.upper(),pass_token(secret,(int(t//PASS_PERIOD)-d)*PASS_PERIOD)) for d in (0,1))

def _read_code_state(path=CODE_STATE_PATH):
    """Atomic state shared by HTTP server and the e-paper display."""
    import json
    state=json.loads(path.read_text(encoding="ascii"))
    serial=state["serial"]
    if type(serial) is not int or serial < 0:
        raise ValueError("Invalid print challenge state")
    return serial


def init_print_code(path=CODE_STATE_PATH):
    """Create persistent guest code state on first service startup."""
    import json
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd,"w",encoding="ascii") as f:
            json.dump({"serial":secrets.randbits(64)},f)
            f.write("\\n")
    return _read_code_state(path)


def display_code(secret,path=CODE_STATE_PATH):
    """Read the one currently usable guest code."""
    serial=_read_code_state(path)
    return f"{int.from_bytes(_digest(secret,'guest-print',serial)[:4],'big')%1000000:06d}"


def check_display_code(secret,candidate,path=CODE_STATE_PATH):
    if not isinstance(candidate,str) or len(candidate)!=6 or not candidate.isascii() or not candidate.isdecimal():
        return False
    return hmac.compare_digest(candidate,display_code(secret,path))


def rotate_display_code(secret,path=CODE_STATE_PATH):
    """Invalidate the previous displayed code using an atomic file replacement.

    Call while holding the print queue lock after a job is accepted.
    """
    import json
    old=_read_code_state(path)
    next_serial=old+1
    current=display_code(secret,path)
    # Avoid even a rare six-digit collision with the previous code.
    while f"{int.from_bytes(_digest(secret,'guest-print',next_serial)[:4],'big')%1000000:06d}" == current:
        next_serial+=1
    temp=path.with_name(path.name+".tmp")
    try:
        fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,"w",encoding="ascii") as f:
            json.dump({"serial":next_serial},f)
            f.write("\\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
    return display_code(secret,path)
