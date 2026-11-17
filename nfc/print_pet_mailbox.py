#!/usr/bin/env python3
"""PT35 ↔ FMI Print Pet offline NFC fast-transfer mailbox client (experimental).

Use internal ST25R3916 ISO15693 reader on I2C bus 1, no Wi-Fi.
Requires confirmed external Print Pet ST25DV UID; use nfcv_scan.py to find it.
Explicit --confirm is needed for print actions. Never writes EEPROM.
Do not run at the same time as PT35 NFC scanner/GUI (shared reader).
"""
import argparse
import base64
import hashlib
import io
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"print_station"))
from mailbox_protocol import pack,unpack
from mailbox_auth import read_key,sign,PT35_KEY

from smbus2 import SMBus
from nfcv_dump import Reader, decode_response
from nfcv_scan import encode_vcd

class MailboxReader(Reader):
    def exchange_large(self,payload,timeout=.65):
        """Existing reader transport with enough FIFO data for a short FTM reply.

        Firmware-specific Manchester stream; requires hardware validation.
        """
        frame=encode_vcd(payload)
        if len(frame)>512:
            raise ValueError("Encoded NFC-V frame exceeds ST25R3916 512-byte FIFO")
        ticks=min(65535,max(1,int(timeout*13560000/4096)))
        self.update(0x12,setbits=1)
        self.wr(0x10,ticks>>8)
        self.wr(0x11,ticks&255)
        self.irqs()
        self.cmd(0xdb)
        self.send(0x80,*frame)
        bits=len(frame)*8
        self.wr(0x22,bits>>8)
        self.wr(0x23,bits&255)
        self.cmd(0xc5)
        if not self.await_irq(0x08,timeout+.1)&0x08:
            raise TimeoutError("NFC-V transmit timeout")
        irq=self.await_irq(0x10,timeout+.1)
        n1,n2=self.read(0x5e,2)
        count=n1|((n2&0xc0)<<2)
        if not count:
            raise TimeoutError(f"No NFC-V response (IRQ=0x{irq:02x})")
        if count>512:
            raise ValueError("Unexpected large RF FIFO frame")
        raw=self.read(0x9f,count)
        decoded=decode_response(raw,sizes=range(3,min(220,(len(raw)*8-5)//16)+1))
        if decoded[0]&1:
            raise RuntimeError("ST25DV RF error "+decoded.hex(" "))
        return decoded[1:]

def rf_command(reader,uid,opcode,*params):
    # Proprietary ST25DV commands: ISO15693 flags, opcode, ST manufacturer
    # ID 0x02, addressed UID in least-significant-byte-first wire order.
    frame=bytes([0x22,opcode,0x02])+bytes.fromhex(uid)[::-1]+bytes(params)
    return reader.exchange_large(frame)

def transact(reader,uid,packet,timeout=5):
    # 0xAD: read dynamic MB_CTRL_Dyn, register ID 0x0D (not I2C address).
    stop=time.monotonic()+timeout
    while time.monotonic()<stop:
        ctrl=rf_command(reader,uid,0xad,0x0d)
        if ctrl and (ctrl[0]&1) and not (ctrl[0]&0x06):
            break
        time.sleep(.09)
    else:
        raise TimeoutError("ST25DV mailbox not ready; check static MB_MODE and host service")

    # 0xAA: RF Write Message. Length argument is payload length minus 1.
    answer=rf_command(reader,uid,0xaa,len(packet)-1,*packet)
    if answer:
        raise RuntimeError("Unexpected write reply "+answer.hex(" "))

    # Host consumes message and replies via I2C. Wait for HOST_PUT_MSG.
    while time.monotonic()<stop:
        ctrl=rf_command(reader,uid,0xad,0x0d)
        if ctrl and (ctrl[0]&0x02):
            length=rf_command(reader,uid,0xab)[0]+1
            if not 1<=length<=112:
                raise ValueError("Unexpected reply length")
            # 0xAC: read message starting offset 0; count is length-1.
            reply=rf_command(reader,uid,0xac,0,length-1)
            if len(reply)!=length:
                raise ValueError(f"Truncated reply {len(reply)}/{length}")
            return unpack(reply)
        time.sleep(.09)
    raise TimeoutError("No host response; keep PT35 antenna over Print Pet tag")

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=("status","print","image"))
    ap.add_argument("--uid",required=True,help="EXTERNAL Print Pet ST25DV ISO15693 UID (16 hex chars)")
    ap.add_argument("--bus",type=int,default=1)
    ap.add_argument("--name",default="PT35")
    ap.add_argument("--message",default="AWOO from PT35")
    ap.add_argument("--key-file",type=Path,default=PT35_KEY,help="Paired NFC owner key file")
    ap.add_argument("--confirm",action="store_true",help="Required for physical printing")
    ap.add_argument("--image",type=Path,help="Image file for NFC transfer (PNG/JPEG)")
    args=ap.parse_args()
    uid=args.uid.upper()
    if len(uid)!=16 or any(c not in "0123456789ABCDEF" for c in uid):
        ap.error("--uid must contain exactly 16 hexadecimal digits")
    if args.action in ("print","image") and not args.confirm:
        ap.error("Printing requires explicit --confirm")
    if args.action=="image" and not args.image:
        ap.error("--image PATH is required for image printing")
    key=None
    if args.action in ("print","image"):
        try:key=read_key(args.key_file)
        except (OSError,ValueError) as exc:ap.error("NFC owner pairing unavailable: "+str(exc))
    ident=secrets.token_hex(4)
    if args.action=="print":
        signed=sign({"v":"FMP1","t":"print","id":ident,"name":args.name,"message":args.message},key)
        payload=pack("print",ident,name=args.name,message=args.message,a=signed["a"])
    else:
        payload=pack("status",ident) if args.action=="status" else None
    with SMBus(args.bus) as bus:
        reader=MailboxReader(bus)
        try:
            reader.initialize()
            print("Hold PT35's NFC reader at the Print Pet tag throughout exchange.",flush=True)
            if args.action=="image":
                from PIL import Image, ImageOps
                with Image.open(args.image.expanduser()) as im:
                    im=ImageOps.exif_transpose(im)
                    im.thumbnail((160,120), Image.Resampling.LANCZOS)
                    bw=ImageOps.autocontrast(im.convert("L")).point(lambda x:255 if x>=150 else 0).convert("1")
                    out=io.BytesIO()
                    bw.save(out,format="PNG",optimize=True)
                png=out.getvalue()
                if len(png)>7680:
                    raise ValueError("Compressed image exceeds 7.5 KiB NFC limit; crop or simplify it")
                sid=secrets.token_hex(4)
                def ask(kind,**values):
                    reqid=secrets.token_hex(4)
                    fields=dict(s=sid,**values)
                    if kind=="img0":
                        unsigned={"v":"FMP1","t":kind,"id":reqid,**fields}
                        fields["a"]=sign(unsigned,key)["a"]
                    req=pack(kind,reqid,**fields)
                    result=transact(reader,uid,req,timeout=8)
                    if not result.get("ok"):
                        raise RuntimeError("Print Pet rejected transfer: "+str(result))
                    return result
                reply=ask("img0",n=len(png),h=hashlib.sha256(png).hexdigest()[:16])
                step=30
                for idx,start in enumerate(range(0,len(png),step)):
                    segment=base64.b64encode(png[start:start+step]).decode("ascii")
                    reply=ask("img1",i=idx,d=segment)
                    print(f"Image NFC {min(start+step,len(png))}/{len(png)} bytes",flush=True)
                reply=ask("img2")
            else:
                reply=transact(reader,uid,payload)
            print("Print Pet:",reply,flush=True)
            return 0 if reply.get("ok") else 2
        finally:
            try:reader.shutdown()
            except OSError:pass

if __name__=="__main__":
    raise SystemExit(main())
