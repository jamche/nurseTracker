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
        """
        Workday's cxs API commonly returns externalPath values like:
          /job/<location>/<slug>
        but the user-facing URL that works reliably is typically:
          /en-US/<site>/details/<slug>
        """
        path = (external_path or "").strip()
        if not path:
            return self.hospital.url

        # If the link already points to the external site, keep it.
        if "/details/" in path or f"/{self.site}/" in path:
            return urljoin(self.host, path)

        slug = path.rstrip("/").split("/")[-1]
        return f"{self.host}/en-US/{self.site}/details/{slug}"

    def _normalize_href_to_details(self, href: str) -> str:
        h = (href or "").strip()
        if not h:
            return self.hospital.url
        if "/details/" in h:
            return urljoin(self.host, h)
        if "/job/" in h:
            slug = h.rstrip("/").split("/")[-1]
            return f"{self.host}/en-US/{self.site}/details/{slug}"
        return urljoin(self.host, h)

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
        # Empty search_text fetches all postings; filtering happens post-scrape.
        search_text = app_config.scrape.workday_search_text
        max_pages = app_config.scrape.max_pages
        pages = 0
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.host,
            "Referer": self.hospital.url,
        }
        effective_total: int | None = None

        while True:
            pages += 1
            if pages > max_pages:
                self.logger.warning("Workday pagination stop after %s pages for %s", max_pages, self.hospital.hospital)
                break
            payload: dict[str, Any] = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "sortBy": "Most recent",
            }
            # Some tenants behave differently when searchText is explicitly empty;
            # omit the field entirely to request the unfiltered listing.
            if search_text:
                payload["searchText"] = search_text
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
            # Some tenants return total=0 on subsequent pages even though results exist.
            # Treat total=0 as "unknown" unless it's the first page and postings are empty.
            received_total = total if isinstance(total, int) else None
            if isinstance(received_total, int) and received_total > 0:
                effective_total = received_total

            if effective_total is not None:
                self.logger.info(
                    "%s: Workday page %s offset=%s limit=%s total=%s",
                    self.hospital.hospital,
                    pages,
                    offset,
                    limit,
                    effective_total,
                )
                offset += limit
                if offset >= effective_total:
                    break
            else:
                # No reliable total; continue until a short/empty page.
                offset += limit
                if len(postings) < limit:
                    break

        return results

    def _scrape_via_browser(self, app_config: "AppConfig") -> list[JobPosting]:
        browser = BrowserClient(timeout_ms=app_config.scrape.timeout_seconds * 1000)
        pairs = browser.get_workday_job_links(self.hospital.url, max_iterations=app_config.scrape.max_pages)

        results: list[JobPosting] = []
        seen: set[str] = set()
        for title, href in pairs:
            title = (title or "").strip()
            href = (href or "").strip()
            if not title or title.lower() in _GENERIC_WORKDAY_TEXT:
                continue
            url = self._normalize_href_to_details(href)
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
