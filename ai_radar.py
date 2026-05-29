#!/usr/bin/env python3
"""
AI OSS Radar

Find fast-moving open-source projects around Codex, Claude Code, OpenAI,
agentic coding, MCP, and adjacent AI developer tools. The script is dependency
free so it can run from a scheduled Codex automation without environment setup.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from project_guidance import leverage_note


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "topics.json"
STATE_PATH = ROOT / "data" / "seen_repos.json"
RAW_DIR = ROOT / "data" / "raw"
REPORTS_DIR = ROOT / "reports"
USER_AGENT = "codex-ai-oss-radar/0.1"


@dataclass
class RepoSignal:
    labels: set[str] = field(default_factory=set)
    queries: set[str] = field(default_factory=set)
    hn_points: int = 0
    hn_comments: int = 0
    hn_stories: list[dict[str, Any]] = field(default_factory=list)
    readme_excerpt: str = ""


@dataclass
class ScoredRepo:
    repo: dict[str, Any]
    signal: RepoSignal
    score: float
    relevance: int
    tags: list[str]
    reason: str
    leverage: str
    is_new: bool
    warnings: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_days(value: str, now: datetime) -> int:
    delta = now - parse_github_time(value)
    return max(1, int(delta.total_seconds() // 86400))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def http_json(url: str, headers: dict[str, str] | None = None, retries: int = 2) -> Any:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=request_headers)
            with urlopen(req, timeout=30) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {body[:300]}"
            if exc.code in {403, 429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(last_error) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(last_error) from exc

    raise RuntimeError(last_error or "unknown request error")


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_search(query: str, per_page: int) -> dict[str, Any]:
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": str(per_page),
    }
    url = "https://api.github.com/search/repositories?" + urlencode(params)
    return http_json(url, github_headers())


def hn_search(query: str, since: datetime, per_page: int) -> dict[str, Any]:
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": str(per_page),
        "numericFilters": f"created_at_i>{int(since.timestamp())}",
    }
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urlencode(params)
    return http_json(url)


def fetch_readme_excerpt(repo_full_name: str, max_chars: int = 700) -> str:
    url = f"https://api.github.com/repos/{repo_full_name}/readme"
    try:
        payload = http_json(url, github_headers(), retries=1)
    except RuntimeError:
        return ""
    content = payload.get("content")
    encoding = payload.get("encoding")
    if not content or encoding != "base64":
        return ""
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:
        return ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]+\]\([^)]*\)", lambda m: m.group(0).split("](")[0].lstrip("["), text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def github_repo_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if owner in {"features", "topics", "marketplace", "collections", "trending"}:
        return None
    repo = repo.removesuffix(".git")
    return f"{owner}/{repo}"


def text_blob(repo: dict[str, Any], signal: RepoSignal) -> str:
    pieces = [
        repo.get("name") or "",
        repo.get("full_name") or "",
        repo.get("description") or "",
        " ".join(repo.get("topics") or []),
        " ".join(signal.labels),
        signal.readme_excerpt,
    ]
    return " ".join(pieces).lower()


def count_hits(blob: str, keywords: list[str]) -> int:
    hits = 0
    for keyword in keywords:
        if keyword.lower() in blob:
            hits += 1
    return hits


def classify_repo(blob: str) -> list[str]:
    tags = []
    tag_rules = [
        ("coding-agent", ["coding agent", "agentic coding", "code agent", "terminal agent", "cli agent"]),
        ("codex", ["codex", "openai codex"]),
        ("claude-code", ["claude code", "claude-code"]),
        ("mcp", ["mcp", "model context protocol"]),
        ("skills-prompts", ["skill", "prompt", "command", "system prompt"]),
        ("memory-context", ["memory", "context", "rag", "knowledge"]),
        ("workflow-orchestration", ["workflow", "orchestration", "swarm", "multi-agent", "subagent"]),
        ("observability", ["token", "monitor", "usage", "rate limit", "cost", "telemetry"]),
        ("ide-editor", ["vscode", "cursor", "windsurf", "editor", "ide"]),
        ("automation", ["automation", "scheduler", "browser", "computer use"]),
    ]
    for tag, needles in tag_rules:
        if any(needle in blob for needle in needles):
            tags.append(tag)
    return tags[:5]

def relevance_score(repo: dict[str, Any], signal: RepoSignal, config: dict[str, Any]) -> int:
    blob = text_blob(repo, signal)
    keywords = config["keywords"]
    priority = count_hits(blob, keywords["priority"])
    adjacent = count_hits(blob, keywords["adjacent"])
    source_boost = 0
    if any(label.startswith("topic:") for label in signal.labels):
        source_boost += 2
    if any(label in {"claude-code", "codex", "ai-coding-agent", "mcp-server"} for label in signal.labels):
        source_boost += 2
    return priority * 3 + adjacent + source_boost


def noise_penalty(repo: dict[str, Any], signal: RepoSignal, config: dict[str, Any]) -> int:
    blob = text_blob(repo, signal)
    penalty = 0
    for keyword in config["keywords"].get("noise", []):
        if keyword.lower() in blob:
            penalty += 3
    name = (repo.get("name") or "").lower()
    if name.startswith("awesome"):
        penalty += 8
    if repo.get("fork"):
        penalty += 6
    if repo.get("archived"):
        penalty += 12
    return penalty


def score_repo(
    repo: dict[str, Any],
    signal: RepoSignal,
    config: dict[str, Any],
    now: datetime,
    seen: set[str],
) -> ScoredRepo:
    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    repo_age = age_days(repo.get("created_at"), now)
    pushed_age = age_days(repo.get("pushed_at"), now)
    updated_age = age_days(repo.get("updated_at"), now)
    star_velocity = stars / max(repo_age, 1)
    relevance = relevance_score(repo, signal, config)
    penalty = noise_penalty(repo, signal, config)
    tags = classify_repo(text_blob(repo, signal))
    is_new = repo.get("full_name") not in seen
    has_license = bool(repo.get("license"))

    score = (
        math.log1p(stars) * 16
        + math.log1p(forks) * 5
        + min(star_velocity, 500) * 2.8
        + max(0, 16 - pushed_age) * 2
        + max(0, 10 - updated_age)
        + relevance * 10
        + min(signal.hn_points, 500) * 0.35
        + min(signal.hn_comments, 300) * 0.18
        + (10 if is_new else 0)
        + (6 if has_license else -8)
        - penalty * 8
    )

    warnings = []
    if repo.get("archived"):
        warnings.append("archived")
    if repo.get("fork"):
        warnings.append("fork")
    if not has_license:
        warnings.append("no license detected")
    if relevance < config.get("min_relevance", 4):
        warnings.append("low keyword relevance")

    reasons = [
        f"{stars:,} stars",
        f"{forks:,} forks",
        f"{star_velocity:.1f} stars/day since creation",
        f"pushed {pushed_age}d ago",
    ]
    if signal.hn_points or signal.hn_comments:
        reasons.append(f"HN {signal.hn_points} pts/{signal.hn_comments} comments")
    if is_new:
        reasons.append("new on radar")

    return ScoredRepo(
        repo=repo,
        signal=signal,
        score=round(score, 1),
        relevance=relevance,
        tags=tags,
        reason="; ".join(reasons),
        leverage=leverage_note(tags, text_blob(repo, signal), repo.get("description") or "", repo.get("full_name") or ""),
        is_new=is_new,
        warnings=warnings,
    )


def merge_repo(target: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    # Keep the richer latest GitHub payload; search results are usually identical.
    return incoming if len(json.dumps(incoming)) >= len(json.dumps(target)) else target


def collect_github(config: dict[str, Any], since: datetime, per_query: int) -> tuple[dict[str, dict[str, Any]], dict[str, RepoSignal], list[str]]:
    repos: dict[str, dict[str, Any]] = {}
    signals: dict[str, RepoSignal] = {}
    warnings: list[str] = []

    for query_def in config["github_queries"]:
        label = query_def["label"]
        query = query_def["query"]
        if query_def.get("append_since", True):
            query = f"{query} pushed:>={since.date().isoformat()}"
        try:
            payload = github_search(query, per_query)
        except RuntimeError as exc:
            warnings.append(f"GitHub query failed [{label}]: {exc}")
            continue

        for item in payload.get("items", []):
            full_name = item.get("full_name")
            if not full_name:
                continue
            repos[full_name] = merge_repo(repos.get(full_name, item), item)
            signal = signals.setdefault(full_name, RepoSignal())
            signal.labels.add(label)
            if query_def.get("topic_label"):
                signal.labels.add(f"topic:{query_def['topic_label']}")
            signal.queries.add(query)

        time.sleep(0.35)

    return repos, signals, warnings


def collect_hn(config: dict[str, Any], since: datetime, per_query: int) -> tuple[dict[str, RepoSignal], list[dict[str, Any]], list[str]]:
    repo_signals: dict[str, RepoSignal] = {}
    external_hits: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_story_ids: set[str] = set()

    for query in config["hn_queries"]:
        try:
            payload = hn_search(query, since, per_query)
        except RuntimeError as exc:
            warnings.append(f"HN query failed [{query}]: {exc}")
            continue

        for hit in payload.get("hits", []):
            story_id = str(hit.get("objectID") or hit.get("story_id") or "")
            if story_id in seen_story_ids:
                continue
            seen_story_ids.add(story_id)

            url = hit.get("url") or ""
            story = {
                "title": hit.get("title") or hit.get("story_title") or "(untitled)",
                "url": url or f"https://news.ycombinator.com/item?id={story_id}",
                "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
                "points": int(hit.get("points") or 0),
                "comments": int(hit.get("num_comments") or 0),
                "created_at": hit.get("created_at"),
                "query": query,
            }
            full_name = github_repo_from_url(url)
            if full_name:
                signal = repo_signals.setdefault(full_name, RepoSignal())
                signal.labels.add("hacker-news")
                signal.hn_points += story["points"]
                signal.hn_comments += story["comments"]
                signal.hn_stories.append(story)
            else:
                external_hits.append(story)

        time.sleep(0.2)

    external_hits.sort(key=lambda x: (x["points"], x["comments"]), reverse=True)
    return repo_signals, external_hits, warnings


def enrich_missing_hn_repos(repos: dict[str, dict[str, Any]], signals: dict[str, RepoSignal], warnings: list[str]) -> None:
    for full_name in list(signals.keys()):
        if full_name in repos:
            continue
        url = f"https://api.github.com/repos/{full_name}"
        try:
            payload = http_json(url, github_headers(), retries=1)
        except RuntimeError as exc:
            warnings.append(f"GitHub repo fetch failed [{full_name}]: {exc}")
            continue
        if payload.get("full_name"):
            repos[full_name] = payload
        time.sleep(0.25)


def add_readme_excerpts(scored: list[ScoredRepo], limit: int) -> None:
    for item in scored[:limit]:
        if item.signal.readme_excerpt:
            continue
        item.signal.readme_excerpt = fetch_readme_excerpt(item.repo["full_name"])
        time.sleep(0.2)


def format_date(value: str) -> str:
    return parse_github_time(value).date().isoformat()


def md_escape(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


def truncate(value: str, length: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def render_report(
    scored: list[ScoredRepo],
    external_hits: list[dict[str, Any]],
    warnings: list[str],
    config: dict[str, Any],
    since: datetime,
    now: datetime,
    max_items: int,
) -> str:
    lines: list[str] = []
    lines.append("# AI OSS Radar")
    lines.append("")
    lines.append(f"- Run time: {now.astimezone().strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"- Window: {since.date().isoformat()} to {now.date().isoformat()}")
    lines.append(f"- Focus: Codex, Claude Code, OpenAI/agentic coding, MCP, AI developer tools")
    lines.append(f"- Sources: GitHub Search API, Hacker News Algolia API")
    lines.append("")

    if warnings:
        lines.append("## Collection Warnings")
        for warning in warnings[:8]:
            lines.append(f"- {warning}")
        if len(warnings) > 8:
            lines.append(f"- ... {len(warnings) - 8} more")
        lines.append("")

    new_items = [item for item in scored if item.is_new]
    lines.append("## Executive Picks")
    if not scored:
        lines.append("No qualifying repositories found. Consider widening the query window or adding sources.")
        lines.append("")
    else:
        for idx, item in enumerate(scored[:5], 1):
            repo = item.repo
            lines.append(
                f"{idx}. [{repo['full_name']}]({repo['html_url']}) "
                f"- score {item.score}, {item.reason}."
            )
            lines.append(f"   - Why use it: {item.leverage}")
        lines.append("")

    lines.append("## Top Open-Source Projects")
    lines.append("| # | Project | Score | Stars | Lang | Updated | Tags | Why it surfaced |")
    lines.append("|---:|---|---:|---:|---|---|---|---|")
    for idx, item in enumerate(scored[:max_items], 1):
        repo = item.repo
        tags = ", ".join(item.tags) or "general"
        marker = " NEW" if item.is_new else ""
        warning = f" ({', '.join(item.warnings)})" if item.warnings else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    f"[{md_escape(repo['full_name'])}]({repo['html_url']}){marker}",
                    str(item.score),
                    f"{int(repo.get('stargazers_count') or 0):,}",
                    md_escape(repo.get("language") or "-"),
                    format_date(repo.get("pushed_at")),
                    md_escape(tags),
                    md_escape(truncate(item.reason + warning, 180)),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Quick Leverage Notes")
    for item in scored[: min(10, len(scored))]:
        repo = item.repo
        description = truncate(repo.get("description") or "", 150)
        lines.append(f"- [{repo['full_name']}]({repo['html_url']}): {description}")
        lines.append(f"  - Move: {item.leverage}")
    lines.append("")

    fast_risers = sorted(
        scored,
        key=lambda item: int(item.repo.get("stargazers_count") or 0)
        / max(age_days(item.repo.get("created_at"), now), 1),
        reverse=True,
    )
    lines.append("## Fast-Rising Watchlist")
    for item in fast_risers[:8]:
        repo = item.repo
        velocity = int(repo.get("stargazers_count") or 0) / max(age_days(repo.get("created_at"), now), 1)
        lines.append(
            f"- [{repo['full_name']}]({repo['html_url']}): "
            f"{velocity:.1f} stars/day since {format_date(repo.get('created_at'))}; "
            f"{truncate(repo.get('description') or '', 120)}"
        )
    lines.append("")

    hn_linked = [item for item in scored if item.signal.hn_stories]
    lines.append("## Hacker News Signals")
    if hn_linked:
        for item in hn_linked[:8]:
            repo = item.repo
            story_bits = []
            for story in item.signal.hn_stories[:2]:
                story_bits.append(f"[{md_escape(story['title'])}]({story['hn_url']})")
            lines.append(
                f"- [{repo['full_name']}]({repo['html_url']}): "
                f"{item.signal.hn_points} pts, {item.signal.hn_comments} comments; "
                + "; ".join(story_bits)
            )
    else:
        lines.append("- No GitHub repository links from HN matched the current top list.")
    if external_hits:
        lines.append("")
        lines.append("Other high-signal HN links:")
        for story in external_hits[:8]:
            lines.append(
                f"- [{md_escape(story['title'])}]({story['url']}): "
                f"{story['points']} pts, {story['comments']} comments "
                f"([HN]({story['hn_url']}))"
            )
    lines.append("")

    lines.append("## Query Coverage")
    for query_def in config["github_queries"]:
        lines.append(f"- GitHub: `{query_def['label']}`")
    for query in config["hn_queries"]:
        lines.append(f"- HN: `{query}`")
    lines.append("")

    lines.append("## Next Moves")
    lines.append("- Clone the top 3 and run their demos in a sandbox.")
    lines.append("- For each useful repo, extract: install path, license risk, reusable prompts/skills, tool integrations, and missing product gaps.")
    lines.append("- Keep this radar running daily; new items will be marked `NEW` after the first snapshot.")
    lines.append("")

    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    now = utc_now()
    since = now - timedelta(days=args.days)
    config = load_json(args.config, {})
    if not config:
        print(f"Missing config: {args.config}", file=sys.stderr)
        return 2

    seen_payload = load_json(STATE_PATH, {"seen": []})
    seen = set(seen_payload.get("seen", []))

    repos, signals, warnings = collect_github(config, since, args.per_query)
    hn_signals, external_hits, hn_warnings = collect_hn(config, since, args.hn_per_query)
    warnings.extend(hn_warnings)

    for full_name, signal in hn_signals.items():
        current = signals.setdefault(full_name, RepoSignal())
        current.labels.update(signal.labels)
        current.hn_points += signal.hn_points
        current.hn_comments += signal.hn_comments
        current.hn_stories.extend(signal.hn_stories)

    enrich_missing_hn_repos(repos, signals, warnings)

    scored: list[ScoredRepo] = []
    min_relevance = config.get("min_relevance", 4)
    for full_name, repo in repos.items():
        signal = signals.setdefault(full_name, RepoSignal())
        item = score_repo(repo, signal, config, now, seen)
        if item.relevance >= min_relevance or signal.hn_points >= 30:
            scored.append(item)

    scored.sort(key=lambda item: item.score, reverse=True)
    add_readme_excerpts(scored, args.readme_limit)
    # Re-score after README enrichment so keyword relevance can improve.
    rescored = [score_repo(item.repo, item.signal, config, now, seen) for item in scored]
    rescored.sort(key=lambda item: item.score, reverse=True)
    scored = rescored

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    write_json(
        RAW_DIR / f"{run_id}.json",
        {
            "run_time": now.isoformat(),
            "since": since.isoformat(),
            "repos": [item.repo for item in scored],
            "scores": [
                {
                    "full_name": item.repo["full_name"],
                    "score": item.score,
                    "relevance": item.relevance,
                    "tags": item.tags,
                    "reason": item.reason,
                    "leverage": item.leverage,
                    "new": item.is_new,
                    "warnings": item.warnings,
                }
                for item in scored
            ],
            "external_hn_hits": external_hits,
            "warnings": warnings,
        },
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = render_report(scored, external_hits, warnings, config, since, now, args.max_items)
    dated_report = REPORTS_DIR / f"{now.date().isoformat()}-ai-oss-radar.md"
    latest_report = REPORTS_DIR / "latest.md"
    dated_report.write_text(report, encoding="utf-8")
    latest_report.write_text(report, encoding="utf-8")

    new_seen = sorted(set(seen) | {item.repo["full_name"] for item in scored})
    write_json(STATE_PATH, {"updated_at": now.isoformat(), "seen": new_seen})

    print(f"Wrote {dated_report}")
    print(f"Wrote {latest_report}")
    print(f"Ranked {len(scored)} repositories; {sum(1 for item in scored if item.is_new)} new on radar.")
    if warnings:
        print(f"Warnings: {len(warnings)}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an AI open-source project radar report.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to topics JSON config.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    parser.add_argument("--per-query", type=int, default=20, help="GitHub results per query.")
    parser.add_argument("--hn-per-query", type=int, default=20, help="Hacker News results per query.")
    parser.add_argument("--max-items", type=int, default=25, help="Max projects in the main report table.")
    parser.add_argument("--readme-limit", type=int, default=12, help="Fetch README excerpts for top N repos.")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
