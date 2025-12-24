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
                job_title="Registered Nurse – Operating Room",
                location="Oshawa, ON",
                url="https://example.com/3",
                date_posted=None,
                job_type="Part-Time Permanent",
            ),
        ]

        matched = filter_postings(
            postings,
            title_all_of=["Registered Nurse"],
            title_any_of=["Operating Room", "Surgical"],
            employment_all_of=["Full-Time", "Permanent"],
        )

        self.assertEqual([p.url for p in matched], ["https://example.com/1"])

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
        matched = filter_postings(postings, title_all_of=[], title_any_of=[], employment_all_of=[])
        self.assertEqual(matched, postings)
