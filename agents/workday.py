from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from agents.base import BaseAgent
from models import JobPosting
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

        results: list[JobPosting] = []
        offset = 0
        limit = app_config.scrape.workday_page_size
        search_text = " ".join([*app_config.role.title_all_of, *app_config.role.title_any_of]).strip()
        max_pages = app_config.scrape.max_pages
        pages = 0

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
            }
            data = self.http.post_json(endpoint, payload=payload)

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
