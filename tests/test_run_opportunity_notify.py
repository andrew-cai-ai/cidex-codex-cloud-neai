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

        self.assertIn("今日主推", body)
        self.assertIn("如果今天只能看一个: OpenHive", body)
        self.assertIn("OpenHive", body)
        self.assertIn("次优先:", body)
        self.assertIn("今天只做一件事:", body)
        self.assertIn("客户是谁？怎么赚钱？", body)
        self.assertIn("今日信号分布", body)
        self.assertNotIn("值得程度表:", body)
        self.assertNotIn("| OpenHive |", body)
        self.assertLess(len(body.splitlines()), 55)

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


if __name__ == "__main__":
    unittest.main()
