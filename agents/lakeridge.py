from __future__ import annotations

import logging
import os
import re
from datetime import date
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
        else:
            html = self.http.get_text(self.hospital.url)
        return _parse_recent_vacancies(html, base_url=self.hospital.url, hospital=self.hospital.hospital)


def _env_bool(key: str, *, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


_GENERIC_ERECRUIT_TEXT = {
    "view job details",
    "job details",
    "details",
    "view",
    "apply",
    "apply now",
}

_NAV_TITLES = {
    "login",
    "register",
    "home",
    "contact us",
    "rss feed",
    "my job basket (0)",
}

_NAV_PATH_RE = re.compile(
    r"/eRecruit/(Login|Contact_Us|User_Registration|Default|My_Interests|RSS)\\.aspx$",
    flags=re.IGNORECASE,
)


def _extract_row_title(tr, *, fallback: str) -> str:
    txt = (fallback or "").strip()
    if txt and txt.lower() not in _GENERIC_ERECRUIT_TEXT and len(txt) >= 6:
        return txt
    candidates: list[str] = []
    for cell in tr.select("td,th"):
        t = cell.get_text(" ", strip=True)
        if not t:
            continue
        if t.lower() in _GENERIC_ERECRUIT_TEXT:
            continue
        if len(t) < 6:
            continue
        candidates.append(t)
    if not candidates:
        return ""
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def _looks_like_job_link(href: str, onclick: str | None) -> bool:
    h = (href or "").lower()
    # Avoid treating every .aspx navigation link as a "job". eRecruit job links usually include these hints.
    if any(token in h for token in ("vacancy", "jobdetail", "job_details", "posting", "requisition", "req")):
        return True
    oc = (onclick or "").lower()
    if any(token in oc for token in ("vacancy", "job", "posting", "requisition", "req")):
        return True
    if "location.href" in oc or "window.location" in oc:
        return True
    return False


def _is_nav_link(*, base: str, href: str) -> bool:
    absolute = urljoin(base, href)
    return _NAV_PATH_RE.search(absolute) is not None


def _resolve_link(base_url: str, href: str, *, onclick: str | None) -> str:
    if href:
        return urljoin(base_url, href)
    oc = onclick or ""
    m = re.search(r"(https?://[^\s'\";]+)", oc)
    if m:
        return m.group(1)
    m2 = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", oc, flags=re.IGNORECASE)
    if m2:
        return urljoin(base_url, m2.group(1))
    m3 = re.search(r"window\.location\s*=\s*['\"]([^'\"]+)['\"]", oc, flags=re.IGNORECASE)
    if m3:
        return urljoin(base_url, m3.group(1))
    return base_url


def _parse_recent_vacancies(html: str, *, base_url: str, hospital: str) -> list[JobPosting]:
    soup = BeautifulSoup(html, "html.parser")

    # Target the known "recent vacancies" grid view:
    # <table id="..._gvwSearchResults"> with anchors to VacancyDetail.aspx?VacancyUID=...
    table = soup.find("table", id=re.compile(r"gvwSearchResults$", re.IGNORECASE))
    if table:
        postings: list[JobPosting] = []
        for tr in table.select("tr"):
            link = tr.select_one('a[href*="VacancyDetail.aspx?VacancyUID="]')
            if not link:
                continue
            href = (link.get("href") or "").strip()
            if not href:
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue

            loc = None
            loc_span = tr.select_one('span[id$="hlnkVacancyLocation"]')
            if loc_span:
                loc_txt = loc_span.get_text(" ", strip=True)
                if loc_txt:
                    loc = loc_txt.replace("Job Location:", "").strip()

            posted = None
            posted_span = tr.select_one('span[id$="lblFldPublishDate"]')
            if posted_span:
                posted_txt = posted_span.get_text(" ", strip=True)
                posted = _parse_mmddyyyy(posted_txt)

            postings.append(
                JobPosting(
                    hospital=hospital,
                    job_title=_collapse_spaces(title),
                    location=loc,
                    url=urljoin(base_url, href),
                    date_posted=posted,
                    job_type="Full-Time Permanent",
                )
            )
        if postings:
            return postings

    # Fallback to a conservative link scrape if the grid isn't found.
    out: list[JobPosting] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.lower().startswith("javascript:"):
            continue
        if _is_nav_link(base=base_url, href=href):
            continue
        title = (a.get_text(" ", strip=True) or "").strip()
        if not title:
            continue
        if title.lower() in _NAV_TITLES or title.lower() in _GENERIC_ERECRUIT_TEXT:
            continue
        if not _looks_like_job_link(href, a.get("onclick")):
            continue
        out.append(
            JobPosting(
                hospital=hospital,
                job_title=title,
                location=None,
                url=_resolve_link(base_url, href, onclick=a.get("onclick")),
                date_posted=None,
                job_type="Full-Time Permanent",
            )
        )
    return out


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_mmddyyyy(s: str) -> date | None:
    try:
        parts = (s or "").strip().split("/")
        if len(parts) != 3:
            return None
        m, d, y = (int(parts[0]), int(parts[1]), int(parts[2]))
        if y < 100:
            y += 2000
        return date(y, m, d)
    except Exception:
        return None
