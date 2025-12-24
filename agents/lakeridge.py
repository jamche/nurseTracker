from __future__ import annotations

import logging
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from agents.base import BaseAgent
from models import JobPosting
from utils.browser import BrowserClient
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import AppConfig, HospitalConfig


class LakeridgeERecruitAgent(BaseAgent):
    def __init__(self, hospital: "HospitalConfig", *, http, logger: logging.Logger):
        super().__init__(hospital, http=http, logger=logger)

    def scrape(self, app_config: "AppConfig") -> list[JobPosting]:
        self.logger.info("eRecruit scrape start %s (%s)", self.hospital.hospital, self.hospital.url)
        # eRecruit often renders via server-side HTML but can be JS-heavy.
        # If pagination/row expansion is UI-driven (“view more rows”), prefer Playwright when enabled.
        use_browser = _env_bool("USE_PLAYWRIGHT", default=False)
        if use_browser:
            browser = BrowserClient(timeout_ms=app_config.scrape.timeout_seconds * 1000)
            html = browser.get_html(self.hospital.url, expand_rows=bool(app_config.scrape.playwright_expand_rows))
            soup = BeautifulSoup(html, "html.parser")
        else:
            html = self.http.get_text(self.hospital.url)
            soup = BeautifulSoup(html, "html.parser")

        postings: list[JobPosting] = []
        for a in soup.select("a[href]"):
            title = a.get_text(" ", strip=True)
            href = a.get("href")
            if not title or not href:
                continue
            if "job" not in href.lower():
                continue
            postings.append(
                JobPosting(
                    hospital=self.hospital.hospital,
                    job_title=title,
                    location=None,
                    url=urljoin(self.hospital.url, href),
                    date_posted=None,
                    job_type="Full-Time Permanent",
                )
            )

        return postings


def _env_bool(key: str, *, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}
