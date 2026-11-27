"""Offline paired NFC picture protocol tests; no hardware needed."""
import base64
import hashlib
import io
import unittest
from unittest.mock import Mock
from PIL import Image

from mailbox_protocol import pack, unpack
from mailbox_image import ImageReceiver
from mailbox_auth import sign

KEY=b"K"*32

class OfflinePictureTests(unittest.TestCase):
    def image(self):
        im=Image.new("1",(32,24),"white")
        out=io.BytesIO()
        im.save(out,format="PNG")
        return out.getvalue()

    def test_image_transfer_to_custom_receipt(self):
        calls=[]
        def fake_http(url,payload=None,internal_key=None):
            calls.append((url,payload,internal_key))
            return {"job_id":"test-queue"}
        host=ImageReceiver(fake_http,KEY)
        sid="aabbccdd"
        content=self.image()
        def send(kind,number,**kw):
            ident=f"{number:08x}"
            if kind=="img0":
                body={"v":"FMP1","t":kind,"id":ident,"s":sid,**kw}
                kw["a"]=sign(body,KEY)["a"]
            msg=unpack(pack(kind,ident,s=sid,**kw))
            return unpack(host.process(msg,"http://127.0.0.1:8767"))
        self.assertTrue(send("img0",1,n=len(content),
                             h=hashlib.sha256(content).hexdigest()[:16])["ok"])
        for i,start in enumerate(range(0,len(content),30)):
            data=base64.b64encode(content[start:start+30]).decode("ascii")
            self.assertTrue(send("img1",i+2,i=i,d=data)["ok"])
        self.assertTrue(send("img2",100)["ok"])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][2],KEY)
        self.assertNotIn("challenge_code",calls[0][1])
        self.assertTrue(send("img2",101)["ok"])
        self.assertEqual(len(calls),1)

    def test_hash_mismatch_does_not_print(self):
        http=Mock(return_value={"message":"queued"})
        host=ImageReceiver(http,KEY)
        session="abcd1234"
        start={"v":"FMP1","t":"img0","id":"11111111","s":session,"n":3,"h":"0"*16}
        start["a"]=sign(start,KEY)["a"]
        host.process(unpack(pack("img0","11111111",s=session,n=3,h="0"*16,a=start["a"])),"http://local")
        host.process(unpack(pack("img1","11111112",s=session,i=0,d=base64.b64encode(b"XYZ").decode())),"http://local")
        result=unpack(host.process(unpack(pack("img2","11111113",s=session)),"http://local"))
        self.assertFalse(result["ok"])
        http.assert_not_called()

    def test_unpaired_start_does_not_accept(self):
        host=ImageReceiver(Mock(),KEY)
        msg=unpack(pack("img0","12345678",s="abcd1234",n=100,h="0"*16,a="0"*16))
        self.assertFalse(unpack(host.process(msg,"http://local"))["ok"])

    def test_bad_chunk_rejected(self):
        with self.assertRaises(ValueError):
            unpack(pack("img1","01234567",s="abcd1234",i=0,d="bad%%%"))

if __name__=="__main__":unittest.main()
