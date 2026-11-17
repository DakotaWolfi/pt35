import unittest
import time
import tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import challenge

class ChallengeTests(unittest.TestCase):
    def setUp(self):
        self.key=bytes.fromhex("ab"*32)

    def test_current_and_previous_codes(self):
        now=1800000022
        code=challenge.current_code(self.key,now)
        self.assertEqual(len(code),6)
        self.assertTrue(challenge.check_code(self.key,code,now))
        self.assertTrue(challenge.check_code(self.key,challenge.current_code(self.key,now-600),now))
        self.assertFalse(challenge.check_code(self.key,"00000",now))
        self.assertFalse(challenge.check_code(self.key,"12345a",now))
        self.assertFalse(challenge.check_code(self.key,code,now+1200))

    def test_guest_code_rotates_and_persists(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"guest-code.json"
            challenge.init_print_code(path)
            first=challenge.display_code(self.key,path)
            self.assertTrue(challenge.check_display_code(self.key,first,path))
            second=challenge.rotate_display_code(self.key,path)
            self.assertNotEqual(first,second)
            self.assertFalse(challenge.check_display_code(self.key,first,path))
            self.assertTrue(challenge.check_display_code(self.key,second,path))
            self.assertEqual(challenge.display_code(self.key,path),second)
            challenge.init_print_code(path)
            self.assertEqual(challenge.display_code(self.key,path),second)

    def test_owner_pass_is_distinct_and_expires(self):
        now=1800000022
        token=challenge.pass_token(self.key,now)
        self.assertEqual(len(token),10)
        self.assertTrue(challenge.check_pass(self.key,token,now))
        self.assertFalse(challenge.check_pass(self.key,token,now+600))
        self.assertFalse(challenge.check_code(self.key,token,now))

if __name__=="__main__": unittest.main()
