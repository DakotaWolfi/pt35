"""Tests for SSH-armed, single-use NFC owner pairing without hardware."""
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import nfc_pairing
from mailbox_auth import sign,read_key
from mailbox_protocol import pack,unpack

class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.patchers=[
            patch.object(nfc_pairing,"PRIVATE",root),
            patch.object(nfc_pairing,"ARM",root/"arm.json"),
            patch.object(nfc_pairing,"HOST_KEY",root/"nfc_pairing.key")
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_single_use_pair_and_confirmation(self):
        nfc_pairing.arm(90)
        pair={"t":"pair","id":"12345678"}
        fields,update=nfc_pairing.handle_pair(pair)
        # Exactly fits 112-byte FMP1 mailbox message.
        unpack(pack("reply",pair["id"],**fields))
        provisional=base64.b64decode(fields["k"],validate=True)
        self.assertEqual(len(provisional),32)
        nfc_pairing.issue_completed(update)
        second,update2=nfc_pairing.handle_pair(pair)
        self.assertFalse(second["ok"])
        self.assertIsNone(update2)
        done={"v":"FMP1","t":"pair-done","id":"abcdef01","s":fields["s"]}
        done=sign(done,provisional)
        self.assertTrue(nfc_pairing.handle_done(done)["ok"])
        self.assertEqual(read_key(nfc_pairing.HOST_KEY),provisional)
        self.assertFalse(nfc_pairing.state())
        self.assertTrue(nfc_pairing.paired())
        failed,_=nfc_pairing.handle_pair(pair)
        self.assertFalse(failed["ok"])

    def test_unarmed_pair_denied(self):
        result,update=nfc_pairing.handle_pair({"t":"pair","id":"12345678"})
        self.assertFalse(result["ok"])
        self.assertIsNone(update)

    def test_wrong_key_cannot_confirm(self):
        nfc_pairing.arm(90)
        fields,update=nfc_pairing.handle_pair({"t":"pair","id":"12345678"})
        nfc_pairing.issue_completed(update)
        done={"v":"FMP1","t":"pair-done","id":"abcdef01","s":fields["s"]}
        forged=sign(done,b"Z"*32)
        self.assertFalse(nfc_pairing.handle_done(forged)["ok"])
        self.assertFalse(nfc_pairing.paired())

if __name__=="__main__":
    unittest.main()
