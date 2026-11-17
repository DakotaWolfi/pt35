"""FMI Print Pet NFC mailbox protocol v1.

Transport-independent payload encoding shared with PT35. ST25DV FTM is a
single 256-byte half-duplex mailbox. This format is *not authentication*:
any nearby ISO15693 reader with mailbox support may send a command.
"""
import json
import re

MAGIC="FMP1"
MAX_BYTES=112
MAX_TEXT=40
ID=re.compile(r"^[0-9a-f]{8}$")

def pack(kind, ident, **fields):
    if kind not in ("status","print","reply","image-start","image-part","image-finish"):
        raise ValueError("Unknown mailbox command")
    if not ID.fullmatch(ident):
        raise ValueError("Request ID must be eight lowercase hex digits")
    msg={"v":MAGIC,"t":kind,"id":ident}
    msg.update(fields)
    encoded=json.dumps(msg,separators=(",",":"),ensure_ascii=True).encode("ascii")
    if len(encoded)>MAX_BYTES:
        raise ValueError("Mailbox message exceeds bounded protocol size")
    return encoded

def unpack(raw):
    if not isinstance(raw,(bytes,bytearray)) or len(raw)>MAX_BYTES:
        raise ValueError("Invalid mailbox length")
    msg=json.loads(raw.decode("ascii"))
    if not isinstance(msg,dict) or msg.get("v")!=MAGIC:
        raise ValueError("Unknown mailbox protocol")
    if not ID.fullmatch(str(msg.get("id",""))):
        raise ValueError("Missing request ID")
    if msg.get("t") not in ("status","print","reply","image-start","image-part","image-finish"):
        raise ValueError("Unknown command")
    if msg["t"]=="print":
        if set(msg) - {"v","t","id","name","message","code"}:
            raise ValueError("Unsupported fields in print command")
        for key,limit in (("name",40),("message",MAX_TEXT)):
            val=msg.get(key,"")
            if not isinstance(val,str) or not 1<=len(val)<=limit or any(ord(c)<32 or ord(c)>126 for c in val):
                raise ValueError("Print fields must be short printable ASCII")
    if msg["t"]=="print" and not (isinstance(msg.get("code"),str) and len(msg["code"])==6 and msg["code"].isascii() and msg["code"].isdecimal()):
        raise ValueError("Print requires six-digit code")
    if msg["t"] in ("image-start","image-part","image-finish"):
        if not ID.fullmatch(str(msg.get("sid",""))):
            raise ValueError("Invalid image session")
        if msg["t"]=="image-start":
            if not (isinstance(msg.get("length"),int) and 1<=msg["length"]<=8192):
                raise ValueError("Image size outside 8 KiB limit")
            if not (isinstance(msg.get("sha"),str) and re.fullmatch(r"[0-9a-f]{64}",msg["sha"])):
                raise ValueError("Invalid image hash")
            if not (isinstance(msg.get("code"),str) and re.fullmatch(r"[0-9]{6}",msg["code"])):
                raise ValueError("Physical print code required")
            if not (isinstance(msg.get("title"),str) and 1<=len(msg["title"])<=24):
                raise ValueError("Image title required")
        elif msg["t"]=="image-part":
            if not (isinstance(msg.get("seq"),int) and 0<=msg["seq"]<=255):
                raise ValueError("Invalid image chunk number")
            if not (isinstance(msg.get("data"),str) and 1<=len(msg["data"])<=56 and
                    re.fullmatch(r"[A-Za-z0-9+/]*={0,2}",msg["data"])):
                raise ValueError("Invalid base64 image data")
    return msg
