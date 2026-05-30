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
    all_ok = all(result.ok for result in test_results + [radar_result])
    status = "OK" if all_ok else "ATTENTION"

    run_url = os.environ.get("GITHUB_RUN_URL")
    report_pointer = run_url or str(REPORT_PATH)
    job = pick_best_job(items)
    startup = pick_best_startup(items)
    open_source = pick_best_open_source(items)
    pain = pain_point_score(items)
    action, reason = choose_os_action(job, startup, open_source, pain)

    body: list[str] = [
        "# Andrew Opportunity OS V2",
        "",
        f"状态: {status}",
        "",
        "## 今日唯一工作机会",
    ]
    body.extend(format_job_os(job, items))
    body.extend(["", "## 今日唯一创业机会"])
    body.extend(format_startup_os(startup))
    body.extend(["", "## 今日唯一开源机会"])
    body.extend(format_open_source_os(open_source))
    body.extend(["", "## 本周重复出现最多的需求"])
    body.extend(format_pain_os(pain))

    body.extend(
        [
            "",
            "## 今日唯一动作",
            "",
            "如果今天只能花30分钟:",
            action,
            f"原因: {reason}",
            "",
            f"完整原始报告: {report_pointer}",
        ]
    )
    return "\n".join(body).strip() + "\n"


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
