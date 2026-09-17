#!/usr/bin/env python3
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("p44", ROOT / "scripts" / "p44-leak-gate.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class P44LeakGateTests(unittest.TestCase):
    def test_clean_page_passes(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "clean.html"
            path.write_text("<html><body>official public evidence</body></html>")
            self.assertEqual(MOD.scan(path), [])

    def test_page_and_log_secrets_fail(self):
        with tempfile.TemporaryDirectory() as td:
            page = pathlib.Path(td) / "page.html"
            log = pathlib.Path(td) / "run.log"
            page.write_text("<div>/Users/private/person/file</div>")
            log.write_text("webhook=https://hooks.slack.com/services/AAA/BBB/CCC")
            self.assertTrue(MOD.scan(page))
            self.assertTrue(MOD.scan(log))


if __name__ == "__main__":
    unittest.main()
