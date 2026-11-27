"""Bounded image-upload staging for offline NFC mailbox Print Pet requests.

One active image per host process; not persisted. Owner HMAC signing is
required for printing; no web visitor code is needed.
"""
import base64
import hashlib
import io
import time

from mailbox_protocol import pack
from mailbox_auth import verify

class ImageReceiver:
    def __init__(self,http_json,key):
        self.http_json=http_json
        self.key=key
        self.active=None
        self.completed={}

    def process(self,request,api):
        typ=request["t"]; sid=request["s"]; rid=request["id"]
        now=time.monotonic()
        self.completed={k:v for k,v in self.completed.items() if now-v[0]<180}
        if typ=="img0":
            if self.key is None or not verify(request,self.key):
                return pack("reply",rid,ok=False,error="NFC not paired")
            current=self.active
            if current and current["sid"]==sid:
                return pack("reply",rid,ok=True,seq=current["seq"])
            self.active={"sid":sid,"title":"PT35 NFC IMAGE",
                         "length":request["n"],"sha":request["h"],
                         "data":bytearray(),"seq":0,"updated":now}
            return pack("reply",rid,ok=True,seq=0)
        if typ=="img2" and sid in self.completed:
            return pack("reply",rid,ok=True,message="Already submitted")
        state=self.active
        if not state or state["sid"]!=sid or now-state["updated"]>120:
            self.active=None
            return pack("reply",rid,ok=False,error="Image session expired")
        state["updated"]=now
        if typ=="img1":
            seq=request["i"]
            if seq==state["seq"]-1:
                return pack("reply",rid,ok=True,seq=state["seq"])
            if seq!=state["seq"]:
                return pack("reply",rid,ok=False,error="Unexpected chunk",seq=state["seq"])
            try:
                chunk=base64.b64decode(request["d"],validate=True)
            except (ValueError,base64.binascii.Error):
                return pack("reply",rid,ok=False,error="Invalid image chunk")
            if not chunk or len(state["data"])+len(chunk)>state["length"] or state["seq"]>=256:
                return pack("reply",rid,ok=False,error="Image size exceeded")
            state["data"].extend(chunk)
            state["seq"]+=1
            return pack("reply",rid,ok=True,seq=state["seq"])
        data=bytes(state["data"])
        if len(data)!=state["length"] or hashlib.sha256(data).hexdigest()[:16]!=state["sha"]:
            return pack("reply",rid,ok=False,error="Image hash mismatch")
        # A low-resolution NFC thumbnail is deliberately upscaled by Pillow
        # only AFTER the full, authenticated and hash-checked transfer.
        # This preserves print width without sending larger RF packets.
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                if im.format!="PNG" or not 1<=im.width<=384 or not 1<=im.height<=240:
                    raise ValueError("Invalid NFC PNG dimensions")
                im.verify()
            with Image.open(io.BytesIO(data)) as im:
                bw=im.convert("1")
                factor=min(384/bw.width,240/bw.height)
                if factor>1:
                    bw=bw.resize((min(384,max(1,round(bw.width*factor))),
                                  min(240,max(1,round(bw.height*factor)))),
                                 Image.Resampling.NEAREST)
                out=io.BytesIO()
                bw.save(out,format="PNG",optimize=True)
                printable=out.getvalue()
                if len(printable)>32*1024:
                    raise ValueError("PNG exceeds receipt limits")
        except (OSError,ValueError,ImportError):
            return pack("reply",rid,ok=False,error="Invalid PNG")
        result=self.http_json(api+"/api/custom",{
            "title":state["title"],
            "lines":[{"type":"image","image":base64.b64encode(printable).decode("ascii")}],
            
        },internal_key=self.key)
        if "error" in result:
            return pack("reply",rid,ok=False,error=str(result["error"])[:25])
        self.completed[sid]=(now,result)
        self.active=None
        return pack("reply",rid,ok=True,message="Image queued")
