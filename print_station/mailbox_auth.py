"""Paired NFC HMAC; key provisioned out of band, never transmitted over RF.
MAC is bound to the current one-minute time slot; accept adjacent slot
to tolerate clock differences. Keep reader/host clocks reasonably synchronized.
"""
import hashlib
import hmac
import json
from pathlib import Path
import time

HOST_KEY=Path(__file__).resolve().parent/".private/nfc_pairing.key"
PT35_KEY=Path.home()/".config/pt35/print_pet.key"

def read_key(path):
    raw=Path(path).read_text(encoding="ascii").strip()
    if len(raw)!=64:raise ValueError("NFC key must be 64 hex characters")
    return bytes.fromhex(raw)

def signature(message,key,slot):
    fields={k:v for k,v in message.items() if k!="a"}
    canonical=json.dumps(fields,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("ascii")
    return hmac.new(key,canonical+b"|"+str(slot).encode("ascii"),hashlib.sha256).hexdigest()[:16]

def sign(message,key,now=None):
    msg=dict(message)
    msg["a"]=signature(msg,key,int(time.time() if now is None else now)//60)
    return msg

def verify(message,key,now=None):
    auth=message.get("a")
    if not (isinstance(auth,str) and len(auth)==16):return False
    slot=int(time.time() if now is None else now)//60
    return any(hmac.compare_digest(auth,signature(message,key,candidate))
               for candidate in (slot-1,slot,slot+1))
