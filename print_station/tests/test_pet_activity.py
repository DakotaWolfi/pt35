"""Activity priority and TTL tests (no NFC, display, or printer hardware)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import pet_activity

class ActivityTests(unittest.TestCase):
    def test_recent_events_and_priority(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(pet_activity,"ROOT",root):
                with patch.object(pet_activity.time,"time",return_value=1000.0):
                    self.assertEqual(pet_activity.current(),"idle")
                    pet_activity.report("web")
                    self.assertEqual(pet_activity.current(),"web")
                    pet_activity.report("nfc")
                    self.assertEqual(pet_activity.current(),"nfc")
                    pet_activity.report("nfc_print")
                    self.assertEqual(pet_activity.current(),"nfc_print")
                self.assertEqual(pet_activity.current(now=1060),"idle")

    def test_private_event_files_do_not_store_user_data(self):
        with TemporaryDirectory() as tmp:
            with patch.object(pet_activity,"ROOT",Path(tmp)):
                pet_activity.report("web")
                data=json.loads((Path(tmp)/"activity_web.json").read_text())
                self.assertEqual(list(data),["at"])

if __name__=="__main__":unittest.main()
