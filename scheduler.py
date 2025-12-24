from __future__ import annotations

import argparse
import time

from controller import run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--interval-seconds", type=int, default=24 * 60 * 60)
    parser.add_argument("--send-email", action="store_true")
    parser.add_argument("--email-preview-path", default="output/email_preview.html")
    parser.add_argument("--update-last-state", action="store_true")
    parser.add_argument("--dump-raw", action="store_true")
    args = parser.parse_args()

    while True:
        rc = run(
            args.config,
            send_email=bool(args.send_email),
            email_preview_path=str(args.email_preview_path) if args.email_preview_path else None,
            dump_raw=bool(args.dump_raw),
            update_last_state=bool(args.update_last_state),
        )
        if rc != 0:
            return rc
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
