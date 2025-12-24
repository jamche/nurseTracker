import unittest

from agents.workday import _parse_workday_site


class TestWorkdayParsing(unittest.TestCase):
    def test_parse_workday_site_with_lang(self) -> None:
        host, tenant, site = _parse_workday_site(
            "https://oakvalleyhealth.wd10.myworkdayjobs.com/en-US/OakValleyHealth"
        )
        self.assertEqual(host, "https://oakvalleyhealth.wd10.myworkdayjobs.com")
        self.assertEqual(tenant, "oakvalleyhealth")
        self.assertEqual(site, "OakValleyHealth")

    def test_parse_workday_site_without_lang(self) -> None:
        host, tenant, site = _parse_workday_site("https://shn.wd10.myworkdayjobs.com/SHN_External_Career_Site")
        self.assertEqual(host, "https://shn.wd10.myworkdayjobs.com")
        self.assertEqual(tenant, "shn")
        self.assertEqual(site, "SHN_External_Career_Site")
