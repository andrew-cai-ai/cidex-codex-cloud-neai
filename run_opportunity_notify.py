#!/usr/bin/env python3
"""Run Opportunity Radar and send a concise Gmail digest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from run_and_notify import load_env_file, send_email


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "opportunity_latest.md"
EMAIL_LOG_PATH = ROOT / "reports" / "last_opportunity_email.txt"
RAW_DIR = ROOT / "data" / "opportunity_raw"


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
        timeout=240,
        check=False,
    )
    return StepResult(name=name, ok=proc.returncode == 0, output=proc.stdout.strip())


def run_self_tests() -> list[StepResult]:
    return [
        run_command("compile", [sys.executable, "-m", "py_compile", "opportunity_radar.py", "run_opportunity_notify.py"]),
        run_command("unit-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ]


def run_radar(args: argparse.Namespace) -> StepResult:
    command = [
        sys.executable,
        "opportunity_radar.py",
        "--hours",
        str(args.hours),
        "--max-items",
        str(args.max_items),
        "--hn-per-query",
        str(args.hn_per_query),
        "--feed-limit",
        str(args.feed_limit),
        "--github-limit",
        str(args.github_limit),
    ]
    return run_command("opportunity-radar", command)


def latest_raw() -> dict | None:
    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def short(value: str, limit: int = 120) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def clean_warning(value: str) -> str:
    value = short(value, 180)
    if "Reddit feed failed" in value and "HTTP 403" in value:
        return value.split(": HTTP 403", 1)[0] + ": Reddit RSS blocked with HTTP 403"
    return value


def line_for_item(item: dict, index: int) -> list[str]:
    tags = ", ".join(item.get("tags") or []) or "general"
    return [
        f"{index}. {item['title']}",
        f"   来源: {item['source']} / {tags}",
        f"   为什么看: {item.get('why') or '可能是新的机会信号。'}",
        f"   今天动作: {item.get('action') or '打开链接快速判断是否值得跟进。'}",
        f"   链接: {item['url']}",
    ]


def top_by_tag(items: list[dict], wanted: set[str], limit: int) -> list[dict]:
    selected = []
    seen = set()
    for item in items:
        if item["id"] in seen:
            continue
        if wanted.intersection(set(item.get("tags") or [])):
            selected.append(item)
            seen.add(item["id"])
        if len(selected) >= limit:
            break
    return selected


def build_email_body(test_results: list[StepResult], radar_result: StepResult) -> str:
    raw = latest_raw() or {"items": [], "warnings": []}
    items = raw.get("items", [])
    warnings = raw.get("warnings", [])
    all_ok = all(result.ok for result in test_results + [radar_result])
    status = "OK" if all_ok else "ATTENTION"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    body: list[str] = [
        f"Opportunity Radar · {now} · {status}",
        "",
        "怎么读: 这封不是新闻汇总，是每天帮你找工作/合作/创业/产品机会。重点看“为什么看”和“今天动作”。",
        "",
        "今天最值得看:",
    ]

    for idx, item in enumerate(items[:5], 1):
        body.extend(line_for_item(item, idx))
        body.append("")

    job_items = top_by_tag(items, {"job"}, 3)
    startup_items = top_by_tag(items, {"startup", "product"}, 4)
    market_items = top_by_tag(items, {"market", "devtools", "ai"}, 4)

    if job_items:
        body.append("工作/合作线索:")
        for item in job_items:
            body.append(f"- {short(item['title'], 92)} → {item['url']}")
        body.append("")

    if startup_items:
        body.append("创业/产品线索:")
        for item in startup_items:
            body.append(f"- {short(item['title'], 92)} → {item['url']}")
        body.append("")

    if market_items:
        body.append("市场/技术趋势:")
        for item in market_items:
            body.append(f"- {short(item['title'], 92)} ({item['source']})")
        body.append("")

    if warnings:
        body.append("采集异常:")
        body.extend(f"- {clean_warning(warning)}" for warning in warnings[:6])
        body.append("")

    run_url = os.environ.get("GITHUB_RUN_URL")
    report_pointer = run_url or str(REPORT_PATH)
    body.extend(
        [
            f"完整报告 → {report_pointer}",
            "",
            "今天只做一件事: 从“今天最值得看”里挑 1 个，记录它的客户、痛点、变现方式，以及你能不能复制/合作/投简历。",
        ]
    )
    return "\n".join(body).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Opportunity Radar and send Gmail digest.")
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--max-items", type=int, default=25)
    parser.add_argument("--hn-per-query", type=int, default=12)
    parser.add_argument("--feed-limit", type=int, default=10)
    parser.add_argument("--github-limit", type=int, default=10)
    parser.add_argument("--skip-radar", action="store_true")
    parser.add_argument("--dry-run-email", action="store_true")
    parser.add_argument("--require-email", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file()
    test_results = run_self_tests()
    radar_result = StepResult("opportunity-radar", True, "Skipped radar run; used existing report.") if args.skip_radar else run_radar(args)
    if not REPORT_PATH.exists():
        print(f"Missing report: {REPORT_PATH}", file=sys.stderr)
        return 2

    all_ok = all(result.ok for result in test_results + [radar_result])
    subject_prefix = os.environ.get("OPPORTUNITY_EMAIL_SUBJECT_PREFIX", "[Opportunity Radar]")
    subject = f"{subject_prefix} {'OK' if all_ok else 'NEEDS ATTENTION'} {datetime.now().strftime('%Y-%m-%d')}"
    body = build_email_body(test_results, radar_result)
    sent, message = send_email(subject, body, dry_run=args.dry_run_email)

    EMAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_LOG_PATH.write_text(f"subject: {subject}\nstatus: {message}\n\n{body}", encoding="utf-8")

    print(message)
    print(f"Wrote {EMAIL_LOG_PATH}")
    for result in test_results + [radar_result]:
        print(f"{result.name}: {'OK' if result.ok else 'FAILED'}")
        if not result.ok and result.output:
            print(result.output[-2000:])
    if args.require_email and not sent:
        return 3
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
