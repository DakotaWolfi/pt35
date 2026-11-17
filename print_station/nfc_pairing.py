#!/usr/bin/env python3
"""One-shot Print Pet NFC owner pairing, armed explicitly from trusted SSH.

Usage on Print Pet:
  python3 nfc_pairing.py arm --seconds 90
  python3 nfc_pairing.py status
  python3 nfc_pairing.py cancel

A successful NFC pair + keyed confirmation consumes the arm and persists the
new key. Do not put .private files in Git. RF pairing is NOT encrypted.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import time

from mailbox_auth import HOST_KEY, verify

PRIVATE=HOST_KEY.parent
ARM=PRIVATE/"nfc_pairing_arm.json"

def atomic_write(path,data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    temporary=path.with_name(path.name+"."+secrets.token_hex(5)+".tmp")
    fd=os.open(str(temporary),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        # Host may run as root; let the printer service owner read this key.
        if os.geteuid()==0:
            owner=path.parent.stat()
            os.fchown(fd,owner.st_uid,owner.st_gid)
        with os.fdopen(fd,"w",encoding="ascii") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)

def arm(seconds=90):
    if not 15<=seconds<=180:raise ValueError("Pairing window must be 15..180 seconds")
    now=int(time.time())
    data={"until":now+seconds,"key":secrets.token_hex(32),"state":"armed","session":""}
    atomic_write(ARM,json.dumps(data)+"\n")
    return data["until"]

def state():
    try:
        data=json.loads(ARM.read_text(encoding="ascii"))
        if not (isinstance(data,dict) and isinstance(data.get("key"),str)
                and len(data["key"])==64 and int(data["until"])>time.time()
                and data.get("state") in ("armed","issued")):
            return None
        return data
    except (OSError,ValueError,TypeError,KeyError):
        return None

def paired():
    try:
        from mailbox_auth import read_key
        read_key(HOST_KEY)
        return True
    except (OSError,ValueError):
        return False

def handle_pair(request):
    """Return (fields, state_update). Caller writes reply before marking issued."""
    if request.get("t")!="pair":return None
    active=state()
    if active is None:
        return {"ok":False,"error":"Pairing not armed"},None
    if active["state"]!="armed":
        return {"ok":False,"error":"Pairing already used"},None
    active["state"]="issued"
    active["session"]=secrets.token_hex(4)
    fields={"k":base64.b64encode(bytes.fromhex(active["key"])).decode("ascii"),
            "s":active["session"]}
    return fields,active

def issue_completed(update):
    """Called only after the NFC mailbox reply was successfully written."""
    if update is not None:
        current=state()
        if current and current["state"]=="armed" and current["key"]==update["key"]:
            atomic_write(ARM,json.dumps(update)+"\n")

def handle_done(request):
    """Only the recipient who received the provisional secret can confirm."""
    active=state()
    if active is None or active["state"]!="issued":
        return {"ok":False,"error":"No pending pairing"}
    if request.get("s")!=active["session"]:
        return {"ok":False,"error":"Pairing session mismatch"}
    key=bytes.fromhex(active["key"])
    if not verify(request,key):
        return {"ok":False,"error":"Pair confirmation failed"}
    atomic_write(HOST_KEY,active["key"]+"\n")
    ARM.unlink(missing_ok=True)
    return {"ok":True,"message":"NFC owner paired"}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("arm","status","cancel"))
    parser.add_argument("--seconds",type=int,default=90)
    args=parser.parse_args()
    if args.action=="arm":
        deadline=arm(args.seconds)
        print("NFC pairing armed ONCE until",time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(deadline)))
        print("Hold PT35 at tag and select Pair in Print Pet GUI. Secret is sent over NFC only while armed.")
    elif args.action=="cancel":
        ARM.unlink(missing_ok=True)
        print("NFC pairing disarmed")
    else:
        current=state()
        print("Paired:",paired(),"Armed:",bool(current),
              "Pending confirmation:",bool(current and current["state"]=="issued"))
if __name__=="__main__":main()
