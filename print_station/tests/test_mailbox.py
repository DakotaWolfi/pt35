import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mailbox_protocol import pack,unpack
from mailbox_auth import sign,verify
import mailbox_host

KEY=b"K"*32
NOW=1794938400

def signed_packet(kind,ident,**fields):
    body={"v":"FMP1","t":kind,"id":ident,**fields}
    signature=sign(body,KEY,now=NOW)["a"]
    return pack(kind,ident,**fields,a=signature)

class MailboxProtocolTests(unittest.TestCase):
    def test_status_roundtrip(self):
        self.assertEqual(unpack(pack("status","12ab56ff"))["t"],"status")

    def test_print_roundtrip(self):
        packet=signed_packet("print","00aabbcc",name="PT35",message="AWOO")
        self.assertEqual(unpack(packet)["message"],"AWOO")

    def test_signature_required(self):
        with self.assertRaises(ValueError):
            unpack(pack("print","00aabbcc",name="PT35",message="AWOO"))

    def test_authentication_and_expiry(self):
        packet=unpack(signed_packet("print","00aabbcc",name="PT35",message="AWOO"))
        self.assertTrue(verify(packet,KEY,now=NOW))
        self.assertFalse(verify(packet,b"Z"*32,now=NOW))
        self.assertFalse(verify(packet,KEY,now=NOW+180))
        packet["message"]="BOOP"
        self.assertFalse(verify(packet,KEY,now=NOW))

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            pack("reply","00aabbcc",message="X"*256)

    @patch("mailbox_host.verify",return_value=False)
    @patch("mailbox_host.http_json")
    def test_unpaired_print_rejected(self,http,verify_mock):
        packet=signed_packet("print","00aabbcc",name="PT35",message="AWOO")
        result=unpack(mailbox_host.process(packet,"http://127.0.0.1:8767",KEY))
        self.assertFalse(result["ok"])
        http.assert_not_called()

    @patch("mailbox_host.verify",return_value=True)
    @patch("mailbox_host.http_json")
    def test_paired_print_uses_internal_api(self,http,verify_mock):
        http.return_value={"message":"Queued"}
        packet=signed_packet("print","00aabbcc",name="PT35",message="AWOO")
        result=unpack(mailbox_host.process(packet,"http://127.0.0.1:8767",KEY))
        self.assertTrue(result["ok"])
        self.assertEqual(http.call_count,1)
        self.assertEqual(http.call_args.kwargs["internal_key"],KEY)
        self.assertEqual(http.call_args.args[1]["message"],"AWOO")
        self.assertNotIn("challenge_code",http.call_args.args[1])

if __name__=="__main__":unittest.main()
