"""Bounded image-upload staging for offline NFC mailbox Print Pet requests.

One active image per host process; not persisted. Printing requires physical
challenge even if the normal web service challenge setting is disabled.
"""
import base64
import hashlib
import io
import time

from mailbox_protocol import pack
from mailbox_host import http_json

class ImageReceiver:
    def __init__(self):
        self.active=None
        self.completed={}

    def process(self,request,api):
        typ=request["t"]; sid=request["sid"]; rid=request["id"]
        now=time.monotonic()
        self.completed={k:v for k,v in self.completed.items() if now-v[0]<180}
        if typ=="image-start":
            status=http_json(api+"/api/status")
            if not status.get("challenge_enabled"):
                return pack("reply",rid,ok=False,error="Print challenge disabled")
            current=self.active
            if current and current["sid"]==sid:
                return pack("reply",rid,ok=True,seq=current["seq"])
            self.active={"sid":sid,"title":request["title"],"code":request["code"],
                         "length":request["length"],"sha":request["sha"],
                         "data":bytearray(),"seq":0,"updated":now}
            return pack("reply",rid,ok=True,seq=0)
        if typ=="image-finish" and sid in self.completed:
            return pack("reply",rid,ok=True,message="Already submitted")
        state=self.active
        if not state or state["sid"]!=sid or now-state["updated"]>120:
            self.active=None
            return pack("reply",rid,ok=False,error="Image session expired")
        state["updated"]=now
        if typ=="image-part":
            seq=request["seq"]
            if seq==state["seq"]-1:
                return pack("reply",rid,ok=True,seq=state["seq"])
            if seq!=state["seq"]:
                return pack("reply",rid,ok=False,error="Unexpected chunk",seq=state["seq"])
            try:
                chunk=base64.b64decode(request["data"],validate=True)
            except (ValueError,base64.binascii.Error):
                return pack("reply",rid,ok=False,error="Invalid image chunk")
            if not chunk or len(state["data"])+len(chunk)>state["length"] or state["seq"]>=256:
                return pack("reply",rid,ok=False,error="Image size exceeded")
            state["data"].extend(chunk)
            state["seq"]+=1
            return pack("reply",rid,ok=True,seq=state["seq"])
        data=bytes(state["data"])
        if len(data)!=state["length"] or hashlib.sha256(data).hexdigest()!=state["sha"]:
            return pack("reply",rid,ok=False,error="Image hash mismatch")
        # Validate image server-side before invoking the local API.
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                if im.format!="PNG" or im.width>384 or im.height>240 or im.width<1 or im.height<1:
                    raise ValueError("Invalid PNG size")
                im.verify()
        except (OSError,ValueError,ImportError):
            return pack("reply",rid,ok=False,error="Invalid PNG")
        result=http_json(api+"/api/custom",{
            "title":state["title"],
            "lines":[{"type":"image","image":base64.b64encode(data).decode("ascii")}],
            "challenge_code":state["code"],
        })
        if "error" in result:
            return pack("reply",rid,ok=False,error=str(result["error"])[:25])
        self.completed[sid]=(now,result)
        self.active=None
        return pack("reply",rid,ok=True,message="Image queued")
