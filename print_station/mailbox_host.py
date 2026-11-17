#!/usr/bin/env python3
"""Print Pet ST25DV16K FTM host: opt-in I2C bridge to existing HTTP print API.

Never touches tag EEPROM, passwords, security session or GPO configuration.
Fails closed unless MB_MODE (static) was already enabled. No arbitrary raw
ESC/POS; NFC submits only short application-layer ticket fields and requires
the same physical six-digit challenge as browser print requests.
"""
import argparse
import json
import errno
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from smbus2 import SMBus, i2c_msg
from mailbox_protocol import pack, unpack

LOG=logging.getLogger("fmi.mailbox")
TAG=0x53
SYSTEM=0x57
MB_MODE=0x000D
CTRL=0x2006
LENGTH=0x2007
RAM=0x2008

def read(bus, slave, address, count=1):
    w=i2c_msg.write(slave, [address>>8,address&255])
    r=i2c_msg.read(slave,count)
    bus.i2c_rdwr(w,r)
    return bytes(r)

def write(bus, slave, address, data):
    bus.i2c_rdwr(i2c_msg.write(slave,[address>>8,address&255,*data]))

def setup(bus):
    mode=read(bus,SYSTEM,MB_MODE)[0]
    if not mode&1:
        raise RuntimeError("FTM MB_MODE is disabled in static settings. Not enabling a password-protected register automatically.")
    flags=read(bus,TAG,CTRL)[0]
    if not flags&1:
        write(bus,TAG,CTRL,[1])
    flags=read(bus,TAG,CTRL)[0]
    if not flags&1:
        raise RuntimeError("ST25DV mailbox could not be enabled")
    return flags

def receive(bus):
    flags=read(bus,TAG,CTRL)[0]
    if not flags&0x04:  # RF_PUT_MSG
        return None
    n=read(bus,TAG,LENGTH)[0]+1
    if not 1<=n<=112:
        # Still consume invalid RF input to free mailbox.
        read(bus,TAG,RAM,n)
        raise ValueError(f"RF mailbox message invalid length {n}")
    return read(bus,TAG,RAM,n)

def respond(bus,data,timeout=1.8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        flags=read(bus,TAG,CTRL)[0]
        if not flags & 0x06:  # neither HOST nor RF owns mailbox
            write(bus,TAG,RAM,data)
            return True
        time.sleep(.03)
    return False

def http_json(url, payload=None):
    req=Request(url,method="GET" if payload is None else "POST",
                data=None if payload is None else json.dumps(payload).encode("utf-8"),
                headers={} if payload is None else {"Content-Type":"application/json"})
    try:
        with urlopen(req,timeout=3) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail=json.load(exc)
            return {"error":str(detail.get("error","Rejected"))[:70]}
        except (ValueError,OSError):
            return {"error":"Print API rejected request"}
    except (URLError,TimeoutError,OSError) as exc:
        return {"error":"Local print API unavailable"}

def process(message,api):
    msg=unpack(message)
    uid=msg["id"]
    if msg["t"]=="status":
        status=http_json(api+"/api/status")
        return pack("reply",uid,ok="error" not in status,
                    ready=bool(status.get("printer_dhcp_ip")),
                    printing=bool(status.get("printing")),
                    queue=int(status.get("queue",0)) if isinstance(status.get("queue"),int) else 0,
                    printed=int(status.get("stats",{}).get("printed",0)))
    if msg["t"]=="print":
        # NFC is not authenticated by proximity; require same code as web.
        code=msg.get("code","")
        if not isinstance(code,str) or not (len(code)==6 and code.isdecimal()):
            return pack("reply",uid,ok=False,error="Print code required")
        status=http_json(api+"/api/status")
        if not status.get("challenge_enabled"):
            return pack("reply",uid,ok=False,error="Print challenge disabled")
        result=http_json(api+"/api/print",{"name":msg["name"],
                                          "message":msg["message"],
                                          "challenge_code":code})
        return pack("reply",uid,ok="error" not in result,
                    error=str(result.get("error",""))[:25],
                    message=str(result.get("message",""))[:20])
    return pack("reply",uid,ok=False,error="Unsupported request")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus",type=int,default=0)
    parser.add_argument("--api",default="http://127.0.0.1:8767")
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    seen={}
    offline=True
    failures=0
    while True:
        try:
            # Reopen on errors: do not keep reusing a failed I2C file descriptor.
            with SMBus(args.bus) as bus:
                if offline:
                    setup(bus)
                    LOG.info("ST25DV ready on I2C-%d at 0x%02x (FTM active)",args.bus,TAG)
                    offline=False
                    failures=0
                msg=receive(bus)
                if msg is not None:
                    try:
                        request=unpack(msg)
                        uid=request["id"]
                        now=time.monotonic()
                        seen={key:val for key,val in seen.items() if now-val[0]<90}
                        if uid in seen:
                            response=seen[uid][1] # retry must not reprint
                        else:
                            response=process(msg,args.api)
                            seen[uid]=(now,response)
                    except (ValueError,UnicodeError,KeyError,TypeError) as exc:
                        LOG.warning("Bad RF request: %s",exc)
                        response=None
                    if response and not respond(bus,response):
                        LOG.warning("PT35 did not clear mailbox in time; reply not sent")
                    if args.once: return
            time.sleep(.07)
        except (OSError, RuntimeError) as exc:
            failures += 1
            if not offline or failures == 1 or failures % 30 == 0:
                detail = " (EINVAL: I2C driver rejected transfer; not proof of missing tag)" if isinstance(exc,OSError) and exc.errno==errno.EINVAL else ""
                LOG.warning("ST25DV I2C unavailable (%s)%s; retrying",exc,detail)
            offline=True
            if args.once: raise
            time.sleep(min(5.0,0.2*2**min(failures,5)))

if __name__=="__main__":
    main()
