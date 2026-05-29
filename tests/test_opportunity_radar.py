import unittest

import opportunity_radar


CONFIG = {
    "candidate_profile": {
        "strong_terms": ["backend", "kafka", "flink", "distributed systems", "aws"],
        "ai_terms": ["ai", "llm", "agent"],
        "remote_terms": ["remote", "canada"],
        "avoid_terms": ["junior", "intern"],
        "min_salary_usd": 180000,
    },
    "keywords": {
        "opportunity": ["hiring", "remote", "startup", "SaaS", "revenue", "Launch HN", "AI", "agent"],
        "high_intent": ["hiring", "remote", "founder", "Launch HN", "revenue"],
        "noise": ["rocket explodes", "apocalypse"],
    }
}


class OpportunityRadarTest(unittest.TestCase):
    def test_mrr_case_is_startup_not_job(self):
        item = opportunity_radar.Opportunity(
            id="x",
            title="I was stuck at $150/mo for 2 years. One change took me to $8.6K MRR.",
            url="https://example.com",
            source="reddit-saas",
            source_type="reddit",
            summary="SaaS revenue customers founder story",
        )

        tags = opportunity_radar.classify(item, CONFIG)

        self.assertIn("startup", tags)
        self.assertIn("saas", tags)
        self.assertNotIn("job", tags)

    def test_explicit_hiring_is_job(self):
        item = opportunity_radar.Opportunity(
            id="x",
            title="We are hiring remote AI engineers",
            url="https://example.com",
            source="hn:hiring",
            source_type="hacker-news",
            summary="",
        )

        self.assertIn("job", opportunity_radar.classify(item, CONFIG))

    def test_job_match_prefers_andrew_backend_streaming_profile(self):
        item = opportunity_radar.Opportunity(
            id="job",
            title="Senior Backend Engineer - AI infrastructure",
            url="https://example.com",
            source="yc",
            source_type="job-board",
            summary="Remote Canada. Java backend, Kafka, Flink, AWS, distributed systems. Salary $180K - $240K.",
        )

        score, reasons, risks = opportunity_radar.candidate_job_match(item, CONFIG)

        self.assertGreaterEqual(score, 90)
        self.assertIn("kafka", reasons)
        self.assertEqual(risks, [])

    def test_salary_parser_does_not_turn_hourly_price_into_350k(self):
        self.assertEqual(opportunity_radar.parse_salary_max_usd("$350 architecture audit"), 0)
        self.assertEqual(opportunity_radar.parse_salary_max_usd("$180K - $240K"), 240000)


if __name__ == "__main__":
    unittest.main()
