#!/usr/bin/env python3
"""Run Opportunity Radar and send a concise Gmail digest."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from radar_notify_common import StepResult, load_env_file, load_latest_json, run_command, truncate
from run_and_notify import send_email


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "opportunity_latest.md"
EMAIL_LOG_PATH = ROOT / "reports" / "last_opportunity_email.txt"
RAW_DIR = ROOT / "data" / "opportunity_raw"

THEME_BOOST = {
    "agent-memory": 70,
    "agent-search": 60,
    "agent-security": 55,
    "agent-infra": 35,
}
THEME_PENALTY = {
    "product-launch": 15,
}
THEME_LABELS = {
    "agent-memory": "Agent Memory",
    "agent-search": "Agent Search",
    "agent-security": "Agent Security",
    "agent-infra": "Agent Infrastructure",
    "product-launch": "产品发布",
    "startup": "创业",
    "saas": "SaaS",
    "job": "招聘",
    "ai": "AI",
    "devtools": "开发者工具",
    "product": "产品",
    "market": "市场",
}


def run_self_tests() -> list[StepResult]:
    return [
        run_command(
            "compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "opportunity_radar.py",
                "run_opportunity_notify.py",
                "project_guidance.py",
                "radar_notify_common.py",
            ],
            timeout=240,
        ),
        run_command("unit-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], timeout=240),
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
    return run_command("opportunity-radar", command, timeout=240)


def latest_raw() -> dict | None:
    return load_latest_json(RAW_DIR)


def short(value: str, limit: int = 120) -> str:
    return truncate(value, limit)


def item_text(item: dict) -> str:
    return f"{item.get('title', '')} {item.get('summary', '')} {' '.join(item.get('tags') or [])}".lower()


def detect_themes(text: str) -> set[str]:
    themes: set[str] = set()
    if any(needle in text for needle in ("memory poisoning", "memory guard", "owasp")):
        themes.add("agent-security")
    elif any(
        needle in text
        for needle in (
            "share solution",
            "openhive",
            "dont re-solve",
            "agents share",
            "agent memory",
            "long-term memory",
            "memory layer",
        )
    ):
        themes.add("agent-memory")
    if any(needle in text for needle in ("search router", "web search", "retrieval", "retrieval-ready")):
        themes.add("agent-search")
    if any(needle in text for needle in ("mcp", "model context protocol", "infrastructure")):
        themes.add("agent-infra")
    if any(needle in text for needle in ("product hunt", "product trailers", "launch hn")):
        themes.add("product-launch")
    return themes


def editorial_priority(item: dict) -> float:
    text = item_text(item)
    score = float(item.get("score") or 0)
    for theme in detect_themes(text):
        score += THEME_BOOST.get(theme, 0)
        score -= THEME_PENALTY.get(theme, 0)
    return score


def grade_for_item(item: dict, rank: int) -> str:
    score = float(item.get("score") or 0)
    if rank == 1 and score >= 65:
        return "A"
    if rank <= 2 and score >= 55:
        return "A"
    if rank == 3 or score >= 50:
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


def focus_context() -> str:
    return os.environ.get("OPPORTUNITY_FOCUS_CONTEXT", "你现有的 agent 工作流")


def opportunity_profile(item: dict) -> tuple[str, list[str], list[str]]:
    text = item_text(item)
    themes = detect_themes(text)
    focus = focus_context()

    if "agent-memory" in themes and any(x in text for x in ("share", "openhive", "dont re-solve")):
        return (
            "AI Agent 之间共享经验库，避免每个 agent 重复解决同一个问题。",
            [
                "Agent Memory 是最近明显升温的方向。",
                "它像是 MCP 之后的下一层基础设施: 让 agent 记住、复用、共享经验。",
                "如果企业未来部署多个 agent，这类共享记忆层会很有价值。",
            ],
            [
                "学习它的 memory / solution sharing 架构。",
                f"思考能不能接入{focus}，复用历史决策和解决方案。",
            ],
        )
    if "agent-search" in themes:
        return (
            "给 AI Agent 提供统一搜索接口，让 agent 更容易调用 web/search/retrieval 能力。",
            [
                "几乎所有 agent 都需要搜索和检索。",
                "它属于基础设施层，不是一次性 wrapper。",
                f"比较容易接到{focus}里。",
            ],
            [
                "Fork 或 clone，跑 demo。",
                f"评估能不能作为{focus}的搜索模块。",
            ],
        )
    if "agent-security" in themes:
        return (
            "Agent Memory 安全项目，防止恶意内容污染 agent 的长期记忆。",
            [
                "Agent Security 还很早，但企业客户一定会关心。",
                "Memory Poisoning 会随着长期 agent 普及变成真实问题。",
                "懂这块会让你在产品判断和安全设计上更领先。",
            ],
            [
                "了解 memory poisoning 攻击面。",
                "记录 2 个可以加进你 agent 系统的防护点。",
            ],
        )
    if "agent-infra" in themes or ("agent" in text and "search" in text):
        return (
            "Agent 基础设施项目，帮助 agent 获取或组织外部信息。",
            [
                "基础设施层机会通常比普通 AI wrapper 更耐久。",
                "如果能嵌进现有工作流，就可能变成长期工具。",
            ],
            [
                "看 API 和 demo。",
                f"判断它能否接入{focus}。",
            ],
        )
    if "product-launch" in themes:
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
    if "hiring" in text or "remote" in text:
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


def summarize_trends(items: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for item in items[:30]:
        for tag in item.get("tags") or []:
            counts[tag] = counts.get(tag, 0) + 1
        for theme in detect_themes(item_text(item)):
            counts[theme] = counts.get(theme, 0) + 1

    top = sorted(counts.items(), key=lambda pair: -pair[1])[:5]
    if not top or top[0][1] < 2:
        return ["样本量偏小，暂不判断宏观趋势；先看今日主推项。"]

    return [f"{THEME_LABELS.get(key, key)} ({count})" for key, count in top]


def pick_research_items(items: list[dict], limit: int = 3) -> list[dict]:
    research_items = [item for item in items if item.get("source_type") != "job-board"]
    return sorted(research_items or items, key=editorial_priority, reverse=True)[:limit]


def top_by_tag(items: list[dict], wanted: set[str], limit: int) -> list[dict]:
    selected = []
    seen = set()
    for item in items:
        item_key = str(item.get("id") or item.get("url") or item.get("title") or id(item))
        if item_key in seen:
            continue
        if wanted.intersection(set(item.get("tags") or [])):
            selected.append(item)
            seen.add(item_key)
        if len(selected) >= limit:
            break
    return selected


def is_actionable_job(item: dict) -> bool:
    text = item_text(item)
    weak_offer_patterns = [
        "i help teams",
        "architecture audits",
        "fractional",
        "for hire",
        "my resume",
        "cal.com/",
    ]
    if any(pattern in text for pattern in weak_offer_patterns):
        return False
    if item.get("source_type") == "job-board":
        return not any(re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", text) for pattern in ("intern", "junior", "customer support"))
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


def job_match_score(item: dict) -> float:
    metrics = item.get("metrics") or {}
    return float(metrics.get("job_match_score") or 0)


def job_grade(item: dict, rank: int) -> str:
    score = job_match_score(item)
    risks = " ".join((item.get("metrics") or {}).get("job_match_risks") or [])
    if "可能限制 US" in risks and score < 105:
        return "B"
    if score >= 95 or (rank == 1 and score >= 80):
        return "A"
    if score >= 70:
        return "B+"
    if score >= 50:
        return "B"
    return "C"


def compact_salary_location(item: dict) -> str:
    metrics = item.get("metrics") or {}
    pieces: list[str] = []
    salary = metrics.get("salary") or ""
    salary_max = int(metrics.get("salary_max_detected") or metrics.get("salary_max") or 0)
    if salary:
        pieces.append(str(salary))
    elif salary_max:
        pieces.append(f"up to ${salary_max:,}")
    location = metrics.get("location") or ""
    if location:
        pieces.append(str(location))
    return " / ".join(pieces) or "薪资/地点未写清"


def clean_job_role(item: dict) -> str:
    metrics = item.get("metrics") or {}
    role = str(metrics.get("role") or display_name(item))
    if len(role) > 90 or role.lower().startswith("visa sponsorship"):
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        match = re.search(
            r"((?:senior|sr\.?|staff|principal|lead|backend|platform|infra|software)[^.|\n]{0,80}engineer[^.|\n]{0,80})",
            text,
            re.I,
        )
        if match:
            role = match.group(1).strip()
    return short(role, 90)


def format_job_candidate(item: dict, rank: int) -> list[str]:
    metrics = item.get("metrics") or {}
    company = short(metrics.get("company") or display_name(item).split("|", 1)[0].split(" - ", 1)[0].strip(), 48)
    role = clean_job_role(item)
    reasons = metrics.get("job_match_reasons") or []
    risks = metrics.get("job_match_risks") or []
    source = metrics.get("source_name") or item.get("source") or "job source"
    reason_text = "、".join(reasons[:4]) if reasons else "后端/AI/remote 关键词匹配，需要人工确认"
    risk_text = "；".join(risks[:3]) if risks else "暂无明显硬伤"
    return [
        f"{rank}. {company} — {role} ({job_grade(item, rank)})",
        f"   匹配: {reason_text}",
        f"   薪资/地点: {compact_salary_location(item)}",
        f"   风险: {risk_text}",
        f"   来源: {source} → {item.get('url', '')}",
    ]


def pick_job_items(items: list[dict], limit: int = 3) -> list[dict]:
    job_items = [item for item in top_by_tag(items, {"job"}, len(items)) if is_actionable_job(item)]
    job_items = [item for item in job_items if job_match_score(item) >= 45]
    job_items.sort(key=lambda item: (job_match_score(item), float(item.get("score") or 0)), reverse=True)
    return job_items[:limit]


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
    ]

    if picks:
        item = picks[0]
        grade = grade_for_item(item, 1)
        one_liner, why_lines, action_lines = opportunity_profile(item)
        body.extend(
            [
                "",
                f"今日主推 — {display_name(item)} ({grade})",
                one_liner,
                "",
                "为什么值得看:",
                *[f"- {line}" for line in why_lines],
                "",
                "你可以:",
                *[f"- {line}" for line in action_lines],
                f"投入时间: {effort_for_grade(grade)}",
                f"链接: {item.get('url', '')}",
            ]
        )

    if len(picks) > 1:
        body.extend(["", "次优先:"])
        for idx, item in enumerate(picks[1:3], 2):
            grade = grade_for_item(item, idx)
            one_liner, _, _ = opportunity_profile(item)
            body.append(
                f"{idx}. {display_name(item)} — {grade} · {short(one_liner, 72)} → {item.get('url', '')}"
            )

    explicit_jobs = pick_job_items(items, 3)
    body.extend(["", "工作机会（按 Andrew 简历匹配）:"])
    body.append("来源: YC Jobs / HNHIRING / RemoteOK / HN / Reddit。筛选目标: Senior Backend + Kafka/Flink + distributed systems + AWS + AI infra + remote/high comp。")
    if explicit_jobs:
        for idx, item in enumerate(explicit_jobs, 1):
            body.extend(format_job_candidate(item, idx))
    else:
        body.append("今天没有 A/B 级匹配岗位；不是“没有岗位”，而是没有明显适合你这份简历、薪资和 remote 条件的高质量目标。")

    trends = summarize_trends(items)
    body.extend(["", "今日信号分布 (来自本次抓取):"])
    body.extend(f"- {line}" for line in trends)

    if warnings:
        compact_warnings = [clean_warning(warning) for warning in warnings[:2]]
        body.extend(["", "采集异常:", *[f"- {warning}" for warning in compact_warnings]])

    run_url = os.environ.get("GITHUB_RUN_URL")
    report_pointer = run_url or str(REPORT_PATH)
    body.extend(["", "今天只做一件事:"])
    if explicit_jobs:
        top_job = explicit_jobs[0]
        top_metrics = top_job.get("metrics") or {}
        top_job_name = top_metrics.get("company") or display_name(top_job)
        body.append(f"先打开工作机会 #1: {short(top_job_name, 60)}。")
        body.append("判断: 加拿大 remote 能不能投？薪资是否够？如果够，今天就发第一封定制申请。")
    else:
        body.append(f"打开 {best_name}。")
        body.append("回答: 客户是谁？怎么赚钱？你会怎么改？")
    body.extend(["", f"完整原始报告 → {report_pointer}"])
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
    radar_result = (
        StepResult("opportunity-radar", True, "Skipped radar run; used existing report.")
        if args.skip_radar
        else run_radar(args)
    )
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
