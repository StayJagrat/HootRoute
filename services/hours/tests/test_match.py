"""Business names can carry search terms, but proximity still gates a match."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from match_osm import match, name_sim


class MatchTests(unittest.TestCase):
    def test_google_keyword_suffix_does_not_hide_business_name(self):
        self.assertGreater(name_sim("Town and County Market", "Town Country Market - Sake, Fruits, Beer, Pharmacy"), 0.72)
        self.assertGreater(name_sim("MMC Wine & Spirit", "MMC Wines & Spirits - Sake, Fruits, Beer, Pharmacy"), 0.72)

    def test_distance_and_name_both_required(self):
        osm = [
            dict(id="n1", name="Town and County Market", cat="shop", hours=None, address="", lat=37.79, lon=-122.41),
            dict(id="n2", name="Town and County Market", cat="shop", hours=None, address="", lat=37.79, lon=-122.408),
            dict(id="n3", name="Different Store", cat="shop", hours=None, address="", lat=37.79001, lon=-122.41001),
        ]
        google = [dict(title="Town Country Market - Sake, Fruits, Beer, Pharmacy", placeId="g1",
                       location=dict(lat=37.79001, lng=-122.41001))]
        result = match(osm, google)
        self.assertEqual(result["stats"]["matched"], 1)
        self.assertEqual(result["matches"][0]["osm_id"], "n1")


if __name__ == "__main__":
    unittest.main()
