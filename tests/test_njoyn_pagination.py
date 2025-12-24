import unittest

from bs4 import BeautifulSoup

from agents.njoyn import find_next_page_url


class TestNjoynPagination(unittest.TestCase):
    def test_find_next_page_url_prefers_next_link(self) -> None:
        html = """
        <html><body>
          <a href="xweb.asp?CLID=77108&page=joblisting&lang=1&pg=1">1</a>
          <a href="xweb.asp?CLID=77108&page=joblisting&lang=1&pg=2">Next</a>
        </body></html>
        """.strip()
        soup = BeautifulSoup(html, "html.parser")
        nxt = find_next_page_url(
            current_url="https://clients.njoyn.com/cl4/xweb/xweb.asp?CLID=77108&page=joblisting&lang=1&pg=1",
            soup=soup,
            visited=set(),
        )
        self.assertIsNotNone(nxt)
        self.assertIn("pg=2", str(nxt))

    def test_find_next_page_url_returns_none_when_only_visited(self) -> None:
        html = """
        <html><body>
          <a href="xweb.asp?CLID=77108&page=joblisting&lang=1&pg=2">Next</a>
        </body></html>
        """.strip()
        soup = BeautifulSoup(html, "html.parser")
        visited = {
            "https://clients.njoyn.com/cl4/xweb/xweb.asp?CLID=77108&page=joblisting&lang=1&pg=2",
        }
        nxt = find_next_page_url(
            current_url="https://clients.njoyn.com/cl4/xweb/xweb.asp?CLID=77108&page=joblisting&lang=1&pg=1",
            soup=soup,
            visited=visited,
        )
        self.assertIsNone(nxt)

