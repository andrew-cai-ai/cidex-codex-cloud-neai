import json
import unittest
from pathlib import Path
from unittest.mock import patch

import run_and_notify


ROOT = Path(__file__).resolve().parents[1]


SAMPLE_RAW = {
    "scores": [
        {
            "full_name": "affaan-m/ECC",
            "score": 1931.8,
            "tags": ["codex", "claude-code", "mcp", "skills-prompts", "memory-context"],
            "leverage": "优先拆 agent harness：skills、instincts、memory、security 四层怎么协作。",
            "new": False,
        },
        {
            "full_name": "Lum1104/Understand-Anything",
            "score": 1922.8,
            "tags": ["codex", "skills-prompts", "workflow-orchestration"],
            "leverage": "优先学知识图谱流程。",
            "new": False,
        },
        {
            "full_name": "safishamsi/graphify",
            "score": 1903.3,
            "tags": ["skills-prompts", "ide-editor"],
            "leverage": "优先拆 editor skills。",
            "new": False,
        },
        {
            "full_name": "nexu-io/open-design",
            "score": 1893.4,
            "tags": ["skills-prompts", "ide-editor"],
            "leverage": "设计工具。",
            "new": False,
        },
        {
            "full_name": "tirth8205/code-review-graph",
            "score": 858.4,
            "tags": ["claude-code", "mcp", "workflow-orchestration"],
            "leverage": "新 repo。",
            "new": True,
        },
        {
            "full_name": "K-Dense-AI/scientific-agent-skills",
            "score": 713.4,
            "tags": ["skills-prompts", "ide-editor"],
            "leverage": "新 repo 2。",
            "new": True,
        },
        {
            "full_name": "diegosouzapw/OmniRoute",
            "score": 535.0,
            "tags": ["mcp", "observability"],
            "leverage": "新 repo 3。",
            "new": True,
        },
        {
            "full_name": "ciembor/agent-rules-books",
            "score": 471.3,
            "tags": ["skills-prompts"],
            "leverage": "新 repo 4。",
            "new": True,
        },
    ],
    "repos": [
        {
            "full_name": "affaan-m/ECC",
            "html_url": "https://github.com/affaan-m/ECC",
            "description": "The agent harness performance optimization system. Skills, instincts, memory, security.",
            "stargazers_count": 198078,
        },
        {
            "full_name": "nexu-io/open-design",
            "html_url": "https://github.com/nexu-io/open-design",
            "description": "Local-first Claude Design alternative.",
            "stargazers_count": 55221,
        },
    ],
    "external_hn_hits": [
        {"title": "Claude Code hidden config article", "points": 174, "comments": 33},
        {"title": "DeepSWE benchmark", "points": 62, "comments": 20},
        {"title": "jqwik prompt injection", "points": 43, "comments": 57},
        {"title": "Local RAG agent", "points": 7, "comments": 7},
    ],
}


class EmailDigestTest(unittest.TestCase):
    def test_concise_digest_skips_top_three_in_rest(self):
        primary, rest, new_preview, hn_items, extra_new = run_and_notify.concise_digest_from_raw(SAMPLE_RAW)

        self.assertTrue(primary[0].startswith("affaan-m/ECC — The agent harness"))
        self.assertTrue(primary[1].startswith("→ https://github.com/affaan-m/ECC"))
        self.assertTrue(any("harness" in line for line in primary))
        self.assertEqual(len(rest), 4)
        self.assertIn("nexu-io/open-design", rest[0])
        for name in ("affaan-m/ECC", "Lum1104/Understand-Anything", "safishamsi/graphify"):
            self.assertTrue(all(name not in line for line in rest))
        self.assertEqual(len(new_preview), 3)
        self.assertEqual(extra_new, 1)
        self.assertEqual(len(hn_items), 3)

    def test_build_email_body_is_compact(self):
        report = "# AI OSS Radar\n\n## Executive Picks\n1. sample\n"
        with patch("run_and_notify.load_latest_raw", return_value=SAMPLE_RAW):
            body = run_and_notify.build_email_body(
                [run_and_notify.StepResult("compile", True, ""), run_and_notify.StepResult("unit-tests", True, "")],
                run_and_notify.StepResult("radar", True, ""),
                report,
            )

        self.assertIn("AI OSS Radar ·", body)
        self.assertIn("今日主推:", body)
        self.assertNotIn("Top 10 候选", body)
        self.assertNotIn("今天优先看这 3 个", body)
        self.assertLess(len(body.splitlines()), 30)

    def test_format_tags_limits_count(self):
        self.assertEqual(run_and_notify.format_tags(["a", "b", "c"], limit=2), "a, b")


if __name__ == "__main__":
    unittest.main()
