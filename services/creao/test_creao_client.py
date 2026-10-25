"""Only sourced, engine-readable Creao hours can enter the evidence cache."""
import unittest

from creao_client import valid


class CreaoValidationTests(unittest.TestCase):
    def test_accepts_sourced_schedule(self):
        result = dict(osm_id="n1", opening_hours="Mo-Fr 09:00-17:00", confidence=0.9,
                      sources=[dict(url="https://example.org/hours", quote="Monday to Friday, 9 to 5")])
        self.assertTrue(valid(result, "n1"))

    def test_rejects_invalid_or_unsourced_schedule(self):
        result = dict(osm_id="n1", opening_hours="every day until late", confidence=0.9,
                      sources=[dict(url="https://example.org/hours", quote="Open late")])
        self.assertFalse(valid(result, "n1"))
        result["opening_hours"] = "Mo-Fr 09:00-17:00"
        result["sources"] = []
        self.assertFalse(valid(result, "n1"))
        result["sources"] = [dict(url="https://example.org/hours", quote="Monday to Friday, 9 to 5")]
        result["confidence"] = 0.3
        self.assertFalse(valid(result, "n1"))
        self.assertFalse(valid(result, "n2"))


if __name__ == "__main__":
    unittest.main()
