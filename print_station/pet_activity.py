"""Low-write, local-only activity signals for the monochrome Print Pet.

Each source uses its own file, avoiding writer races between the HTTP server
and NFC host. Activities expire automatically; no identifying data is saved.
"""
import json
import os
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parent/".private"
ALLOWED={"web","web_print","nfc","nfc_print","pair","printing","printed","error"}
# Every visible event outlives the default minimum 25s e-paper refresh
# (plus a 5s poll), so brief taps can still be displayed.
DURATION={"web":40,"web_print":50,"nfc":40,"nfc_print":50,
          "pair":45,"printing":40,"printed":45,"error":60}

def report(kind):
    if kind not in ALLOWED:raise ValueError("Unknown activity")
    try:
        ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
        path=ROOT/("activity_"+kind+".json")
        now=time.time()
        try:
            old=json.loads(path.read_text(encoding="ascii"))
            # Avoid writing during repeated NFC link quality tests.
            if kind=="nfc" and now-float(old.get("at",0))<6:return
        except (OSError,ValueError,TypeError):
            pass
        temp=path.with_name(path.name+"."+str(os.getpid())+".tmp")
        temp.write_text(json.dumps({"at":now}),encoding="ascii")
        os.chmod(temp,0o600)
        temp.replace(path)
    except OSError:
        # UI telemetry must never make receipt printing fail.
        pass

def current(now=None):
    now=time.time() if now is None else now
    for kind in ("error","printing","printed","nfc_print","web_print","pair","nfc","web"):
        try:
            data=json.loads((ROOT/("activity_"+kind+".json")).read_text(encoding="ascii"))
            age=now-float(data["at"])
            if 0<=age<DURATION[kind]:return kind
        except (OSError,ValueError,TypeError,KeyError):
            pass
    return "idle"
