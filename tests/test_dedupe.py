import unittest

from models import JobPosting
from utils.dedupe import dedupe_by_url


class TestDedupe(unittest.TestCase):
    def test_dedupe_by_url_keeps_first(self) -> None:
        a = JobPosting(
            hospital="H",
            job_title="T",
            location=None,
            url="https://example.com/job/1",
            date_posted=None,
            job_type="Full-Time Permanent",
        )
        b = JobPosting(
            hospital="H",
            job_title="T2",
            location=None,
            url="https://example.com/job/1",
            date_posted=None,
            job_type="Full-Time Permanent",
        )
        out = dedupe_by_url([a, b])
        self.assertEqual(out, [a])
