import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import receipt_store

class TestReceipts(unittest.TestCase):
    def test_custom_receipt(self):
        fields={"title":"Test", "subtitle":"Sub", "footer":"bye",
                "lines":[{"type":"heading","text":"hello","label":""},
                         {"type":"pair","label":"Price","text":"CHF 0","unused":5},
                         {"type":"rule","text":"","label":""}]}
        clean=app.validate_custom(fields,app.DEFAULT)
        data=app.make_custom_receipt(clean,app.DEFAULT)
        self.assertIn(b"HELLO",data)
        self.assertIn(b"Price: CHF 0",data)
        self.assertNotIn(b"\x1b",data)
    def test_reject_raw_control(self):
        fields={"title":"Test","lines":[{"type":"text","text":"Bad\nCMD"}]}
        with self.assertRaises(ValueError): app.validate_custom(fields,app.DEFAULT)
    def test_reject_unbounded_jobs(self):
        fields={"title":"Test","lines":[{"type":"text","text":"X"}]*26}
        with self.assertRaises(ValueError): app.validate_custom(fields,app.DEFAULT)
    def test_compact_round_trip(self):
        old=receipt_store.DB
        try:
            with tempfile.TemporaryDirectory() as tmp:
                receipt_store.DB=Path(tmp)/"history.sqlite3"
                payload={"title":"FMI","lines":[{"type":"text","text":"AWOO!"}]}
                job_id=receipt_store.record("custom",payload)
                self.assertEqual(receipt_store.get_job(job_id)["state"],"queued")
                receipt_store.complete(job_id,False,"Printer offline")
                receipt_store.set_reverse_dns(job_id,"my-laptop.example")
                payload["ticket_number"]="00003"
                receipt_store.update_payload(job_id,payload)
                job=receipt_store.get_job(job_id)
                self.assertEqual(job["receipt"],payload)
                self.assertEqual(job["state"],"failed")
                self.assertEqual(job["reverse_dns"],"my-laptop.example")
                self.assertEqual(len(receipt_store.list_jobs()),1)
        finally: receipt_store.DB=old

if __name__=="__main__":unittest.main()
