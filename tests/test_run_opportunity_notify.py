import unittest
from unittest.mock import patch

import run_opportunity_notify


SAMPLE_RAW = {
    "items": [
        {
            "id": "search",
            "title": "Show HN: Search Router – retrieval-ready web search for AI agents",
            "url": "https://github.com/search-router/simple-search",
            "source": "hn:Launch HN",
            "tags": ["startup", "product", "ai"],
            "score": 81.6,
            "why": "startup signal",
            "action": "look",
        },
        {
            "id": "openhive",
            "title": "Show HN: OpenHive – AI agents share solutions so other agents dont re-solve them",
            "url": "https://openhivemind.vercel.app/",
            "source": "hn:Show HN AI",
            "tags": ["startup", "product", "ai"],
            "score": 76.6,
            "why": "startup signal",
            "action": "look",
        },
        {
            "id": "guard",
            "title": "Show HN: Agent Memory Guard – OWASP defense for AI agent memory poisoning",
            "url": "https://github.com/OWASP/www-project-agent-memory-guard",
            "source": "hn:Show HN AI",
            "tags": ["startup", "product", "ai"],
            "score": 76.4,
            "why": "startup signal",
            "action": "look",
        },
        {
            "id": "trailers",
            "title": "Show HN: Product Trailers – The TV Channel for Product Hunt Launches",
            "url": "https://producttrailers.xyz",
            "source": "hn:Launch HN",
            "tags": ["startup", "product"],
            "score": 81.6,
            "why": "startup signal",
            "action": "look",
        },
        {
            "id": "brandfetch-job",
            "title": "Brandfetch | Senior Backend Engineer | Remote",
            "url": "https://brandfetch.com",
            "source": "hnhiring-remote",
            "source_type": "job-board",
            "tags": ["job", "ai", "devtools"],
            "score": 190,
            "summary": "Senior Backend Engineer. Remote. AI agent MCP. AWS. Real-time metering.",
            "metrics": {
                "company": "Brandfetch",
                "role": "Senior Backend Engineer",
                "job_match_score": 105,
                "job_match_reasons": ["senior backend", "backend", "aws", "AI/LLM/agent 相关"],
                "job_match_risks": [],
                "source_name": "HNHIRING",
            },
        },
    ],
    "warnings": ["Reddit feed failed [reddit-saas]: HTTP 403: blocked html"],
}


class OpportunityDigestTest(unittest.TestCase):
    def test_editorial_digest_has_conclusion_and_one_action(self):
        with patch("run_opportunity_notify.latest_raw", return_value=SAMPLE_RAW):
            body = run_opportunity_notify.build_email_body(
                [run_opportunity_notify.StepResult("compile", True, "")],
                run_opportunity_notify.StepResult("opportunity-radar", True, ""),
            )

        self.assertIn("# 今日 AI 机会雷达", body)
        self.assertIn("## 最值得关注（最多3个）", body)
        self.assertIn("## 工作机会（最多3个）", body)
        self.assertIn("OpenHive", body)
        self.assertIn("是否值得投简历:", body)
        self.assertIn("是否值得 Fork:", body)
        self.assertIn("是否值得创业参考:", body)
        self.assertIn("优先级 / 预计商业价值:", body)
        self.assertIn("Brandfetch", body)
        self.assertIn("预计TC:", body)
        self.assertIn("## 今日唯一动作", body)
        self.assertNotIn("值得程度表:", body)
        self.assertNotIn("| OpenHive |", body)
        self.assertNotIn("今日信号分布", body)
        self.assertLessEqual(body.count("链接:"), 5)
        self.assertLess(len(body.splitlines()), 80)

    def test_editorial_priority_prefers_agent_infrastructure(self):
        picks = run_opportunity_notify.pick_research_items(SAMPLE_RAW["items"], 3)
        names = [run_opportunity_notify.display_name(item) for item in picks]

        self.assertEqual(names[:3], ["OpenHive", "Search Router", "Agent Memory Guard"])

    def test_macro_hiring_discussion_is_not_actionable_job(self):
        item = {
            "title": "What if remote working, not AI, is to blame for weak junior hiring?",
            "summary": "",
        }

        self.assertFalse(run_opportunity_notify.is_actionable_job(item))

    def test_top_by_tag_handles_missing_ids(self):
        items = [
            {"title": "market note", "tags": ["market"]},
            {"title": "remote engineer", "url": "https://example.com/job", "tags": ["job"]},
        ]

        selected = run_opportunity_notify.top_by_tag(items, {"job"}, 3)

        self.assertEqual(selected[0]["title"], "remote engineer")

    def test_job_formatter_uses_match_reasons_and_risks(self):
        item = {
            "title": "Atomic - Backend Engineer",
            "url": "https://example.com",
            "source_type": "job-board",
            "source": "yc-remote-engineering",
            "tags": ["job"],
            "score": 120,
            "metrics": {
                "company": "Atomic",
                "role": "Backend Engineer",
                "salary": "$150K - $200K",
                "location": "Remote",
                "job_match_score": 86,
                "job_match_reasons": ["backend", "AI/LLM/agent 相关", "remote/Canada-friendly"],
                "job_match_risks": [],
                "source_name": "YC Jobs",
            },
        }

        lines = run_opportunity_notify.format_job_candidate(item, 1)

        self.assertIn("Atomic", lines[0])
        self.assertTrue(any("backend" in line for line in lines))
        self.assertTrue(any("YC Jobs" in line for line in lines))

    def test_attention_item_has_required_decision_fields(self):
        item = SAMPLE_RAW["items"][1]

        lines = run_opportunity_notify.format_attention_item(item, 1)
        text = "\n".join(lines)

        self.assertIn("为什么值得 Andrew 看:", text)
        self.assertIn("对 Andrew 的价值:", text)
        self.assertIn("是否值得投简历:", text)
        self.assertIn("是否值得 Fork:", text)
        self.assertIn("是否值得创业参考:", text)
        self.assertIn("优先级 / 预计商业价值:", text)


if __name__ == "__main__":
    unittest.main()
