from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
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
        enrich_budget = app_config.scrape.enrich_detail_max_requests

        while next_url and pages < max_pages:
            if next_url in visited:
                break
            visited.add(next_url)
            pages += 1

            html = self.http.get_text(next_url)
            soup = BeautifulSoup(html, "html.parser")

            # Njoyn pages vary. Prefer job detail links; derive a title from row context if needed.
            for a in soup.select("a[href]"):
                text = a.get_text(" ", strip=True)
                href = a.get("href")
                if not href or not text:
                    continue
                if href.lower().startswith("javascript:"):
                    continue
                href_l = href.lower()
                if "page=jobdetail" not in href_l and "jobdetail" not in href_l:
                    continue
                url = urljoin(next_url, href)
                title = _extract_njoyn_title(a, fallback=text)
                if (not title or title.lower() in _GENERIC_LINK_TEXT) and app_config.scrape.enrich_detail_titles:
                    if enrich_budget > 0:
                        enrich_budget -= 1
                        title = _fetch_detail_title(self.http, url) or title
                    else:
                        self.logger.info("%s: detail enrichment budget exhausted", self.hospital.hospital)
                if title and _JOB_ID_ONLY.match(title) and app_config.scrape.enrich_detail_titles:
                    if enrich_budget > 0:
                        enrich_budget -= 1
                        title = _fetch_detail_title(self.http, url) or title
                if not title or title.lower() in _GENERIC_LINK_TEXT:
                    continue

                postings.append(
                    JobPosting(
                        hospital=self.hospital.hospital,
                        job_title=title,
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


_GENERIC_LINK_TEXT = {
    "details",
    "detail",
    "view",
    "view details",
    "view job details",
    "job details",
    "apply",
    "apply now",
    "learn more",
    "more",
}

_JOB_ID_ONLY = re.compile(r"^j\d{4}-\d{4}$", re.IGNORECASE)


def _extract_njoyn_title(a, *, fallback: str) -> str:
    txt = (fallback or "").strip()
    if txt and txt.lower() not in _GENERIC_LINK_TEXT and len(txt) >= 6:
        return txt

    tr = a.find_parent("tr")
    if not tr:
        return txt if txt.lower() not in _GENERIC_LINK_TEXT else ""

    candidates: list[str] = []
    for cell in tr.find_all(["td", "th"]):
        cell_txt = cell.get_text(" ", strip=True)
        if not cell_txt:
            continue
        lower = cell_txt.lower()
        if lower in _GENERIC_LINK_TEXT:
            continue
        # Avoid picking row numbers / tiny labels
        if len(cell_txt) < 6:
            continue
        candidates.append(cell_txt)

    if not candidates:
        return ""
    candidates.sort(key=lambda s: len(s), reverse=True)
    return candidates[0]


def _fetch_detail_title(http, url: str) -> str | None:
    # Some Njoyn detail URLs include short-lived tokens (e.g., tbtoken/chk). Try a sanitized URL first.
    detail_url = _sanitize_njoyn_detail_url(url)
    try:
        html = http.get_text(detail_url)
    except Exception:
        return None
    soup = BeautifulSoup(html, "html.parser")
    # Common patterns: h1/h2 page header
    for sel in ("h1", "h2", "td.title", ".title"):
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if txt and txt.lower() not in _GENERIC_LINK_TEXT:
                return txt
    # OpenGraph title is common on older templates.
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        t = str(og.get("content")).strip()
        if t and t.lower() not in _GENERIC_LINK_TEXT:
            return t
    for tr in soup.select("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        left = cells[0].get_text(" ", strip=True).lower()
        if left in {"job title", "position title", "title"} or "job title" in left:
            right = cells[1].get_text(" ", strip=True)
            if right and right.lower() not in _GENERIC_LINK_TEXT and not _JOB_ID_ONLY.match(right):
                return right
    # Fallback: document title
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t and t.lower() not in _GENERIC_LINK_TEXT:
            return t
    return None


def _sanitize_njoyn_detail_url(url: str) -> str:
    """
    Njoyn sometimes includes short-lived query tokens (e.g., tbtoken/chk) on detail links.
    Strip those so we can refetch details deterministically.
    """
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        keep_keys = {"clid", "CLID", "page", "Page", "jobid", "Jobid", "brid", "BRID", "lang", "Lang"}
        kept: dict[str, list[str]] = {k: v for k, v in qs.items() if k in keep_keys and v}
        if not kept:
            return url
        new_query = urlencode({k: v[0] for k, v in kept.items()}, doseq=False)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    except Exception:
        return url
