import unittest
from receipt import format_receipt, validate_report


class ReceiptTests(unittest.TestCase):
    def test_original_result_is_not_inferred(self):
        record={"device":"Coffee maker","tester":"Unknown instrument","date":"2026-11-19",
                "result":"UNKNOWN","measurements":[{"name":"PE resistance","value":"0.12","unit":"ohm"}]}
        text=format_receipt(record)
        self.assertIn("TESTER RESULT: UNKNOWN",text)
        self.assertNotIn("TESTER RESULT: PASS",text)

    def test_reject_untrusted_result(self):
        with self.assertRaises(ValueError):
            validate_report({"device":"A","tester":"B","date":"2026-11-19","result":"CERTIFIED"})

    def test_escape_does_not_inject_escpos_commands(self):
        text=format_receipt({"device":"A\x1b@","tester":"B","date":"today","result":"FAIL"})
        self.assertNotIn("\x1b",text)
        self.assertIn("TESTER RESULT: FAIL",text)


if __name__=="__main__":
    unittest.main()
