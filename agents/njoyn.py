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
        if self.hospital.entry_url:
            return self._scrape_via_entry_page(app_config)
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

    def _scrape_via_entry_page(self, app_config: "AppConfig") -> list[JobPosting]:  # pragma: no cover
        """
        Some njoyn deployments (e.g., NYGH) sit behind Radware bot protection and require a
        click-through from a referrer page that mints a tokenized listing URL on the fly.

        Approach: open `entry_url` in a real browser, click the configured listing link
        (matched against `url`), and scrape the resulting jobs table directly from the DOM.
        """
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Playwright is required when entry_url is set. Install with "
                "`pip install playwright` and `python -m playwright install chromium`."
            ) from e

        entry_url = self.hospital.entry_url or ""
        listing_host = urlparse(self.hospital.url).netloc
        timeout_ms = app_config.scrape.timeout_seconds * 1000
        max_pages = max(1, app_config.scrape.max_pages)
        self.logger.info(
            "Njoyn scrape start %s via entry page %s",
            self.hospital.hospital,
            entry_url,
        )

        # njoyn is fronted by Radware bot detection. Default Playwright Chromium gets flagged
        # because of `navigator.webdriver`, headless UA fingerprints, and missing JS shims.
        # The combination below (real Chrome UA + AutomationControlled disabled + a small
        # init script that masks the obvious tells) is enough to pass the validate.perfdrive
        # challenge.
        browser_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        stealth_init = """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = window.chrome || { runtime: {} };
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(
                    user_agent=browser_ua,
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                context.add_init_script(stealth_init)
                page = context.new_page()
                page.goto(entry_url, wait_until="domcontentloaded", timeout=timeout_ms)

                link = page.locator(
                    f'a[href*="{listing_host}"][href*="tbtoken"]'
                ).first
                link.wait_for(timeout=timeout_ms)
                with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_ms):
                    link.click()

                seen_urls: set[str] = set()
                postings: list[JobPosting] = []
                for page_index in range(max_pages):
                    page.wait_for_selector(
                        'a[href*="Page=JobDetails"], a[href*="page=JobDetails"], a[href*="page=jobdetails"]',
                        timeout=timeout_ms,
                    )
                    html = page.content()
                    base_url = page.url
                    page_postings = _parse_njoyn_listing_table(
                        html, base_url=base_url, hospital=self.hospital.hospital
                    )
                    fresh = [p for p in page_postings if p.url not in seen_urls]
                    for fp in fresh:
                        seen_urls.add(fp.url)
                    postings.extend(fresh)
                    self.logger.info(
                        "%s: njoyn entry-page %s scraped %s rows (%s new); total %s",
                        self.hospital.hospital,
                        page_index + 1,
                        len(page_postings),
                        len(fresh),
                        len(postings),
                    )

                    next_link = page.get_by_role("link", name="NEXT", exact=True).first
                    try:
                        if next_link.count() == 0:
                            break
                    except Exception:
                        break
                    previous_first = ""
                    try:
                        previous_first = page.locator(
                            'a[href*="Page=JobDetails"], a[href*="page=JobDetails"], a[href*="page=jobdetails"]'
                        ).first.get_attribute("href") or ""
                    except Exception:
                        pass
                    try:
                        next_link.click(timeout=timeout_ms)
                    except Exception:
                        break
                    try:
                        page.wait_for_function(
                            "(prev) => { const a = document.querySelector('a[href*=\"Page=JobDetails\"], a[href*=\"page=JobDetails\"], a[href*=\"page=jobdetails\"]'); return a && a.getAttribute('href') !== prev; }",
                            arg=previous_first,
                            timeout=timeout_ms,
                        )
                    except Exception:
                        break

                return postings
            finally:
                browser.close()


def _parse_njoyn_listing_table(html: str, *, base_url: str, hospital: str) -> list[JobPosting]:
    """
    NYGH-style njoyn listing: a single table with header columns
    [Job Number, Program/Area, Job Title, Category, Job Type, Closing Date].
    The Job Number cell holds a JobDetails link; row metadata lives in the other cells.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[JobPosting] = []

    target_table = None
    for table in soup.find_all("table"):
        headers = [
            (th.get_text(" ", strip=True) or "").lower()
            for th in table.find_all(["th"])
        ]
        if not headers:
            headers = [
                (a.get_text(" ", strip=True) or "").lower()
                for a in table.select("tr:first-child a")
            ]
        if any("job number" in h for h in headers) and any("job title" in h for h in headers):
            target_table = table
            break

    if target_table is None:
        return out

    for tr in target_table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue
        link = cells[0].find("a", href=True)
        if not link:
            continue
        href = (link.get("href") or "").strip()
        if not href or "jobdetails" not in href.lower():
            continue
        title = cells[2].get_text(" ", strip=True)
        if not title:
            continue
        job_type = cells[4].get_text(" ", strip=True) if len(cells) > 4 else ""
        out.append(
            JobPosting(
                hospital=hospital,
                job_title=title,
                location=None,
                url=urljoin(base_url, href),
                date_posted=None,
                job_type=job_type or "Full-Time Permanent",
            )
        )
    return out


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
