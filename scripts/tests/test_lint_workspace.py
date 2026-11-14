import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lint_workspace as lw  # noqa: E402

SA = """---
name: sa-demo
description: Demo rules — one, two. Use when testing.
user-invocable: false
---
# Demo
1. **First.** x
2. **Second.** y
"""
CHECKLIST = """---
name: sa-analysis-checklist
description: Checklist. Use before presenting a plan.
user-invocable: false
---
| The change touches | Open |
|---|---|
| a demo | `sa-demo` |
"""
AGENT = """---
name: demo-expert
description: Demo.
tools: Read, Grep, Skill
skills:
  - sa-analysis-checklist
---
body
"""


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write(".claude/skills/sa-demo/SKILL.md", SA)
        self.write(".claude/skills/sa-analysis-checklist/SKILL.md", CHECKLIST)
        self.write(".claude/agents/demo-expert.md", AGENT)
        self.write("CLAUDE.md", "# map\n")
        self.write("architecture/open-questions.md", "# Open\n\n4. first\n17. second\n")
        self.write("architecture/integration.md", "# Integration\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def errors(self):
        return lw.lint(self.root).errors

    def assertError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), f"no error containing {fragment!r} in {errs}")

    def test_clean_workspace_has_no_errors(self):
        self.assertEqual(self.errors(), [])

    def test_rule_reference_to_missing_rule(self):
        self.write("CLAUDE.md", "see `sa-demo` rule 3\n")
        self.assertError("`sa-demo` has no rule 3")

    def test_rule_range_checks_both_ends(self):
        self.write("CLAUDE.md", "see `sa-demo` rules 1–2 and `sa-demo` rules 2–5\n")
        errs = self.errors()
        self.assertEqual(len(errs), 1)
        self.assertIn("no rule 5", errs[0])

    def test_unknown_skill_name(self):
        self.write("CLAUDE.md", "open `sa-gone`\n")
        self.assertError("skill `sa-gone` does not exist")

    def test_missing_path(self):
        self.write("CLAUDE.md", "read `architecture/nope.md` and `architecture/integration.md`\n")
        errs = self.errors()
        self.assertEqual(len(errs), 1)
        self.assertIn("architecture/nope.md", errs[0])

    def test_paths_with_placeholders_and_generated_are_skipped(self):
        self.write("CLAUDE.md", "`architecture/generated/x.md` `architecture/flows/*.md` `.claude/skills/<name>/SKILL.md`\n")
        self.assertEqual(self.errors(), [])

    def test_open_question_that_is_gone(self):
        self.write("architecture/integration.md", "# I\nsee open question 19\nsee open questions 4, 17\n")
        errs = self.errors()
        self.assertEqual(len(errs), 1)
        self.assertIn("open question 19", errs[0])

    def test_open_question_marked_closed_is_allowed(self):
        self.write("architecture/business.md", "done (closes open question 35)\nopen question 45 fixed\n")
        self.assertEqual(self.errors(), [])

    def test_history_note_in_state_only_doc(self):
        self.write("architecture/integration.md", "# I\nbuilt (stores-service#48; live once merged)\n")
        self.assertError("history note `stores-service#48`")

    def test_history_note_allowed_elsewhere(self):
        self.write("architecture/open-questions.md", "# Open\n\n4. since stores-service#59\n")
        self.assertEqual(self.errors(), [])

    def test_description_with_colon_space(self):
        self.write(".claude/skills/sa-demo/SKILL.md", SA.replace("Demo rules — one", "Demo rules: one"))
        self.assertError("contains ': '")

    def test_description_too_long(self):
        self.write(".claude/skills/sa-demo/SKILL.md", SA.replace("one, two", "x" * 260))
        self.assertError("characters (max 250)")

    def test_sa_skill_must_not_be_user_invocable(self):
        self.write(".claude/skills/sa-demo/SKILL.md", SA.replace("user-invocable: false\n", ""))
        self.assertError("user-invocable: false")

    def test_sa_skill_too_large(self):
        self.write(".claude/skills/sa-demo/SKILL.md", SA + "x" * 7100)
        self.assertError("bytes (max 7000)")

    def test_name_must_match_folder(self):
        self.write(".claude/skills/sa-other/SKILL.md", SA)
        self.assertError("the folder is 'sa-other'")

    def test_sa_skill_missing_from_routing_table(self):
        self.write(".claude/skills/sa-analysis-checklist/SKILL.md", CHECKLIST.replace("`sa-demo`", "nothing"))
        self.assertError("no row that opens `sa-demo`")

    def test_side_effect_skill_needs_disable_model_invocation(self):
        self.write(".claude/skills/ship/SKILL.md", "---\nname: ship\ndescription: Ship a change.\n---\n")
        self.assertError("disable-model-invocation: true")

    def test_agent_preloading_other_skills(self):
        self.write(".claude/agents/demo-expert.md", AGENT.replace("  - sa-analysis-checklist", "  - sa-analysis-checklist\n  - sa-demo"))
        self.assertError("preloads sa-demo")

    def test_agent_with_skills_needs_skill_tool(self):
        self.write(".claude/agents/demo-expert.md", AGENT.replace(", Skill", ""))
        self.assertError("no `Skill` tool")

    def test_claude_md_too_large(self):
        self.write("CLAUDE.md", "x" * 12000)
        self.assertError("CLAUDE.md: 12000 bytes")

    def test_the_real_workspace_is_clean(self):
        real = Path(__file__).resolve().parent.parent.parent
        self.assertEqual(lw.lint(real).errors, [])


if __name__ == "__main__":
    unittest.main()
