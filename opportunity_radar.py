#!/usr/bin/env python3
"""
Opportunity Radar

Daily scout for startup, job, product, and market signals across Hacker News,
GitHub Trending, Reddit RSS, Product Hunt, YC, and AI newsletters.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "opportunity_sources.json"
STATE_PATH = ROOT / "data" / "opportunity_seen.json"
RAW_DIR = ROOT / "data" / "opportunity_raw"
REPORTS_DIR = ROOT / "reports"
USER_AGENT = "codex-opportunity-radar/0.1"


@dataclass
class Opportunity:
    id: str
    title: str
    url: str
    source: str
    source_type: str
    published_at: str | None = None
    summary: str = ""
    score: float = 0
    tags: list[str] = field(default_factory=list)
    why: str = ""
    action: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    is_new: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def http_text(url: str, accept: str = "*/*", retries: int = 2) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
    }
    last_error = ""
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {body[:220]}"
            if exc.code in {403, 429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(last_error) from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(last_error) from exc
    raise RuntimeError(last_error or "request failed")


def http_json(url: str, retries: int = 2) -> Any:
    return json.loads(http_text(url, "application/json", retries=retries))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return normalize_space(value)


def truncate(value: str, length: int) -> str:
    value = normalize_space(value)
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def item_id(source: str, url: str, title: str) -> str:
    key = url or f"{source}:{title}"
    return re.sub(r"\s+", "-", key.strip().lower())


def hn_search(query: str, since: datetime, per_query: int) -> list[Opportunity]:
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": str(per_query),
        "numericFilters": f"created_at_i>{int(since.timestamp())}",
    }
    payload = http_json("https://hn.algolia.com/api/v1/search_by_date?" + urlencode(params))
    items: list[Opportunity] = []
    for hit in payload.get("hits", []):
        story_id = str(hit.get("objectID") or hit.get("story_id") or "")
        title = hit.get("title") or hit.get("story_title") or "(untitled)"
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        hn_url = f"https://news.ycombinator.com/item?id={story_id}"
        items.append(
            Opportunity(
                id=f"hn:{story_id}",
                title=normalize_space(title),
                url=url,
                source=f"hn:{query}",
                source_type="hacker-news",
                published_at=hit.get("created_at"),
                summary=f"HN discussion: {points} points, {comments} comments. {hn_url}",
                metrics={"points": points, "comments": comments, "hn_url": hn_url},
            )
        )
    return items


def parse_feed(url: str, label: str, source_type: str, since: datetime, limit: int) -> list[Opportunity]:
    xml_text = http_text(url, "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*")
    root = ET.fromstring(xml_text)
    items: list[Opportunity] = []

    def text_of(node: ET.Element, names: list[str]) -> str:
        for name in names:
            found = node.find(name)
            if found is not None and found.text:
                return found.text
        return ""

    atom_entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    rss_items = root.findall("./channel/item")

    if atom_entries:
        for entry in atom_entries[:limit]:
            title = text_of(entry, ["{http://www.w3.org/2005/Atom}title"])
            link = ""
            for link_node in entry.findall("{http://www.w3.org/2005/Atom}link"):
                rel = link_node.attrib.get("rel", "alternate")
                if rel == "alternate" and link_node.attrib.get("href"):
                    link = link_node.attrib["href"]
                    break
            link = link or text_of(entry, ["{http://www.w3.org/2005/Atom}id"])
            published = text_of(entry, ["{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"])
            published_dt = parse_datetime(published)
            if published_dt and published_dt < since:
                continue
            summary = text_of(entry, ["{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"])
            items.append(
                Opportunity(
                    id=item_id(label, link, title),
                    title=normalize_space(title),
                    url=link,
                    source=label,
                    source_type=source_type,
                    published_at=published_dt.isoformat() if published_dt else published,
                    summary=strip_html(summary),
                )
            )

    for item in rss_items[:limit]:
        title = text_of(item, ["title"])
        link = text_of(item, ["link"])
        published = text_of(item, ["pubDate", "{http://purl.org/dc/elements/1.1/}date"])
        published_dt = parse_datetime(published)
        if published_dt and published_dt < since:
            continue
        summary = text_of(item, ["description", "{http://purl.org/rss/1.0/modules/content/}encoded"])
        items.append(
            Opportunity(
                id=item_id(label, link, title),
                title=normalize_space(title),
                url=link,
                source=label,
                source_type=source_type,
                published_at=published_dt.isoformat() if published_dt else published,
                summary=strip_html(summary),
            )
        )

    return items


class GitHubTrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.in_article = False
        self.capture: str | None = None
        self.link_depth = 0
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        class_attr = attrs_dict.get("class", "")
        if tag == "article" and "Box-row" in class_attr:
            self.in_article = True
            self.current = {"repo": "", "url": "", "description": "", "language": "", "stars": ""}
            return
        if not self.in_article or self.current is None:
            return
        if tag == "h2":
            self.capture = "repo"
            self.text_parts = []
        elif tag == "p" and "col-9" in class_attr:
            self.capture = "description"
            self.text_parts = []
        elif tag == "span" and "repo-language-color" in class_attr:
            self.capture = "language_next"
        elif tag == "a" and self.capture == "repo" and attrs_dict.get("href"):
            self.current["url"] = "https://github.com" + attrs_dict["href"]
        elif tag == "a" and attrs_dict.get("href", "").endswith("/stargazers"):
            self.capture = "stars"
            self.text_parts = []

    def handle_data(self, data: str) -> None:
        if not self.in_article or self.current is None:
            return
        if self.capture == "language_next":
            value = normalize_space(data)
            if value:
                self.current["language"] = value
                self.capture = None
        elif self.capture in {"repo", "description", "stars"}:
            self.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_article or self.current is None:
            return
        if tag == "h2" and self.capture == "repo":
            repo = normalize_space("".join(self.text_parts)).replace(" / ", "/").replace(" ", "")
            self.current["repo"] = repo
            self.capture = None
        elif tag == "p" and self.capture == "description":
            self.current["description"] = normalize_space("".join(self.text_parts))
            self.capture = None
        elif tag == "a" and self.capture == "stars":
            self.current["stars"] = normalize_space("".join(self.text_parts))
            self.capture = None
        elif tag == "article":
            if self.current.get("repo"):
                self.items.append(self.current)
            self.current = None
            self.in_article = False
            self.capture = None


def parse_github_trending(url: str, label: str, limit: int) -> list[Opportunity]:
    parser = GitHubTrendingParser()
    parser.feed(http_text(url, "text/html,*/*"))
    items: list[Opportunity] = []
    for repo in parser.items[:limit]:
        title = repo.get("repo") or "(unknown repo)"
        stars = repo.get("stars") or ""
        items.append(
            Opportunity(
                id=f"github-trending:{title}",
                title=title,
                url=repo.get("url") or f"https://github.com/{title}",
                source=label,
                source_type="github-trending",
                summary=repo.get("description") or "",
                metrics={"stars": stars, "language": repo.get("language") or ""},
            )
        )
    return items


def classify(item: Opportunity, config: dict[str, Any]) -> list[str]:
    text = f"{item.title} {item.summary} {item.source}".lower()
    tags = []
    if item.source_type == "product-hunt":
        tags.append("product")
    if item.source_type == "github-trending":
        tags.append("devtools")
    if item.source_type in {"newsletter", "yc"}:
        tags.append("market")
    job_patterns = [
        r"\bhiring\b",
        r"\bwe'?re hiring\b",
        r"\bremote job\b",
        r"\bremote .* engineer\b",
        r"\bjobs\b",
        r"\bjob board\b",
        r"\bjunior hiring\b",
        r"\bcareer\b",
    ]
    if any(re.search(pattern, text) for pattern in job_patterns):
        tags.append("job")

    if item.source_type == "reddit" and any(needle in text for needle in ["mrr", "revenue", "customers", "validate", "technical founder"]):
        if "startup" not in tags:
            tags.append("startup")
        if "saas" not in tags and "saas" in text:
            tags.append("saas")

    rules = [
        ("startup", ["startup", "founder", "cofounder", "yc", "launch hn", "seed", "raised", "funding"]),
        ("product", ["product hunt", "show hn", "launch", "waitlist", "beta", "customers"]),
        ("ai", [" ai ", "llm", "agent", "automation", "mcp", "model", "openai", "claude"]),
        ("saas", ["saas", "b2b", "revenue", "mrr", "churn"]),
        ("devtools", ["github", "developer", "devtool", "api", "sdk", "coding", "workflow"]),
        ("market", ["trend", "market", "newsletter", "report", "research"]),
    ]
    padded = f" {text} "
    for tag, needles in rules:
        if tag not in tags and any(needle in padded for needle in needles):
            tags.append(tag)
    return tags[:4]


def opportunity_explanation(item: Opportunity) -> tuple[str, str]:
    tags = set(item.tags)
    if "job" in tags:
        return (
            "可能是招聘/合作机会，适合快速判断有没有 AI、devtools、SaaS 相关岗位或客户线索。",
            "打开链接，搜 hiring/remote/founder，记录公司名、岗位、联系方式。",
        )
    if "startup" in tags:
        return (
            "可能是新创业公司、融资、YC/Launch HN 信号，适合找竞品、合作或创业方向。",
            "看它解决什么问题、目标客户是谁、有没有明显可复制的增长/产品角度。",
        )
    if "product" in tags:
        return (
            "可能是新产品发布或 Product Hunt/Show HN 信号，适合找可复用的产品形态。",
            "看 landing page、定价、核心 demo，判断能不能变成你的产品灵感。",
        )
    if "devtools" in tags:
        return (
            "可能是开发者工具趋势，适合找 AI coding、自动化或基础设施机会。",
            "看 README/demo，判断它服务开发者的痛点是不是正在变强。",
        )
    if "market" in tags:
        return (
            "可能是市场/新闻/研究信号，适合判断趋势是否正在扩散。",
            "只看结论和引用案例，决定要不要加入本周观察清单。",
        )
    return (
        "雷达认为它和 AI、SaaS、创业或工作机会有交集，值得快速扫一眼。",
        "用 5 分钟看标题、摘要和评论热度；没有明确机会就跳过。",
    )


def score_item(item: Opportunity, config: dict[str, Any], seen: set[str], now: datetime) -> Opportunity:
    text = f"{item.title} {item.summary} {item.source}".lower()
    opportunity_hits = sum(1 for kw in config["keywords"]["opportunity"] if kw.lower() in text)
    high_intent_hits = sum(1 for kw in config["keywords"]["high_intent"] if kw.lower() in text)
    noise_hits = sum(1 for kw in config["keywords"]["noise"] if kw.lower() in text)
    item.tags = classify(item, config)
    why, action = opportunity_explanation(item)
    item.why = why
    item.action = action
    item.is_new = item.id not in seen

    points = int(item.metrics.get("points") or 0)
    comments = int(item.metrics.get("comments") or 0)
    score = 8 + opportunity_hits * 5 + high_intent_hits * 9 + len(item.tags) * 4
    score += min(points, 500) * 0.2 + min(comments, 300) * 0.35
    if item.source_type == "product-hunt" or item.source == "product-hunt":
        score += 18
    if item.source_type == "github-trending":
        score += 8
    if item.source_type == "hacker-news":
        score += 6
    if item.source_type == "reddit" and any(tag in item.tags for tag in ["startup", "saas", "job"]):
        score += 8
    if item.source_type in {"newsletter", "yc"}:
        score += 4
    if item.source_type == "hacker-news" and re.search(r"^show hn:|^launch hn:", item.title.lower()):
        score += 12
    if item.source_type == "reddit" and re.search(r"mrr|revenue|customers|validate|technical founder", text):
        score += 12
    if re.search(r"apocalypse|explodes|tax costing|politics", text):
        score -= 25
    if item.is_new:
        score += 6
    published = parse_datetime(item.published_at)
    if published:
        age_hours = max(0, (now - published).total_seconds() / 3600)
        score += max(0, 24 - age_hours) * 0.4
    item.score = round(max(0, score - noise_hits * 12), 1)
    return item


def dedupe(items: list[Opportunity]) -> list[Opportunity]:
    by_url: dict[str, Opportunity] = {}
    for item in items:
        key = item.url or item.id
        if key not in by_url or item.score > by_url[key].score:
            by_url[key] = item
    return list(by_url.values())


def collect(config: dict[str, Any], since: datetime, args: argparse.Namespace) -> tuple[list[Opportunity], list[str]]:
    warnings: list[str] = []
    items: list[Opportunity] = []

    for query in config.get("hn_queries", []):
        try:
            items.extend(hn_search(query["query"], since, args.hn_per_query))
        except Exception as exc:
            warnings.append(f"HN failed [{query['label']}]: {exc}")
        time.sleep(0.2)

    for feed in config.get("reddit_feeds", []):
        try:
            items.extend(parse_feed(feed["url"], feed["label"], "reddit", since, args.feed_limit))
        except Exception as exc:
            fallback_url = feed["url"].replace("https://www.reddit.com/", "https://old.reddit.com/")
            if fallback_url != feed["url"]:
                try:
                    items.extend(parse_feed(fallback_url, feed["label"], "reddit", since, args.feed_limit))
                except Exception as fallback_exc:
                    warnings.append(f"Reddit feed failed [{feed['label']}]: {exc}; fallback failed: {fallback_exc}")
            else:
                warnings.append(f"Reddit feed failed [{feed['label']}]: {exc}")
        time.sleep(0.2)

    for feed in config.get("rss_feeds", []):
        try:
            source_type = "product-hunt" if feed["label"] == "product-hunt" else "newsletter"
            if feed["label"] == "yc-blog":
                source_type = "yc"
            items.extend(parse_feed(feed["url"], feed["label"], source_type, since, args.feed_limit))
        except Exception as exc:
            warnings.append(f"RSS failed [{feed['label']}]: {exc}")
        time.sleep(0.2)

    for trending in config.get("github_trending", []):
        try:
            items.extend(parse_github_trending(trending["url"], trending["label"], args.github_limit))
        except Exception as exc:
            warnings.append(f"GitHub Trending failed [{trending['label']}]: {exc}")
        time.sleep(0.2)

    return items, warnings


def render_report(items: list[Opportunity], warnings: list[str], since: datetime, now: datetime, max_items: int) -> str:
    lines: list[str] = []
    lines.append("# Opportunity Radar")
    lines.append("")
    lines.append(f"- Run time: {now.astimezone().strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"- Window: {since.isoformat()} to {now.isoformat()}")
    lines.append("- Focus: jobs, startups, SaaS, AI products, YC, Product Hunt, GitHub Trending, HN, Reddit, newsletters")
    lines.append("")
    if warnings:
        lines.append("## Collection Warnings")
        for warning in warnings[:12]:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## Today Read These")
    for idx, item in enumerate(items[:5], 1):
        lines.append(f"{idx}. [{item.title}]({item.url}) - score {item.score}, {item.source}")
        lines.append(f"   - Why: {item.why}")
        lines.append(f"   - Action: {item.action}")
    lines.append("")

    lines.append("## Top Opportunities")
    lines.append("| # | Item | Score | Source | Tags | Why |")
    lines.append("|---:|---|---:|---|---|---|")
    for idx, item in enumerate(items[:max_items], 1):
        marker = " NEW" if item.is_new else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    f"[{item.title.replace('|', '\\|')}]({item.url}){marker}",
                    str(item.score),
                    item.source.replace("|", "\\|"),
                    ", ".join(item.tags).replace("|", "\\|") or "general",
                    truncate(item.why, 120).replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## New Signals")
    new_items = [item for item in items if item.is_new]
    for item in new_items[:15]:
        lines.append(f"- [{item.title}]({item.url}) - {item.source}; {', '.join(item.tags) or 'general'}")
    if not new_items:
        lines.append("- No new items versus the previous snapshot.")
    lines.append("")

    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    now = utc_now()
    config = load_json(args.config, {})
    if not config:
        print(f"Missing config: {args.config}", file=sys.stderr)
        return 2
    since = now - timedelta(hours=args.hours or config.get("lookback_hours", 48))
    seen_payload = load_json(STATE_PATH, {"seen": []})
    seen = set(seen_payload.get("seen", []))

    collected, warnings = collect(config, since, args)
    scored = [score_item(item, config, seen, now) for item in dedupe(collected)]
    scored = [item for item in scored if item.score >= config.get("min_score", 18)]
    scored.sort(key=lambda item: item.score, reverse=True)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    write_json(
        RAW_DIR / f"{run_id}.json",
        {
            "run_time": now.isoformat(),
            "since": since.isoformat(),
            "items": [asdict(item) for item in scored],
            "warnings": warnings,
        },
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = render_report(scored, warnings, since, now, args.max_items)
    dated_report = REPORTS_DIR / f"{now.date().isoformat()}-opportunity-radar.md"
    latest_report = REPORTS_DIR / "opportunity_latest.md"
    dated_report.write_text(report, encoding="utf-8")
    latest_report.write_text(report, encoding="utf-8")

    write_json(STATE_PATH, {"updated_at": now.isoformat(), "seen": sorted(set(seen) | {item.id for item in scored})})

    print(f"Wrote {dated_report}")
    print(f"Wrote {latest_report}")
    print(f"Ranked {len(scored)} opportunities; {sum(1 for item in scored if item.is_new)} new.")
    if warnings:
        print(f"Warnings: {len(warnings)}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a daily opportunity radar report.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--hours", type=int, default=0, help="Lookback window in hours; defaults to config.")
    parser.add_argument("--max-items", type=int, default=25)
    parser.add_argument("--hn-per-query", type=int, default=15)
    parser.add_argument("--feed-limit", type=int, default=12)
    parser.add_argument("--github-limit", type=int, default=12)
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
