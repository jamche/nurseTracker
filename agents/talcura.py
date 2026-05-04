from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from agents.base import BaseAgent
from models import JobPosting
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import AppConfig, HospitalConfig


_PARENT_PAGE = "https://sunnybrook.ca/join-our-team/current-opportunities/"
_DETAIL_PATH = "/Cands/Job.aspx"
_DATE_FMT = "%B %d, %Y"


class TalcuraAgent(BaseAgent):
    """
    Sunnybrook (Talcura) careers iframe.

    The Talcura jobs page (sunnybrook.talcura.com) frame-busts when loaded directly,
    so we drive it via the parent page's iframe and apply the category / employment-status
    dropdown filters before scraping.
    """

    def __init__(self, hospital: "HospitalConfig", *, http, logger: logging.Logger):
        super().__init__(hospital, http=http, logger=logger)

    def scrape(self, app_config: "AppConfig") -> list[JobPosting]:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Playwright is required for the Talcura agent. Install with "
                "`pip install playwright` and `python -m playwright install chromium`."
            ) from e

        category = self.hospital.talcura_category
        employment_status = self.hospital.talcura_employment_status
        timeout_ms = app_config.scrape.timeout_seconds * 1000
        max_pages = max(1, app_config.scrape.max_pages)

        self.logger.info(
            "Talcura scrape start %s (category=%s, type=%s)",
            self.hospital.hospital,
            category or "*",
            employment_status or "*",
        )

        with sync_playwright() as p:  # pragma: no cover
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=app_config.scrape.user_agent)
                page = context.new_page()
                self.logger.info("Talcura: navigating to %s", _PARENT_PAGE)
                page.goto(_PARENT_PAGE, wait_until="domcontentloaded", timeout=timeout_ms)

                self.logger.info("Talcura: locating jobs iframe")
                frame = _wait_for_jobs_frame(page, timeout_ms=timeout_ms)
                self.logger.info("Talcura: iframe ready (%s)", frame.url)
                frame.wait_for_selector('a[href*="/Cands/Job.aspx?JobId="]', timeout=timeout_ms)

                if category:
                    self.logger.info("Talcura: applying category=%s", category)
                    _select_combobox_option(frame, "Filter by type", category, timeout_ms=timeout_ms)
                if employment_status:
                    self.logger.info("Talcura: applying employment_status=%s", employment_status)
                    _select_combobox_option(
                        frame, "Filter by employment status", employment_status, timeout_ms=timeout_ms
                    )

                if category or employment_status:
                    self.logger.info("Talcura: submitting search")
                    _click_search(frame, timeout_ms=timeout_ms)

                seen_urls: set[str] = set()
                postings: list[JobPosting] = []
                base = "https://sunnybrook.talcura.com"
                for page_index in range(max_pages):
                    frame.wait_for_selector(
                        'a[href*="/Cands/Job.aspx?JobId="]', timeout=timeout_ms
                    )
                    page_postings = _scrape_listing_page(frame, base_url=base, hospital=self.hospital.hospital)
                    fresh = [p for p in page_postings if p.url not in seen_urls]
                    for fp in fresh:
                        seen_urls.add(fp.url)
                    postings.extend(fresh)
                    self.logger.info(
                        "Talcura: page %s scraped %s rows (%s new); total %s",
                        page_index + 1,
                        len(page_postings),
                        len(fresh),
                        len(postings),
                    )

                    if not _go_to_next_page(frame, timeout_ms=timeout_ms):
                        break

                return postings
            finally:
                browser.close()


def _wait_for_jobs_frame(page, *, timeout_ms: int):  # pragma: no cover
    """Find the iframe whose URL points at sunnybrook.talcura.com/cands/jobs.aspx."""
    deadline = page.evaluate("() => Date.now()") + timeout_ms
    while True:
        for f in page.frames:
            url = f.url or ""
            if "talcura.com" in url and "jobs.aspx" in url.lower():
                return f
        now = page.evaluate("() => Date.now()")
        if now >= deadline:
            raise TimeoutError("Timed out waiting for Talcura jobs iframe")
        page.wait_for_timeout(250)


def _select_combobox_option(frame, combo_title: str, option_text: str, *, timeout_ms: int) -> None:  # pragma: no cover
    """
    Open a Telerik RadComboBox by its surrounding title attribute and click the option whose
    accessible name matches `option_text`. Telerik combos animate open/closed, so give them a beat.
    """
    toggle = frame.locator(f'div[title="{combo_title}"] button').first
    toggle.wait_for(timeout=timeout_ms)
    toggle.click(timeout=timeout_ms)
    option = frame.get_by_role("option", name=option_text, exact=True).first
    option.wait_for(timeout=timeout_ms)
    option.click(timeout=timeout_ms)
    frame.page.wait_for_timeout(300)


def _click_search(frame, *, timeout_ms: int) -> None:  # pragma: no cover
    btn = frame.get_by_role("button", name="Search Careers", exact=True).first
    # Capture a stable signal from the current listing so we can detect the WebForms postback.
    previous = _capture_listing_signature(frame)
    btn.click(timeout=timeout_ms)
    _wait_for_listing_change(frame, previous=previous, timeout_ms=timeout_ms)


def _go_to_next_page(frame, *, timeout_ms: int) -> bool:  # pragma: no cover
    """
    Click the pager's "Next Page" button if it's enabled, then wait for the listing to refresh.
    Returns True if we advanced, False if there is no next page (button missing/disabled or
    clicking it didn't change the listing fingerprint within the timeout).
    """
    state = frame.evaluate(
        """() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => (b.getAttribute('aria-label') || b.title || b.textContent || '').trim() === 'Next Page');
            if (!btn) return { present: false, disabled: true };
            const cls = btn.className || '';
            // Talcura/Telerik signals disabled pager buttons by prepending 'return false;'
            // to the onclick handler (no aria-disabled, no disabled attribute, no class change).
            const onclick = btn.getAttribute('onclick') || '';
            const disabled = btn.disabled
                || btn.getAttribute('aria-disabled') === 'true'
                || /\\bdisabled\\b|rdpDisabled/i.test(cls)
                || /^\\s*return\\s+false\\s*;/i.test(onclick);
            return { present: true, disabled };
        }"""
    ) or {"present": False, "disabled": True}
    if not state.get("present") or state.get("disabled"):
        return False

    next_btn = frame.get_by_role("button", name="Next Page", exact=True).first
    previous = _capture_listing_signature(frame)
    try:
        next_btn.click(timeout=timeout_ms)
    except Exception:
        return False

    return _wait_for_listing_change(frame, previous=previous, timeout_ms=timeout_ms)


_SIGNATURE_JS = """
() => {
  const a = document.querySelector('a[href*="/Cands/Job.aspx?JobId="]');
  const pager = document.querySelector('[id*="dpJobsPager"]');
  return ((a && a.getAttribute('href')) || '') + '|' + ((pager && pager.innerText) || '').trim();
}
"""


def _capture_listing_signature(frame) -> str:  # pragma: no cover
    """
    Fingerprint the current results region (first job href + pager text) so we can detect
    when a WebForms postback has replaced the listing. Uses a single page.evaluate to avoid
    Playwright's per-locator auto-waits.
    """
    try:
        return frame.evaluate(_SIGNATURE_JS) or ""
    except Exception:
        return ""


def _wait_for_listing_change(frame, *, previous: str, timeout_ms: int) -> bool:  # pragma: no cover
    """
    Poll until the listing fingerprint differs from `previous`. Returns True on change,
    False on timeout (meaning the click had no effect — typically end of pagination).
    """
    deadline_js = "() => Date.now()"
    deadline = frame.evaluate(deadline_js) + timeout_ms
    while True:
        current = _capture_listing_signature(frame)
        if current and current != previous:
            return True
        if frame.evaluate(deadline_js) >= deadline:
            return False
        frame.page.wait_for_timeout(200)


def _scrape_listing_page(frame, *, base_url: str, hospital: str) -> list[JobPosting]:  # pragma: no cover
    """
    Each result row contains an anchor whose visible text holds the job title and metadata
    (e.g., "Featured", "Regular full-time", "Posted on May 04, 2026").
    Pull title, employment-type, and posted date from the anchor's children.
    """
    items = frame.locator('ul li a[href*="/Cands/Job.aspx?JobId="]')
    n = items.count()
    out: list[JobPosting] = []
    for i in range(n):
        a = items.nth(i)
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if not href:
            continue
        url = urljoin(base_url, href)

        spans = a.locator("div, span")
        title = ""
        job_type = ""
        date_posted = None
        try:
            count = spans.count()
        except Exception:
            count = 0
        for j in range(count):
            try:
                txt = (spans.nth(j).inner_text() or "").strip()
            except Exception:
                continue
            if not txt:
                continue
            low = txt.lower()
            if low == "featured":
                continue
            if low.startswith("posted on"):
                parsed = _parse_posted_date(txt)
                if parsed:
                    date_posted = parsed
                continue
            if _looks_like_employment_status(txt):
                job_type = txt
                continue
            if not title or len(txt) > len(title):
                title = txt

        if not title:
            try:
                title = (a.inner_text() or "").strip()
            except Exception:
                title = ""

        title = _strip_metadata_suffix(title, job_type=job_type, date_posted_raw=_format_iso_date(date_posted))
        if not title:
            continue
        out.append(
            JobPosting(
                hospital=hospital,
                job_title=title,
                location=None,
                url=url,
                date_posted=date_posted,
                job_type=job_type or "Full-Time Permanent",
            )
        )
    return out


_EMPLOYMENT_STATUSES = {
    "casual",
    "regular full-time",
    "regular part-time",
    "reduced full-time",
    "temporary full-time",
    "temporary casual",
    "temporary part-time",
}


def _looks_like_employment_status(s: str) -> bool:
    return s.strip().lower() in _EMPLOYMENT_STATUSES


def _parse_posted_date(s: str):
    m = re.match(r"\s*Posted on\s+(.*)", s, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).strip(), _DATE_FMT).date()
    except Exception:
        return None


def _format_iso_date(d) -> str:
    return d.isoformat() if d else ""


def _strip_metadata_suffix(title: str, *, job_type: str, date_posted_raw: str) -> str:
    """
    The anchor's combined inner_text often ends with the employment status and "Posted on ..."
    metadata. Trim those off to keep just the job title.
    """
    out = (title or "").strip()
    if not out:
        return out
    # Drop trailing "Posted on ..." chunks.
    out = re.sub(r"\s*Posted on\s+\w+\s+\d{1,2},\s*\d{4}\s*$", "", out, flags=re.IGNORECASE).strip()
    # Drop trailing employment status (case-insensitive) if present.
    if job_type:
        pattern = r"\s*" + re.escape(job_type) + r"\s*$"
        out = re.sub(pattern, "", out, flags=re.IGNORECASE).strip()
    out = re.sub(r"^\s*Featured\s+", "", out, flags=re.IGNORECASE).strip()
    return out
