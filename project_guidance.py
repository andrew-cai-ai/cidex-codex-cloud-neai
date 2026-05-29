"""Shared project explanations for OSS radar reports and email digests."""

from __future__ import annotations

import re


def _truncate(value: str, length: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def project_guidance(
    full_name: str,
    tags: list[str],
    description: str = "",
    blob: str = "",
) -> tuple[str, str, str]:
    """Return (what, why, action) for a ranked repository."""
    desc = (description or "").lower()
    name_lower = (full_name or "").lower()
    tag_set = set(tags)
    text = f"{desc} {blob}".lower()

    if full_name == "affaan-m/ECC" or "harness" in desc:
        return (
            "一套给 Codex/Claude Code 用的 agent 工作流脚手架，重点是 skills、memory、security、research-first。",
            "它可能不是直接拿来当产品用，而是值得偷师它怎么把 AI coding 的流程标准化。",
            "打开 README，只看 skills / commands / memory 三块，抽 3 个模板放进你的 Codex 工作流。",
        )
    if full_name == "Lum1104/Understand-Anything" or (
        "knowledge graph" in desc and "interactive" in desc
    ):
        return (
            "把陌生代码库变成可探索、可搜索、可提问的交互式知识图谱。",
            "你经常要研究别人项目，这类工具能减少读代码和建立上下文的时间。",
            "拿一个你想复用的 repo 试跑，看图谱能否让 Codex 更快定位关键模块。",
        )
    if full_name == "safishamsi/graphify" or ("graphify" in name_lower and "skill" in desc):
        return (
            "跨 Cursor/Codex/Claude Code 的 coding skill，把文件夹代码/SQL/shell 转成可分析上下文。",
            "它比完整 app 更容易直接搬进现有 IDE 工作流，适合当「项目理解」skill 模板。",
            "挑一个本地项目文件夹跑 graphify，看输出能否直接喂给 Codex 当首轮上下文。",
        )
    if "knowledge graph" in desc or "interactive graph" in desc:
        return (
            "把代码或资料转成可交互知识图谱，帮助 AI 理解复杂项目结构。",
            "适合作为 repo onboarding 和代码考古的辅助层。",
            "用一个中等规模 repo 试跑，评估图谱质量是否值得接入日常流程。",
        )
    if full_name == "NousResearch/hermes-agent" or ("grows with you" in desc and "agent" in desc):
        return (
            "偏长期成长/记忆/工具使用的开源 agent，重点不是单次补全，而是持续积累能力。",
            "如果你想把 Codex 从一次性助手变成长期工作伙伴，memory 和 tool 设计值得看。",
            "先看 agent loop、memory、tool registry 三块，判断哪些能搬进你的自动化系统。",
        )
    if "gstack" in name_lower:
        return (
            "一套整理好的 Claude Code 高级配置，包含 CEO、设计、工程、QA 等角色工具。",
            "价值在工作流设计，不是代码本身；适合改造成个人 AI 团队模板。",
            "只看角色分工和命令入口，挑 2 个角色迁移到 Codex。",
        )
    if any(needle in desc for needle in ("design system", "design alternative", "prototype")):
        return (
            "本地优先的 AI 设计/原型工具，偏 UI、设计系统、产品 demo 生成。",
            "如果你要快速验证产品形态，它可能比从零写前端更省时间。",
            "看 design systems 和 skills 目录，找能直接复用到产品原型的模板。",
        )
    if "token" in desc or "proxy" in desc or "observability" in tag_set:
        return (
            "AI coding 的 token/成本/命令代理工具，目标是少花 token 或看清会话成本。",
            "当你每天大量用 Codex/Claude，成本和上下文浪费会变成真问题。",
            "跑 demo，记录一次真实任务能省多少 token 或给出多少可观测信息。",
        )
    if "opencode" in name_lower or "coding-agent" in tag_set:
        return (
            "开源 AI coding agent，可对照 Codex 看 agent loop、工具调用和 CLI 体验。",
            "你不一定要换工具，但可以学习开源 coding agent 的产品体验设计。",
            "看 tool calling、权限、上下文管理实现，记下 3 个可借鉴点。",
        )
    if "mcp" in tag_set:
        return (
            "MCP/工具接入项目，把外部工具、数据或软件接进 AI agent。",
            "MCP 是让 Codex/Claude 变强的连接层，好的 MCP 项目可以直接扩展工作流。",
            "先看暴露了哪些 tool，再判断能否接进日常自动化。",
        )
    if "meta-prompt" in desc or "spec-driven" in desc or "context engineering" in desc:
        return (
            "meta-prompt / spec 驱动开发模板，偏规范化和上下文工程。",
            "适合直接移植到你的项目规范和交付流程里。",
            "拆出 spec 模板和 prompt 链，改成自己团队的中文/英文版本。",
        )
    if "skills-prompts" in tag_set:
        if "memory-context" in tag_set:
            return (
                "带 memory/上下文设计的 skills 或 commands 模板集合。",
                "最容易直接复制改造，且能立刻改善长期会话质量。",
                "拆 skills/commands，并重点学 memory/上下文持久化设计。",
            )
        if "workflow-orchestration" in tag_set:
            return (
                "带多步编排的 prompt/skills 模板，不只是单次问答。",
                "适合把零散 prompt 升级成可重复的工作流。",
                "拆 prompt/skills，并学多步工作流编排方式。",
            )
        if "ide-editor" in tag_set:
            return (
                "编辑器集成的 skills/commands，偏 IDE 内一键触发。",
                "投入小、见效快，适合先改一个日常高频任务。",
                "挑最像你日常任务的 1-2 个 skill，改成自己的模板。",
            )
        return (
            "一组 prompt、skills 或 commands 模板，不一定是完整 app。",
            "这种项目最容易直接复制改造，投入小、见效快。",
            "挑最像你日常任务的 1-2 个 skill，改成自己的中文/英文模板。",
        )
    if "workflow-orchestration" in tag_set:
        return (
            "多 agent 编排或任务拆分相关项目。",
            "适合研究复杂任务怎么拆、上下文怎么传、失败怎么恢复。",
            "优先研究编排、任务拆分和上下文传递方式。",
        )
    if "open source" in text or "mit" in text or "apache" in text:
        return (
            "AI 开发相关开源项目，雷达因热度和关键词把它捞出来。",
            "先确认 license 和可复用边界，再决定要不要深入。",
            "先确认 license，再抽取可复用模块或产品交互。",
        )
    return (
        "AI 开发工具相关开源项目，雷达因热度、更新和关键词相关性把它捞出来。",
        "先不要假设它一定有用；它只是今天值得快速扫一眼的候选。",
        "用 10 分钟看 README、license、demo，如果不能立刻复用就跳过。",
    )


def leverage_note(tags: list[str], blob: str, description: str = "", full_name: str = "") -> str:
    """One-line action note for Markdown reports."""
    return project_guidance(full_name, tags, description, blob)[2]


def explain_one_liner(full_name: str, tags: list[str], description: str, limit: int = 72) -> str:
    """Compact summary for email secondary picks."""
    return _truncate(project_guidance(full_name, tags, description)[0], limit)
