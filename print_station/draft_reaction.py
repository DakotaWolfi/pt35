"""Short-lived, local, intentionally silly reactions to completed fine fields.

No cloud service; no model dependency. Draft text is temporarily visible
on the physical e-paper, but never written to the receipt history.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

FILE=Path(__file__).resolve().parent/".private"/"draft_reaction.json"
LOCK=threading.Lock()
FIELDS={"name":"OFFENDER","issuer":"OFFICER","offence":"OFFENCE",
        "location":"LOCATION","amount":"FINE","currency":"CURRENCY",
        "message":"NOTES","fine_title":"TITLE","fine_status":"STATUS"}
TTL=65
INTERVAL=22

def clean(value):
    return re.sub(r"\s+"," ",str(value)).strip()[:65]

def reaction(field,value):
    value=clean(value)
    if field not in FIELDS or not value:
        raise ValueError("Unknown or empty fine field")
    bucket=int.from_bytes(hashlib.sha256((field+"|"+value).encode()).digest()[:2],"big")
    if field=="amount":
        try:
            number=float(value.replace(",",".")) 
            options=(("THATS A LOT!","OW MY WALLET!") if number>=500
                     else ("POCKET CHANGE?","THATS CHEAP!"))
        except ValueError:
            options=("SO MANY DIGITS!","WHAT A FINE!")
    elif field=="name":options=("SUSPICIOUS WOLF!","HI THERE!","WHO'S THAT?")
    elif field=="offence":options=("HOW DARE YOU!","VERY SERIOUS!","HEHE, GUILTY?")
    elif field=="message":options=("INTERESTING...","TELL ME MORE!","OH REALLY?")
    elif field=="location":options=("I KNOW THAT!","WHERE IS THAT?")
    else:options=("NOTED!","HMMM...","INTERESTING!")
    return {"field":FIELDS[field],"value":value,
            "comment":options[bucket%len(options)],"at":time.time()}

def submit(field,value,now=None):
    now=time.time() if now is None else now
    item=reaction(field,value)
    item["at"]=now
    with LOCK:
        try:
            previous=json.loads(FILE.read_text(encoding="utf-8"))
            if now-float(previous.get("at",0))<INTERVAL:
                return False
        except (OSError,ValueError,TypeError):
            pass
        FILE.parent.mkdir(parents=True,exist_ok=True)
        temporary=FILE.with_name(FILE.name+"."+str(os.getpid())+".tmp")
        temporary.write_text(json.dumps(item,ensure_ascii=True)+"\n",encoding="utf-8")
        os.chmod(temporary,0o600)
        temporary.replace(FILE)
    return True

def current(now=None):
    now=time.time() if now is None else now
    try:
        item=json.loads(FILE.read_text(encoding="utf-8"))
        if 0<=now-float(item["at"])<TTL:
            return item
    except (OSError,ValueError,KeyError,TypeError):
        pass
    return None
