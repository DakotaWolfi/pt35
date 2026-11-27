"""Test draft reactions, expiry and cooldown without a running printer."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import draft_reaction

class DraftReactionTests(unittest.TestCase):
    def test_field_to_comment_and_excerpt(self):
        result=draft_reaction.reaction("amount","750")
        self.assertEqual(result["field"],"FINE")
        self.assertTrue(result["comment"])
        self.assertEqual(result["value"],"750")

    def test_reject_unknown_field_and_empty_line(self):
        for field,value in (("password","oops"),("name","  ")):
            with self.assertRaises(ValueError):
                draft_reaction.reaction(field,value)

    def test_writes_only_completed_line_temporarily(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(draft_reaction,"FILE",Path(folder)/"draft.json"):
                self.assertTrue(draft_reaction.submit("name","Very Fluffy Wolf",now=1000))
                self.assertEqual(draft_reaction.current(now=1001)["value"],"Very Fluffy Wolf")
                self.assertFalse(draft_reaction.submit("amount","123",now=1010))
                self.assertTrue(draft_reaction.submit("amount","123",now=1025))
                self.assertEqual(draft_reaction.current(now=1026)["field"],"FINE")
                self.assertIsNone(draft_reaction.current(now=1091))

if __name__=="__main__":unittest.main()
