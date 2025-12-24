import unittest
from datetime import datetime

from models import JobPosting
from rendering.email_templates import render_jobs_email


class TestEmailTemplates(unittest.TestCase):
    def test_email_no_results_renders_message(self) -> None:
        subject, html = render_jobs_email(
            subject_title="Test",
            run_at=datetime(2025, 12, 20, 8, 0, 0),
            new_jobs=[],
            all_jobs=None,
        )
        self.assertEqual(subject, "Test")
        self.assertIn("No matching postings found today", html)

    def test_email_renders_table_rows(self) -> None:
        job = JobPosting(
            hospital="Lakeridge Health",
            job_title="Registered Nurse – Operating Room",
            location="Oshawa, ON",
            url="https://example.com/job/1",
            date_posted=None,
            job_type="Full-Time Permanent",
        )
        subject, html = render_jobs_email(
            subject_title="Test",
            run_at=datetime(2025, 12, 20, 8, 0, 0),
            new_jobs=[job],
            all_jobs=None,
        )
        self.assertIn("New postings", html)
        self.assertIn("Lakeridge Health", html)
        self.assertIn("Operating Room", html)
        self.assertIn("https://example.com/job/1", html)
