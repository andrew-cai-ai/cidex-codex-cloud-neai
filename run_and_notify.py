#!/usr/bin/env python3
"""
Run the AI OSS Radar, self-test it, and email the digest.

Gmail sending uses SMTP environment variables so credentials never need to be
stored in the repository. Use --dry-run-email to verify rendering without
sending.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import ai_radar


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "latest.md"
EMAIL_LOG_PATH = ROOT / "reports" / "last_email.txt"
EMAIL_ENV_PATH = ROOT / "config" / "email.env"
RAW_DIR = ROOT / "data" / "raw"


@dataclass
class StepResult:
    name: str
    ok: bool
    output: str


def run_command(name: str, command: list[str]) -> StepResult:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    return StepResult(name=name, ok=proc.returncode == 0, output=proc.stdout.strip())


def load_env_file(path: Path = EMAIL_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def run_self_tests() -> list[StepResult]:
    return [
        run_command("compile", [sys.executable, "-m", "py_compile", "ai_radar.py", "run_and_notify.py"]),
        run_command("unit-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ]


def run_radar(args: argparse.Namespace) -> StepResult:
    command = [
        sys.executable,
        "ai_radar.py",
        "--days",
        str(args.days),
        "--max-items",
        str(args.max_items),
        "--per-query",
        str(args.per_query),
        "--hn-per-query",
        str(args.hn_per_query),
        "--readme-limit",
        str(args.readme_limit),
    ]
    result = run_command("radar", command)
    transient_markers = [
        "API rate limit exceeded",
        "Connection reset by peer",
        "timed out",
        "Temporary failure",
        "Remote end closed connection",
        "HTTP 403",
        "HTTP 429",
        "HTTP 500",
        "HTTP 502",
        "HTTP 503",
        "HTTP 504",
    ]
    if result.ok or not any(marker in result.output for marker in transient_markers):
        return result

    fallback = [
        sys.executable,
        "ai_radar.py",
        "--days",
        str(args.days),
        "--max-items",
        str(args.max_items),
        "--per-query",
        str(args.fallback_per_query),
        "--hn-per-query",
        str(args.hn_per_query),
        "--readme-limit",
        str(args.fallback_readme_limit),
    ]
    retry = run_command("radar-fallback", fallback)
    retry.output = result.output + "\n\nFallback retry:\n" + retry.output
    return retry


def extract_section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = idx + 1
            break
    if start is None:
        return []

    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip():
            section.append(line)
    return section


def top_projects_from_table(text: str, limit: int = 10) -> list[str]:
    projects: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.strip() == "## Top Open-Source Projects":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("| "):
            continue
        if line.startswith("| #") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 8:
            continue
        rank, project, score, stars, lang, updated, tags, why = cells[:8]
        project_name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", project).replace(" NEW", "")
        projects.append(f"{rank}. {project_name} - score {score}, {stars} stars, {lang}, {tags}; {why}")
        if len(projects) >= limit:
            break
    return projects


def truncate(value: str, length: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def load_latest_raw() -> dict | None:
    raw_files = sorted(RAW_DIR.glob("*.json"))
    if not raw_files:
        return None
    try:
        return json.loads(raw_files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def repo_by_name(raw: dict | None) -> dict[str, dict]:
    if not raw:
        return {}
    return {repo.get("full_name"): repo for repo in raw.get("repos", []) if repo.get("full_name")}


def format_tags(tags: list[str], limit: int = 2) -> str:
    if not tags:
        return "general"
    return ", ".join(tags[:limit])


def concise_digest_from_raw(raw: dict | None) -> tuple[list[str], list[str], list[str], list[str], int]:
    """Return primary_pick lines, rest_candidates, new_preview, hn_items, extra_new_count."""
    if not raw:
        return [], [], [], [], 0

    repos = repo_by_name(raw)
    scores = raw.get("scores", [])
    primary_pick: list[str] = []
    rest_candidates: list[str] = []
    new_preview: list[str] = []
    hn_items: list[str] = []
    new_items_all: list[str] = []

    if scores:
        top = scores[0]
        repo = repos.get(top["full_name"], {})
        url = repo.get("html_url") or f"https://github.com/{top['full_name']}"
        hook = truncate(repo.get("description") or "", 72)
        move = truncate(
            ai_radar.leverage_note(top.get("tags") or [], "", repo.get("description") or ""),
            88,
        )
        primary_pick = [
            f"{top['full_name']} — {hook}",
            f"→ {url}",
            f"动作: {move}",
        ]

    for idx, item in enumerate(scores[3:7], 4):
        repo = repos.get(item["full_name"], {})
        stars = int(repo.get("stargazers_count") or 0)
        tags = format_tags(item.get("tags") or [])
        desc = truncate(repo.get("description") or "", 56)
        rest_candidates.append(f"{idx}. {item['full_name']} — {stars:,}★, {tags} · {desc}")

    for item in scores:
        if not item.get("new"):
            continue
        tags = format_tags(item.get("tags") or [])
        new_items_all.append(f"- {item['full_name']} — score {item['score']}, {tags}")

    new_preview = new_items_all[:3]
    extra_new_count = max(0, len(new_items_all) - len(new_preview))

    for story in (raw.get("external_hn_hits") or [])[:3]:
        title = truncate(story.get("title") or "", 80)
        hn_items.append(f"- {title} ({story.get('points', 0)} pts / {story.get('comments', 0)} comments)")

    return primary_pick, rest_candidates, new_preview, hn_items, extra_new_count


def build_email_body(test_results: list[StepResult], radar_result: StepResult, report_text: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    warnings = extract_section(report_text, "Collection Warnings")[:3]
    raw = load_latest_raw()
    primary_pick, rest_candidates, new_preview, hn_items, extra_new_count = concise_digest_from_raw(raw)

    if not primary_pick:
        picks = extract_section(report_text, "Executive Picks")[:3]
        if picks:
            primary_pick = ["（见完整报告 Executive Picks）", picks[0]]

    all_ok = all(result.ok for result in test_results + [radar_result])
    status_label = "OK" if all_ok else "ATTENTION"

    body = [f"AI OSS Radar · {now} · {status_label}", ""]

    if primary_pick:
        body.append("今日主推:")
        body.extend(primary_pick)
    else:
        body.append("今日主推: 暂无高优先级项目。")

    if rest_candidates:
        body.extend(["", "其余候选 (#4–#7):"])
        body.extend(rest_candidates)

    if new_preview:
        body.append("")
        if extra_new_count:
            body.append(f"新上榜 (另有 {extra_new_count} 个见完整报告):")
        else:
            body.append("新上榜:")
        body.extend(new_preview)

    if hn_items:
        body.extend(["", "社区信号:"])
        body.extend(hn_items)

    if warnings:
        body.extend(["", "采集异常:"])
        body.extend(warnings)

    run_url = os.environ.get("GITHUB_RUN_URL")
    report_pointer = run_url or str(REPORT_PATH)
    body.extend(["", f"完整 Top 25 + 表格 → {report_pointer}", ""])
    if run_url:
        body.append("云端产物: 打开上面的 Actions run，在 Artifacts 下载 radar-reports。")
    body.append("今天只做一件事: clone 主推 repo，只看 skills / commands / memory 三块；其余留到周末扫报告。")
    return "\n".join(body)


def smtp_config() -> dict[str, str | int]:
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "mail_from": os.environ.get("RADAR_EMAIL_FROM") or os.environ.get("SMTP_USER", ""),
        "mail_to": os.environ.get("RADAR_EMAIL_TO", ""),
    }


def missing_smtp_fields(config: dict[str, str | int]) -> list[str]:
    missing = []
    for key in ["user", "password", "mail_to"]:
        if not str(config.get(key) or "").strip():
            missing.append(key)
    return missing


def send_with_local_sendmail(msg: EmailMessage, dry_run: bool) -> tuple[bool, str]:
    sendmail = shutil.which("sendmail") or "/usr/sbin/sendmail"
    if not Path(sendmail).exists():
        return False, "SMTP is not configured and local sendmail was not found."
    if dry_run:
        return True, f"Dry run only; local sendmail would send to {msg['To']}."

    proc = subprocess.run(
        [sendmail, "-t", "-oi"],
        input=msg.as_string(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=45,
        check=False,
    )
    if proc.returncode == 0:
        return True, f"Email accepted by local sendmail for {msg['To']}; delivery to Gmail inbox is not guaranteed without SMTP authentication."
    return False, "Local sendmail failed: " + (proc.stdout.strip() or f"exit {proc.returncode}")


def send_email(subject: str, body: str, dry_run: bool) -> tuple[bool, str]:
    config = smtp_config()
    allow_sendmail = os.environ.get("RADAR_ALLOW_SENDMAIL_FALLBACK", "").lower() in {"1", "true", "yes"}
    msg = EmailMessage()
    msg["Subject"] = subject
    fallback_from = os.environ.get("USER", "ai-oss-radar") + "@localhost"
    msg["From"] = str(config["mail_from"] or config["user"] or fallback_from)
    msg["To"] = str(config["mail_to"])
    msg.set_content(body)

    if not str(config["mail_to"]).strip():
        return False, "Missing email config: mail_to. Set RADAR_EMAIL_TO."

    missing = missing_smtp_fields(config)
    if missing:
        if not allow_sendmail:
            return (
                False,
                "Gmail SMTP is not configured: "
                + ", ".join(missing)
                + ". I did not use unauthenticated local sendmail because Gmail may silently filter it. "
                + "Set SMTP_USER and SMTP_PASSWORD (Gmail App Password) in config/email.env.",
            )
        local_ok, local_message = send_with_local_sendmail(msg, dry_run)
        if local_ok:
            return local_ok, local_message + " SMTP was skipped because " + ", ".join(missing) + " is missing."
        return (
            False,
            "Missing SMTP config: "
            + ", ".join(missing)
            + ". Set SMTP_USER and SMTP_PASSWORD for reliable Gmail delivery. "
            + local_message,
        )

    if dry_run:
        return True, f"Dry run only; email would be sent to {config['mail_to']}."

    try:
        with smtplib.SMTP(str(config["host"]), int(config["port"]), timeout=45) as smtp:
            smtp.starttls()
            smtp.login(str(config["user"]), str(config["password"]))
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        return (
            False,
            "Gmail SMTP authentication failed. Gmail usually requires a 16-character App Password; "
            f"server said: {exc.smtp_error.decode('utf-8', errors='replace')[:300]}",
        )
    except smtplib.SMTPException as exc:
        return False, f"Gmail SMTP failed: {str(exc)[:300]}"
    except OSError as exc:
        return False, f"Gmail SMTP network error: {str(exc)[:300]}"
    return True, f"Email sent via Gmail SMTP to {config['mail_to']}."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AI OSS Radar and send an email digest.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-items", type=int, default=25)
    parser.add_argument("--per-query", type=int, default=12)
    parser.add_argument("--fallback-per-query", type=int, default=8)
    parser.add_argument("--hn-per-query", type=int, default=15)
    parser.add_argument("--readme-limit", type=int, default=6)
    parser.add_argument("--fallback-readme-limit", type=int, default=3)
    parser.add_argument("--skip-radar", action="store_true", help="Use the existing latest report.")
    parser.add_argument("--dry-run-email", action="store_true", help="Build the email without sending it.")
    parser.add_argument("--require-email", action="store_true", help="Exit non-zero if email was not sent.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file()
    test_results = run_self_tests()
    tests_ok = all(result.ok for result in test_results)

    if args.skip_radar:
        radar_result = StepResult("radar", True, "Skipped radar run; used existing report.")
    else:
        radar_result = run_radar(args)

    if not REPORT_PATH.exists():
        print(f"Missing report: {REPORT_PATH}", file=sys.stderr)
        return 2

    report_text = REPORT_PATH.read_text(encoding="utf-8")
    subject_prefix = os.environ.get("RADAR_EMAIL_SUBJECT_PREFIX", "[AI OSS Radar]")
    status = "OK" if tests_ok and radar_result.ok else "NEEDS ATTENTION"
    subject = f"{subject_prefix} {status} {datetime.now().strftime('%Y-%m-%d')}"
    body = build_email_body(test_results, radar_result, report_text)
    sent, message = send_email(subject, body, dry_run=args.dry_run_email)

    EMAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG_PATH.write_text(
        f"subject: {subject}\nstatus: {message}\n\n{body}\n",
        encoding="utf-8",
    )

    print(message)
    print(f"Wrote {EMAIL_LOG_PATH}")
    for result in test_results + [radar_result]:
        print(f"{result.name}: {'OK' if result.ok else 'FAILED'}")
        if not result.ok and result.output:
            print(result.output[-2000:])

    if args.require_email and not sent:
        return 3
    return 0 if tests_ok and radar_result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
