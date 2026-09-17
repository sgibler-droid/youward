#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_status", ROOT / "scripts" / "verify-status.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class WeeklyRefreshTests(unittest.TestCase):
    def test_two_consecutive_fetch_failures(self):
        fixture = json.loads((ROOT / "tests/fixtures/two-failure.json").read_text())
        status1, evidence1 = MOD.apply_resolution(
            fixture["prior_status"], fixture["prior_evidence"],
            "unverified", fixture["failure_evidence"], "2026-09-21")
        self.assertEqual(status1, fixture["expected_first_status"])
        self.assertIn("[FETCH_FAILURE_COUNT=1]", evidence1)

        status2, evidence2 = MOD.apply_resolution(
            status1, evidence1, "unverified",
            fixture["failure_evidence"], "2026-09-28")
        self.assertEqual(status2, fixture["expected_second_status"])
        self.assertIn("[FETCH_FAILURE_COUNT=2]", evidence2)
        self.assertNotEqual(status2, "open")

    def test_success_resets_failure_counter(self):
        status, evidence = MOD.apply_resolution(
            "open",
            "[FETCH_FAILURE_COUNT=1] prior source evidence || FETCH_FAILURE checked 2026-09-21: fetch returned 503",
            "closed", "official page | checked 2026-09-28 | applications are closed",
            "2026-09-28")
        self.assertEqual(status, "closed")
        self.assertNotIn("FETCH_FAILURE_COUNT", evidence)

    def test_breaker_boundary_fixture(self):
        fixture = json.loads((ROOT / "tests/fixtures/circuit-breaker.json").read_text())
        self.assertFalse(MOD.breaker_tripped(
            fixture["allowed_status_changes"], fixture["record_count"]))
        self.assertTrue(MOD.breaker_tripped(
            fixture["blocked_status_changes"], fixture["record_count"]))

    def test_row_rewrite_changes_only_status_and_evidence(self):
        row = ('<tr class="rec" data-evidence="old" data-class="grant">'
               '<td><a href="https://example.org">Title</a></td><td>grant</td>'
               '<td>Agency</td><td>$10</td><td>10/01/2026</td><td>open</td></tr>')
        updated = MOD.rewrite_row(row, "closed", "exact official wording")
        self.assertEqual(MOD.mask_mutable_fields(row), MOD.mask_mutable_fields(updated))
        self.assertIn('data-evidence="exact official wording"', updated)
        self.assertIn('<a href="https://example.org">Title</a>', updated)
        self.assertIn('<td>Agency</td><td>$10</td><td>10/01/2026</td>', updated)
        self.assertEqual(updated.count("<td>"), row.count("<td>"))
        self.assertTrue(updated.endswith("<td>closed</td></tr>"))


if __name__ == "__main__":
    unittest.main()
