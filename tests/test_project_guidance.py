import unittest

import project_guidance


class ProjectGuidanceTest(unittest.TestCase):
    def test_graphify_and_understand_anything_differ(self):
        graph = project_guidance.project_guidance(
            "safishamsi/graphify",
            ["skills-prompts", "ide-editor"],
            "AI coding assistant skill. Turn any folder of code into analyzable context.",
        )
        understand = project_guidance.project_guidance(
            "Lum1104/Understand-Anything",
            ["skills-prompts", "workflow-orchestration"],
            "Turn any code into an interactive knowledge graph you can explore.",
        )

        self.assertIn("skill", graph[0].lower())
        self.assertIn("知识图谱", understand[0])
        self.assertNotEqual(graph[0], understand[0])

    def test_leverage_note_matches_action(self):
        what, why, action = project_guidance.project_guidance(
            "affaan-m/ECC",
            ["skills-prompts", "memory-context"],
            "The agent harness performance optimization system.",
        )
        note = project_guidance.leverage_note(
            ["skills-prompts", "memory-context"],
            "",
            "The agent harness performance optimization system.",
            "affaan-m/ECC",
        )

        self.assertEqual(note, action)
        self.assertIn("skills", what.lower())


if __name__ == "__main__":
    unittest.main()
