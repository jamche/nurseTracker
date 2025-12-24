from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from agents.base import BaseAgent
from models import JobPosting
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import AppConfig, HospitalConfig


class NjoynAgent(BaseAgent):
    def __init__(self, hospital: "HospitalConfig", *, http, logger: logging.Logger):
        super().__init__(hospital, http=http, logger=logger)

    def scrape(self, app_config: "AppConfig") -> list[JobPosting]:
        self.logger.info("Njoyn scrape start %s (%s)", self.hospital.hospital, self.hospital.url)
        visited: set[str] = set()
        next_url: str | None = self.hospital.url

        postings: list[JobPosting] = []
        max_pages = app_config.scrape.max_pages
        pages = 0

        while next_url and pages < max_pages:
            if next_url in visited:
                break
            visited.add(next_url)
            pages += 1

            html = self.http.get_text(next_url)
            soup = BeautifulSoup(html, "html.parser")

            # Njoyn pages vary; this aims to capture common table listing with links.
            for a in soup.select("a[href]"):
                text = a.get_text(" ", strip=True)
                href = a.get("href")
                if not href or not text:
                    continue
                if href.lower().startswith("javascript:"):
                    continue
                if "jobdetail" not in href.lower() and "job" not in href.lower():
                    continue
                url = urljoin(next_url, href)

                postings.append(
                    JobPosting(
                        hospital=self.hospital.hospital,
                        job_title=text,
                        location=None,
                        url=url,
                        date_posted=None,
                        job_type="Full-Time Permanent",
                    )
                )

            next_url = find_next_page_url(current_url=next_url, soup=soup, visited=visited)

        return postings


def find_next_page_url(*, current_url: str, soup: BeautifulSoup, visited: set[str]) -> str | None:
    def page_num(url: str) -> int | None:
        try:
            qs = parse_qs(urlparse(url).query)
        except Exception:
            return None
        for key in ("pg", "page", "pagenum", "pagenumber"):
            if key in qs and qs[key]:
                try:
                    return int(str(qs[key][0]))
                except Exception:
                    return None
        return None

    current_page = page_num(current_url)
    explicit_next: list[str] = []
    paginated: list[tuple[int, str]] = []

    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        if href.lower().startswith("javascript:"):
            continue
        absolute = urljoin(current_url, href)
        if absolute == current_url:
            continue
        if absolute in visited:
            continue

        txt = a.get_text(" ", strip=True).lower()
        if "next" in txt or txt in {">", ">>"}:
            explicit_next.append(absolute)
            continue
        if "suivant" in txt:  # FR "Next" appears on some boards
            explicit_next.append(absolute)
            continue

        if "page=joblisting" in absolute.lower() and re.search(r"(pg|page|pagenum|pagenumber)=\d+", absolute.lower()):
            pn = page_num(absolute)
            if pn is not None:
                paginated.append((pn, absolute))

    if explicit_next:
        return explicit_next[0]

    if not paginated:
        return None

    if current_page is None:
        paginated.sort(key=lambda x: x[0])
        return paginated[0][1]

    higher = [p for p in paginated if p[0] > current_page]
    if not higher:
        return None
    higher.sort(key=lambda x: x[0])
    return higher[0][1]
