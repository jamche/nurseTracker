from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class BrowserClient:
    timeout_ms: int = 30_000

    def get_html(self, url: str, *, expand_rows: bool = False) -> str:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Playwright is not installed. Install with `pip install playwright` and "
                "`python -m playwright install chromium`."
            ) from e

        with sync_playwright() as p:  # pragma: no cover
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                if expand_rows:
                    _try_expand_rows(page)
                return page.content()
            finally:
                browser.close()


def _try_expand_rows(page) -> None:  # pragma: no cover
    # Heuristics for “view more rows / show more / load more” style tables.
    patterns = [
        r"view more rows",
        r"more rows",
        r"show more",
        r"load more",
        r"view more",
    ]

    # 1) Try to set a “rows per page” dropdown to the largest numeric option.
    try:
        selects = page.query_selector_all("select")
        for sel in selects:
            try:
                options = sel.query_selector_all("option")
                numeric: list[tuple[int, str]] = []
                for opt in options:
                    txt = (opt.inner_text() or "").strip()
                    val = opt.get_attribute("value") or ""
                    m = re.search(r"(\d+)", txt)
                    if m:
                        numeric.append((int(m.group(1)), val))
                if not numeric:
                    continue
                numeric.sort(key=lambda x: x[0], reverse=True)
                _, best_value = numeric[0]
                if best_value:
                    sel.select_option(best_value)
                    page.wait_for_timeout(500)
            except Exception:
                continue
    except Exception:
        pass

    # 2) Click “more” buttons/links repeatedly (bounded).
    for _ in range(20):
        clicked = False
        for pat in patterns:
            try:
                locator = page.get_by_role("button", name=re.compile(pat, re.I))
                if locator.count() > 0:
                    locator.first.click(timeout=1000)
                    page.wait_for_timeout(700)
                    clicked = True
                    break
            except Exception:
                pass
            try:
                locator = page.get_by_text(re.compile(pat, re.I))
                if locator.count() > 0:
                    locator.first.click(timeout=1000)
                    page.wait_for_timeout(700)
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            break
