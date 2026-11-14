#!/usr/bin/env python3
"""Checks that the workspace's own map still holds together.

It catches what a reader cannot see at a glance: a reference to a rule, skill, file or open question that no longer
exists, a skill or agent that breaks the conventions in `.claude/rules/agents-skills.md`, and history notes in the docs
that must describe the system as it is now (`.claude/rules/architecture-docs.md`).

Usage: python3 scripts/lint_workspace.py [--root <workspace>]
Exit code 1 when an error is found. Warnings do not fail the run.
Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Size limits (bytes). The rule file says "about"; these are the hard stops, a little above it.
MAX_SA_SKILL = 7000
MAX_WORKFLOW_SKILL = 3500
MAX_CLAUDE_MD = 11500
MAX_DESCRIPTION = 250

WORKFLOW_SKILLS = {"change-event", "change-api", "add-migration", "add-aws-resource", "new-service", "docs-sync"}
SIDE_EFFECT_SKILLS = {"ship", "release-core"}
# Docs that must describe the present only: no PR numbers, branch names or merge notes.
STATE_ONLY_DOCS = ("architecture/system-overview.md", "architecture/domain-map.md", "architecture/integration.md",
                   "architecture/glossary.md", "architecture/delivery.md")
STATE_ONLY_DIRS = ("architecture/flows",)
CLOSED_WORDS = re.compile(r"\b(closed|closes|resolved|fixed|was open question)\b|✅", re.I)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
RULE_REF_RE = re.compile(r"`(sa-[a-z-]+)` rules? (\d+)(?:[–-](\d+))?")
SKILL_NAME_RE = re.compile(r"`((?:sa|change|add|new|docs)-[a-z-]+)`")
# `.github/...` is left out: the same path names a file in every repo.
PATH_RE = re.compile(r"`((?:architecture|scripts|\.claude)/[A-Za-z0-9_./-]+)`")
OPEN_Q_RE = re.compile(r"open questions? ((?:\d+(?:, | and )?)+)")
HISTORY_RE = re.compile(r"\b[a-z][a-z-]+#\d+\b|live once|once merged|BREAKING \(|\b(?:feature|fix)/[a-z][a-z-]+")
NUMBERED_RULE_RE = re.compile(r"^(\d+)\. \*\*", re.M)
QUESTION_ID_RE = re.compile(r"^(\d+)\. ", re.M)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"ERROR {where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"warn  {where}: {msg}")


def frontmatter(text: str) -> dict[str, str | list[str]]:
    """The few YAML shapes the skills and agents use: `key: value` and `key:` followed by `  - item` lines."""
    m = FRONTMATTER_RE.match(text)
    out: dict[str, str | list[str]] = {}
    if not m:
        return out
    key = None
    for line in m.group(1).split("\n"):
        item = re.match(r"\s+-\s+(.*)", line)
        if item and key:
            cur = out.get(key)
            out[key] = (cur if isinstance(cur, list) else []) + [item.group(1).strip()]
            continue
        kv = re.match(r"([A-Za-z-]+):\s*(.*)", line)
        if kv:
            key = kv.group(1)
            out[key] = kv.group(2).strip()
    return out


def check_skills(root: Path, r: Report) -> dict[str, set[int]]:
    """Returns the numbered rules of every sa-* skill, for the reference check."""
    rules: dict[str, set[int]] = {}
    for d in sorted((root / ".claude/skills").iterdir()) if (root / ".claude/skills").is_dir() else []:
        f = d / "SKILL.md"
        where = f".claude/skills/{d.name}/SKILL.md"
        if not f.is_file():
            r.error(where, "missing")
            continue
        text = f.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm.get("name") != d.name:
            r.error(where, f"frontmatter name is {fm.get('name')!r}, the folder is {d.name!r}")
        desc = fm.get("description", "")
        if not isinstance(desc, str) or not desc:
            r.error(where, "no description")
        else:
            if len(desc) > MAX_DESCRIPTION:
                r.error(where, f"description has {len(desc)} characters (max {MAX_DESCRIPTION})")
            if ": " in desc and not (desc.startswith('"') or desc.startswith("'")):
                r.error(where, "description contains ': ' (breaks the YAML); use ' — '")
            if "Use " not in desc and d.name not in SIDE_EFFECT_SKILLS:
                r.warn(where, "description does not say when to use the skill ('Use when …')")
        size = len(text.encode("utf-8"))
        if d.name.startswith("sa-"):
            rules[d.name] = {int(n) for n in NUMBERED_RULE_RE.findall(text)}
            if fm.get("user-invocable") != "false":
                r.error(where, "sa-* skills set `user-invocable: false`")
            if size > MAX_SA_SKILL:
                r.error(where, f"{size} bytes (max {MAX_SA_SKILL}); move current state to references/current-state.md")
        if d.name in WORKFLOW_SKILLS and size > MAX_WORKFLOW_SKILL:
            r.error(where, f"{size} bytes (max {MAX_WORKFLOW_SKILL} for a workflow skill)")
        if d.name in SIDE_EFFECT_SKILLS and fm.get("disable-model-invocation") != "true":
            r.error(where, "a skill with side effects sets `disable-model-invocation: true`")
    checklist = root / ".claude/skills/sa-analysis-checklist/SKILL.md"
    if checklist.is_file():
        text = checklist.read_text(encoding="utf-8")
        for name in sorted(rules):
            if name != "sa-analysis-checklist" and f"`{name}`" not in text:
                r.error(".claude/skills/sa-analysis-checklist/SKILL.md", f"routing table has no row that opens `{name}`")
    return rules


def check_agents(root: Path, r: Report) -> None:
    d = root / ".claude/agents"
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        where = f".claude/agents/{f.name}"
        fm = frontmatter(f.read_text(encoding="utf-8"))
        if fm.get("name") != f.stem:
            r.error(where, f"frontmatter name is {fm.get('name')!r}, the file is {f.stem!r}")
        skills = fm.get("skills")
        if isinstance(skills, list):
            extra = [s for s in skills if s != "sa-analysis-checklist"]
            if extra:
                r.error(where, f"preloads {', '.join(extra)}; agents preload only sa-analysis-checklist")
            if "Skill" not in str(fm.get("tools", "")):
                r.error(where, "has skills but no `Skill` tool, so it cannot open the others")


def text_files(root: Path) -> list[Path]:
    out = [root / "CLAUDE.md", root / "README.md"]
    for sub in (".claude", "architecture"):
        out += [p for p in (root / sub).rglob("*.md") if "generated" not in p.parts]
    return sorted(p for p in out if p.is_file())


def check_references(root: Path, rules: dict[str, set[int]], r: Report) -> None:
    skills = {d.name for d in (root / ".claude/skills").iterdir() if d.is_dir()} if (root / ".claude/skills").is_dir() else set()
    oq = root / "architecture/open-questions.md"
    open_ids = {int(n) for n in QUESTION_ID_RE.findall(oq.read_text(encoding="utf-8"))} if oq.is_file() else None
    for f in text_files(root):
        where = str(f.relative_to(root))
        for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            for m in RULE_REF_RE.finditer(line):
                for num in (m.group(2), m.group(3)):
                    if num and int(num) not in rules.get(m.group(1), set()):
                        r.error(f"{where}:{n}", f"`{m.group(1)}` has no rule {num}")
            for m in SKILL_NAME_RE.finditer(line):
                name = m.group(1)
                if name.startswith("sa-") and name not in skills and not name.endswith("-"):
                    r.error(f"{where}:{n}", f"skill `{name}` does not exist")
            for m in PATH_RE.finditer(line):
                p = m.group(1).rstrip(".")
                if any(c in p for c in "*<>…") or "/generated/" in p + "/":
                    continue
                if not (root / p).exists():
                    r.error(f"{where}:{n}", f"path `{p}` does not exist")
            if open_ids is not None and f != oq and not CLOSED_WORDS.search(line):
                for m in OPEN_Q_RE.finditer(line):
                    for num in re.findall(r"\d+", m.group(1)):
                        if int(num) not in open_ids:
                            r.error(f"{where}:{n}", f"open question {num} is not in architecture/open-questions.md "
                                                   "(closed? then cite the ADR or say it is closed)")


def check_state_only(root: Path, r: Report) -> None:
    files = [root / p for p in STATE_ONLY_DOCS]
    for d in STATE_ONLY_DIRS:
        files += sorted((root / d).glob("*.md"))
    for f in files:
        if not f.is_file():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            m = HISTORY_RE.search(line)
            if m:
                r.error(f"{f.relative_to(root)}:{n}", f"history note `{m.group(0)}`: describe the system as it is now")


def check_sizes(root: Path, r: Report) -> None:
    f = root / "CLAUDE.md"
    if f.is_file():
        size = len(f.read_bytes())
        if size > MAX_CLAUDE_MD:
            r.error("CLAUDE.md", f"{size} bytes (max {MAX_CLAUDE_MD}); move detail into a skill or architecture/")


def lint(root: Path) -> Report:
    r = Report()
    rules = check_skills(root, r)
    check_agents(root, r)
    check_references(root, rules, r)
    check_state_only(root, r)
    check_sizes(root, r)
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    r = lint(Path(ap.parse_args().root))
    for line in r.warnings + r.errors:
        print(line)
    print(f"{len(r.errors)} error(s), {len(r.warnings)} warning(s)")
    sys.exit(1 if r.errors else 0)


if __name__ == "__main__":
    main()
