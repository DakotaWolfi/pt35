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
