from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable, Optional


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]
    email_from: str
    email_to: list[str]
    email_cc: list[str]
    subject_prefix: str


def _split_emails(value: str) -> list[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items


def load_smtp_config_from_env() -> SmtpConfig:
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip() or None
    password = os.environ.get("SMTP_PASS", "").strip() or None
    email_from = os.environ.get("EMAIL_FROM", "").strip() or (user or "")
    email_to = _split_emails(os.environ.get("EMAIL_TO", ""))
    email_cc = _split_emails(os.environ.get("EMAIL_CC", ""))
    subject_prefix = os.environ.get("EMAIL_SUBJECT_PREFIX", "[nurseTracker]").strip()

    if not host:
        raise ValueError("Missing SMTP_HOST")
    if not email_from:
        raise ValueError("Missing EMAIL_FROM (or SMTP_USER)")
    if not email_to:
        raise ValueError("Missing EMAIL_TO")

    return SmtpConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        email_from=email_from,
        email_to=email_to,
        email_cc=email_cc,
        subject_prefix=subject_prefix,
    )


def send_html_email(*, smtp: SmtpConfig, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{smtp.subject_prefix} {subject}".strip()
    msg["From"] = smtp.email_from
    msg["To"] = ", ".join(smtp.email_to)
    if smtp.email_cc:
        msg["Cc"] = ", ".join(smtp.email_cc)

    msg.attach(MIMEText(html, "html", "utf-8"))

    recipients = smtp.email_to + smtp.email_cc
    with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        if smtp.user and smtp.password:
            server.login(smtp.user, smtp.password)
        server.sendmail(smtp.email_from, recipients, msg.as_string())

