#!/usr/bin/env python3
"""Run Opportunity Radar and send a concise Gmail digest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar_notify_common import StepResult, load_env_file, load_latest_json, run_command, truncate
from run_and_notify import send_email


ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "opportunity_latest.md"
EMAIL_LOG_PATH = ROOT / "reports" / "last_opportunity_email.txt"
RAW_DIR = ROOT / "data" / "opportunity_raw"
WEEKLY_UPDATE_PATH = Path("/Users/shixun.cai.-nd/Documents/Codex/opportunity_os/weekly_update.md")

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

PAIN_TOPICS = [
    {
        "name": "AI 求职/面试准备低效",
        "keywords": ["interview", "job search", "resume", "hiring", "leetcode", "career"],
        "users": "AI/软件工程求职者",
        "willingness": "高",
    },
    {
        "name": "Agent 记忆和上下文无法复用",
        "keywords": ["memory", "context", "dont re-solve", "share solutions", "long-term memory"],
        "users": "AI agent 开发者、AI infra 团队",
        "willingness": "高",
    },
    {
        "name": "Agent 搜索/检索质量不稳定",
        "keywords": ["search", "retrieval", "rag", "web search", "knowledge graph"],
        "users": "AI 应用团队、开发者工具团队",
        "willingness": "中高",
    },
    {
        "name": "AI coding 成本、上下文和安全不可控",
        "keywords": ["token", "cost", "prompt injection", "memory poisoning", "security", "usage"],
        "users": "重度使用 Codex/Claude/Cursor 的工程团队",
        "willingness": "中高",
    },
    {
        "name": "企业 AI 工作流缺少可靠基础设施",
        "keywords": ["workflow", "automation", "platform", "infrastructure", "observability"],
        "users": "B2B SaaS、平台工程、AI infra 团队",
        "willingness": "高",
    },
]

S_TIER_COMPANIES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "cursor": "Cursor",
    "perplexity": "Perplexity",
    "glean": "Glean",
    "cohere": "Cohere",
}

TREND_TOPICS = [
    {
        "key": "agent-memory",
        "name": "Agent Memory",
        "keywords": [
            "agent memory",
            "memory layer",
            "long-term memory",
            "memory poisoning",
            "memory guard",
            "share solutions",
            "dont re-solve",
            "context reuse",
            "openhive",
            "async agents",
        ],
        "andrew_reasons": ["Distributed Systems", "State Management", "Data Platform", "Reliability", "AI Infra"],
        "stage": "Early",
        "competition": "Low",
        "enterprise_demand": "Growing",
        "action": "本周投入2小时研究 memory/schema/versioning，判断能否做成 Agent infra 组件。",
    },
    {
        "key": "agent-infrastructure",
        "name": "Agent Infrastructure",
        "keywords": [
            "agent infrastructure",
            "agent platform",
            "agentic",
            "mcp",
            "model context protocol",
            "tool calling",
            "workflow",
            "orchestration",
            "observability",
        ],
        "andrew_reasons": ["Backend Platform", "Distributed Systems", "AWS", "Reliability", "Developer Tools"],
        "stage": "Early-Mid",
        "competition": "Medium",
        "enterprise_demand": "Growing",
        "action": "持续监控，把重复出现的 agent infra 模块整理成自己的架构地图。",
    },
    {
        "key": "evaluation",
        "name": "Evaluation",
        "keywords": [
            "eval",
            "evaluation",
            "benchmark",
            "code smells",
            "guardrail",
            "llm judge",
            "agent test",
        ],
        "andrew_reasons": ["Reliability", "Production Quality", "Observability", "Incident Response"],
        "stage": "Early-Mid",
        "competition": "Medium",
        "enterprise_demand": "Growing",
        "action": "收集 3 个 eval/quality 产品，判断企业是否愿意按 seat 或 usage 付费。",
    },
    {
        "key": "ai-coding",
        "name": "AI Coding",
        "keywords": [
            "ai coding",
            "coding agent",
            "codex",
            "claude code",
            "cursor",
            "opencode",
            "developer productivity",
            "code generation",
            "vibe coding",
        ],
        "andrew_reasons": ["Senior Backend", "Developer Tools", "Code Review", "Platform Engineering"],
        "stage": "Mid",
        "competition": "High",
        "enterprise_demand": "Growing",
        "action": "只看 infra/quality/security 子方向，避开普通 wrapper。",
    },
    {
        "key": "voice-agents",
        "name": "Voice Agents",
        "keywords": ["voice agent", "voice ai", "speech", "realtime voice", "call center", "phone agent"],
        "andrew_reasons": ["Real-Time Systems", "Streaming", "Low Latency", "Backend"],
        "stage": "Early-Mid",
        "competition": "Medium",
        "enterprise_demand": "Growing",
        "action": "观察实时语音 infra 和垂直场景，不急着做通用 voice bot。",
    },
    {
        "key": "browser-agents",
        "name": "Browser Agents",
        "keywords": ["browser agent", "computer use", "web automation", "browser automation", "desktop agent", "operator"],
        "andrew_reasons": ["Workflow Automation", "Reliability", "Backend Orchestration"],
        "stage": "Early",
        "competition": "Medium",
        "enterprise_demand": "Unclear but rising",
        "action": "监控可靠性和权限模型，只有出现企业刚需再深入。",
    },
    {
        "key": "agent-search",
        "name": "Agent Search",
        "keywords": ["agent search", "search router", "web search", "retrieval", "rag", "knowledge graph", "vector search"],
        "andrew_reasons": ["Data Platform", "Retrieval", "Backend APIs", "Performance"],
        "stage": "Early-Mid",
        "competition": "Medium",
        "enterprise_demand": "Growing",
        "action": "研究搜索路由、缓存、质量评估，判断能否接进自己的 agent 工作流。",
    },
    {
        "key": "agent-security",
        "name": "Agent Security",
        "keywords": ["agent security", "prompt injection", "memory poisoning", "owasp", "guardrail", "security"],
        "andrew_reasons": ["Reliability", "Production Systems", "Risk Control", "Enterprise Infra"],
        "stage": "Early",
        "competition": "Low-Medium",
        "enterprise_demand": "Growing",
        "action": "跟踪企业安全需求，优先学习攻击面和防护边界。",
    },
]

TOPIC_THESIS_META = {
    "agent-infrastructure": {
        "why": "所有可落地的 agent 最终都需要 Memory、Search、Evaluation、Orchestration 和 Observability；这些不是一次性 demo，而是平台层能力。",
        "customers": "AI-native 公司、Enterprise AI 平台团队、DevTools/平台工程团队",
        "budget": "Platform budget / Developer productivity budget / AI transformation budget",
        "why_now": "企业开始从单个 chatbot 转向长期运行的 agent workflow，可靠性、权限、上下文和工具调用会变成刚需。",
    },
    "agent-security": {
        "why": "长期运行的 agent 会读写上下文、调用工具、连接内部系统，prompt injection 和 memory poisoning 会从理论风险变成企业采购门槛。",
        "customers": "Enterprise AI 团队、安全团队、合规敏感行业的 AI 平台团队",
        "budget": "Security budget / Risk budget / Platform governance budget",
        "why_now": "agent 开始接触真实数据和真实动作，企业会要求可审计、可隔离、可回滚的安全层。",
    },
    "agent-memory": {
        "why": "agent 如果不能复用上下文和经验，就会重复推理、重复踩坑、成本高且表现不稳定；memory 是长期 agent 的基础设施。",
        "customers": "AI agent 开发者、企业 AI 平台团队、客服/销售/工程自动化团队",
        "budget": "AI platform budget / Data platform budget / Automation budget",
        "why_now": "agent 从短会话走向长期任务，状态管理和记忆治理开始成为真实痛点。",
    },
    "evaluation": {
        "why": "AI 输出越来越多进入生产环境，企业需要知道 agent 是否稳定、是否退化、是否符合预期。",
        "customers": "AI 应用团队、QA/平台团队、DevTools 团队",
        "budget": "Quality budget / Observability budget / Developer productivity budget",
        "why_now": "AI coding 和 agent 工作流扩散后，传统测试覆盖不了非确定性行为。",
    },
    "ai-coding": {
        "why": "AI coding 使用量会继续增长，但普通 wrapper 竞争太强，只有 infra、质量、安全和团队治理层值得看。",
        "customers": "工程团队、平台工程、开发者工具采购方",
        "budget": "Developer productivity budget",
        "why_now": "Codex/Claude Code/Cursor 已经成为日常工具，下一阶段需求会转向成本、上下文、安全和协作治理。",
    },
    "agent-search": {
        "why": "agent 需要稳定获取外部和内部知识；search/retrieval 是几乎所有 agent workflow 的公共依赖。",
        "customers": "AI 应用团队、企业知识管理团队、DevTools 公司",
        "budget": "AI platform budget / Knowledge management budget",
        "why_now": "agent 的答案质量越来越依赖检索质量，企业内部知识接入正在变成基础设施问题。",
    },
    "voice-agents": {
        "why": "实时语音 agent 有清晰场景，但更依赖垂直行业、低延迟和运营能力，不适合现在泛化投入。",
        "customers": "客服、销售、医疗、金融呼叫中心",
        "budget": "Support ops budget / Sales ops budget",
        "why_now": "实时模型和语音接口成熟后，电话/客服自动化会继续增长。",
    },
    "browser-agents": {
        "why": "浏览器 agent 可以自动执行工作流，但可靠性、权限和错误恢复还早；适合监控，不适合重押。",
        "customers": "运营团队、数据录入/后台流程密集的企业",
        "budget": "Automation budget / Ops budget",
        "why_now": "computer use 能力变强，但企业采用会被可靠性和权限卡住。",
    },
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_historical_raws(max_days: int = 30) -> list[dict]:
    cutoff = utc_now() - timedelta(days=max_days)
    snapshots: list[dict] = []
    for path in sorted(RAW_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_time = parse_datetime(str(raw.get("run_time") or ""))
        if run_time and run_time < cutoff:
            continue
        raw["_path"] = str(path)
        snapshots.append(raw)
    return snapshots


def history_with_current(raw: dict, historical: list[dict] | None = None) -> list[dict]:
    snapshots = list(historical if historical is not None else load_historical_raws(30))
    current_id = str(raw.get("run_time") or id(raw))
    if not any(str(snapshot.get("run_time") or id(snapshot)) == current_id for snapshot in snapshots):
        snapshots.append(raw)
    return snapshots


def parse_weekly_update_date(text: str) -> datetime.date | None:
    match = re.search(r"^#\s*Week\b.*?(\d{4}-\d{2}-\d{2})\s*$", text, re.M)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def extract_markdown_section(text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, re.M)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.M)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def bullet_lines(section: str) -> list[str]:
    lines: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        value = stripped[1:].strip()
        if value:
            lines.append(value)
    return lines


def parse_invested_hours(section: str) -> dict[str, float]:
    hours: dict[str, float] = {}
    for line in bullet_lines(section):
        match = re.match(r"([^:：]+)[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*(?:h|hr|hrs|hour|hours|小时)?\b", line, re.I)
        if match:
            hours[match.group(1).strip()] = float(match.group(2))
    return hours


def read_internal_loop(path: Path = WEEKLY_UPDATE_PATH, today: datetime.date | None = None) -> dict:
    today = today or datetime.now().astimezone().date()
    if not path.exists():
        return {
            "status": "Missing",
            "state_line": "Internal Loop: missing weekly_update.md",
            "hours": {},
            "did": [],
            "got": [],
            "next_action": [],
            "roi": "Waiting",
            "reason": "ROI Tracker: waiting for Andrew update",
            "updated_at": None,
        }

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "status": "Missing",
            "state_line": "Internal Loop: missing weekly_update.md",
            "hours": {},
            "did": [],
            "got": [],
            "next_action": [],
            "roi": "Waiting",
            "reason": "ROI Tracker: waiting for Andrew update",
            "updated_at": None,
        }

    update_date = parse_weekly_update_date(text)
    if not update_date:
        update_date = datetime.fromtimestamp(path.stat().st_mtime).date()
    stale = update_date < today - timedelta(days=7)

    invest_section = extract_markdown_section(text, "投入")
    did = bullet_lines(extract_markdown_section(text, "做了什么"))
    got = bullet_lines(extract_markdown_section(text, "得到了什么"))
    next_action = bullet_lines(extract_markdown_section(text, "下周一个最重要的行动"))
    hours = parse_invested_hours(invest_section)

    if stale:
        roi = "Waiting"
        reason = "ROI Tracker: waiting for Andrew update"
        status = "Stale"
        state_line = "Internal Loop: stale"
    elif not hours and not did and not got:
        roi = "Waiting"
        reason = "ROI Tracker: waiting for Andrew update"
        status = "Fresh"
        state_line = "Internal Loop: fresh"
    else:
        total_hours = sum(hours.values())
        has_output = bool(got)
        if has_output and total_hours > 0:
            roi = "High" if total_hours <= 6 else "Medium"
            reason = "基于 weekly_update.md：本周有明确产出，且投入时间可计算。"
        elif has_output:
            roi = "Medium"
            reason = "基于 weekly_update.md：有产出记录，但没有可计算投入时间。"
        elif total_hours > 0:
            roi = "Low"
            reason = "基于 weekly_update.md：有投入但没有记录到明确产出。"
        else:
            roi = "Waiting"
            reason = "ROI Tracker: waiting for Andrew update"
        status = "Fresh"
        state_line = "Internal Loop: fresh"

    return {
        "status": status,
        "state_line": state_line,
        "hours": hours,
        "did": did,
        "got": got,
        "next_action": next_action,
        "roi": roi,
        "reason": reason,
        "updated_at": update_date.isoformat() if update_date else None,
    }


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


def title_detail(item: dict) -> str:
    title = (item.get("title") or "").removeprefix("Show HN: ").removeprefix("Launch HN: ").strip()
    for sep in (" – ", " — ", " - ", ", "):
        if sep in title:
            return short(title.split(sep, 1)[1], 110)
    return short(title, 110)


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


def normalized_company_name(item: dict) -> str:
    metrics = item.get("metrics") or {}
    company = str(metrics.get("company") or display_name(item).split("|", 1)[0].split(" - ", 1)[0])
    company = re.sub(r"https?://\S+", "", company)
    company = re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()
    return company


def text_has_term(text: str, term: str) -> bool:
    term = term.lower()
    if re.fullmatch(r"[a-z0-9#+.-]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def ai_job_category(item: dict) -> str:
    text = item_text(item)
    company = normalized_company_name(item)
    top_domains = ("openai.com", "anthropic.com", "cursor.com", "perplexity.ai", "glean.com", "cohere.com")
    if company in S_TIER_COMPANIES or any(domain in str(item.get("url") or "").lower() for domain in top_domains):
        return "S: Frontier AI / 顶级 AI 公司"
    if any(
        text_has_term(text, term)
        for term in (
            "genai",
            "generative ai",
            "llm",
            "ai agent platform",
            "ai agent",
            "agent platform",
            "ai infrastructure",
            "ml platform",
            "machine learning engineer",
            "inference",
            "mcp",
            "mcp server",
            "vector search",
            "rag",
        )
    ):
        return "A: AI-native / AI Infra"
    if any(text_has_term(text, term) for term in ("ai risk", "ai moderation", "ai tooling", "model", "automation")):
        return "B: AI-adjacent，岗位本身更偏后端/平台"
    return "C: 不是 AI 核心岗位，但可能适合 Andrew 的后端/平台背景"


def company_type(item: dict) -> str:
    text = item_text(item)
    company = normalized_company_name(item)
    if company in S_TIER_COMPANIES:
        return "AI Native"
    if any(text_has_term(text, term) for term in ("ai platform", "ai risk decisioning", "genai", "machine learning platform", "inference platform", "agent platform")):
        return "AI First"
    if any(text_has_term(text, term) for term in ("llm", "ai agent", "mcp", "vector search", "ai moderation", "ai tooling", "model")):
        return "AI Adjacent"
    if any(text_has_term(text, term) for term in ("ai", "llm", "agent", "machine learning", "model")):
        return "AI Adjacent"
    return "Traditional SaaS"


def role_type(item: dict) -> str:
    text = item_text(item)
    role = str((item.get("metrics") or {}).get("role") or item.get("title") or "").lower()
    combined = f"{role} {text}"
    if any(text_has_term(combined, term) for term in ("ai infrastructure", "inference", "mcp", "vector search", "platform infrastructure")):
        return "AI Infra"
    if any(text_has_term(combined, term) for term in ("machine learning", "ml platform", "model", "training", "inference")):
        return "ML Systems"
    if any(text_has_term(combined, term) for term in ("agent platform", "ai agent", "agentic")):
        return "Agent Platform"
    if any(text_has_term(combined, term) for term in ("data platform", "kafka", "flink", "streaming", "real-time", "analytics")):
        return "Data Platform"
    if any(text_has_term(combined, term) for term in ("backend", "api", "java", "microservices", "serverless")):
        return "Backend"
    return "Other"


def ai_job_rank(item: dict) -> int:
    category = ai_job_category(item)
    if category.startswith("S:"):
        return 3
    if category.startswith("A:"):
        return 2
    if category.startswith("B:"):
        return 1
    return 0


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
    job_items.sort(key=lambda item: (ai_job_rank(item), job_match_score(item), float(item.get("score") or 0)), reverse=True)
    return job_items[:limit]


def is_github_url(item: dict) -> bool:
    return "github.com/" in str(item.get("url") or "").lower()


def commercial_value(item: dict) -> str:
    text = item_text(item)
    themes = detect_themes(text)
    if {"agent-memory", "agent-search", "agent-security", "agent-infra"}.intersection(themes):
        return "A"
    if is_github_url(item) and any(tag in item.get("tags") or [] for tag in ("devtools", "ai", "startup")):
        return "A"
    if any(tag in item.get("tags") or [] for tag in ("startup", "product", "devtools", "saas")):
        return "B"
    return "C"


def project_priority(item: dict, rank: int) -> str:
    value = commercial_value(item)
    if value == "A" or rank == 1:
        return "A"
    if value == "B":
        return "B"
    return "C"


def worth_applying_to_project(item: dict) -> str:
    text = item_text(item)
    if "hiring" in text or "jobs" in text or "careers" in text:
        return "可能，先查 careers/LinkedIn 有没有 Senior/Staff backend 或 AI infra 岗。"
    if any(tag in item.get("tags") or [] for tag in ("startup", "product", "ai")):
        return "暂不直接投；先把它当公司/方向线索，看到岗位再投。"
    return "否，先研究项目价值。"


def worth_forking(item: dict) -> str:
    text = item_text(item)
    if is_github_url(item):
        if "agent" in text or "mcp" in text or "devtools" in item.get("tags", []):
            return "是，优先 Fork/clone 看架构、接口和可复用模块。"
        return "可以，先看 license 和 demo。"
    return "否，先看产品/市场，不急着 Fork。"


def worth_startup_reference(item: dict) -> str:
    value = commercial_value(item)
    if value == "A":
        return "是，适合作为 AI infra / agent 平台方向参考。"
    if value == "B":
        return "可以，适合观察定位、客户和获客方式。"
    return "一般，只做背景信号。"


def paying_signal(item: dict | None) -> str:
    if not item:
        return "未知"
    text = item_text(item)
    if any(text_has_term(text, term) for term in ("customers", "revenue", "mrr", "pricing", "paid", "enterprise", "api usage")):
        return "有付费信号"
    if any(text_has_term(text, term) for term in ("waitlist", "beta", "show hn", "launch hn")):
        return "未证实，仍在验证"
    return "未证实"


def market_size(item: dict | None) -> str:
    if not item:
        return "未知"
    text = item_text(item)
    if any(text_has_term(text, term) for term in ("agent", "llm", "infrastructure", "developer", "enterprise", "api")):
        return "大：AI infra / developer tooling / enterprise workflow"
    if any(text_has_term(text, term) for term in ("job", "interview", "resume", "hiring")):
        return "中：求职和招聘工具市场明确，但竞争激烈"
    return "中小：需要验证目标客户密度"


def concrete_pain(item: dict | None, fallback: str = "") -> str:
    if not item:
        return fallback or "未知"
    detail = title_detail(item)
    text = item_text(item)
    if "trust an expert" in text or "whether to trust" in text:
        return "AI agent 在调用专家/外部知识时不知道该信任谁，企业 agent 需要可信度判断层。"
    if "code smells" in text:
        return "AI 生成代码质量不稳定，团队需要自动发现 AI 代码坏味道和维护风险。"
    if "memory" in text and ("reuse" in text or "share" in text or "context" in text):
        return "Agent 经验和上下文无法复用，导致每个 agent 重复推理、重复踩坑。"
    if detail and detail.lower() not in {"untitled", "show hn"}:
        return detail
    return fallback or "需要人工打开链接确认真实痛点。"


def startup_decision(item: dict | None) -> str:
    if not item:
        return "Ignore"
    value = commercial_value(item)
    score = andrew_score(item)
    paid = paying_signal(item)
    if value == "A" and score >= 90 and paid == "有付费信号":
        return "Copy"
    if value == "A" and score >= 35:
        return "Study"
    if value == "B" and score >= 45:
        return "Study"
    return "Ignore"


def open_source_decision(item: dict | None) -> str:
    if not item:
        return "Ignore"
    if not is_github_url(item):
        return "Ignore"
    value = commercial_value(item)
    score = andrew_score(item)
    text = item_text(item)
    if value == "A" and score >= 45 and any(text_has_term(text, term) for term in ("agent", "mcp", "cli", "developer", "code", "search")):
        return "Fork"
    if value in {"A", "B"} and score >= 35:
        return "Bookmark"
    return "Ignore"


def andrew_project_value(item: dict) -> str:
    text = item_text(item)
    if "backend" in text or "infrastructure" in text or "platform" in text:
        return "能帮你把 Disney/Binance/TikTok 的后端和实时系统经验，转成 AI infra 叙事。"
    if "agent" in text or "mcp" in text or "llm" in text:
        return "能帮你补足 Agent/LLM 产品判断，方便求职面试和创业选题。"
    if is_github_url(item):
        return "能作为可复用技术样本，帮你更快搭 demo 或扩展 Codex 工作流。"
    return "能作为市场线索，判断 AI 产品机会是否值得继续追。"


def format_attention_item(item: dict, rank: int) -> list[str]:
    name = display_name(item)
    one_liner, why_lines, action_lines = opportunity_profile(item)
    priority = project_priority(item, rank)
    return [
        f"{rank}. {name}",
        short(one_liner, 120),
        f"为什么值得 Andrew 看: {short(' '.join(why_lines), 150)}",
        f"对 Andrew 的价值: {andrew_project_value(item)}",
        f"是否值得投简历: {worth_applying_to_project(item)}",
        f"是否值得 Fork: {worth_forking(item)}",
        f"是否值得创业参考: {worth_startup_reference(item)}",
        f"优先级 / 预计商业价值: {priority}",
        f"链接: {item.get('url', '')}",
    ]


def estimate_tc(item: dict) -> str:
    metrics = item.get("metrics") or {}
    salary = metrics.get("salary") or ""
    salary_max = int(metrics.get("salary_max_detected") or metrics.get("salary_max") or 0)
    if salary:
        return str(salary)
    if salary_max:
        return f"最高约 ${salary_max:,}"
    return "Unknown（当前抓取材料没有薪资证据；不能假设 >$300k）"


def detected_terms(item: dict, terms: tuple[str, ...]) -> list[str]:
    text = item_text(item)
    found: list[str] = []
    for term in terms:
        if text_has_term(text, term) and term not in found:
            found.append(term)
    return found


def company_type_evidence(item: dict) -> str:
    ctype = company_type(item)
    company = normalized_company_name(item)
    if company in S_TIER_COMPANIES:
        return f"公司名命中 S级 AI 公司: {S_TIER_COMPANIES[company]}"
    if ctype == "AI First":
        terms = detected_terms(
            item,
            (
                "ai platform",
                "ai risk decisioning",
                "genai",
                "machine learning platform",
                "inference platform",
                "agent platform",
            ),
        )
        return f"公司/JD 明确 AI-first 信号: {', '.join(terms[:4]) or 'AI platform'}"
    if ctype == "AI Adjacent":
        terms = detected_terms(item, ("llm", "ai agent", "mcp", "vector search", "ai moderation", "ai tooling", "model", "ai"))
        return f"只有 AI-adjacent 信号: {', '.join(terms[:4]) or 'AI keyword'}"
    return "未看到 AI-native 或 AI-first 证据"


def role_type_evidence(item: dict) -> str:
    rtype = role_type(item)
    terms = detected_terms(
        item,
        (
            "ai infrastructure",
            "inference",
            "mcp",
            "vector search",
            "platform infrastructure",
            "machine learning",
            "ml platform",
            "agent platform",
            "ai agent",
            "data platform",
            "kafka",
            "flink",
            "streaming",
            "real-time",
            "backend",
            "api",
            "java",
            "microservices",
            "serverless",
        ),
    )
    if rtype == "Other":
        return "JD 没有清晰命中 AI infra / ML systems / data platform / backend"
    return f"Role Type={rtype}，JD/标题信号: {', '.join(terms[:5]) or clean_job_role(item)}"


def salary_evidence(item: dict) -> str:
    metrics = item.get("metrics") or {}
    salary = metrics.get("salary") or ""
    salary_max = int(metrics.get("salary_max_detected") or metrics.get("salary_max") or 0)
    if salary:
        return f"薪资字段写明: {salary}"
    if salary_max:
        return f"JD/来源可解析薪资上限: ${salary_max:,}"
    return "未发现薪资字段或可解析区间"


def job_evidence(item: dict) -> list[str]:
    metrics = item.get("metrics") or {}
    source = metrics.get("source_name") or item.get("source") or "unknown"
    evidence = [
        f"Source: {source}",
        company_type_evidence(item),
        role_type_evidence(item),
        f"TC evidence: {salary_evidence(item)}",
    ]
    summary = short(str(item.get("summary") or ""), 120)
    if summary:
        evidence.insert(1, f"JD/company intro: {summary}")
    url = item.get("url") or ""
    if url:
        evidence.append(f"URL: {url}")
    return evidence[:6]


def job_confidence(item: dict) -> str:
    ctype = company_type(item)
    rtype = role_type(item)
    tc_known = not estimate_tc(item).startswith("Unknown")
    if ctype in {"AI Native", "AI First"} and rtype != "Other" and tc_known:
        return "High"
    if ctype in {"AI Native", "AI First", "AI Adjacent"} and rtype != "Other":
        return "Medium"
    return "Low"


def job_priority(item: dict) -> str:
    category = ai_job_category(item)
    if category.startswith("S:"):
        return "S"
    if category.startswith("A:") and job_match_score(item) >= 70:
        return "A"
    if job_match_score(item) >= 70:
        return "B"
    return "B"


def job_decision(item: dict | None) -> str:
    if not item:
        return "Ignore"
    ctype = company_type(item)
    rtype = role_type(item)
    score = job_match_score(item)
    risks = " ".join((item.get("metrics") or {}).get("job_match_risks") or [])
    salary_max = int((item.get("metrics") or {}).get("salary_max_detected") or (item.get("metrics") or {}).get("salary_max") or 0)
    if "可能限制 US" in risks:
        return "Watchlist"
    if salary_max and salary_max < 180000:
        return "Watchlist"
    strong_role = rtype in {"AI Infra", "ML Systems", "Agent Platform", "Data Platform", "Backend"}
    if ctype == "AI Native" and strong_role and score >= 85:
        return "Apply Now"
    if ctype == "AI First" and strong_role and score >= 85 and salary_max >= 250000:
        return "Apply Now"
    if ctype in {"AI First", "AI Adjacent"} and score >= 70 and rtype in {"Data Platform", "Backend", "AI Infra", "ML Systems", "Agent Platform"}:
        return "Watchlist"
    return "Ignore"


def decision_rank(decision: str) -> int:
    return {"Apply Now": 3, "Study": 3, "Copy": 3, "Fork": 3, "Watchlist": 2, "Bookmark": 2, "Ignore": 0}.get(decision, 1)


def pick_best_job(items: list[dict]) -> dict | None:
    jobs = [item for item in top_by_tag(items, {"job"}, len(items)) if is_actionable_job(item)]
    jobs = [item for item in jobs if job_match_score(item) >= 45]
    if not jobs:
        return None
    jobs.sort(
        key=lambda item: (
            decision_rank(job_decision(item)),
            ai_job_rank(item),
            job_match_score(item),
            float(item.get("score") or 0),
        ),
        reverse=True,
    )
    return jobs[0]


def format_job_decision(item: dict, rank: int) -> list[str]:
    metrics = item.get("metrics") or {}
    company = short(metrics.get("company") or display_name(item).split("|", 1)[0].split(" - ", 1)[0].strip(), 48)
    role = clean_job_role(item)
    reasons = metrics.get("job_match_reasons") or []
    risks = metrics.get("job_match_risks") or []
    reason_text = "、".join(reasons[:4]) if reasons else "和 Andrew 后端/AI/remote 目标有交集，需要人工确认。"
    risk_text = "；".join(risks[:3]) if risks else "暂无明显硬伤"
    return [
        f"{rank}. {company}",
        f"岗位: {role}",
        f"AI属性: {ai_job_category(item)}",
        f"预计TC: {estimate_tc(item)}",
        f"匹配度: {job_priority(item)} / {int(job_match_score(item))}",
        f"为什么值得投: {reason_text}",
        f"风险: {risk_text}",
        f"链接: {item.get('url', '')}",
    ]


def choose_daily_action(picks: list[dict], jobs: list[dict]) -> tuple[str, str]:
    if jobs and job_priority(jobs[0]) in {"S", "A"}:
        company = (jobs[0].get("metrics") or {}).get("company") or display_name(jobs[0])
        return (
            f"去看 {short(company, 60)}",
            "它和 Andrew 的 Senior Backend / AI infra / remote 目标最接近，30 分钟内能判断是否值得定制简历投递。",
        )
    if picks:
        name = display_name(picks[0])
        return (
            f"去看 {name}",
            "它是今天商业价值最高的非岗位机会，适合判断是否值得 Fork、学习或做成创业方向。",
        )
    return ("整理岗位关键词", "今天没有足够强的机会，先优化搜索条件和简历关键词。")


def andrew_score(item: dict) -> int:
    text = item_text(item)
    score = int(float(item.get("score") or 0) // 2)
    if "job" in item.get("tags", []):
        score += int(job_match_score(item))
        score += ai_job_rank(item) * 25
    for term in (
        "backend",
        "distributed systems",
        "streaming",
        "real-time",
        "kafka",
        "flink",
        "aws",
        "platform",
        "infrastructure",
        "agent",
        "llm",
        "mcp",
        "retrieval",
        "vector search",
    ):
        if text_has_term(text, term):
            score += 8
    if "product-launch" in detect_themes(text):
        score -= 12
    return max(0, score)


def pick_best_startup(items: list[dict]) -> dict | None:
    blocked = ("remote working", "weak junior hiring", "job losses", "blame for", "market report")

    def is_startup_candidate(item: dict) -> bool:
        text = item_text(item)
        if item.get("source_type") == "job-board" or "job" in item.get("tags", []):
            return False
        if any(term in text for term in blocked):
            return False
        source = str(item.get("source") or "").lower()
        title = str(item.get("title") or "").lower()
        return (
            item.get("source_type") == "product-hunt"
            or "launch hn" in source
            or "show hn" in source
            or title.startswith("show hn:")
            or title.startswith("launch hn:")
            or {"startup", "product"}.intersection(set(item.get("tags") or []))
            and "market" not in item.get("tags", [])
        )

    candidates = [
        item
        for item in items
        if not is_github_url(item) and is_startup_candidate(item)
    ]
    return max(candidates, key=lambda item: (decision_rank(startup_decision(item)), andrew_score(item)), default=None)


def pick_best_open_source(items: list[dict]) -> dict | None:
    candidates = [
        item
        for item in items
        if item.get("source_type") != "job-board" and (is_github_url(item) or item.get("source_type") == "github-trending")
    ]
    return max(candidates, key=lambda item: (decision_rank(open_source_decision(item)), andrew_score(item)), default=None)


def pain_point_score(items: list[dict]) -> dict:
    best = {
        "name": "暂无明确高频痛点",
        "count": 0,
        "users": "未知",
        "willingness": "未知",
        "evidence": [],
    }
    for topic in PAIN_TOPICS:
        evidence = []
        for item in items:
            if item.get("source_type") == "job-board" or "job" in item.get("tags", []):
                continue
            text = item_text(item)
            if any(text_has_term(text, keyword) for keyword in topic["keywords"]):
                evidence.append(display_name(item))
        if len(evidence) > int(best["count"]):
            best = {
                "name": topic["name"],
                "count": len(evidence),
                "users": topic["users"],
                "willingness": topic["willingness"],
                "evidence": evidence[:3],
            }
    return best


def signal_key(item: dict) -> str:
    raw = str(item.get("url") or item.get("id") or item.get("title") or id(item))
    return re.sub(r"\s+", " ", raw.lower()).strip()


def topic_matches(item: dict, topic: dict) -> bool:
    text = item_text(item)
    return any(text_has_term(text, keyword) for keyword in topic["keywords"])


def item_topics(item: dict) -> list[dict]:
    matched = [topic for topic in TREND_TOPICS if topic_matches(item, topic)]
    if not matched:
        for theme in detect_themes(item_text(item)):
            if theme == "agent-memory":
                matched.extend(topic for topic in TREND_TOPICS if topic["key"] == "agent-memory")
            elif theme == "agent-search":
                matched.extend(topic for topic in TREND_TOPICS if topic["key"] == "agent-search")
            elif theme == "agent-security":
                matched.extend(topic for topic in TREND_TOPICS if topic["key"] == "agent-security")
            elif theme == "agent-infra":
                matched.extend(topic for topic in TREND_TOPICS if topic["key"] == "agent-infrastructure")
    deduped: dict[str, dict] = {}
    for topic in matched:
        deduped[topic["key"]] = topic
    return list(deduped.values())


def snapshot_time(snapshot: dict, fallback: datetime) -> datetime:
    return parse_datetime(str(snapshot.get("run_time") or "")) or fallback


def item_is_trend_signal(item: dict) -> bool:
    if item.get("source_type") == "job-board":
        return False
    text = item_text(item)
    if any(term in text for term in ("product trailers", "tv channel for product hunt")):
        return False
    return bool(item_topics(item))


def count_topic_periods(snapshots: list[dict], now: datetime) -> tuple[dict[str, dict[str, set[str]]], dict[str, list[dict]], dict[str, bool]]:
    periods = {
        "7": (0, 7),
        "14": (0, 14),
        "30": (0, 30),
        "prev7": (7, 14),
    }
    counts: dict[str, dict[str, set[str]]] = {
        topic["key"]: {period: set() for period in periods}
        for topic in TREND_TOPICS
    }
    examples: dict[str, dict[str, dict]] = {topic["key"]: {} for topic in TREND_TOPICS}
    has_period = {"prev7": False, "prev30": False}

    for snapshot in snapshots:
        run_time = snapshot_time(snapshot, now)
        age_days = max(0.0, (now - run_time).total_seconds() / 86400)
        if 7 < age_days <= 14:
            has_period["prev7"] = True
        if 14 < age_days <= 30:
            has_period["prev30"] = True
        if age_days > 30:
            continue
        for item in snapshot.get("items") or []:
            if not item_is_trend_signal(item):
                continue
            key = signal_key(item)
            for topic in item_topics(item):
                topic_key = topic["key"]
                for period, (start, end) in periods.items():
                    if start < age_days <= end or (start == 0 and age_days <= end):
                        counts[topic_key][period].add(key)
                if key not in examples[topic_key]:
                    examples[topic_key][key] = item

    return counts, {key: list(value.values()) for key, value in examples.items()}, has_period


def trend_label(current_7: int, previous_7: int, has_previous_7: bool) -> str:
    if not has_previous_7:
        if current_7 >= 3:
            return "→ Early signal（历史不足，先不判断涨跌）"
        return "→ Weak signal"
    if previous_7 == 0 and current_7 >= 3:
        return "↑ New Uptrend"
    if previous_7 and current_7 >= previous_7 * 1.5 and current_7 >= 3:
        return "↑ Strong Uptrend"
    if current_7 > previous_7:
        return "↑ Uptrend"
    if previous_7 and current_7 <= previous_7 * 0.6:
        return "↓ Cooling"
    return "→ Stable"


def compounding_level(count_30: int) -> str:
    if count_30 >= 10:
        return "Strategic"
    if count_30 >= 5:
        return "Important"
    if count_30 >= 3:
        return "Interesting"
    return "Noise"


def andrew_match_for_topic(topic: dict, counts: dict[str, int]) -> int:
    base_scores = {
        "agent-memory": 90,
        "agent-infrastructure": 88,
        "agent-search": 86,
        "agent-security": 86,
        "evaluation": 84,
        "ai-coding": 80,
        "voice-agents": 78,
        "browser-agents": 74,
    }
    base = base_scores.get(str(topic["key"]), 70)
    boost = min(10, counts["7"] * 2) + min(5, counts["30"] // 3)
    return min(100, base + boost)


def strategic_decision(level: str, match: int) -> str:
    if level == "Strategic" and match >= 85:
        return "Study"
    if level in {"Strategic", "Important", "Interesting"} and match >= 80:
        return "Monitor"
    return "Ignore"


def strategic_signal_score(signal: dict) -> int:
    level_bonus = {"Strategic": 25, "Important": 15, "Interesting": 8, "Noise": 0}.get(str(signal.get("compounding")), 0)
    competition_bonus = {
        "Low": 12,
        "Low-Medium": 8,
        "Medium": 0,
        "High": -20,
    }.get(str(signal.get("competition") or "Medium"), 0)
    stage_bonus = {
        "Early": 10,
        "Early-Mid": 6,
        "Mid": 0,
    }.get(str(signal.get("stage") or "Mid"), 0)
    return int(signal.get("andrew_match") or 0) + level_bonus + competition_bonus + stage_bonus


def thesis_signal_score(signal: dict, signals: list[dict]) -> int:
    score = strategic_signal_score(signal)
    if signal.get("key") == "agent-infrastructure":
        related = {"agent-memory", "agent-search", "evaluation", "agent-security"}
        present_related = {
            str(other.get("key"))
            for other in signals
            if str(other.get("key")) in related and int((other.get("counts") or {}).get("30") or 0) > 0
        }
        score += len(present_related) * 12
    if signal.get("key") == "ai-coding" and signal.get("competition") == "High":
        score -= 12
    return score


def conviction_score(signal: dict, signals: list[dict] | None = None) -> int:
    raw = thesis_signal_score(signal, signals or [signal])
    if raw >= 135:
        return 9
    if raw >= 120:
        return 8
    if raw >= 105:
        return 7
    if raw >= 90:
        return 6
    return max(1, min(5, raw // 18))


def thesis_confidence(signal: dict, signals: list[dict] | None = None) -> str:
    conviction = conviction_score(signal, signals)
    count_30 = int((signal.get("counts") or {}).get("30") or 0)
    trend = str(signal.get("trend") or "")
    if conviction >= 8 and count_30 >= 5 and "历史不足" not in trend:
        return "High"
    if conviction >= 7 and count_30 >= 3:
        return "Medium"
    return "Low"


def pick_thesis_signal(signals: list[dict]) -> dict | None:
    candidates = [
        signal
        for signal in signals
        if signal.get("compounding") in {"Interesting", "Important", "Strategic"}
        and int(signal.get("andrew_match") or 0) >= 80
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda signal: thesis_signal_score(signal, signals))


def trend_representative_score(item: dict, topic: dict) -> float:
    text = item_text(item)
    score = float(item.get("score") or 0)
    for keyword in topic.get("keywords") or []:
        if text_has_term(text, str(keyword)):
            score += 35
    if is_github_url(item):
        score += 20
    source = str(item.get("source") or "").lower()
    title = str(item.get("title") or "").lower()
    if "show hn" in source or "launch hn" in source or title.startswith(("show hn:", "launch hn:")):
        score += 12
    if any(term in text for term in ("random saas", "get 10 users", "product hunt launches")):
        score -= 45
    return score


def topic_meta(signal: dict | None) -> dict:
    if not signal:
        return {}
    return TOPIC_THESIS_META.get(str(signal.get("key")), {})


def build_repeated_signals(snapshots: list[dict]) -> list[dict]:
    now_candidates = [parse_datetime(str(snapshot.get("run_time") or "")) for snapshot in snapshots]
    now = max((candidate for candidate in now_candidates if candidate), default=utc_now())
    raw_counts, examples, has_period = count_topic_periods(snapshots, now)
    topics_by_key = {topic["key"]: topic for topic in TREND_TOPICS}
    signals: list[dict] = []

    for key, topic in topics_by_key.items():
        counts = {
            "7": len(raw_counts[key]["7"]),
            "14": len(raw_counts[key]["14"]),
            "30": len(raw_counts[key]["30"]),
            "prev7": len(raw_counts[key]["prev7"]),
        }
        if counts["30"] == 0:
            continue
        representatives = sorted(examples.get(key, []), key=lambda item: trend_representative_score(item, topic), reverse=True)[:3]
        match = andrew_match_for_topic(topic, counts)
        level = compounding_level(counts["30"])
        signals.append(
            {
                "key": key,
                "topic": topic["name"],
                "counts": counts,
                "trend": trend_label(counts["7"], counts["prev7"], has_period["prev7"]),
                "representatives": representatives,
                "andrew_match": match,
                "andrew_reasons": topic["andrew_reasons"],
                "stage": topic["stage"],
                "competition": topic["competition"],
                "enterprise_demand": topic["enterprise_demand"],
                "action": topic["action"],
                "compounding": level,
                "decision": strategic_decision(level, match),
            }
        )

    signals.sort(key=lambda signal: (signal["counts"]["7"], signal["counts"]["30"], signal["andrew_match"]), reverse=True)
    return signals


def format_repeated_signal(signal: dict, rank: int) -> list[str]:
    counts = signal["counts"]
    representative_names = [display_name(item) for item in signal.get("representatives") or []]
    return [
        f"{rank}. {signal['topic']}",
        f"7天: {counts['7']} | 14天: {counts['14']} | 30天: {counts['30']}",
        f"趋势: {signal['trend']}",
        f"代表项目: {', '.join(representative_names) or '暂无'}",
        f"Andrew Match: {signal['andrew_match']}/100",
        f"原因: {', '.join(signal['andrew_reasons'][:5])}",
        f"行动建议: {signal['action']}",
    ]


def format_repeated_signals(signals: list[dict], limit: int = 3) -> list[str]:
    if not signals:
        return ["暂无足够重复信号；今天不做趋势判断。"]
    lines: list[str] = []
    for idx, signal in enumerate(signals[:limit], 1):
        if lines:
            lines.append("")
        lines.extend(format_repeated_signal(signal, idx))
    return lines


def format_strategic_opportunities(signals: list[dict], limit: int = 3) -> list[str]:
    strategic = [
        signal
        for signal in signals
        if signal["compounding"] in {"Interesting", "Important", "Strategic"} and signal["decision"] != "Ignore"
    ]
    strategic.sort(key=strategic_signal_score, reverse=True)
    strategic = strategic[:limit]
    if not strategic:
        return ["暂无 Strategic/Important 级方向；继续观察，不要硬投入。"]

    lines: list[str] = []
    for signal in strategic:
        if lines:
            lines.append("")
        lines.extend(
            [
                f"Market: {signal['topic']}",
                f"Current Stage: {signal['stage']}",
                f"Competition: {signal['competition']}",
                f"Enterprise Demand: {signal['enterprise_demand']}",
                f"Andrew Advantage: {'High' if signal['andrew_match'] >= 85 else 'Medium'}",
                f"Compounding: {signal['compounding']} ({signal['counts']['30']} signals / 30天)",
                f"Decision: {signal['decision']}",
            ]
        )
    return lines


def format_andrew_thesis(signals: list[dict]) -> list[str]:
    thesis = pick_thesis_signal(signals)
    if not thesis:
        return [
            "未来6-24个月最值得关注: 暂无",
            "观点: 当前重复信号还没有达到 Andrew 投入标准。",
            "Confidence: Low",
        ]

    meta = topic_meta(thesis)
    representatives = [display_name(item) for item in thesis.get("representatives") or []]
    counts = thesis["counts"]
    return [
        "未来6-24个月最值得关注:",
        f"#1 {thesis['topic']}",
        f"为什么: {meta.get('why', thesis['action'])}",
        f"谁会付钱: {meta.get('customers', 'AI/平台工程团队')}",
        f"预算来源: {meta.get('budget', 'Platform budget')}",
        f"为什么现在出现: {meta.get('why_now', 'agent 工作流从 demo 走向生产，基础设施需求开始暴露。')}",
        f"Andrew优势: {', '.join(thesis['andrew_reasons'][:5])}",
        f"Signals: 7天 {counts['7']} / 14天 {counts['14']} / 30天 {counts['30']}",
        f"Conviction: {conviction_score(thesis, signals)}/10",
        f"Confidence: {thesis_confidence(thesis, signals)}",
        f"代表样本: {', '.join(representatives) or '暂无'}",
    ]


def build_capital_allocation(signals: list[dict], job: dict | None) -> list[tuple[int, str, str]]:
    thesis = pick_thesis_signal(signals)
    if not thesis:
        job_pct = 30 if job and job_decision(job) == "Apply Now" else 15
        return [
            (job_pct, "AI Jobs", "只投 Apply Now 级别岗位；其余 Watchlist 不定制简历。"),
            (100 - job_pct, "Cash / Wait", "趋势信号不足，保留时间，不为了忙而忙。"),
        ]

    ordered = sorted(
        [signal for signal in signals if signal is not thesis and signal.get("compounding") != "Noise"],
        key=lambda signal: thesis_signal_score(signal, signals),
        reverse=True,
    )
    job_pct = 20 if job and job_decision(job) == "Apply Now" else 10
    allocation: list[tuple[int, str, str]] = [
        (45, str(thesis["topic"]), "主 thesis；未来30天默认押注方向。"),
    ]
    if ordered:
        allocation.append((25, str(ordered[0]["topic"]), "第二优先级；只研究与主 thesis 有耦合的部分。"))
    else:
        allocation.append((25, "Thesis Deep Work", "没有第二强方向，把时间加到主 thesis 深挖。"))
    allocation.append((job_pct, "AI Jobs", "只投 OpenAI/Anthropic/Cursor/Glean/高薪 AI infra remote；Watchlist 不投。"))
    used = sum(percent for percent, _, _ in allocation)
    allocation.append((100 - used, "Other", "保留给关系维护、简历微调和不可预期机会；不碰低护城河项目。"))
    return allocation


def format_capital_allocation(signals: list[dict], job: dict | None) -> list[str]:
    lines = ["未来30天投入比例:"]
    for percent, name, reason in build_capital_allocation(signals, job):
        lines.append(f"{percent}% {name} — {reason}")
    return lines


def format_top_signal_v4(signal: dict, rank: int, signals: list[dict]) -> list[str]:
    counts = signal["counts"]
    representatives = [display_name(item) for item in signal.get("representatives") or []]
    return [
        f"{rank}. {signal['topic']}",
        f"Signals: {counts['30']}（7天 {counts['7']} / 14天 {counts['14']} / 30天 {counts['30']}）",
        f"Conviction: {conviction_score(signal, signals)}/10",
        f"Reason: {signal['compounding']}；{signal['enterprise_demand']} enterprise demand；Andrew Match {signal['andrew_match']}/100；Competition {signal['competition']}",
        f"代表样本: {', '.join(representatives) or '暂无'}",
        f"Decision: {signal['decision']}",
    ]


def format_top_signals_v4(signals: list[dict], limit: int = 3) -> list[str]:
    if not signals:
        return ["暂无可用信号。"]
    ordered = sorted(signals, key=lambda signal: thesis_signal_score(signal, signals), reverse=True)
    lines: list[str] = []
    for idx, signal in enumerate(ordered[:limit], 1):
        if lines:
            lines.append("")
        lines.extend(format_top_signal_v4(signal, idx, signals))
    return lines


def format_ignore_list(signals: list[dict], job: dict | None) -> list[str]:
    lines = [
        "1. Generic Chatbot — Ignore",
        "原因: 竞争激烈、分发困难、与 Andrew 的分布式系统/平台优势不匹配。",
        "",
        "2. Thin AI Wrapper / Random SaaS — Ignore",
        "原因: 护城河弱，容易被模型平台或现有 SaaS 吞掉。",
        "",
        "3. Broad AI Coding Wrapper — Ignore",
        "原因: AI Coding 方向只看 infra、quality、security、team governance；不做普通插件或壳。",
        "",
        "4. Low-Confidence AI-Adjacent Jobs — Ignore",
        "原因: 没有 AI-native 证据、没有高薪证据、没有 Staff/Senior Staff 远程证据时，不定制简历。",
    ]
    if job and job_decision(job) == "Watchlist":
        company = short((job.get("metrics") or {}).get("company") or display_name(job), 50)
        lines.extend(["", f"当前例子: {company} 是 Watchlist，不是 Apply。"])
    return lines


def first_github_representative(signal: dict | None) -> dict | None:
    if not signal:
        return None
    for item in signal.get("representatives") or []:
        if is_github_url(item):
            return item
    return None


def format_action_plan(signals: list[dict], job: dict | None) -> list[str]:
    thesis = pick_thesis_signal(signals)
    if not thesis:
        return [
            "未来7天:",
            "阅读: 不新增材料；等待更多重复信号。",
            "Fork: 无。",
            "联系: 无。",
            "申请: 只查 S级 AI infra remote，其他岗位不投。",
            "目标: 保持现金仓位，不为低质量机会分心。",
        ]

    meta = topic_meta(thesis)
    representatives = thesis.get("representatives") or []
    reading = ", ".join(display_name(item) for item in representatives[:3]) or thesis["topic"]
    fork_item = first_github_representative(thesis)
    apply_line = "申请: 0 个；只把 OpenAI/Anthropic/Cursor/Glean 的 Staff/Senior AI Infra Remote 加入候选清单。"
    if job and job_decision(job) == "Apply Now":
        company = short((job.get("metrics") or {}).get("company") or display_name(job), 60)
        apply_line = f"申请: 定制并投递 {company}，前提是远程范围和薪资证据确认。"
    return [
        "未来7天:",
        f"阅读: {reading}；目标是提取客户、预算、架构和失败模式。",
        f"Fork: {display_name(fork_item)} ({fork_item.get('url')})" if fork_item else "Fork: 暂无合适 GitHub 样本；先找一个可运行实现。",
        f"联系: 找 3 个 {meta.get('customers', 'AI/平台工程')} 从业者，问他们是否已经为这个问题付费或预算归谁。",
        apply_line,
        f"目标: 验证 {thesis['topic']} 是否有明确企业预算，以及 Andrew 能否用后端/平台优势切进去。",
    ]


def choose_v4_action(signals: list[dict], job: dict | None) -> tuple[str, str]:
    thesis = pick_thesis_signal(signals)
    if job and job_decision(job) == "Apply Now":
        company = short((job.get("metrics") or {}).get("company") or display_name(job), 60)
        return (f"确认并投递 {company}", "岗位达到 Apply Now，但仍必须先确认薪资、远程范围和 AI-native 证据。")
    if thesis:
        return (
            f"执行 7-Day Plan: {thesis['topic']}",
            f"这是当前最高 conviction thesis：{conviction_score(thesis, signals)}/10；未来30天先押这里。",
        )
    return ("NO ACTION TODAY", "没有 thesis 达到最低 conviction；保持等待。")


def external_evidence_level(signal: dict | None, signals: list[dict]) -> str:
    if not signal:
        return "Low"
    count_30 = int((signal.get("counts") or {}).get("30") or 0)
    confidence = thesis_confidence(signal, signals)
    if confidence == "High" and count_30 >= 10:
        return "High"
    if confidence in {"High", "Medium"} and count_30 >= 3:
        return "Medium"
    return "Low"


def format_single_bet(signals: list[dict]) -> list[str]:
    thesis = pick_thesis_signal(signals)
    if not thesis:
        return [
            "Bet: Cash / Wait",
            "观点: 外部信号还不足以形成未来30天押注。",
            "Decision: Wait",
            "Conviction: 0/10",
        ]
    meta = topic_meta(thesis)
    return [
        f"Bet: {thesis['topic']}",
        f"观点: 未来30天默认押注 {thesis['topic']}，不是分散看一堆项目。",
        f"为什么: {meta.get('why', thesis['action'])}",
        f"谁会付钱: {meta.get('customers', 'AI/平台工程团队')}",
        f"预算来源: {meta.get('budget', 'Platform budget')}",
        f"Decision: {'Study' if conviction_score(thesis, signals) >= 8 else 'Monitor'}",
        f"Conviction: {conviction_score(thesis, signals)}/10",
    ]


def format_external_evidence_level(signals: list[dict]) -> list[str]:
    thesis = pick_thesis_signal(signals)
    if not thesis:
        return ["Level: Low", "原因: 还没有重复主题达到 Interesting。"]
    counts = thesis["counts"]
    representatives = [display_name(item) for item in thesis.get("representatives") or []]
    return [
        f"Level: {external_evidence_level(thesis, signals)}",
        f"Signals: 7天 {counts['7']} / 14天 {counts['14']} / 30天 {counts['30']}",
        f"Trend: {thesis['trend']}",
        f"Representative Evidence: {', '.join(representatives) or '暂无'}",
        f"Confidence: {thesis_confidence(thesis, signals)}",
    ]


def format_andrew_edge_v51(signals: list[dict]) -> list[str]:
    thesis = pick_thesis_signal(signals)
    if not thesis:
        return ["Edge: 暂无可映射方向。"]
    return [
        f"Edge: {', '.join(thesis['andrew_reasons'][:5])}",
        "为什么是 Andrew: 你的 Disney / Binance / TikTok 背景更适合做可靠平台、状态管理、吞吐、延迟和生产可观测性，而不是做低门槛 wrapper。",
        f"Match: {thesis['andrew_match']}/100",
    ]


def format_internal_loop(loop: dict) -> list[str]:
    hours = loop.get("hours") or {}

    def hour_line(label: str) -> str:
        value = hours.get(label)
        if value is None:
            return f"{label}: 未提供"
        return f"{label}: {value:g}h"

    got = loop.get("got") or []
    lines = [
        "Internal Loop:",
        f"状态: {loop['status']}",
        str(loop["state_line"]),
        f"Updated: {loop.get('updated_at') or 'unknown'}",
        "",
        "本周投入:",
        hour_line("Agent Infra"),
        hour_line("Agent Security"),
        hour_line("Job Search"),
        hour_line("Side Project"),
        "",
        "本周产出:",
    ]
    if got:
        lines.extend(f"- {item}" for item in got[:4])
    else:
        lines.append("- 未提供")
    lines.extend(
        [
            "",
            f"ROI判断: {loop['roi']}",
            f"原因: {loop['reason']}",
        ]
    )
    return lines


def format_validation_plan(signals: list[dict], loop: dict) -> list[str]:
    thesis = pick_thesis_signal(signals)
    if loop["status"] != "Fresh":
        return [
            "1. 先补 Internal Loop：用 10 分钟填写 weekly_update.md。",
            "2. 不做 ROI 判断，直到 Andrew 提供本周投入和产出。",
            "3. 外部验证只保留一个问题：这个方向是否有明确企业预算？",
        ]
    if not thesis:
        return [
            "1. 暂停新项目。",
            "2. 只收集更多外部信号。",
            "3. 下周再决定是否形成 Single Bet。",
        ]
    meta = topic_meta(thesis)
    representatives = [display_name(item) for item in thesis.get("representatives") or []]
    return [
        f"1. 阅读: {', '.join(representatives[:3]) or thesis['topic']}，只提取客户、预算、架构、失败模式。",
        f"2. 联系: 找 3 个 {meta.get('customers', 'AI/平台工程团队')} 从业者，问是否已经为这个问题付费。",
        f"3. Fork: {display_name(first_github_representative(thesis)) if first_github_representative(thesis) else '找一个可运行样本'}，只看接口、状态、权限、可观测性。",
        f"4. 输出: 写 1 页验证结论：{thesis['topic']} 是否值得 Andrew 连续投入 30 天。",
    ]


def format_stop_doing_v51(job: dict | None) -> list[str]:
    lines = [
        "Generic Chatbot — Stop",
        "原因: 竞争激烈、分发困难、与 Andrew 平台优势不匹配。",
        "",
        "Thin AI Wrapper / Random SaaS — Stop",
        "原因: 护城河弱，容易被模型平台或现有 SaaS 吞掉。",
        "",
        "Broad AI Coding Wrapper — Stop",
        "原因: 只看 infra / quality / security / governance，不做普通壳。",
        "",
        "Low-Confidence AI-Adjacent Jobs — Stop",
        "原因: 没有 AI-native 证据、没有高薪证据、没有 Staff/Senior Staff remote 证据，不定制简历。",
    ]
    if job and job_decision(job) == "Watchlist":
        company = short((job.get("metrics") or {}).get("company") or display_name(job), 50)
        lines.extend(["", f"当前例子: {company} 是 Watchlist，不是 Apply。"])
    return lines


def choose_v51_action(signals: list[dict], job: dict | None, loop: dict) -> tuple[str, str]:
    if loop["status"] == "Missing":
        return (
            "填写 weekly_update.md",
            "Internal Loop 缺失；没有 Andrew 的投入/产出数据，就不能形成真实 ROI 闭环。",
        )
    if loop["status"] == "Stale":
        return (
            "更新 weekly_update.md",
            "Internal Loop 已过期；先更新本周投入和产出，再判断下一步。",
        )
    if job and job_decision(job) == "Apply Now":
        company = short((job.get("metrics") or {}).get("company") or display_name(job), 60)
        return (
            f"确认并投递 {company}",
            "岗位达到 Apply Now，但仍必须先确认薪资、远程范围和 AI-native 证据。",
        )
    thesis = pick_thesis_signal(signals)
    if thesis:
        return (
            f"验证 Single Bet: {thesis['topic']}",
            f"外部 conviction={conviction_score(thesis, signals)}/10；今天只验证客户预算和 Andrew 能否切入。",
        )
    return ("NO ACTION TODAY", "外部信号和内部数据都不足，不要为了行动而行动。")


def development_difficulty(item: dict | None) -> str:
    if not item:
        return "未知"
    text = item_text(item)
    if any(term in text for term in ("infrastructure", "distributed systems", "platform", "security", "memory poisoning")):
        return "高"
    if any(term in text for term in ("agent", "mcp", "retrieval", "search", "workflow")):
        return "中"
    return "中低"


def monetization_model(item: dict | None) -> str:
    if not item:
        return "未知"
    text = item_text(item)
    if any(term in text for term in ("api", "infrastructure", "platform", "search", "retrieval", "agent")):
        return "B2B SaaS / API usage / seat-based"
    if any(term in text for term in ("job", "interview", "resume", "hiring")):
        return "订阅 / 成功费 / B2C Pro"
    return "SaaS 订阅或专业版"


def recommendation_grade(score: int) -> str:
    if score >= 140:
        return "A"
    if score >= 90:
        return "B"
    return "C"


def s_tier_company_key(item: dict) -> str | None:
    metrics = item.get("metrics") or {}
    company = normalized_company_name({"metrics": {"company": metrics.get("company") or display_name(item)}})
    first_word = company.split(" ", 1)[0] if company else ""
    if company in S_TIER_COMPANIES:
        return company
    if first_word in S_TIER_COMPANIES:
        return first_word
    return None


def opportunity_competition(selected: dict | None, items: list[dict]) -> list[str]:
    target_names = "/".join(S_TIER_COMPANIES.values())
    jobs = [item for item in top_by_tag(items, {"job"}, len(items)) if is_actionable_job(item)]
    captured_targets = [item for item in jobs if s_tier_company_key(item)]
    if not captured_targets:
        if not selected:
            return [f"S级目标 {target_names}: 今天抓取源未捕获可投岗位；这不是官网全网结论。"]
        decision = job_decision(selected)
        if decision == "Apply Now":
            return [
                f"S级目标 {target_names}: 今天抓取源未捕获可投岗位；这不是官网全网结论。",
                "为什么今天推荐它: 在已抓取候选里，它有明确 AI-first/role/匹配证据，达到 Apply Now。",
            ]
        return [
            f"S级目标 {target_names}: 今天抓取源未捕获可投岗位；这不是官网全网结论。",
            f"为什么不是今天唯一投递: 当前候选只是已抓取来源里的最好观察对象，Decision={decision}，不占用投递名额。",
        ]

    captured_targets.sort(key=lambda item: (job_decision(item) == "Apply Now", job_match_score(item)), reverse=True)
    names = ", ".join(
        short((item.get("metrics") or {}).get("company") or display_name(item), 28)
        for item in captured_targets[:3]
    )
    selected_key = s_tier_company_key(selected) if selected else None
    if selected_key:
        return [
            f"S级候选已捕获: {names}",
            "为什么它赢: 它在 S级候选里当前匹配度最高，且证据链足够进入今日决策。",
        ]
    return [
        f"S级候选已捕获: {names}",
        "为什么不是它们: 今日抓取到的 S级候选匹配度/地区/角色证据弱于当前候选；需要人工复核官网。",
    ]


def format_job_os(job: dict | None, items: list[dict] | None = None) -> list[str]:
    items = items or []
    if not job or job_decision(job) == "Ignore":
        lines = ["工作: 无", "Decision: Ignore", "原因: 今天没有达到 Andrew 标准的 AI/AI infra 岗位。", "Opportunity Competition:"]
        lines.extend(f"- {line}" for line in opportunity_competition(None, items))
        return lines
    metrics = job.get("metrics") or {}
    company = short(metrics.get("company") or display_name(job), 48)
    lines = [
        f"公司: {company}",
        f"岗位: {clean_job_role(job)}",
        f"Company Type: {company_type(job)}",
        f"Role Type: {role_type(job)}",
        f"TC Estimate: {estimate_tc(job)}",
        "Evidence:",
    ]
    lines.extend(f"- {line}" for line in job_evidence(job))
    lines.extend(
        [
            f"Confidence: {job_confidence(job)}",
            f"Andrew Score: {andrew_score(job)}",
            f"Decision: {job_decision(job)}",
            f"Reason: {'、'.join((metrics.get('job_match_reasons') or [])[:4]) or '和 Andrew 背景匹配不足'}",
            "Opportunity Competition:",
        ]
    )
    lines.extend(f"- {line}" for line in opportunity_competition(job, items))
    lines.append(f"链接: {job.get('url', '')}")
    return lines


def format_job_v3(job: dict | None, items: list[dict] | None = None) -> list[str]:
    items = items or []
    if not job:
        lines = ["无值得立刻投递岗位。", "Decision: Ignore", "原因: 今天没有达到 Andrew 标准的 AI/AI infra 岗位。"]
        lines.extend(f"Competition: {line}" for line in opportunity_competition(None, items)[:1])
        return lines

    metrics = job.get("metrics") or {}
    company = short(metrics.get("company") or display_name(job), 48)
    decision = job_decision(job)
    if decision != "Apply Now":
        lines = [
            "无值得立刻投递岗位。",
            f"观察候选: {company} — {clean_job_role(job)}",
            f"Company Type: {company_type(job)}",
            f"TC Estimate: {estimate_tc(job)}",
            f"Confidence: {job_confidence(job)}",
            f"Decision: {decision}",
            "为什么不投: 证据不足以占用当天唯一投递名额。",
        ]
        lines.extend(f"Competition: {line}" for line in opportunity_competition(job, items)[:2])
        return lines

    return [
        f"公司: {company}",
        f"岗位: {clean_job_role(job)}",
        f"Company Type: {company_type(job)}",
        f"Role Type: {role_type(job)}",
        f"TC Estimate: {estimate_tc(job)}",
        f"Confidence: {job_confidence(job)}",
        f"Decision: Apply Now",
        f"为什么投: {'、'.join((metrics.get('job_match_reasons') or [])[:4]) or '和 Andrew 背景匹配。'}",
        f"链接: {job.get('url', '')}",
    ]


def format_startup_os(item: dict | None) -> list[str]:
    if not item or startup_decision(item) == "Ignore":
        return ["Decision: Ignore", "原因: 今天没有明确创业机会。"]
    one_liner, why_lines, _ = opportunity_profile(item)
    if one_liner.startswith("可能是") or one_liner.startswith("雷达认为"):
        one_liner = title_detail(item)
    score = andrew_score(item)
    return [
        f"项目: {display_name(item)}",
        f"一句话: {short(one_liner, 100)}",
        f"客户是谁: {user_group_for_item(item)}",
        f"痛点是什么: {short(concrete_pain(item, ' '.join(why_lines)), 150)}",
        f"客户是否已经付费: {paying_signal(item)}",
        f"Andrew是否有明显优势: {andrew_project_value(item)}",
        f"开发难度: {development_difficulty(item)}",
        f"市场大小: {market_size(item)}",
        f"Decision: {startup_decision(item)}",
        f"链接: {item.get('url', '')}",
    ]


def format_startup_v3(item: dict | None) -> list[str]:
    if not item or startup_decision(item) == "Ignore":
        return ["无值得单独研究的创业项目。", "Decision: Ignore", "原因: 单个项目不如重复趋势重要。"]
    one_liner, why_lines, _ = opportunity_profile(item)
    if one_liner.startswith("可能是") or one_liner.startswith("雷达认为"):
        one_liner = title_detail(item)
    return [
        f"项目: {display_name(item)}",
        f"一句话: {short(one_liner, 100)}",
        f"背后需求: {short(concrete_pain(item, ' '.join(why_lines)), 130)}",
        f"客户: {user_group_for_item(item)}",
        f"付费信号: {paying_signal(item)}",
        f"Decision: {startup_decision(item)}",
        f"链接: {item.get('url', '')}",
    ]


def user_group_for_item(item: dict | None) -> str:
    if not item:
        return "未知"
    text = item_text(item)
    if "agent" in text or "mcp" in text:
        return "AI agent 开发者、AI infra 团队"
    if "developer" in text or "github" in text or "api" in text:
        return "开发者和平台工程团队"
    if "startup" in item.get("tags", []) or "product" in item.get("tags", []):
        return "B2B SaaS / AI 产品团队"
    return "早期 AI 工具用户"


def format_open_source_os(item: dict | None) -> list[str]:
    if not item or open_source_decision(item) == "Ignore":
        return ["Decision: Ignore", "原因: 今天没有明确开源机会。"]
    one_liner, _, action_lines = opportunity_profile(item)
    if one_liner.startswith("可能是") or one_liner.startswith("雷达认为"):
        one_liner = title_detail(item)
    summary = concrete_pain(item, one_liner)
    return [
        f"项目: {display_name(item)}",
        f"一句话: {short(one_liner, 100)}",
        f"解决什么问题: {short(summary, 130)}",
        f"是否值得 Fork: {worth_forking(item)}",
        f"是否有商业化潜力: {commercial_value(item)}",
        f"是否能帮助 Andrew 获得工作机会: {'是' if commercial_value(item) == 'A' else '有限'}",
        f"是否能帮助 Andrew 创业: {'是' if commercial_value(item) in {'A', 'B'} else '有限'}",
        f"Decision: {open_source_decision(item)}",
        f"Reason: {short(' '.join(action_lines), 120)}",
        f"链接: {item.get('url', '')}",
    ]


def format_pain_os(pain: dict) -> list[str]:
    return [
        str(pain["name"]),
        f"需求出现次数: {pain['count']}",
        f"用户群体: {pain['users']}",
        f"是否愿意付费: {pain['willingness']}",
        f"证据: {', '.join(pain.get('evidence') or []) or '暂无'}",
        "Andrew是否有优势: 后端、平台、实时系统和 AI infra 背景适合做可靠工具层。",
        f"Decision: {'Study' if int(pain['count']) >= 3 else 'Ignore'}",
    ]


def build_email_body(test_results: list[StepResult], radar_result: StepResult) -> str:
    raw = latest_raw() or {"items": [], "warnings": []}
    items = raw.get("items", [])
    snapshots = history_with_current(raw)
    repeated_signals = build_repeated_signals(snapshots)
    internal_loop = read_internal_loop()
    all_ok = all(result.ok for result in test_results + [radar_result])
    status = "OK" if all_ok else "ATTENTION"

    run_url = os.environ.get("GITHUB_RUN_URL")
    report_pointer = run_url or str(REPORT_PATH)
    job = pick_best_job(items)
    action, reason = choose_v51_action(repeated_signals, job, internal_loop)

    body: list[str] = [
        "# Andrew Opportunity OS V5.1",
        "",
        f"状态: {status}",
        "",
        "## 1. Single Bet",
    ]
    body.extend(format_single_bet(repeated_signals))
    body.extend(["", "## 2. External Evidence Level"])
    body.extend(format_external_evidence_level(repeated_signals))
    body.extend(["", "## 3. Andrew Edge"])
    body.extend(format_andrew_edge_v51(repeated_signals))
    body.extend(["", "## 4. Internal Loop"])
    body.extend(format_internal_loop(internal_loop))
    body.extend(["", "## 5. Validation Plan"])
    body.extend(format_validation_plan(repeated_signals, internal_loop))
    body.extend(["", "## 6. Stop Doing"])
    body.extend(format_stop_doing_v51(job))

    body.extend(
        [
            "",
            "## 7. 今日唯一行动",
            action,
            f"原因: {reason}",
            "",
            f"完整原始报告: {report_pointer}",
        ]
    )
    return "\n".join(body).strip() + "\n"


def choose_v3_action(job: dict | None, startup: dict | None, repeated_signals: list[dict]) -> tuple[str, str]:
    if job and job_decision(job) == "Apply Now":
        company = short((job.get("metrics") or {}).get("company") or display_name(job), 60)
        return (
            f"研究/投递 {company}",
            "这是今天唯一达到 Apply Now 的岗位；先确认 JD、薪资和远程范围，再定制简历。",
        )

    strategic = [
        signal
        for signal in repeated_signals
        if signal["compounding"] in {"Interesting", "Important", "Strategic"} and signal["andrew_match"] >= 85
    ]
    if strategic:
        signal = max(strategic, key=strategic_signal_score)
        return (
            f"验证趋势: {signal['topic']}",
            f"{signal['topic']} 在 30 天窗口达到 {signal['compounding']}，Andrew Match={signal['andrew_match']}/100，竞争={signal.get('competition', 'Unknown')}；今天只验证客户和付费场景。",
        )

    if startup and startup_decision(startup) == "Copy":
        return (
            f"研究 {display_name(startup)}",
            "这个创业机会有付费信号且和 Andrew 背景匹配，但仍需先验证它是否属于可复利趋势。",
        )

    return ("NO ACTION TODAY", "没有重复信号达到 Interesting，也没有岗位达到 Apply Now；今天不应该硬行动。")


def choose_os_action(job: dict | None, startup: dict | None, open_source: dict | None, pain: dict) -> tuple[str, str]:
    candidates: list[tuple[int, int, str, str]] = []
    if job and job_decision(job) == "Apply Now":
        candidates.append(
            (
                4,
                andrew_score(job) + 80,
                f"研究/投递 {short((job.get('metrics') or {}).get('company') or display_name(job), 60)}",
                "Decision 是 Apply Now，且公司/角色与 Andrew 的 AI infra 和后端背景匹配。",
            )
        )
    if int(pain["count"]) >= 3:
        candidates.append(
            (
                3,
                int(pain["count"]) * 20,
                f"验证痛点: {pain['name']}",
                "需求重复出现，优先确认用户是否愿意为解决方案付费。",
            )
        )
    if open_source and open_source_decision(open_source) == "Fork":
        candidates.append(
            (
                2,
                andrew_score(open_source) + 30,
                f"Fork/clone {display_name(open_source)}",
                "Decision 是 Fork，能帮助 Andrew 拆 AI 工具/infra 可复用能力。",
            )
        )
    if startup and startup_decision(startup) in {"Study", "Copy"}:
        candidates.append(
            (
                1,
                andrew_score(startup) + (40 if startup_decision(startup) == "Copy" else 20),
                f"研究 {display_name(startup)}",
                f"Decision 是 {startup_decision(startup)}，需要验证客户和付费信号。",
            )
        )
    if not candidates:
        return ("NO ACTION TODAY", "没有候选达到 Apply / Study / Fork 标准，今天不应该分散注意力。")
    _, _, action, reason = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    return action, reason


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
