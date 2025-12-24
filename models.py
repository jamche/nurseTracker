from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional


@dataclass(frozen=True)
class JobPosting:
    hospital: str
    job_title: str
    location: Optional[str]
    url: str
    date_posted: Optional[date]
    job_type: str

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["date_posted"] = self.date_posted.isoformat() if self.date_posted else None
        return data

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> "JobPosting":
        posted = data.get("date_posted")
        parsed = date.fromisoformat(posted) if posted else None
        return JobPosting(
            hospital=str(data["hospital"]),
            job_title=str(data["job_title"]),
            location=data.get("location"),
            url=str(data["url"]),
            date_posted=parsed,
            job_type=str(data["job_type"]),
        )

