"""Regression coverage for local Phase 2 tracker features."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import storage


class TrackerStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_paths = (storage.DATA_DIR, storage.DATA_FILE, storage.TEMP_FILE, storage.LEGACY_DATA_FILE)
        root = Path(self.temp_dir.name)
        storage.DATA_DIR = root
        storage.DATA_FILE = root / "job_tracker.xlsx"
        storage.TEMP_FILE = root / "job_tracker.tmp.xlsx"
        storage.LEGACY_DATA_FILE = root / "job_tracker.json"

    def tearDown(self) -> None:
        storage.DATA_DIR, storage.DATA_FILE, storage.TEMP_FILE, storage.LEGACY_DATA_FILE = self.original_paths
        self.temp_dir.cleanup()

    def test_captured_listing_persists_and_duplicate_is_detected(self) -> None:
        saved = storage.add_application({
            "company": "Acme AI",
            "role": "Senior ML Engineer",
            "url": "https://jobs.example/role/42",
            "job_description": "Build local machine learning systems.",
            "work_mode": "Remote",
            "salary": "$150k–$180k",
            "requirements": "Python\nMachine learning",
            "captured_at": "2026-10-21T10:30:00",
            "source": "Captured from job link",
        })

        loaded = storage.dashboard()["applications"][0]
        self.assertEqual(loaded["id"], saved["id"])
        self.assertEqual(loaded["job_description"], "Build local machine learning systems.")
        self.assertEqual(loaded["work_mode"], "Remote")
        self.assertEqual(loaded["salary"], "$150k–$180k")
        self.assertIn("Python", loaded["requirements"])
        self.assertEqual(loaded["captured_at"], "2026-10-21T10:30:00")

        matches = storage.find_duplicates({"url": "https://jobs.example/role/42/"})
        self.assertEqual([item["id"] for item in matches], [saved["id"]])
        with self.assertRaisesRegex(ValueError, "similar opportunity"):
            storage.add_application({"company": "Acme AI", "role": "Senior ML Engineer", "url": "https://jobs.example/role/42"})

    def test_saved_searches_and_preference_matching_are_local_and_persistent(self) -> None:
        storage.add_application({
            "company": "Orbit Labs",
            "role": "AI Platform Engineer",
            "requirements": "Python\nMCP\nLocal inference",
        })
        searches = storage.save_search("AI platform")
        self.assertEqual(searches[0]["query"], "AI platform")
        storage.set_matching_preferences("Python, MCP, Rust")

        dashboard = storage.dashboard()
        self.assertEqual(dashboard["saved_searches"][0]["query"], "AI platform")
        app = dashboard["applications"][0]
        self.assertEqual(app["match_terms"], ["python", "mcp"])
        self.assertEqual(app["match_score"], 67)

        remaining = storage.delete_search(searches[0]["id"])
        self.assertEqual(remaining, [])
        self.assertEqual(storage.dashboard()["saved_searches"], [])

    def test_old_workbook_without_phase_two_columns_still_loads(self) -> None:
        storage.add_application({"company": "Old Co", "role": "Software Engineer"})
        workbook = storage.load_workbook(storage.DATA_FILE)
        sheet = workbook["Applications"]
        new_columns = 5
        sheet.delete_cols(14, new_columns)
        workbook.save(storage.DATA_FILE)
        workbook.close()

        app = storage.dashboard()["applications"][0]
        self.assertEqual(app["company"], "Old Co")
        self.assertEqual(app["job_description"], "")
        self.assertEqual(app["requirements"], "")
        self.assertEqual(app["captured_at"], "")

    def test_resume_profile_match_explains_supported_and_missing_requirements(self) -> None:
        profile = storage.save_candidate_profile({
            "skills": ["Python", "Spring Boot"],
            "experiences": [{"company": "Acme", "title": "Engineer", "evidence": "Built distributed systems using Java."}],
        })
        analysis = storage.analyze_job_match(
            {"requirements": "Python\nKubernetes\nDistributed systems"}, profile
        )
        self.assertEqual(analysis["score"], 75)
        self.assertEqual([item["requirement"] for item in analysis["matched"]], ["Python", "Distributed systems"])
        self.assertEqual(analysis["gaps"][0]["requirement"], "Kubernetes")
        self.assertIn("keyword coverage", analysis["explanation"])

        no_requirements = storage.analyze_job_match({"requirements": ""}, profile)
        self.assertIsNone(no_requirements["score"])


if __name__ == "__main__":
    unittest.main()
