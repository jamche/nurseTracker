from __future__ import annotations

import json
from pathlib import Path


def read_seen_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return set()
        return {str(x) for x in raw if isinstance(x, str) and x.strip()}
    except Exception:
        return set()


def write_seen_urls(path: Path, urls: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = sorted({u.strip() for u in urls if u and u.strip()})
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

