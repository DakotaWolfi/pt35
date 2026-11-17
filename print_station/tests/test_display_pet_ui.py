"""Exercise monochrome Print Pet layouts without touching the SPI panel."""
import sys
import types
import unittest
from unittest.mock import patch

with patch.dict(sys.modules,{"epaper_test":types.SimpleNamespace(Epaper=object)}):
    from display_epaper import render

BASE={"printer_ok":True,"printing":False,"activity":"idle",
      "guest_url":"","challenge_code":"","queue":0,"printed":0,
      "nfc_paired":False,"pair_armed":False,"dry_run":False}

class DisplayLayoutTests(unittest.TestCase):
    def test_monochrome_size_and_rotation(self):
        img=render(BASE,rotation=0)
        self.assertEqual(img.size,(250,122))
        self.assertEqual(img.mode,"1")
        rotated=render(BASE,rotation=180)
        self.assertEqual(rotated.size,(250,122))
        self.assertEqual(rotated.tobytes(),img.rotate(180).tobytes())

    def test_pet_reacts_to_activity(self):
        idle=render(BASE,rotation=0).tobytes()
        for action in ("web","nfc","pair","web_print","nfc_print",
                       "printing","printed","error"):
            with self.subTest(action=action):
                state=dict(BASE,activity=action)
                self.assertNotEqual(idle,render(state,rotation=0).tobytes())

    def test_web_code_renders_without_nfc_pairing(self):
        plain=render(BASE,rotation=0).tobytes()
        with_code=render(dict(BASE,challenge_code="123456"),rotation=0).tobytes()
        self.assertNotEqual(plain,with_code)

if __name__=="__main__":unittest.main()
