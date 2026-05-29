import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import ai_radar


ROOT = Path(__file__).resolve().parents[1]


class RadarConfigTest(unittest.TestCase):
    def test_config_is_valid(self):
        config = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
        labels = [query["label"] for query in config["github_queries"]]

        self.assertEqual(len(labels), len(set(labels)))
        self.assertGreaterEqual(len(config["github_queries"]), 8)
        self.assertIn("claude code", " ".join(config["keywords"]["priority"]).lower())
        self.assertIn("mcp", " ".join(config["keywords"]["adjacent"]).lower())

    def test_github_repo_from_url(self):
        self.assertEqual(
            ai_radar.github_repo_from_url("https://github.com/openai/codex"),
            "openai/codex",
        )
        self.assertEqual(
            ai_radar.github_repo_from_url("https://github.com/openai/codex/issues/1"),
            "openai/codex",
        )
        self.assertIsNone(ai_radar.github_repo_from_url("https://example.com/openai/codex"))


class RadarScoringTest(unittest.TestCase):
    def test_relevant_project_scores_and_tags(self):
        config = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
        repo = {
            "full_name": "example/agent-skills",
            "name": "agent-skills",
            "description": "Claude Code and Codex skills for AI coding agents with MCP integrations",
            "html_url": "https://github.com/example/agent-skills",
            "stargazers_count": 1200,
            "forks_count": 100,
            "created_at": "2026-05-01T00:00:00Z",
            "pushed_at": "2026-05-28T00:00:00Z",
            "updated_at": "2026-05-28T00:00:00Z",
            "topics": ["claude-code", "codex", "mcp"],
            "license": {"spdx_id": "MIT"},
            "fork": False,
            "archived": False,
            "language": "Python",
        }
        signal = ai_radar.RepoSignal(labels={"claude-code", "topic:claude-code"})
        scored = ai_radar.score_repo(
            repo,
            signal,
            config,
            datetime(2026, 5, 29, tzinfo=timezone.utc),
            seen=set(),
        )

        self.assertGreater(scored.relevance, 10)
        self.assertIn("claude-code", scored.tags)
        self.assertIn("skills-prompts", scored.tags)
        self.assertTrue(scored.is_new)
        self.assertGreater(scored.score, 100)

    def test_leverage_note_differs_by_description(self):
        harness = ai_radar.leverage_note(
            ["skills-prompts", "memory-context"],
            "",
            "The agent harness performance optimization system. Skills, instincts, memory, security.",
        )
        graph = ai_radar.leverage_note(
            ["skills-prompts", "workflow-orchestration"],
            "",
            "Turn any code into an interactive knowledge graph you can explore.",
        )
        token = ai_radar.leverage_note(
            ["observability"],
            "",
            "CLI proxy that reduces LLM token consumption by 60-90%.",
        )

        self.assertIn("harness", harness)
        self.assertIn("知识图谱", graph)
        self.assertIn("token", token.lower())
        self.assertNotEqual(harness, graph)


if __name__ == "__main__":
    unittest.main()
