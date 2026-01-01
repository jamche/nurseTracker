from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv
from tenacity import RetryError

from agents.lakeridge import LakeridgeERecruitAgent
from agents.njoyn import NjoynAgent
from agents.workday import WorkdayAgent
from config import AppConfig, HospitalConfig, load_config
from filtering import filter_postings, keyword_match
from models import JobPosting
from notifiers.emailer import load_smtp_config_from_env, send_html_email
from rendering.email_templates import render_jobs_email
from utils.dedupe import dedupe_by_url
from utils.http import HttpClient
from utils.logging_setup import setup_logging
from utils.state import read_seen_urls, write_seen_urls


@dataclass
class HospitalRunResult:
    hospital: str
    type: str
    url: str
    status: str  # "ok" | "failed"
    attempts: int
    scraped_count: int
    matched_count: int
    duration_seconds: float
    error: Optional[str] = None
    warnings: list[str] | None = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--send-email", action="store_true", help="Send the email after scraping and filtering")
    parser.add_argument(
        "--email-preview-path",
        default="output/email_preview.html",
        help="Write the rendered HTML email to this path (useful for local review)",
    )
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help="Write raw scraped postings (pre-filter) to output/raw_scraped.json for debugging",
    )
    parser.add_argument(
        "--update-last-state",
        action="store_true",
        help="Update output/seen_urls.json (and output/last_jobs.json) even if --send-email is not used",
    )
    args = parser.parse_args()
    return run(
        args.config,
        send_email=bool(args.send_email),
        email_preview_path=str(args.email_preview_path) if args.email_preview_path else None,
        dump_raw=bool(args.dump_raw),
        update_last_state=bool(args.update_last_state),
    )


def run(
    config_path: str,
    *,
    send_email: bool,
    email_preview_path: str | None,
    dump_raw: bool,
    update_last_state: bool,
) -> int:

    load_dotenv()
    run_started_at = datetime.now()
    app_config = load_config(config_path)

    output_dir = app_config.output.dir
    output_dir.mkdir(parents=True, exist_ok=True)

    log_dir = Path("logs")
    logger = setup_logging(log_dir)

    http = HttpClient(timeout_seconds=app_config.scrape.timeout_seconds, user_agent=app_config.scrape.user_agent)

    all_postings: list[JobPosting] = []
    failures: list[dict[str, str]] = []
    run_results: list[HospitalRunResult] = []

    for hospital in app_config.hospitals:
        t0 = perf_counter()
        postings, error, attempts = _run_agent_with_retry(app_config, hospital=hospital, http=http, logger=logger)
        duration = perf_counter() - t0
        if error:
            failures.append({"hospital": hospital.hospital, "error": error})
            run_results.append(
                HospitalRunResult(
                    hospital=hospital.hospital,
                    type=hospital.type,
                    url=hospital.url,
                    status="failed",
                    attempts=attempts,
                    scraped_count=0,
                    matched_count=0,
                    duration_seconds=duration,
                    error=error,
                    warnings=None,
                )
            )
        else:
            warnings: list[str] = []
            if len(postings) == 0:
                warnings.append("scraped_zero_postings")
            run_results.append(
                HospitalRunResult(
                    hospital=hospital.hospital,
                    type=hospital.type,
                    url=hospital.url,
                    status="ok",
                    attempts=attempts,
                    scraped_count=len(postings),
                    matched_count=0,
                    duration_seconds=duration,
                    error=None,
                    warnings=warnings or None,
                )
            )
        all_postings.extend(postings)

    if dump_raw:
        raw_path = output_dir / "raw_scraped.json"
        _write_json(raw_path, all_postings)
        logger.info("Wrote raw scraped postings to %s", str(raw_path))

    filtered = filter_postings(
        all_postings,
        title_groups_all=app_config.role.title_groups_all,
        title_groups_mode=app_config.role.title_groups_mode,
        title_exclude_any_of=app_config.role.title_exclude_any_of,
        employment_any_of=app_config.role.employment_any_of,
        employment_exclude_any_of=app_config.role.employment_exclude_any_of,
    )
    filtered = _apply_hospital_location_filters(filtered, app_config)
    filtered = dedupe_by_url(filtered)

    filtered_sorted = sorted(filtered, key=lambda p: (p.hospital.lower(), p.job_title.lower(), p.url))
    matched_by_hospital: dict[str, int] = {}
    for p in filtered_sorted:
        matched_by_hospital[p.hospital] = matched_by_hospital.get(p.hospital, 0) + 1
    for r in run_results:
        r.matched_count = matched_by_hospital.get(r.hospital, 0)
        if r.status == "ok" and r.matched_count == 0:
            r.warnings = (r.warnings or []) + ["matched_zero_postings"]

    jobs_json_path = output_dir / app_config.output.json
    jobs_csv_path = output_dir / app_config.output.csv
    last_json_path = output_dir / app_config.output.last_json
    seen_urls_path = output_dir / app_config.output.seen_urls
    run_report_path = output_dir / app_config.output.run_report

    _write_json(jobs_json_path, filtered_sorted)
    _write_csv(jobs_csv_path, filtered_sorted)
    _write_run_report(
        run_report_path,
        run_started_at=run_started_at,
        config_path=config_path,
        run_results=run_results,
        matched_count=len(filtered_sorted),
        failures=failures,
    )

    seen_urls = read_seen_urls(seen_urls_path)
    new_jobs = [p for p in filtered_sorted if p.url not in seen_urls]

    include_all = _env_bool("EMAIL_INCLUDE_ALL_RESULTS", default=app_config.email.include_all_results)
    subject, html = render_jobs_email(
        subject_title="RN Operating Room — daily scrape",
        run_at=datetime.now(),
        new_jobs=new_jobs,
        all_jobs=filtered_sorted if include_all else None,
        failures=failures or None,
    )

    if email_preview_path:
        preview_path = Path(email_preview_path)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(html, encoding="utf-8")
        logger.info("Wrote email preview to %s", str(preview_path))

    if send_email:
        try:
            smtp = load_smtp_config_from_env()
            send_html_email(smtp=smtp, subject=subject, html=html)
            logger.info("Email sent to %s", ",".join(smtp.email_to))
            _write_json(last_json_path, filtered_sorted)
            write_seen_urls(seen_urls_path, seen_urls | {p.url for p in filtered_sorted})
        except Exception as e:
            logger.exception("Email send failed: %s", e)
            return 2
    elif update_last_state:
        _write_json(last_json_path, filtered_sorted)
        write_seen_urls(seen_urls_path, seen_urls | {p.url for p in filtered_sorted})
        logger.info("Updated state at %s (without sending email)", str(seen_urls_path))
    else:
        logger.info("Email skipped (use --send-email). Last state not updated.")

    failed_names = [f.get("hospital", "") for f in failures if f.get("hospital")]
    succeeded = sum(1 for r in run_results if r.status == "ok")
    failed = sum(1 for r in run_results if r.status == "failed")
    scraped_total = sum(r.scraped_count for r in run_results if r.status == "ok")
    zero_scraped = [r.hospital for r in run_results if r.status == "ok" and r.scraped_count == 0]
    zero_matched = [r.hospital for r in run_results if r.status == "ok" and r.matched_count == 0]
    logger.info(
        "Done. Hospitals=%s Succeeded=%s Failed=%s Scraped=%s Matched=%s New=%s FailedHospitals=%s ZeroScraped=%s ZeroMatched=%s",
        len(run_results),
        succeeded,
        failed,
        scraped_total,
        len(filtered_sorted),
        len(new_jobs),
        ",".join(failed_names) if failed_names else "none",
        ",".join(zero_scraped) if zero_scraped else "none",
        ",".join(zero_matched) if zero_matched else "none",
    )
    return 0


def _run_agent_with_retry(
    app_config: AppConfig,
    *,
    hospital: HospitalConfig,
    http: HttpClient,
    logger,
) -> tuple[list[JobPosting], str | None, int]:
    agent = _build_agent(hospital, http=http, logger=logger)
    last_error: str | None = None
    attempts = 0
    for attempt in range(1, app_config.scrape.retry_attempts + 1):
        attempts = attempt
        try:
            postings = agent.scrape(app_config)
            logger.info("%s: scraped %s postings", hospital.hospital, len(postings))
            return postings, None, attempts
        except Exception as e:
            last_error = f"attempt {attempt}: {_format_exception_short(e)}"
            logger.exception("%s: scrape failed (%s)", hospital.hospital, last_error)
            _append_hospital_error_log(hospital.hospital, last_error)
    return [], last_error, attempts


def _build_agent(hospital: HospitalConfig, *, http: HttpClient, logger):
    if hospital.type == "workday":
        return WorkdayAgent(hospital, http=http, logger=logger)
    if hospital.type == "njoyn":
        return NjoynAgent(hospital, http=http, logger=logger)
    if hospital.type == "erecruit":
        return LakeridgeERecruitAgent(hospital, http=http, logger=logger)
    raise ValueError(f"Unknown hospital type: {hospital.type}")


def _apply_hospital_location_filters(postings: list[JobPosting], app_config: AppConfig) -> list[JobPosting]:
    by_name = {h.hospital: h for h in app_config.hospitals}
    out: list[JobPosting] = []
    for p in postings:
        h = by_name.get(p.hospital)
        if h and h.location_include_any_of:
            if not p.location:
                continue
            if not keyword_match(p.location, h.location_include_any_of):
                continue
        out.append(p)
    return out


def _write_json(path: Path, postings: list[JobPosting]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [p.to_json_dict() for p in postings]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, postings: list[JobPosting]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([p.to_json_dict() for p in postings])
    if df.empty:
        df = pd.DataFrame(columns=["hospital", "job_title", "location", "url", "date_posted", "job_type"])
    df.to_csv(path, index=False)


def _read_json(path: Path) -> list[JobPosting]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [JobPosting.from_json_dict(x) for x in raw if isinstance(x, dict)]
    except Exception:
        return []

def _write_run_report(
    path: Path,
    *,
    run_started_at: datetime,
    config_path: str,
    run_results: list[HospitalRunResult],
    matched_count: int,
    failures: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "run_started_at": run_started_at.isoformat(timespec="seconds"),
        "config_path": config_path,
        "totals": {
            "hospitals": len(run_results),
            "succeeded": sum(1 for r in run_results if r.status == "ok"),
            "failed": sum(1 for r in run_results if r.status == "failed"),
            "scraped": sum(r.scraped_count for r in run_results if r.status == "ok"),
            "matched": matched_count,
        },
        "results": [asdict(r) for r in run_results],
        "failures": failures,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _format_exception_short(e: Exception) -> str:
    if isinstance(e, RetryError):
        last = getattr(e, "last_attempt", None)
        inner = getattr(last, "exception", None)
        if callable(inner):
            try:
                ie = inner()
                return f"RetryError[{type(ie).__name__}: {ie}]"
            except Exception:
                return f"{type(e).__name__}: {e}"
        return f"{type(e).__name__}: {e}"
    return f"{type(e).__name__}: {e}"

 


def _env_bool(key: str, *, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _append_hospital_error_log(hospital_name: str, message: str) -> None:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in hospital_name).strip("_")
    path = Path("logs") / f"{slug}.log"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="ignore") as f:
        f.write(f"{ts} {message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
