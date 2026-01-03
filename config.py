from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional


HospitalType = Literal["workday", "njoyn", "erecruit"]
_HOSPITAL_TYPES: set[str] = {"workday", "njoyn", "erecruit"}


@dataclass(frozen=True)
class HospitalConfig:
    hospital: str
    type: HospitalType
    url: str
    location_include_any_of: list[str]


@dataclass(frozen=True)
class RoleConfig:
    title_groups_mode: TitleGroupsMode
    title_groups_all: list[list[str]]
    title_exclude_any_of: list[str]
    employment_any_of: list[str]
    employment_exclude_any_of: list[str]


@dataclass(frozen=True)
class OutputConfig:
    dir: Path
    json: str
    csv: str
    last_json: str
    seen_urls: str
    run_report: str


@dataclass(frozen=True)
class ScrapeConfig:
    timeout_seconds: int
    retry_attempts: int
    user_agent: str
    max_pages: int
    workday_page_size: int
    workday_search_text: str
    playwright_expand_rows: bool
    enrich_detail_titles: bool
    enrich_detail_max_requests: int


@dataclass(frozen=True)
class EmailConfig:
    include_all_results: bool


@dataclass(frozen=True)
class AppConfig:
    role: RoleConfig
    output: OutputConfig
    scrape: ScrapeConfig
    email: EmailConfig
    hospitals: list[HospitalConfig]


def _require_dict(obj: Any, path: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"Expected mapping at {path}")
    return obj


def load_config(path: str | Path) -> AppConfig:
    try:
        import yaml  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Missing dependency PyYAML. Install with `pip install -r requirements.txt`.") from e

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    root = _require_dict(raw, "root")

    role_raw = _require_dict(root.get("role"), "role")
    output_raw = _require_dict(root.get("output"), "output")
    scrape_raw = _require_dict(root.get("scrape"), "scrape")
    email_raw = _require_dict(root.get("email", {}), "email")

    title_groups_all = role_raw.get("title_groups_all")
    if title_groups_all is None:
        # Back-compat: interpret previous schema (title_all_of + title_any_of).
        all_of = list(role_raw.get("title_all_of") or [])
        any_of = list(role_raw.get("title_any_of") or [])
        title_groups_all = []
        if all_of:
            title_groups_all.append(all_of)
        if any_of:
            title_groups_all.append(any_of)

    if not isinstance(title_groups_all, list):
        raise ValueError("Expected role.title_groups_all to be a list of lists")
    parsed_groups: list[list[str]] = []
    for i, g in enumerate(title_groups_all):
        if not isinstance(g, list):
            raise ValueError(f"Expected role.title_groups_all[{i}] to be a list")
        parsed_groups.append([str(x) for x in g if str(x).strip()])

    title_groups_mode = str(role_raw.get("title_groups_mode", "all")).strip().lower()
    if title_groups_mode not in {"all", "any"}:
        raise ValueError("Expected role.title_groups_mode to be one of: all, any")

    role = RoleConfig(
        title_groups_mode=title_groups_mode,  # type: ignore[arg-type]
        title_groups_all=parsed_groups,
        title_exclude_any_of=[str(x) for x in (role_raw.get("title_exclude_any_of") or []) if str(x).strip()],
        employment_any_of=[str(x) for x in (role_raw.get("employment_any_of") or []) if str(x).strip()],
        employment_exclude_any_of=[
            str(x) for x in (role_raw.get("employment_exclude_any_of") or []) if str(x).strip()
        ],
    )
    output = OutputConfig(
        dir=Path(str(output_raw.get("dir", "output"))),
        json=str(output_raw.get("json", "jobs.json")),
        csv=str(output_raw.get("csv", "jobs.csv")),
        last_json=str(output_raw.get("last_json", "last_jobs.json")),
        seen_urls=str(output_raw.get("seen_urls", "seen_urls.json")),
        run_report=str(output_raw.get("run_report", "run_report.json")),
    )
    scrape = ScrapeConfig(
        timeout_seconds=int(scrape_raw.get("timeout_seconds", 30)),
        retry_attempts=int(scrape_raw.get("retry_attempts", 2)),
        user_agent=str(scrape_raw.get("user_agent", "nurseTracker/1.0")),
        max_pages=int(scrape_raw.get("max_pages", 50)),
        workday_page_size=int(scrape_raw.get("workday_page_size", 50)),
        workday_search_text=str(scrape_raw.get("workday_search_text", "") or ""),
        playwright_expand_rows=bool(scrape_raw.get("playwright_expand_rows", True)),
        enrich_detail_titles=bool(scrape_raw.get("enrich_detail_titles", True)),
        enrich_detail_max_requests=int(scrape_raw.get("enrich_detail_max_requests", 25)),
    )
    email = EmailConfig(include_all_results=bool(email_raw.get("include_all_results", False)))

    hospitals_raw = root.get("hospitals")
    if not isinstance(hospitals_raw, list) or not hospitals_raw:
        raise ValueError("Expected non-empty hospitals list")

    hospitals: list[HospitalConfig] = []
    for i, h in enumerate(hospitals_raw):
        h_dict = _require_dict(h, f"hospitals[{i}]")
        h_type = str(h_dict["type"])
        if h_type not in _HOSPITAL_TYPES:
            raise ValueError(f"Unsupported hospital type at hospitals[{i}].type: {h_type}")
        hospitals.append(
            HospitalConfig(
                hospital=str(h_dict["hospital"]),
                type=h_type,  # type: ignore[arg-type]
                url=str(h_dict["url"]),
                location_include_any_of=[
                    str(x) for x in (h_dict.get("location_include_any_of") or []) if str(x).strip()
                ],
            )
        )

    return AppConfig(role=role, output=output, scrape=scrape, email=email, hospitals=hospitals)
TitleGroupsMode = Literal["all", "any"]
