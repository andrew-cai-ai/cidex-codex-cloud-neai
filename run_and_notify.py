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
from pathlib import Path
from email.message import EmailMessage


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


def explain_project(full_name: str, tags: list[str], description: str) -> tuple[str, str, str]:
    desc = (description or "").lower()
    tag_set = set(tags)

    if full_name == "affaan-m/ECC" or "harness" in desc:
        return (
            "一套给 Codex/Claude Code 用的 agent 工作流脚手架，重点是 skills、memory、security、research-first。",
            "它可能不是直接拿来当产品用，而是值得偷师它怎么把 AI coding 的流程标准化。",
            "打开 README，只看 skills / commands / memory 三块，抽 3 个模板放进你的 Codex 工作流。",
        )
    if full_name in {"Lum1104/Understand-Anything", "safishamsi/graphify"} or "knowledge graph" in desc or "interactive graph" in desc:
        return (
            "把代码库变成可搜索、可提问、可视化的知识图谱，帮 AI 更快理解陌生项目。",
            "你经常要研究别人项目，这类工具能减少读代码和建立上下文的时间。",
            "拿一个你最近想复用的 repo 试跑，看它生成的图谱能不能让 Codex 更快定位关键模块。",
        )
    if full_name == "NousResearch/hermes-agent":
        return (
            "一个偏长期成长/记忆/工具使用的开源 agent 项目，重点不是单次补全，而是 agent 怎样持续积累能力。",
            "如果你想把 Codex 从一次性助手变成长期工作伙伴，这类项目的 memory 和 tool 设计值得看。",
            "先看 agent loop、memory、tool registry 三块，判断哪些能搬进你的自动化系统。",
        )
    if "gstack" in full_name.lower():
        return (
            "一套别人已经整理好的 Claude Code 高级使用配置，包含 CEO、设计、工程、QA 等角色工具。",
            "它的价值是工作流设计，不是代码本身；适合拿来改造成你的个人 AI 团队模板。",
            "只看角色分工和命令入口，挑 2 个角色迁移到 Codex。",
        )
    if "design" in desc or "prototype" in desc:
        return (
            "本地优先的 AI 设计/原型工具，偏 UI、设计系统、产品 demo 生成。",
            "如果你要快速验证产品形态，它可能比从零写前端更省时间。",
            "看它的 design systems 和 skills 目录，找能直接复用到你产品原型里的模板。",
        )
    if "token" in desc or "proxy" in desc or "observability" in tag_set:
        return (
            "AI coding 的 token/成本/命令代理工具，目标是少花 token 或看清会话成本。",
            "当你每天大量用 Codex/Claude，成本和上下文浪费会变成真问题。",
            "跑它的 demo，记录一次真实任务能省多少 token 或给出多少可观测信息。",
        )
    if "opencode" in full_name.lower() or "coding-agent" in tag_set:
        return (
            "一个开源 AI coding agent，可以对照 Codex 看 agent loop、工具调用和 CLI 体验。",
            "你不一定要换工具，但可以学习它怎么设计开源 coding agent 的产品体验。",
            "看它的 tool calling、权限、上下文管理实现，记下 3 个可借鉴点。",
        )
    if "mcp" in tag_set:
        return (
            "一个 MCP/工具接入相关项目，用来把外部工具、数据或软件接进 AI agent。",
            "MCP 是让 Codex/Claude 变强的连接层，好的 MCP 项目可以直接扩展你的工作流。",
            "先看它暴露了哪些 tool，再判断能否接进你的日常自动化。",
        )
    if "skills-prompts" in tag_set:
        return (
            "一组 prompt、skills 或 commands 模板，不一定是完整 app。",
            "这种项目最容易被你直接复制改造，投入小、见效快。",
            "挑最像你日常任务的 1-2 个 skill，改成自己的中文/英文模板。",
        )
    return (
        "一个 AI 开发工具相关开源项目，雷达因为热度、更新和关键词相关性把它捞出来。",
        "先不要假设它一定有用；它只是今天值得快速扫一眼的候选。",
        "用 10 分钟看 README、license、demo，如果不能立刻复用就跳过。",
    )


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

    for idx, item in enumerate(scores[:3], 1):
        repo = repos.get(item["full_name"], {})
        full_name = item["full_name"]
        url = repo.get("html_url") or f"https://github.com/{full_name}"
        description = repo.get("description") or ""
        what, why, action = explain_project(full_name, item.get("tags") or [], description)
        primary_pick.extend(
            [
                f"{idx}. {full_name}",
                f"   是什么: {what}",
                f"   为什么看: {why}",
                f"   今天动作: {action}",
                f"   链接: {url}",
            ]
        )
        if idx != min(3, len(scores)):
            primary_pick.append("")

    for idx, item in enumerate(scores[3:7], 4):
        repo = repos.get(item["full_name"], {})
        stars = int(repo.get("stargazers_count") or 0)
        tags = format_tags(item.get("tags") or [])
        description = repo.get("description") or ""
        what, _, _ = explain_project(item["full_name"], item.get("tags") or [], description)
        rest_candidates.append(f"{idx}. {item['full_name']} — {stars:,}★, {tags} · {truncate(what, 68)}")

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

    body = [
        f"AI OSS Radar · {now} · {status_label}",
        "",
        "怎么读: 这不是新闻列表，是每天帮你找“别人已经造好的 AI coding 轮子”。重点看: 它是什么、为什么值得偷师、今天能拿走什么。",
        "",
    ]

    if primary_pick:
        body.append("今日要看:")
        body.extend(primary_pick)
    else:
        body.append("今日要看: 暂无高优先级项目。")

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
    body.append("今天只做一件事: 不要全看。只 clone 第 1 个，确认有没有能直接搬进你工作流的 skills / commands / memory。")
    return "\n".join(body)


def smtp_config() -> dict[str, str | int]:
    smtp_password = "".join(os.environ.get("SMTP_PASSWORD", "").split())
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", ""),
        "password": smtp_password,
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
