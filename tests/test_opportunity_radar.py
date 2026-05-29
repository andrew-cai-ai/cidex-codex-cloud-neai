import unittest

import opportunity_radar


CONFIG = {
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


if __name__ == "__main__":
    unittest.main()
