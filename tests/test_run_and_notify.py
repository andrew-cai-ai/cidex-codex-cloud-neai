import unittest
from unittest.mock import patch

import run_and_notify


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
            "full_name": "Lum1104/Understand-Anything",
            "html_url": "https://github.com/Lum1104/Understand-Anything",
            "description": "Turn any code into an interactive knowledge graph you can explore.",
            "stargazers_count": 43889,
        },
        {
            "full_name": "safishamsi/graphify",
            "html_url": "https://github.com/safishamsi/graphify",
            "description": "AI coding assistant skill. Turn any folder of code into analyzable context.",
            "stargazers_count": 55916,
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
    def test_concise_digest_primary_and_secondary(self):
        primary, secondary, rest, new_preview, hn_items, extra_new = run_and_notify.concise_digest_from_raw(SAMPLE_RAW)

        self.assertTrue(primary[0].startswith("1. affaan-m/ECC"))
        self.assertTrue(any("是什么:" in line for line in primary))
        self.assertEqual(len(secondary), 2)
        self.assertIn("Lum1104/Understand-Anything", secondary[0])
        self.assertIn("safishamsi/graphify", secondary[1])
        self.assertNotEqual(secondary[0], secondary[1])
        self.assertEqual(len(rest), 4)
        self.assertEqual(len(new_preview), 3)
        self.assertEqual(extra_new, 1)
        self.assertEqual(len(hn_items), 3)

    def test_concise_digest_handles_missing_raw(self):
        primary, secondary, rest, new_preview, hn_items, extra_new = run_and_notify.concise_digest_from_raw(None)

        self.assertEqual(primary, [])
        self.assertEqual(secondary, [])
        self.assertEqual(rest, [])
        self.assertEqual(new_preview, [])
        self.assertEqual(hn_items, [])
        self.assertEqual(extra_new, 0)

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
        self.assertIn("次优先 (#2–#3):", body)
        self.assertIn("是什么:", body)
        self.assertNotIn("Top 10 候选", body)
        self.assertLess(len(body.splitlines()), 40)

    def test_format_tags_limits_count(self):
        self.assertEqual(run_and_notify.format_tags(["a", "b", "c"], limit=2), "a, b")

    @patch.dict(
        "os.environ",
        {
            "SMTP_PASSWORD": "abcd efgh ijkl mnop",
            "SMTP_USER": "sender@example.com",
            "RADAR_EMAIL_TO": "to@example.com",
        },
        clear=True,
    )
    def test_smtp_config_strips_app_password_spaces(self):
        config = run_and_notify.smtp_config()

        self.assertEqual(config["password"], "abcdefghijklmnop")


if __name__ == "__main__":
    unittest.main()
