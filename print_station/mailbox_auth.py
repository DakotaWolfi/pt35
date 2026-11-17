"""Shared-key authentication for PT35 -> Print Pet NFC commands.

The 32-byte key must be provisioned on both devices OUT OF BAND.
Never send it as an unprotected ISO15693 mailbox message.
"""
import hashlib
import hmac
import json
from pathlib import Path
import time

HOST_KEY=Path("/etc/fmi-print-station/nfc_pairing.key")
PT35_KEY=Path.home()/".config/pt35/print_pet.key"
MAX_SKEW=120

def read_key(path):
    raw=Path(path).read_text(encoding="ascii").strip()
    if len(raw)!=64:
        raise ValueError("NFC pairing key must be 64 hex characters")
    key=bytes.fromhex(raw)
    if len(key)!=32:
        raise ValueError("NFC pairing key length mismatch")
    return key

def signature(message,key):
    message={k:v for k,v in message.items() if k!="a"}
    canonical=json.dumps(message,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("ascii")
    return hmac.new(key,canonical,hashlib.sha256).hexdigest()[:16]

def sign(message,key,now=None):
    msg=dict(message)
    msg["ts"]=int(time.time() if now is None else now)
    msg["a"]=signature(msg,key)
    return msg

def verify(message,key,now=None):
    ts=message.get("ts")
    if type(ts) is not int:
        return False
    t=int(time.time() if now is None else now)
    if abs(t-ts)>MAX_SKEW:
        return False
    auth=message.get("a")
    return isinstance(auth,str) and len(auth)==16 and hmac.compare_digest(auth,signature(message,key))
