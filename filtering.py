from __future__ import annotations

import re
from typing import Iterable

from models import JobPosting


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def keyword_match(text: str, keywords: Iterable[str]) -> bool:
    normalized = _normalize(text)
    for kw in keywords:
        if _normalize(kw) in normalized:
            return True
    return False


def all_keywords_match(text: str, keywords: Iterable[str]) -> bool:
    normalized = _normalize(text)
    for kw in keywords:
        if _normalize(kw) not in normalized:
            return False
    return True


def filter_postings(
    postings: list[JobPosting],
    *,
    title_all_of: list[str],
    title_any_of: list[str],
    employment_all_of: list[str],
) -> list[JobPosting]:
    out: list[JobPosting] = []
    for p in postings:
        if title_all_of and not all_keywords_match(p.job_title, title_all_of):
            continue
        if title_any_of and not keyword_match(p.job_title, title_any_of):
            continue
        if employment_all_of and not all_keywords_match(p.job_type, employment_all_of):
            continue
        out.append(p)
    return out
