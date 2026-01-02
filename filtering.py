from __future__ import annotations

import re
from typing import Iterable, Sequence

from models import JobPosting


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def keyword_match(text: str, keywords: Iterable[str]) -> bool:
    normalized = _normalize(text)
    for kw in keywords:
        if keyword_in_text(text, normalized_text=normalized, keyword=str(kw)):
            return True
    return False


def all_keywords_match(text: str, keywords: Iterable[str]) -> bool:
    normalized = _normalize(text)
    for kw in keywords:
        if not keyword_in_text(text, normalized_text=normalized, keyword=str(kw)):
            return False
    return True


def keyword_in_text(text: str, *, normalized_text: str, keyword: str) -> bool:
    kw = keyword.strip()
    if not kw:
        return False

    # For short acronyms (RN/OR/FT), avoid substring matching.
    if len(kw) <= 3 and kw.isalpha():
        return re.search(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE) is not None

    return _normalize(kw) in normalized_text


def groups_match(text: str, groups: Sequence[Sequence[str]], *, mode: str) -> bool:
    normalized = _normalize(text)
    if not groups:
        return True
    if mode == "any":
        for group in groups:
            if keyword_match_with_normalized(text, normalized, group):
                return True
        return False
    # default: "all"
    for group in groups:
        if not keyword_match_with_normalized(text, normalized, group):
            return False
    return True


def keyword_match_with_normalized(text: str, normalized_text: str, keywords: Iterable[str]) -> bool:
    for kw in keywords:
        if keyword_in_text(text, normalized_text=normalized_text, keyword=str(kw)):
            return True
    return False


def filter_postings(
    postings: list[JobPosting],
    *,
    title_groups_all: list[list[str]],
    title_groups_mode: str,
    title_exclude_any_of: list[str],
    employment_any_of: list[str],
    employment_exclude_any_of: list[str],
) -> list[JobPosting]:
    out: list[JobPosting] = []
    for p in postings:
        if title_exclude_any_of and keyword_match(p.job_title, title_exclude_any_of):
            continue
        if title_groups_all and not groups_match(p.job_title, title_groups_all, mode=title_groups_mode):
            continue
        # Employment terms often appear in the title on some boards, and agents may not have a reliable job_type yet.
        employment_text = f"{p.job_type or ''} {p.job_title or ''}".strip()
        if employment_exclude_any_of and keyword_match(employment_text, employment_exclude_any_of):
            continue
        if employment_any_of and not keyword_match(employment_text, employment_any_of):
            continue
        out.append(p)
    return out
