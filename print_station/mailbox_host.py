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
import random
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from smbus2 import SMBus, i2c_msg
from mailbox_protocol import pack, unpack
from mailbox_image import ImageReceiver
from mailbox_auth import read_key, verify, HOST_KEY

LOG=logging.getLogger("fmi.mailbox")
TAG=0x53
SYSTEM=0x57
MB_MODE=0x000D
CTRL=0x2006
LENGTH=0x2007
RAM=0x2008

def read(bus, slave, address, count=1):
    # ST25DV RF/I2C arbitration: RF busy makes the I2C device-select NACK.
    # All reads below are idempotent at the transport level; retry only a
    # bounded number of times, leaving RF a chance to finish each command.
    for attempt in range(5):
        try:
            w=i2c_msg.write(slave,[address>>8,address&255])
            r=i2c_msg.read(slave,count)
            bus.i2c_rdwr(w,r)
            return bytes(r)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL,errno.EREMOTEIO,errno.ENXIO) or attempt==4:
                raise
            time.sleep(random.uniform(.005,.015)*(attempt+1))

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

def http_json(url, payload=None, internal_key=None):
    req=Request(url,method="GET" if payload is None else "POST",
                data=None if payload is None else json.dumps(payload).encode("utf-8"),
                headers={} if payload is None else dict({"Content-Type":"application/json"}, **({"X-FMI-NFC-Internal":internal_key.hex()} if internal_key is not None else {})))
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

def process(message,api,key=None):
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
        if key is None or not verify(msg,key):
            return pack("reply",uid,ok=False,error="NFC not paired")
        # NFC is not authenticated by proximity; require same code as web.
        code=msg.get("code","")
        if not isinstance(code,str) or not (len(code)==6 and code.isdecimal()):
            return pack("reply",uid,ok=False,error="Print code required")
        result=http_json(api+"/api/print",{"name":msg["name"],
                                          "message":msg["message"],
                                          },internal_key=key)
        return pack("reply",uid,ok="error" not in result,
                    error=str(result.get("error",""))[:25],
                    message=str(result.get("message",""))[:20])
    return pack("reply",uid,ok=False,error="Unsupported request")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus",type=int,default=0)
    parser.add_argument("--api",default="http://127.0.0.1:8767")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--pair-key",default=str(HOST_KEY),help="Locally provisioned shared-key file")
    parser.add_argument("--poll-interval",type=float,default=0.20,
                        help="I2C mailbox polling period; avoid starving NFC RF commands")
    args=parser.parse_args()
    if not 0.10 <= args.poll_interval <= 5.0:
        parser.error("--poll-interval must be 0.10..5 seconds")
    logging.basicConfig(level=logging.INFO)
    try:
        key=read_key(args.pair_key)
        LOG.info("NFC paired-owner printing enabled")
    except (OSError,ValueError) as exc:
        key=None
        LOG.warning("NFC printing disabled: no pairing key: %s",exc)
    seen={}
    image_receiver=ImageReceiver(http_json,key)
    bus=None
    failures=0
    try:
        while True:
            try:
                if bus is None:
                    bus=SMBus(args.bus)
                    setup(bus)
                    LOG.info("ST25DV ready on I2C-%d at 0x%02x (FTM active)",args.bus,TAG)
                    failures=0
                msg=receive(bus)
                if msg is not None:
                    try:
                        request=unpack(msg)
                        uid=request["id"]
                        now=time.monotonic()
                        seen={key:val for key,val in seen.items() if now-val[0]<90}
                        if uid in seen:
                            response=seen[uid][1]
                        else:
                            response=(image_receiver.process(request,args.api)
                                      if request["t"] in ("img0","img1","img2")
                                      else process(msg,args.api,key))
                            seen[uid]=(now,response)
                    except (ValueError,UnicodeError,KeyError,TypeError) as exc:
                        LOG.warning("Bad RF request: %s",exc)
                        response=None
                    if response and not respond(bus,response):
                        LOG.warning("PT35 did not clear mailbox; reply not sent")
                    if args.once: return
                time.sleep(args.poll_interval)
            except (OSError,RuntimeError) as exc:
                failures+=1
                if failures==1 or failures%30==0:
                    detail=" (EINVAL: rejected I2C transfer, not proof tag vanished)" if isinstance(exc,OSError) and exc.errno==errno.EINVAL else ""
                    LOG.warning("ST25DV I2C unhealthy: %s%s; retrying",exc,detail)
                if bus is not None:
                    try:bus.close()
                    except OSError:pass
                    bus=None
                if args.once:raise
                time.sleep(min(5.0,0.2*2**min(failures,5)))
    finally:
        if bus is not None:
            bus.close()

if __name__=="__main__":
    main()
