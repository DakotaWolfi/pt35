"""Durable short-lived NFC print replay cache.

A captured owner-signed print packet must not enqueue another receipt after
a mailbox host restart. Keep a 5-minute receipt cache (longer than the HMAC
time acceptance window); no printing payloads or secrets are written.
"""
import base64
import hashlib
import json
import time
from mailbox_auth import HOST_KEY

FILE=HOST_KEY.parent/"nfc_replay.json"
KEEP_SECONDS=300

class ReplayGuard:
    def __init__(self,path=FILE):
        self.path=path
        try:
            loaded=json.loads(path.read_text(encoding="ascii"))
            self.seen=loaded if isinstance(loaded,dict) else {}
        except (OSError,ValueError):
            self.seen={}

    def lookup(self,packet):
        key=hashlib.sha256(packet).hexdigest()
        item=self.seen.get(key)
        if isinstance(item,dict) and time.time()-item.get("at",0)<KEEP_SECONDS:
            try:return base64.b64decode(item["reply"],validate=True)
            except (KeyError,TypeError,ValueError):pass
        return None

    def record(self,packet,response):
        from nfc_pairing import atomic_write
        now=time.time()
        self.seen={k:v for k,v in self.seen.items()
                   if isinstance(v,dict) and isinstance(v.get("at"),(int,float))
                   and 0<=now-v["at"]<KEEP_SECONDS}
        self.seen[hashlib.sha256(packet).hexdigest()]={
            "at":now,"reply":base64.b64encode(response).decode("ascii")}
        if len(self.seen)>500:
            self.seen=dict(sorted(self.seen.items(),key=lambda kv:kv[1]["at"])[-500:])
        atomic_write(self.path,json.dumps(self.seen,separators=(",",":"))+chr(10))
