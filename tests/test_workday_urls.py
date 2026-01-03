import unittest

from agents.workday import WorkdayAgent
from config import HospitalConfig
from utils.http import HttpClient


class _NullLogger:
    def info(self, *args, **kwargs): ...
    def warning(self, *args, **kwargs): ...
    def exception(self, *args, **kwargs): ...


class TestWorkdayUrls(unittest.TestCase):
    def test_details_url_from_external_path(self) -> None:
        hospital = HospitalConfig(
            hospital="SHN",
            type="workday",  # type: ignore[arg-type]
            url="https://shn.wd10.myworkdayjobs.com/SHN_External_Career_Site",
            location_include_any_of=[],
        )
        agent = WorkdayAgent(hospital, http=HttpClient(timeout_seconds=1, user_agent="x"), logger=_NullLogger())  # type: ignore[arg-type]
        url = agent._details_url("/job/Centenary-Hospital/Registered-Nurse---9W-Medicine--CEN-_JR104721")
        self.assertEqual(
            url,
            "https://shn.wd10.myworkdayjobs.com/en-US/SHN_External_Career_Site/details/Registered-Nurse---9W-Medicine--CEN-_JR104721",
        )

