#!/usr/bin/env python3
"""PT35 ↔ FMI Print Pet offline NFC fast-transfer mailbox client (experimental).

Use internal ST25R3916 ISO15693 reader on I2C bus 1, no Wi-Fi.
Requires confirmed external Print Pet ST25DV UID; use nfcv_scan.py to find it.
Explicit --confirm is needed for print actions. Never writes EEPROM.
Do not run at the same time as PT35 NFC scanner/GUI (shared reader).
"""
import argparse
import os
import base64
import hashlib
import io
from collections import deque
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
    ap.add_argument("action",choices=("status","print","image","pair","linktest"))
    ap.add_argument("--uid",required=True,help="EXTERNAL Print Pet ST25DV ISO15693 UID (16 hex chars)")
    ap.add_argument("--bus",type=int,default=1)
    ap.add_argument("--name",default="PT35")
    ap.add_argument("--message",default="AWOO from PT35")
    ap.add_argument("--key-file",type=Path,default=PT35_KEY,help="Paired NFC owner key file")
    ap.add_argument("--confirm",action="store_true",help="Required for physical printing")
    ap.add_argument("--image",type=Path,help="Image file for NFC transfer (PNG/JPEG)")
    ap.add_argument("--samples",type=int,default=40,
                    help="Number of status round trips for RF link test (1-500)")
    ap.add_argument("--interval",type=float,default=.15,
                    help="Pause between link-test samples (0-5 seconds)")
    args=ap.parse_args()
    if not 1 <= args.samples <= 500:ap.error("--samples must be 1-500")
    if not 0 <= args.interval <= 5:ap.error("--interval must be 0-5 seconds")
    uid=args.uid.upper()
    if len(uid)!=16 or any(c not in "0123456789ABCDEF" for c in uid):
        ap.error("--uid must contain exactly 16 hexadecimal digits")
    if args.action in ("print","image") and not args.confirm:
        ap.error("Printing requires explicit --confirm")
    if args.action=="pair" and not args.confirm:
        ap.error("Pairing requires explicit --confirm; first arm via SSH on Print Pet")
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
            if args.action=="linktest":
                # No printer commands, no key, and no modification to the tag.
                # A test transaction is the same status exchange the GUI uses.
                # It measures APPLICATION-LAYER quality, not RF SNR/RSSI.
                results=deque(maxlen=10)
                start=time.monotonic()
                successes=0
                errors=0
                payload_bytes=0
                elapsed_success=0.0
                for attempt in range(1,args.samples+1):
                    request=pack("status",secrets.token_hex(4))
                    t0=time.monotonic()
                    try:
                        response=transact(reader,uid,request,timeout=5)
                        elapsed=time.monotonic()-t0
                        if not response.get("ok"):
                            raise RuntimeError(str(response.get("error","status failed")))
                        successes+=1
                        results.append(True)
                        # Includes request + response payload; excludes ISO15693 overhead.
                        payload_bytes+=len(request)+len(
                            pack("reply",response["id"],
                                 **{k:v for k,v in response.items()
                                    if k not in ("v","t","id")}))
                        elapsed_success+=elapsed
                        verdict="OK"
                    except (OSError,ValueError,TimeoutError,RuntimeError,IndexError) as exc:
                        elapsed=time.monotonic()-t0
                        errors+=1
                        results.append(False)
                        verdict="FAIL "+str(exc)[:80]
                    total=time.monotonic()-start
                    quality=int(round(100*sum(results)/len(results)))
                    print(
                        f"LINK {attempt}/{args.samples} {verdict} "
                        f"RTT={elapsed*1000:.0f}ms "
                        f"quality10={quality}% "
                        f"success={successes}/{attempt} "
                        f"payload={payload_bytes/max(total,0.001):.1f}B/s",
                        flush=True,
                    )
                    if attempt<args.samples:time.sleep(args.interval)
                total=time.monotonic()-start
                print(f"SUMMARY success={successes}/{args.samples} "
                      f"rate={100*successes/args.samples:.1f}% "
                      f"avg_success_rtt={1000*elapsed_success/max(successes,1):.0f}ms "
                      f"payload={payload_bytes/max(total,0.001):.1f}B/s "
                      f"failures={errors}",flush=True)
                return 0 if successes==args.samples else 2
            if args.action=="pair":
                from cryptography.hazmat.primitives.asymmetric import x25519
                from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
                from cryptography.hazmat.primitives.kdf.hkdf import HKDF
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                private=x25519.X25519PrivateKey.generate()
                pub=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
                pair_id=secrets.token_hex(4)
                result=transact(reader,uid,pack("pair",pair_id,
                    p=base64.b64encode(pub).decode("ascii")))
                if not result.get("p"):
                    raise RuntimeError("Print Pet pairing rejected: "+str(result))
                server_pub=base64.b64decode(result["p"],validate=True)
                if len(server_pub)!=32:
                    raise ValueError("Invalid server X25519 public key")
                peer=x25519.X25519PublicKey.from_public_bytes(server_pub)
                shared=private.exchange(peer)
                nonce_salt=bytes.fromhex(pair_id)
                wrapping_key=HKDF(algorithm=hashes.SHA256(),length=32,
                                  salt=nonce_salt,
                                  info=b"FMI Print Pet NFC pairing v2").derive(shared)
                result=transact(reader,uid,pack("pair-key",secrets.token_hex(4),s=pair_id))
                if not result.get("c"):
                    raise RuntimeError("Print Pet secret transfer rejected: "+str(result))
                ciphertext=base64.b64decode(result["c"],validate=True)
                nonce=hashlib.sha256(b"FMI-NFC-pair"+nonce_salt).digest()[:12]
                keydata=AESGCM(wrapping_key).decrypt(nonce,ciphertext,nonce_salt)
                if len(keydata)!=32:
                    raise ValueError("Incorrect decrypted pairing key length")
                session=pair_id
                target=args.key_file.expanduser()
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                os.chmod(target.parent,0o700)
                temporary=target.with_name(target.name+".pending")
                fd=os.open(str(temporary),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                with os.fdopen(fd,"w",encoding="ascii") as stream:
                    stream.write(keydata.hex()+chr(10))
                    stream.flush()
                    os.fsync(stream.fileno())
                confirmid=secrets.token_hex(4)
                fields={"v":"FMP1","t":"pair-done","id":confirmid,"s":session}
                signed=sign(fields,keydata)
                proof=pack("pair-done",confirmid,s=session,a=signed["a"])
                acknowledged=transact(reader,uid,proof,timeout=10)
                if not acknowledged.get("ok"):
                    raise RuntimeError("Pair confirmation rejected; key not activated")
                os.replace(temporary,target)
                print("PT35 successfully paired; secret stored locally",flush=True)
                reply=acknowledged
            elif args.action=="image":
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
