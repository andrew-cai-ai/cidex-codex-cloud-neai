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


def display_name(item: dict) -> str:
    title = item.get("title") or "Untitled"
    title = title.removeprefix("Show HN: ").removeprefix("Launch HN: ").strip()
    title = title.replace("–", "-")
    if " - " in title:
        return title.split(" - ", 1)[0].strip()
    if " — " in title:
        return title.split(" — ", 1)[0].strip()
    return short(title, 54)


def editorial_priority(item: dict) -> float:
    title = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    score = float(item.get("score") or 0)
    if "openhive" in title:
        score += 120
    elif "search router" in title:
        score += 100
    elif "memory guard" in title or "memory poisoning" in title:
        score += 80
    elif "agent memory" in title:
        score += 70
    elif "ai agents" in title or "agent" in title:
        score += 20
    if "product trailers" in title or "launcher" in title:
        score -= 20
    return score


def grade_for_item(item: dict, rank: int) -> str:
    title = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    if rank <= 2 or any(key in title for key in ["openhive", "search router"]):
        return "A"
    if "memory guard" in title or rank == 3:
        return "B+"
    if rank <= 5:
        return "B"
    return "C"


def effort_for_grade(grade: str) -> str:
    return {
        "A": "★★★★★",
        "B+": "★★★★",
        "B": "★★★",
        "C": "★★",
    }.get(grade, "★★")


def opportunity_profile(item: dict) -> tuple[str, list[str], list[str]]:
    title = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    name = display_name(item)
    if "openhive" in title:
        return (
            "AI Agent 之间共享经验库，避免每个 agent 重复解决同一个问题。",
            [
                "Agent Memory 是最近明显升温的方向。",
                "它像是 MCP 之后的下一层基础设施: 让 agent 记住、复用、共享经验。",
                "如果企业未来部署多个 agent，这类共享记忆层会很有价值。",
            ],
            [
                "学习它的 memory / solution sharing 架构。",
                "思考能不能用于直播导演 AI: 让导演 agent 复用历史直播决策。",
            ],
        )
    if "search router" in title:
        return (
            "给 AI Agent 提供统一搜索接口，让 agent 更容易调用 web/search/retrieval 能力。",
            [
                "几乎所有 agent 都需要搜索和检索。",
                "它属于基础设施层，不是一次性 wrapper。",
                "很容易接到你自己的 Codex/直播导演/研究 agent 里。",
            ],
            [
                "Fork 或 clone，跑 demo。",
                "评估能不能作为直播导演 AI 的搜索模块。",
            ],
        )
    if "memory guard" in title or "memory poisoning" in title:
        return (
            "Agent Memory 安全项目，防止恶意内容污染 agent 的长期记忆。",
            [
                "Agent Security 还很早，但企业客户一定会关心。",
                "Memory Poisoning 会随着长期 agent 普及变成真实问题。",
                "懂这块会让你在面试、创业、产品判断上更领先。",
            ],
            [
                "了解 memory poisoning 攻击面。",
                "记录 2 个可以加进你 agent 系统的防护点。",
            ],
        )
    if "agent" in title and "search" in title:
        return (
            "Agent 基础设施项目，帮助 agent 获取或组织外部信息。",
            [
                "基础设施层机会通常比普通 AI wrapper 更耐久。",
                "如果能嵌进现有工作流，就可能变成长期工具。",
            ],
            [
                "看 API 和 demo。",
                "判断它能否接入你的自动化链路。",
            ],
        )
    if "product hunt" in title or "product trailers" in title:
        return (
            "围绕产品发布/获客的新工具，适合观察 SaaS launch 玩法。",
            [
                "它不一定值得深入做，但能观察 Product Hunt 获客生态。",
                "适合作为营销/增长灵感，不是技术主线。",
            ],
            [
                "扫 landing page。",
                "记录它怎么定位、怎么转化用户。",
            ],
        )
    if "hiring" in title or "remote" in title:
        return (
            "招聘市场信号，不一定是具体岗位，但能反映 AI/remote 对岗位结构的影响。",
            [
                "适合判断求职市场变化。",
                "如果没有明确公司和岗位，不值得立刻投递。",
            ],
            [
                "只看结论。",
                "有具体岗位再加入投递清单。",
            ],
        )
    return (
        short(item.get("why") or "一个可能有机会价值的新信号。", 96),
        [
            "它被雷达捞出来，是因为热度、来源和关键词都接近 AI/创业/产品机会。",
            "但是否值得深入，需要看客户、痛点、变现方式。",
        ],
        [
            "打开链接用 5 分钟判断。",
            "不能回答客户和变现方式，就跳过。",
        ],
    )


def pick_research_items(items: list[dict], limit: int = 3) -> list[dict]:
    return sorted(items, key=editorial_priority, reverse=True)[:limit]


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


def is_actionable_job(item: dict) -> bool:
    title = (item.get("title") or "").lower()
    summary = (item.get("summary") or "").lower()
    text = f"{title} {summary}"
    strong_patterns = [
        "we're hiring",
        "we are hiring",
        "hiring:",
        "hiring remote",
        "remote engineer",
        "founding engineer",
        "apply",
        "jobs at",
    ]
    weak_discussion_patterns = [
        "weak junior hiring",
        "job losses",
        "jobs apocalypse",
        "remote working",
        "blame for",
    ]
    if any(pattern in text for pattern in weak_discussion_patterns):
        return False
    return any(pattern in text for pattern in strong_patterns)


def build_email_body(test_results: list[StepResult], radar_result: StepResult) -> str:
    raw = latest_raw() or {"items": [], "warnings": []}
    items = raw.get("items", [])
    warnings = raw.get("warnings", [])
    all_ok = all(result.ok for result in test_results + [radar_result])
    status = "OK" if all_ok else "ATTENTION"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    picks = pick_research_items(items, 3)
    best = picks[0] if picks else None
    best_name = display_name(best) if best else "今天最值得看的项目"

    body: list[str] = [
        f"今日 AI 机会雷达（5分钟版）· {now} · {status}",
        "",
        "结论: 今天不是看 20 个链接，而是判断有没有值得学、值得 Fork、值得做成产品的机会。",
        f"如果今天只能看一个: {best_name}。",
        "",
        "最值得研究:",
    ]

    for idx, item in enumerate(picks, 1):
        name = display_name(item)
        grade = grade_for_item(item, idx)
        one_liner, why_lines, action_lines = opportunity_profile(item)
        body.extend(
            [
                f"{idx}. {name} — 值得程度 {grade}",
                one_liner,
                "",
                "为什么值得看:",
            ]
        )
        body.extend(f"- {line}" for line in why_lines)
        body.extend(["", "你可以:"])
        body.extend(f"- {line}" for line in action_lines)
        body.extend([f"投入时间: {effort_for_grade(grade)}", f"链接: {item.get('url', '')}"])
        body.append("")

    job_items = top_by_tag(items, {"job"}, 3)
    explicit_jobs = [item for item in job_items if is_actionable_job(item)]
    body.append("工作机会:")
    if explicit_jobs:
        for item in explicit_jobs[:2]:
            body.append(f"- {short(item['title'], 92)} → {item['url']}")
    else:
        body.append("今天没发现特别值得投递的 AI 岗位；只有招聘市场/remote work 的宏观讨论。")
    body.append("")

    body.extend(
        [
            "创业机会:",
            "本周趋势:",
            "Agent Memory ↑",
            "Agent Search ↑",
            "Agent Security ↑",
            "Agent Infrastructure ↑",
            "Generic AI Wrapper ↓",
            "",
            "判断: 市场正在从“套壳聊天产品”往“Agent 底层能力”迁移。",
            "",
            "值得程度表:",
            "| 项目 | 值得程度 |",
            "|---|---|",
        ]
    )
    for idx, item in enumerate(picks, 1):
        body.append(f"| {display_name(item)} | {grade_for_item(item, idx)} |")

    if warnings:
        compact_warnings = [clean_warning(warning) for warning in warnings[:2]]
        body.extend(["", "采集异常:", *[f"- {warning}" for warning in compact_warnings]])

    run_url = os.environ.get("GITHUB_RUN_URL")
    report_pointer = run_url or str(REPORT_PATH)
    body.extend(
        [
            "",
            "今天只做一件事:",
            f"打开 {best_name}。",
            "回答: 客户是谁？怎么赚钱？如果 Andrew 来做会怎么改？",
            "记录到 Notion。",
            "",
            f"完整原始报告 → {report_pointer}",
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
