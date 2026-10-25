"""Exercises the Claude code path with a stubbed API call (no network, no key)."""
import json, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parse_hours as ph


class T(unittest.TestCase):
    def test_valid_json(self):
        with mock.patch.object(ph, "_claude_call", return_value='```json\n{"opening_hours":"Mo-Fr 09:00-17:00","confidence":0.9,"notes":"x"}\n```'):
            r = ph.parse_claude("Mon-Fri 9-5", cache={})
        self.assertEqual(r["opening_hours"], "Mo-Fr 09:00-17:00")

    def test_invalid_then_fixed(self):
        outs = iter(['{"opening_hours":"Mo-Fr 9am-5pm","confidence":0.9,"notes":""}',
                     '{"opening_hours":"Mo-Fr 09:00-17:00","confidence":0.8,"notes":"fixed"}'])
        with mock.patch.object(ph, "_claude_call", side_effect=lambda *a, **k: next(outs)):
            r = ph.parse_claude("Mon-Fri 9-5", cache={})
        self.assertEqual(r["opening_hours"], "Mo-Fr 09:00-17:00")

    def test_garbage_rejected(self):
        with mock.patch.object(ph, "_claude_call", return_value='{"opening_hours":"Mo-Fr 09:00-26:00","confidence":0.9,"notes":""}'):
            r = ph.parse_claude("whatever 9-5", cache={})
        self.assertIsNone(r["opening_hours"])

    def test_no_text_never_calls_api(self):
        with mock.patch.object(ph, "_claude_call", side_effect=AssertionError("must not be called")):
            self.assertIsNone(ph.parse_claude("", cache={})["opening_hours"])
            self.assertIsNone(ph.Parser("claude").parse(None)["opening_hours"])

    def test_auto_uses_rules_when_confident_and_claude_otherwise(self):
        p = ph.Parser("auto"); p.cache = {}
        with mock.patch.object(ph, "_claude_call", return_value='{"opening_hours":"Mo-Su 17:00-23:00","confidence":0.6,"notes":"late"}') as c:
            self.assertEqual(p.parse("Daily 09:00-17:00")["method"], "rules")
            self.assertEqual(c.call_count, 0)
            r = p.parse("Tue-Sun 5pm-late")
            self.assertEqual(r["method"], "claude"); self.assertEqual(c.call_count, 1)


if __name__ == "__main__":
    unittest.main()
