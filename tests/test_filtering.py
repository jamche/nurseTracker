import unittest
from datetime import date

from filtering import filter_postings
from models import JobPosting


class TestFiltering(unittest.TestCase):
    def test_filter_postings_title_all_of_and_any_of_and_employment_all_of(self) -> None:
        postings = [
            JobPosting(
                hospital="X",
                job_title="Registered Nurse – Operating Room (Surgical Suite)",
                location="Oshawa, ON",
                url="https://example.com/1",
                date_posted=date(2025, 12, 20),
                job_type="Full-Time Permanent",
            ),
            JobPosting(
                hospital="X",
                job_title="Registered Nurse – Pediatrics",
                location="Oshawa, ON",
                url="https://example.com/2",
                date_posted=None,
                job_type="Full-Time Permanent",
            ),
            JobPosting(
                hospital="X",
                job_title="Registered Nurse – Operating Room - Part Time",
                location="Oshawa, ON",
                url="https://example.com/3",
                date_posted=None,
                # Simulate a scraper that hardcodes job_type but the title shows the truth.
                job_type="Full-Time Permanent",
            ),
            JobPosting(
                hospital="X",
                job_title="Perioperative RN",
                location="Oshawa, ON",
                url="https://example.com/4",
                date_posted=None,
                job_type="Full-time",
            ),
        ]

        matched = filter_postings(
            postings,
            title_groups_all=[["Registered Nurse", "RN"], ["Operating Room", "Surgical", "Perioperative"]],
            title_groups_mode="any",
            title_exclude_any_of=["Anesthesia Assistant"],
            employment_any_of=["Full-Time", "Permanent"],
            employment_exclude_any_of=["Part-Time", "Part Time"],
        )

        # "any" mode should include RN-only titles (url 2) and periop RN (url 4), but still exclude part-time (url 3).
        self.assertEqual({p.url for p in matched}, {"https://example.com/1", "https://example.com/2", "https://example.com/4"})

    def test_filter_postings_empty_filters_returns_all(self) -> None:
        postings = [
            JobPosting(
                hospital="X",
                job_title="Anything",
                location=None,
                url="https://example.com/1",
                date_posted=None,
                job_type="Any",
            )
        ]
        matched = filter_postings(
            postings,
            title_groups_all=[],
            title_groups_mode="all",
            title_exclude_any_of=[],
            employment_any_of=[],
            employment_exclude_any_of=[],
        )
        self.assertEqual(matched, postings)
