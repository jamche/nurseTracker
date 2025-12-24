import unittest

from agents.njoyn import _sanitize_njoyn_detail_url


class TestNjoynSanitize(unittest.TestCase):
    def test_sanitize_strips_tokens(self) -> None:
        url = (
            "https://clients.njoyn.com/cl4/xweb/xweb.asp?"
            "tbtoken=AAA&chk=BBB&clid=77108&Page=JobDetails&Jobid=J0725-0840&BRID=419681&lang=1"
        )
        out = _sanitize_njoyn_detail_url(url)
        self.assertIn("clid=77108", out)
        self.assertIn("Page=JobDetails", out)
        self.assertIn("Jobid=J0725-0840", out)
        self.assertNotIn("tbtoken=", out)
        self.assertNotIn("chk=", out)

