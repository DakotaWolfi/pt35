"""Test SSH-armed single-use encrypted owner pairing without radio hardware."""
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import nfc_pairing
from mailbox_auth import sign,read_key
from mailbox_protocol import pack,unpack

class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for name,value in (("PRIVATE",root),("ARM",root/"arm.json"),
                           ("HOST_KEY",root/"nfc_pairing.key")):
            patcher=patch.object(nfc_pairing,name,value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def exchange(self):
        client=x25519.X25519PrivateKey.generate()
        public=client.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        pair_id="12345678"
        request=unpack(pack("pair",pair_id,p=base64.b64encode(public).decode("ascii")))
        fields,update=nfc_pairing.handle_pair(request)
        unpack(pack("reply",pair_id,**fields))
        nfc_pairing.issue_completed(update)
        result=nfc_pairing.handle_pair_key({"t":"pair-key","s":pair_id})
        unpack(pack("reply","87654321",**result))
        peer=x25519.X25519PublicKey.from_public_bytes(base64.b64decode(fields["p"]))
        shared=client.exchange(peer)
        salt=bytes.fromhex(pair_id)
        wrap=HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,
                  info=b"FMI Print Pet NFC pairing v2").derive(shared)
        nonce=hashlib.sha256(b"FMI-NFC-pair"+salt).digest()[:12]
        secret=AESGCM(wrap).decrypt(nonce,base64.b64decode(result["c"]),salt)
        return pair_id,secret

    def test_encrypted_pair_and_one_use_confirmation(self):
        nfc_pairing.arm(90)
        pair_id,secret=self.exchange()
        self.assertEqual(len(secret),32)
        self.assertEqual(secret,bytes.fromhex(nfc_pairing.state()["key"]))
        second,update=nfc_pairing.handle_pair({"t":"pair","id":"aabbccdd","p":"A"*43+"="})
        self.assertFalse(second["ok"])
        self.assertIsNone(update)
        done=sign({"v":"FMP1","t":"pair-done","id":"abcdef01","s":pair_id},secret)
        self.assertTrue(nfc_pairing.handle_done(done)["ok"])
        self.assertEqual(read_key(nfc_pairing.HOST_KEY),secret)
        self.assertFalse(nfc_pairing.state())
        self.assertTrue(nfc_pairing.paired())

    def test_unarmed_refuses_pair(self):
        result,update=nfc_pairing.handle_pair({"t":"pair","id":"12345678","p":"A"*43+"="})
        self.assertFalse(result["ok"])
        self.assertIsNone(update)

    def test_unpaired_cannot_confirm(self):
        nfc_pairing.arm(90)
        pair_id,secret=self.exchange()
        done=sign({"v":"FMP1","t":"pair-done","id":"abcdef01","s":pair_id},b"X"*32)
        self.assertFalse(nfc_pairing.handle_done(done)["ok"])
        self.assertFalse(nfc_pairing.paired())

if __name__=="__main__":unittest.main()
