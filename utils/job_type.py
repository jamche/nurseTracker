from __future__ import annotations

import re


def infer_job_type(*, job_title: str, current_job_type: str) -> str:
    """
    Infer an employment/job type label from the job title when possible.

    Many boards include employment hints in the title (e.g., "Part Time", "PTT", "Temporary", "Contract"),
    while our scrapers may not reliably extract structured fields. This function prioritizes signals from
    the title and falls back to the current value when no signal is present.
    """
    title = (job_title or "").strip()
    current = (current_job_type or "").strip() or "Unknown"

    if not title:
        return current

    lower = title.lower()

    # Time basis
    time_basis: str | None = None
    if re.search(r"\bptt\b", lower):
        time_basis = "Part-Time"
    elif re.search(r"\bftt\b", lower):
        time_basis = "Full-Time"
    elif re.search(r"\bpt\b", lower) and ("part time" in lower or "pt (" in lower or " pt " in lower):
        time_basis = "Part-Time"
    elif "part time" in lower or "part-time" in lower:
        time_basis = "Part-Time"
    elif "full time" in lower or "full-time" in lower:
        time_basis = "Full-Time"

    # Status/term
    status: str | None = None
    if "casual" in lower:
        status = "Casual"
    elif "contract" in lower:
        status = "Contract"
    elif "temporary" in lower or re.search(r"\btemp\b", lower):
        status = "Temporary"
    elif "permanent" in lower:
        status = "Permanent"

    # If we got any signal, synthesize a normalized label.
    if time_basis or status:
        parts = [p for p in [time_basis, status] if p]
        return " ".join(parts)

    return current

