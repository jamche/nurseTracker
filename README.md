# nurseTracker job scraper

Daily modular scraper that checks multiple hospital job boards for:
`Registered Nurse – Operating Room (Surgical Suite), Full-Time Permanent`

It aggregates results, filters to the target role, writes JSON/CSV outputs, and can email a styled HTML summary. It tracks “seen” posting URLs so it can email only new postings each day.

## Project overview

Hospitals supported:
- Lakeridge Health (custom eRecruit)
- Markham Stouffville / Oak Valley Health (Workday)
- Scarborough Health Network (Workday)
- North York General Hospital (Njoyn)

Key entry points:
- `controller.py`: run once (cron / GitHub Actions)
- `scheduler.py`: optional long-running loop (not needed for cron)
- `config.yaml`: keywords, hospital URLs, output paths
- `.env`: SMTP/email settings and optional browser mode

## Prerequisites

- Python `3.9+`
- OS: macOS/Linux recommended for cron; GitHub Actions workflow assumes Ubuntu
- Network access to the job boards and your SMTP server

Optional (only if a job board is JS-rendered and HTML scrape returns no results):
- Playwright + Chromium

## Installation

1) Create a virtualenv and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional (recommended for full coverage):

```bash
pip install -r requirements-browser.txt
python3 -m playwright install chromium
```

2) Create `.env` from `.env.example` and edit values:

```bash
cp .env.example .env
```

3) Review `config.yaml` (keywords, URLs, output paths).

## Tests

After installing dependencies:

```bash
python3 -m unittest -q
```

## Run

### Local run (no email)

Runs the full scrape, writes outputs, and writes an HTML email preview without sending email:

```bash
python3 controller.py --config config.yaml --email-preview-path output/email_preview.html
```

Outputs:
- `output/jobs.json`
- `output/jobs.csv`
- `output/email_preview.html`
- `output/seen_urls.json` (used to detect “new” postings; only updated after a successful `--send-email`, or with `--update-last-state`)
- `output/run_report.json` (per-hospital status, counts, and errors for the run)
- logs under `logs/`

Debugging tip: if `output/jobs.json` is empty, it may be because filtering excluded everything. To inspect what was scraped before filtering:

```bash
python3 controller.py --config config.yaml --dump-raw --email-preview-path output/email_preview.html
```

This writes `output/raw_scraped.json`.

If you want to test new-postings tracking without emailing:

```bash
python3 controller.py --config config.yaml --update-last-state
```

### Send email (new postings only)

```bash
python3 controller.py --config config.yaml --send-email
```

This updates `output/seen_urls.json` after a successful send, so the next run only emails new URLs.

## Cron (daily)

Example (runs at 7:10am daily; sends email):

```cron
10 7 * * * cd /Users/jamieyeung/Desktop/Projects/nurseTracker && /usr/bin/env bash -lc 'source .venv/bin/activate && python3 controller.py --config config.yaml --send-email >> logs/cron.log 2>&1'
```

## Scheduler (optional)

If you prefer a long-running process over cron:

```bash
python3 scheduler.py --config config.yaml --interval-seconds 86400 --send-email
```

## Playwright (optional)

Some job boards are JS-rendered (notably Workday, and Lakeridge eRecruit’s “view more rows”). This project supports Playwright as an optional dependency:

```bash
pip install playwright
python3 -m playwright install chromium
```

Enable browser fallback (for JS-rendered boards) by setting `USE_PLAYWRIGHT=true` in `.env`.

When `USE_PLAYWRIGHT=true`:
- Lakeridge eRecruit uses Playwright to click “view more rows”/expand the listing.
- Workday uses the JSON endpoint first, and falls back to Playwright if the API returns a 4xx/blocks the request.

On Linux CI (GitHub Actions), Playwright system dependencies are installed via:

```bash
python3 -m playwright install --with-deps chromium
```

## Configuration

### `config.yaml`

- `role.title_groups_all`: list of keyword groups; each group requires at least one match in the job title
- `role.title_groups_mode`: `all` requires all groups; `any` matches if any group hits (useful to capture all RN postings)
- `role.title_exclude_any_of`: optional title exclude list to drop obvious non-target roles
- `role.employment_any_of`: optional/OR employment terms (matches `job_type`); leave empty to disable employment filtering
- `role.employment_exclude_any_of`: optional exclude list for `job_type` (e.g., filter out part-time/casual)
- `hospitals`: list of hospital boards (`type` is one of `workday`, `njoyn`, `erecruit`)
- `hospitals[*].location_include_any_of`: optional per-hospital location filter (e.g., keep only Ajax for Lakeridge)
- `scrape.enrich_detail_titles`: when a listing title is generic (e.g. “View Job Details”), fetch the detail page to extract a real title
- `scrape.enrich_detail_max_requests`: safety cap for how many detail pages can be fetched per run

### `.env` (SMTP and runtime flags)

Required for `--send-email`:
- `SMTP_HOST`, `SMTP_PORT`
- `SMTP_USER`, `SMTP_PASS` (often required; depends on your SMTP server)
- `EMAIL_FROM`
- `EMAIL_TO` (comma-separated supported)

Optional:
- `EMAIL_CC` (comma-separated)
- `EMAIL_SUBJECT_PREFIX`
- `EMAIL_INCLUDE_ALL_RESULTS` (`true` to include all matches; default is new postings only)
- `USE_PLAYWRIGHT` (`true` to enable Playwright fallback for certain agents)

### Pagination / coverage

- Workday uses an API endpoint and is paginated automatically (configurable via `scrape.workday_page_size` and `scrape.max_pages`).
- Njoyn explicitly follows “Next”/pagination links up to `scrape.max_pages`.
- Lakeridge eRecruit’s “view more rows” is handled via Playwright when `USE_PLAYWRIGHT=true` (controlled by `scrape.playwright_expand_rows`).

## Common errors & troubleshooting

- `ModuleNotFoundError: No module named ...`
  - Activate your venv and run `pip install -r requirements.txt`.
- `NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+ (LibreSSL...)`
  - Reinstall deps after updating requirements: `pip install -r requirements.txt` (this repo pins `urllib3<2` for macOS LibreSSL compatibility), or use a Python build linked against OpenSSL (Homebrew/pyenv).
- No results but you expect matches
  - Check `config.yaml` keywords first.
  - Set `USE_PLAYWRIGHT=true` and install Playwright + Chromium (some boards are JS-rendered).
- Workday requests fail (403/429) or return empty results
  - Reduce frequency (daily is fine), and consider enabling Playwright for that board if needed.
- Workday requests fail with `400 Bad Request`
  - Workday tenants sometimes require specific headers/payloads; check `output/run_report.json` for the response body snippet.
  - If it persists, we can add a Playwright-based fallback that scrapes the rendered Workday listings instead of using the JSON endpoint.
- Email fails to send (auth / TLS / blocked login)
  - Verify SMTP settings, ports, and whether your provider requires an “app password” (common with Gmail).

## GitHub Actions (scheduled runs)

This repo includes a scheduled workflow: `.github/workflows/daily-scrape.yml`.

Notes:
- GitHub cron is UTC; adjust the workflow cron to match your local timezone.
- The runner is ephemeral; `output/seen_urls.json` is cached in the workflow to preserve “seen” state between runs (best-effort cache; if it’s evicted, you may resend older postings once).
- Store SMTP values as GitHub Secrets (never commit `.env`).
- If you want Workday + Lakeridge coverage, set repo variable `USE_PLAYWRIGHT=true` so the workflow installs Playwright/Chromium and enables browser fallback.

Recommended repo setup:
- **Variables**: `USE_PLAYWRIGHT=true`
- **Secrets**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`, `EMAIL_TO` (optional: `EMAIL_CC`, `EMAIL_SUBJECT_PREFIX`, `EMAIL_INCLUDE_ALL_RESULTS`)
