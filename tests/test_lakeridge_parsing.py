import unittest

from agents.lakeridge import _parse_recent_vacancies


class TestLakeridgeParsing(unittest.TestCase):
    def test_parses_vacancy_detail_links(self) -> None:
        html = """
        <table id="ctl00_x_y_gvwSearchResults">
          <tr><th>Header</th></tr>
          <tr>
            <td>
              <a class="hyperlink" href="VacancyDetail.aspx?VacancyUID=000000051498">
                2500003625 - Registered MRI Technologist
              </a>
              <span id="abc_hlnkVacancyLocation">Job Location: Ajax-Pickering</span>
              <span id="abc_lblFldPublishDate">12/23/2025</span>
            </td>
          </tr>
        </table>
        """.strip()
        jobs = _parse_recent_vacancies(html, base_url="https://careers.lakeridgehealth.on.ca/eRecruit/", hospital="Lakeridge Health")
        self.assertEqual(len(jobs), 1)
        self.assertIn("Registered MRI Technologist", jobs[0].job_title)
        self.assertEqual(jobs[0].location, "Ajax-Pickering")
        self.assertEqual(jobs[0].url, "https://careers.lakeridgehealth.on.ca/eRecruit/VacancyDetail.aspx?VacancyUID=000000051498")

