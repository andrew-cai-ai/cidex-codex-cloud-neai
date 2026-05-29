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
from urllib.parse import urlencode, urljoin
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


def parse_remoteok(url: str, label: str, limit: int) -> list[Opportunity]:
    payload = http_json(url)
    items: list[Opportunity] = []
    for row in payload:
        if not isinstance(row, dict) or not row.get("position"):
            continue
        tags = row.get("tags") or []
        salary_min = int(row.get("salary_min") or 0)
        salary_max = int(row.get("salary_max") or 0)
        summary_parts = [
            strip_html(row.get("description") or ""),
            f"Tags: {', '.join(tags[:12])}",
            f"Location: {row.get('location') or 'Remote'}",
        ]
        if salary_min or salary_max:
            summary_parts.append(f"Salary: ${salary_min:,}-${salary_max:,}")
        items.append(
            Opportunity(
                id=f"remoteok:{row.get('id') or row.get('slug')}",
                title=f"{row.get('company')} - {row.get('position')}",
                url=row.get("url") or row.get("apply_url") or "https://remoteok.com/remote-dev-jobs",
                source=label,
                source_type="job-board",
                published_at=row.get("date"),
                summary=" ".join(summary_parts),
                metrics={
                    "company": row.get("company") or "",
                    "role": row.get("position") or "",
                    "location": row.get("location") or "Remote",
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "source_name": "RemoteOK",
                },
            )
        )
        if len(items) >= limit:
            break
    return items


def extract_json_array_after(text: str, marker: str) -> list[Any]:
    decoded = html.unescape(text)
    marker_idx = decoded.find(marker)
    if marker_idx < 0:
        return []
    start = decoded.find("[", marker_idx)
    if start < 0:
        return []
    depth = 0
    in_string = False
    escape = False
    for idx, char in enumerate(decoded[start:], start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(decoded[start : idx + 1])
                except json.JSONDecodeError:
                    return []
    return []


def parse_yc_jobs(url: str, label: str, limit: int) -> list[Opportunity]:
    text = http_text(url, "text/html,*/*")
    jobs = extract_json_array_after(text, '"jobPostings":[')
    items: list[Opportunity] = []
    for job in jobs[:limit]:
        if not isinstance(job, dict):
            continue
        company = job.get("companyName") or "YC company"
        title = job.get("title") or "Engineering role"
        location = job.get("location") or ""
        salary = job.get("salaryRange") or ""
        equity = job.get("equityRange") or ""
        one_liner = job.get("companyOneLiner") or ""
        skills = ", ".join(job.get("skills") or [])
        summary = " ".join(
            part
            for part in [
                one_liner,
                f"Role: {job.get('roleSpecificType') or job.get('prettyRole') or ''}",
                f"Location: {location}",
                f"Salary: {salary}" if salary else "",
                f"Equity: {equity}" if equity else "",
                f"Experience: {job.get('minExperience') or ''}",
                f"Visa: {job.get('visa') or ''}",
                f"Skills: {skills}" if skills else "",
                f"Last active: {job.get('lastActive') or ''}",
            ]
            if part
        )
        items.append(
            Opportunity(
                id=f"yc:{job.get('id')}",
                title=f"{company} - {title}",
                url=urljoin("https://www.ycombinator.com", job.get("url") or ""),
                source=label,
                source_type="job-board",
                summary=summary,
                metrics={
                    "company": company,
                    "role": title,
                    "location": location,
                    "salary": salary,
                    "equity": equity,
                    "last_active": job.get("lastActive") or "",
                    "source_name": "YC Jobs",
                },
            )
        )
    return items


def parse_hnhiring(url: str, label: str, limit: int) -> list[Opportunity]:
    text = http_text(url, "text/html,*/*")
    items: list[Opportunity] = []
    for match in re.finditer(r'<li class="job[^"]*">(?P<li>.*?)</li>', text, re.DOTALL):
        li_html = match.group("li")
        date_match = re.search(r'<span class="gray right type-info">([^<]+)</span>', li_html)
        body_match = re.search(r'<div class="body">(?P<body>.*?)</div>', li_html, re.DOTALL)
        if not body_match:
            continue
        body_html = body_match.group("body")
        body_text = strip_html(body_html)
        if not body_text:
            continue
        parts = [part.strip() for part in re.split(r"\s+\|\s+", body_text) if part.strip()]
        company = re.sub(r"\s*\(\s*https?://[^)]+\)\s*", "", parts[0]).strip() if parts else ""
        role = next((part for part in parts[1:] if re.search(r"engineer|backend|platform|sre|infra", part, re.I)), "")
        if not role or len(role) > 120:
            role_match = re.search(
                r"((?:senior|sr\.?|staff|principal|lead|backend|platform|infra|software)[^.|\n]{0,80}engineer[^.|\n]{0,80})",
                body_text,
                re.I,
            )
            role = role_match.group(1).strip() if role_match else role
        href_match = re.search(r'href="([^"]+)"', body_html)
        target_url = html.unescape(href_match.group(1)) if href_match else url
        title = truncate(body_text, 140)
        items.append(
            Opportunity(
                id=f"hnhiring:{item_id(label, target_url, title)}",
                title=title,
                url=target_url,
                source=label,
                source_type="job-board",
                published_at=date_match.group(1) if date_match else None,
                summary=body_text,
                metrics={"company": company, "role": role or title, "source_name": "HNHIRING"},
            )
        )
        if len(items) >= limit:
            break
    return items


def collect_job_source(source: dict[str, Any]) -> list[Opportunity]:
    source_type = source.get("type")
    limit = int(source.get("limit") or 50)
    if source_type == "remoteok":
        return parse_remoteok(source["url"], source["label"], limit)
    if source_type == "yc-jobs":
        return parse_yc_jobs(source["url"], source["label"], limit)
    if source_type == "hnhiring":
        return parse_hnhiring(source["url"], source["label"], limit)
    raise RuntimeError(f"unsupported job source type: {source_type}")


def parse_salary_max_usd(text: str, metrics: dict[str, Any] | None = None) -> int:
    metrics = metrics or {}
    explicit = int(metrics.get("salary_max") or 0)
    if explicit:
        return explicit
    salary_text = " ".join(
        str(value)
        for value in [
            text,
            metrics.get("salary") or "",
        ]
    )
    values: list[int] = []
    for match in re.finditer(r"\$ ?(\d{2,3}(?:,\d{3})?) ?([kK])?", salary_text):
        raw_number = match.group(1).replace(",", "")
        number = int(raw_number)
        if match.group(2):
            number *= 1000
        elif number < 1000:
            continue
        values.append(number)
    return max(values or [0])


def term_hit(text: str, term: str) -> bool:
    term = term.lower()
    if len(term) <= 3 or re.fullmatch(r"[a-z0-9#+.-]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def candidate_job_match(item: Opportunity, config: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    profile = config.get("candidate_profile", {})
    text = f"{item.title} {item.summary} {item.source} {' '.join(item.tags)}".lower()
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    for term in profile.get("strong_terms", []):
        if term_hit(text, term):
            score += 9
            if len(reasons) < 4:
                reasons.append(term)
    if any(term_hit(text, term) for term in profile.get("ai_terms", [])):
        score += 22
        reasons.append("AI/LLM/agent 相关")
    if any(term_hit(text, term) for term in profile.get("remote_terms", [])):
        score += 18
        reasons.append("remote/Canada-friendly")

    salary_max = parse_salary_max_usd(text, item.metrics)
    item.metrics["salary_max_detected"] = salary_max
    if salary_max >= int(profile.get("min_salary_usd") or 180000):
        score += 14
        reasons.append(f"薪资上限约 ${salary_max:,}+")
    elif salary_max and salary_max < 150000:
        score -= 12
        risks.append(f"薪资可能偏低: ${salary_max:,}")

    for term in profile.get("avoid_terms", []):
        if term_hit(text, term):
            score -= 20
            risks.append(term)
    if "us only" in text or "remote (us)" in text or "us citizen" in text or "remote us" in text:
        score -= 36
        risks.append("可能限制 US")
    if "europe only" in text or "utc+1" in text or "utc+2" in text:
        score -= 10
        risks.append("时区/地区可能不适合 Toronto")
    if "contract" in text or "part-time" in text:
        score -= 10
        risks.append("可能不是全职高薪岗位")

    if "job" in item.tags or item.source_type == "job-board":
        score += 20
    return max(0, score), reasons[:5], risks[:4]


def classify(item: Opportunity, config: dict[str, Any]) -> list[str]:
    text = f"{item.title} {item.summary} {item.source}".lower()
    tags = []
    if item.source_type == "job-board":
        tags.append("job")
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
    job_match_score, job_reasons, job_risks = candidate_job_match(item, config)
    if job_match_score:
        item.metrics["job_match_score"] = job_match_score
        item.metrics["job_match_reasons"] = job_reasons
        item.metrics["job_match_risks"] = job_risks

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
    if item.source_type == "job-board":
        score += 20 + min(job_match_score, 120)
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

    for source in config.get("job_sources", []):
        try:
            items.extend(collect_job_source(source))
        except Exception as exc:
            warnings.append(f"Job source failed [{source.get('label', 'unknown')}]: {exc}")
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
