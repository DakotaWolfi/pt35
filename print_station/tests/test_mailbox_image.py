"""Offline NFC picture chunk tests; no physical hardware needed."""
import base64
import hashlib
import io
import unittest
from unittest.mock import Mock
from PIL import Image

from mailbox_protocol import pack, unpack
from mailbox_image import ImageReceiver

class OfflinePictureTests(unittest.TestCase):
    def image(self):
        im=Image.new("1",(32,24),"white")
        out=io.BytesIO()
        im.save(out,format="PNG")
        return out.getvalue()

    def test_image_transfer_to_custom_receipt(self):
        calls=[]
        def fake_http(url,payload=None):
            calls.append((url,payload))
            if url.endswith("/api/status"):return {"challenge_enabled":True}
            return {"job_id":"test-queue"}
        host=ImageReceiver(fake_http)
        sid="aabbccdd"
        content=self.image()
        def send(kind,number,**kw):
            msg=unpack(pack(kind,f"{number:08x}",s=sid,**kw))
            return unpack(host.process(msg,"http://127.0.0.1:8767"))
        self.assertTrue(send("img0",1,n=len(content),
                             h=hashlib.sha256(content).hexdigest()[:16],c="123456")["ok"])
        chunks=[content[i:i+30] for i in range(0,len(content),30)]
        for i,chunk in enumerate(chunks):
            data=base64.b64encode(chunk).decode("ascii")
            self.assertTrue(send("img1",i+2,i=i,d=data)["ok"])
        done=send("img2",100)
        self.assertTrue(done["ok"])
        self.assertEqual(len([c for c in calls if c[0].endswith("/api/custom")]),1)
        self.assertTrue(send("img2",101)["ok"])
        self.assertEqual(len([c for c in calls if c[0].endswith("/api/custom")]),1)

    def test_hash_mismatch_does_not_print(self):
        http=Mock(return_value={"challenge_enabled":True})
        host=ImageReceiver(http)
        req=unpack(pack("img0","11111111",s="abcd1234",n=3,h="0"*16,c="123456"))
        host.process(req,"http://local")
        req=unpack(pack("img1","11111112",s="abcd1234",i=0,d=base64.b64encode(b"XYZ").decode()))
        host.process(req,"http://local")
        resp=unpack(host.process(unpack(pack("img2","11111113",s="abcd1234")),"http://local"))
        self.assertFalse(resp["ok"])
        self.assertFalse(any("/api/custom" in call.args[0] for call in http.call_args_list))

    def test_bad_chunk_rejected(self):
        with self.assertRaises(ValueError):
            unpack(pack("img1","01234567",s="abcd1234",i=0,d="bad%%%"))

if __name__=="__main__":unittest.main()
