import tempfile
import unittest
from pathlib import Path

from config import load_config


class TestConfig(unittest.TestCase):
    def test_load_config_parses_expected_schema(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text(
                """
role:
  title_all_of: ["Registered Nurse"]
  title_any_of: ["Operating Room"]
  employment_all_of: ["Full-Time", "Permanent"]
output:
  dir: output
  json: jobs.json
  csv: jobs.csv
  last_json: last_jobs.json
  seen_urls: seen_urls.json
scrape:
  timeout_seconds: 10
  retry_attempts: 2
  user_agent: "test-agent"
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
            self.assertEqual(app.role.title_all_of, ["Registered Nurse"])
            self.assertEqual(app.role.title_any_of, ["Operating Room"])
            self.assertEqual(app.role.employment_all_of, ["Full-Time", "Permanent"])
            self.assertEqual(app.output.seen_urls, "seen_urls.json")
            self.assertEqual(len(app.hospitals), 1)
            self.assertEqual(app.hospitals[0].type, "workday")

    def test_load_config_rejects_unknown_hospital_type(self) -> None:
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
