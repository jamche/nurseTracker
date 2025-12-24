from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential


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
            resp.raise_for_status()
            return resp.text

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
    def post_json(self, url: str, *, payload: dict[str, Any], headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        with self._session() as s:
            hdrs = {"Content-Type": "application/json"}
            if headers:
                hdrs.update(headers)
            resp = s.post(url, json=payload, headers=hdrs, timeout=self.timeout_seconds)
            resp.raise_for_status()
            return resp.json()

