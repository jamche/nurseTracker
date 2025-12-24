import tempfile
import unittest
from pathlib import Path

from config import load_config


class TestConfig(unittest.TestCase):
    def test_load_config_parses_expected_schema(self) -> None:
        try:
            import yaml  # noqa: F401
        except Exception:
            raise unittest.SkipTest("PyYAML not installed")

        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text(
                """
role:
  title_groups_all:
    - ["Registered Nurse", "RN"]
    - ["Operating Room", "Perioperative"]
  employment_any_of: ["Full-Time", "Permanent"]
  employment_exclude_any_of: ["Part-Time", "Casual"]
output:
  dir: output
  json: jobs.json
  csv: jobs.csv
  last_json: last_jobs.json
  seen_urls: seen_urls.json
  run_report: run_report.json
scrape:
  timeout_seconds: 10
  retry_attempts: 2
  user_agent: "test-agent"
  max_pages: 50
  workday_page_size: 50
  playwright_expand_rows: true
  enrich_detail_titles: true
  enrich_detail_max_requests: 10
email:
  include_all_results: false
hospitals:
  - hospital: Test Hospital
    type: workday
    url: https://example.wd10.myworkdayjobs.com/en-US/Site
""".strip(),
                encoding="utf-8",
            )

            app = load_config(cfg)
            self.assertEqual(app.role.title_groups_all[0], ["Registered Nurse", "RN"])
            self.assertEqual(app.role.title_groups_all[1], ["Operating Room", "Perioperative"])
            self.assertEqual(app.role.employment_any_of, ["Full-Time", "Permanent"])
            self.assertEqual(app.role.employment_exclude_any_of, ["Part-Time", "Casual"])
            self.assertEqual(app.output.seen_urls, "seen_urls.json")
            self.assertEqual(app.output.run_report, "run_report.json")
            self.assertEqual(len(app.hospitals), 1)
            self.assertEqual(app.hospitals[0].type, "workday")
            self.assertTrue(app.scrape.enrich_detail_titles)
            self.assertEqual(app.scrape.enrich_detail_max_requests, 10)

    def test_load_config_rejects_unknown_hospital_type(self) -> None:
        try:
            import yaml  # noqa: F401
        except Exception:
            raise unittest.SkipTest("PyYAML not installed")

        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text(
                """
role:
  title_all_of: []
  title_any_of: []
  employment_all_of: []
output:
  dir: output
  json: jobs.json
  csv: jobs.csv
  last_json: last_jobs.json
  seen_urls: seen_urls.json
scrape:
  timeout_seconds: 10
  retry_attempts: 1
  user_agent: "test-agent"
hospitals:
  - hospital: Test Hospital
    type: nope
    url: https://example.com
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                load_config(cfg)
            self.assertIn("Unsupported hospital type", str(ctx.exception))
