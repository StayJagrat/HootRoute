"""Run: ../../.venv-hours/bin/python -m unittest discover -s tests   (from services/hours)"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parse_hours import parse_rules
from hours_common import agreement, validate_osm_hours

GOOGLE = ("Monday: 11 AM to 9:30 PM; Tuesday: 11 AM to 9:30 PM; Wednesday: 11 AM to 9:30 PM; Thursday: 11 AM to 9:30 PM; "
          "Friday: 11 AM to 11 PM; Saturday: 5 PM to 2 AM; Sunday: Closed")

CASES = [  # (text, expected OSM string (compared by schedule), min confidence)
    (GOOGLE, "Mo-Th 11:00-21:30; Fr 11:00-23:00; Sa 17:00-02:00; Su off", 0.9),
    ("Open 24 hours", "24/7", 0.9),
    ("11 AM to 2 AM", "Mo-Su 11:00-02:00", 0.9),
    ("Mon-Thu 9-9, Fri/Sat til midnight, closed holidays", "Mo-Th 09:00-21:00; Fr,Sa 09:00-24:00", 0.4),
    ("Weekdays 7:30am-4pm; weekends 8-3", "Mo-Fr 07:30-16:00; Sa-Su 08:00-15:00", 0.5),
    ("Monday: 11 AM to 2 PM, 5 to 10 PM; Tuesday: Closed", "Mo 11:00-14:00,17:00-22:00", 0.8),
    ("Mon: 9:00 AM – 5:00 PM\nTue: 9:00 AM – 5:00 PM", "Mo,Tu 09:00-17:00", 0.8),
    ("Mo-Fr 9:00-17:00", "Mo-Fr 09:00-17:00", 0.8),
    ("Mo-Fr 09:00-17:00; Sa-Su off", "Mo-Fr 09:00-17:00; Sa-Su off", 0.9),
    ("Daily 6am - 11pm", "Mo-Su 06:00-23:00", 0.9),
    ("Closed Sundays, Mon-Sat 10am-6pm", "Mo-Sa 10:00-18:00; Su off", 0.7),
    ("Monday - 9am - 5pm", "Mo 09:00-17:00", 0.7),
    ("Tue-Sun noon to 8pm", "Tu-Su 12:00-20:00", 0.7),
    ("Open daily 10 to midnight", "Mo-Su 10:00-24:00", 0.7),
    ("Open 7am to 7pm Mon-Sat. Closed Sunday", "Mo-Sa 07:00-19:00; Su off", 0.9),
    ("9-5 Mon-Fri, 10-2 Sat", "Mo-Fr 09:00-17:00; Sa 10:00-14:00", 0.5),
    ("Fri & Sat 5 PM-3 AM", "Fr,Sa 17:00-03:00", 0.7),
]
NULLS = ["", None, "   ", "By appointment only", "Hours vary", "Call for hours", "Tue-Sun 5pm-late", "Check website", "Foo Bar Cafe"]


class T(unittest.TestCase):
    def test_cases(self):
        for text, exp, minc in CASES:
            r = parse_rules(text)
            self.assertIsNotNone(r["opening_hours"], (text, r))
            self.assertTrue(validate_osm_hours(r["opening_hours"])[0], (text, r))
            self.assertEqual(agreement(r["opening_hours"], exp), 1.0, (text, r, exp))
            self.assertGreaterEqual(r["confidence"], minc, (text, r))

    def test_nulls(self):
        for text in NULLS:
            r = parse_rules(text)
            self.assertIsNone(r["opening_hours"], (text, r))

    def test_closed(self):
        self.assertEqual(parse_rules("Permanently closed")["opening_hours"], "off")


if __name__ == "__main__":
    unittest.main()
