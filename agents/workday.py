from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from agents.base import BaseAgent
from models import JobPosting
from utils.browser import BrowserClient
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import AppConfig, HospitalConfig


def _parse_workday_site(url: str) -> tuple[str, str, str]:
    """
    Workday external site URLs typically look like:
      https://<host>/<lang>/<site>
      https://<host>/<site>
    and the JSON endpoint is:
      https://<host>/wday/cxs/<tenant>/<site>/jobs
    where <tenant> is usually the first subdomain segment (but not always).
    """
    parsed = urlparse(url)
    host = f"{parsed.scheme}://{parsed.netloc}"
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"en-US", "fr-CA"}:
        site = parts[1]
    elif len(parts) >= 1:
        site = parts[0]
    else:
        raise ValueError(f"Cannot infer Workday site from URL: {url}")

    tenant = parsed.netloc.split(".")[0]
    return host, tenant, site


class WorkdayAgent(BaseAgent):
    def __init__(self, hospital: "HospitalConfig", *, http, logger: logging.Logger):
        super().__init__(hospital, http=http, logger=logger)
        self.host, self.tenant, self.site = _parse_workday_site(hospital.url)

    def _endpoint(self) -> str:
        return f"{self.host}/wday/cxs/{self.tenant}/{self.site}/jobs"

    def _details_url(self, external_path: str) -> str:
        return urljoin(self.host, external_path)

    def scrape(self, app_config: "AppConfig") -> list[JobPosting]:
        endpoint = self._endpoint()
        self.logger.info("Workday scrape start %s (%s)", self.hospital.hospital, endpoint)

        use_browser = _env_bool("USE_PLAYWRIGHT", default=False)
        try:
            return self._scrape_via_api(app_config)
        except Exception as e:
            if not use_browser:
                raise
            self.logger.warning(
                "Workday API failed for %s; falling back to Playwright (%s: %s)",
                self.hospital.hospital,
                type(e).__name__,
                e,
            )
            return self._scrape_via_browser(app_config)

    def _scrape_via_api(self, app_config: "AppConfig") -> list[JobPosting]:
        endpoint = self._endpoint()
        results: list[JobPosting] = []
        offset = 0
        limit = app_config.scrape.workday_page_size
        # Keep Workday search broad; exact filtering happens post-scrape.
        # Use a small hint to reduce irrelevant results without being overly strict.
        search_text = "RN"
        max_pages = app_config.scrape.max_pages
        pages = 0
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.host,
            "Referer": self.hospital.url,
        }

        while True:
            pages += 1
            if pages > max_pages:
                self.logger.warning("Workday pagination stop after %s pages for %s", max_pages, self.hospital.hospital)
                break
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": search_text,
                "sortBy": "Most recent",
            }
            data = self.http.post_json(endpoint, payload=payload, headers=headers)

            postings = data.get("jobPostings") or []
            if not isinstance(postings, list):
                break
            if not postings:
                break

            for p in postings:
                if not isinstance(p, dict):
                    continue
                title = str(p.get("title") or "").strip()
                if not title:
                    continue
                external_path = str(p.get("externalPath") or "").strip()
                if not external_path:
                    continue
                location = p.get("locationsText")
                posted_raw = p.get("postedOn")

                results.append(
                    JobPosting(
                        hospital=self.hospital.hospital,
                        job_title=title,
                        location=str(location).strip() if location else None,
                        url=self._details_url(external_path),
                        date_posted=_parse_posted_on(posted_raw),
                        job_type="Full-Time Permanent",
                    )
                )

            total = data.get("total")
            if isinstance(total, int):
                offset += limit
                if offset >= total:
                    break
            else:
                if len(postings) < limit:
                    break
                offset += limit

        return results

    def _scrape_via_browser(self, app_config: "AppConfig") -> list[JobPosting]:
        # Workday external sites are typically JS-rendered. We load the listing page and pull job title anchors.
        browser = BrowserClient(timeout_ms=app_config.scrape.timeout_seconds * 1000)
        html = browser.get_html(self.hospital.url)

        try:
            from bs4 import BeautifulSoup  # type: ignore
        except Exception as e:
            raise RuntimeError("BeautifulSoup is required for browser fallback parsing") from e

        soup = BeautifulSoup(html, "html.parser")
        results: list[JobPosting] = []

        # Prefer the canonical job title links.
        anchors = soup.select('a[data-automation-id="jobTitle"][href]')
        if not anchors:
            anchors = soup.select('a[href*="/job/"]')

        seen: set[str] = set()
        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            title = (a.get_text(" ", strip=True) or "").strip()
            if not title or title.lower() in _GENERIC_WORKDAY_TEXT:
                # Try to extract a better title from surrounding card/row context.
                title = _extract_title_from_context(a) or title
            if not title or title.lower() in _GENERIC_WORKDAY_TEXT:
                continue
            url = urljoin(self.host, href)
            if url in seen:
                continue
            seen.add(url)
            results.append(
                JobPosting(
                    hospital=self.hospital.hospital,
                    job_title=title,
                    location=None,
                    url=url,
                    date_posted=None,
                    job_type="Full-Time Permanent",
                )
            )

        return results


def _parse_posted_on(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, str):
        # Workday commonly returns "Posted X Days Ago" or an ISO-ish string depending on tenant.
        # Keep it null unless it's ISO-like (YYYY-MM-DD...).
        s = value.strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            try:
                return date.fromisoformat(s[:10])
            except ValueError:
                return None
        return None
    return None


def _env_bool(key: str, *, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


_GENERIC_WORKDAY_TEXT = {
    "view job details",
    "job details",
    "view",
    "details",
    "apply",
    "apply now",
}


def _extract_title_from_context(a) -> str | None:
    # Walk up a bit and find the longest non-generic text in the card/row.
    parent = a
    for _ in range(4):
        parent = getattr(parent, "parent", None)
        if parent is None:
            break
        try:
            txt = parent.get_text(" ", strip=True)
        except Exception:
            continue
        if not txt:
            continue
        # Keep it conservative: return if it looks like a real title.
        if len(txt) >= 8 and txt.lower() not in _GENERIC_WORKDAY_TEXT:
            # Sometimes this includes multiple fields; take first line-ish chunk.
            return txt.split("  ")[0].strip()
    return None
