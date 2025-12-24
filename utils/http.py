from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from requests import HTTPError


@dataclass(frozen=True)
class HttpClient:
    timeout_seconds: int
    user_agent: str

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": self.user_agent, "Accept": "*/*"})
        return s

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
    def get_text(self, url: str, *, params: Optional[dict[str, Any]] = None) -> str:
        with self._session() as s:
            resp = s.get(url, params=params, timeout=self.timeout_seconds)
            try:
                resp.raise_for_status()
            except HTTPError as e:
                raise HTTPError(_http_error_details(resp), response=resp, request=resp.request) from e
            return resp.text

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
    def post_json(self, url: str, *, payload: dict[str, Any], headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        with self._session() as s:
            hdrs = {"Content-Type": "application/json"}
            if headers:
                hdrs.update(headers)
            resp = s.post(url, json=payload, headers=hdrs, timeout=self.timeout_seconds)
            try:
                resp.raise_for_status()
            except HTTPError as e:
                raise HTTPError(_http_error_details(resp), response=resp, request=resp.request) from e
            return resp.json()


def _http_error_details(resp: requests.Response) -> str:
    snippet = ""
    try:
        txt = resp.text or ""
        snippet = txt.strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
    except Exception:
        snippet = ""
    base = f"{resp.status_code} {resp.reason} for url: {resp.url}"
    return f"{base} body={snippet}" if snippet else base
