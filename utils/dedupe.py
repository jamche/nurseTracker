from __future__ import annotations

from models import JobPosting


def dedupe_by_url(postings: list[JobPosting]) -> list[JobPosting]:
    seen: set[str] = set()
    out: list[JobPosting] = []
    for p in postings:
        key = p.url.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

