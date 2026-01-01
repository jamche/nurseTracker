#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract job_title fields from raw_scraped.json as a JSON array.")
    parser.add_argument("input", nargs="?", default="output/raw_scraped.json")
    parser.add_argument("--out", default="", help="Optional output path (writes JSON array). If omitted, prints to stdout.")
    args = parser.parse_args()

    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON array in {input_path}")

    titles: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = item.get("job_title")
        if isinstance(title, str):
            title = title.strip()
            if title:
                titles.append(title)

    out_json = json.dumps(titles, indent=2, ensure_ascii=False)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_json + "\n", encoding="utf-8")
    else:
        print(out_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

