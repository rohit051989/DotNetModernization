"""Claude Code as a second conversion engine, and the scope in the instructions (36-COPILOT-ENHANCED-CONVERSION Parts
O and Q).

- Parity: both engines' renderings carry the same work items, decisions, scope and rules; only the mechanics differ.
- Claude Code's files: where Claude Code reads them, never over a file the repository has, the plugin's helpers in
  their own form with their attribution, guardrails in its settings.
- The scope where the agent reads first: the excluded projects by name and path, with who, when and why, in both
  engines' instructions, the decision sheet and the runbook; no work item points into an excluded project.
- Context isolation: a CLAUDE.md or .claude folder above a worktree is found.

Run: python -m unittest tests.test_engine_claude
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from app.engine import engines, inputs, paths
from app.engine.inputs import claude, render
from tests.test_engine_inputs import _item, model


def scoped(m=None):
    m = m or model([*model()["items"], _item("windows-build-pipeline", "linux-build-pipeline", file="build.cmd")])
    m["vocabulary"]["item_ids"].append("windows-build-pipeline")
    m["vocabulary"]["resolution_ids"].append("linux-build-pipeline")
    m["projects"] = [{"path": "src/A/A.csproj", "framework": "net8.0"}, {"path": "src/Shared/Shared.csproj", "framework": "net8.0"}]
    m["files"] = ["build.cmd", "src/A/A.csproj", "src/A/A.cs", "src/A/appsettings.json", "src/Old/Old.csproj",
                  "src/Old/Dockerfile", "src/Old/build.ps1", "src/Shared/Shared.csproj", "Legacy.csproj", "App.sln"]
    m["scope"] = {"excluded": [{"path": "src/Old/Old.csproj", "name": "Old"}, {"path": "Legacy.csproj", "name": "Legacy"}],
                  "build": "in-scope.sln", "decidedBy": "Pat Example", "decidedAt": "2026-11-18T10:00:00+00:00",
                  "reason": "retired next year", "projects": 4}
    return m


def sections(text: str) -> dict[str, str]:
    """{"## title": body} of a Markdown file."""
    out, title = {}, None
    for line in text.split("\n"):
        if line.startswith("## "):
            title = line
            out[title] = []
        elif title is not None:
            if line.startswith("---") or line.startswith("Adapted from"):
                title = None
                continue
            out[title].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


class EngineParity(unittest.TestCase):
    """One content model, two renderers: mapped back through the mechanics table, Claude Code's files say what
    GitHub Copilot's say."""

    def check(self, m):
        copilot = render.render(m, engines.COPILOT)
        claude_files = render.render(m, engines.CLAUDE)
        # Work items: the same names, the same text.
        copilot_items = {Path(p).stem: t for p, t in copilot.items() if p.startswith(paths.UPGRADE_SKILLS_DIR + "/")}
        claude_items = {p.split("/")[2]: t for p, t in claude_files.items() if p.endswith("/SKILL.md")}
        self.assertTrue(copilot_items)
        self.assertEqual(sorted(copilot_items), sorted(claude_items))
        for name, text in copilot_items.items():
            self.assertEqual(claude.neutral(claude._strip_frontmatter(claude_items[name])), claude._strip_frontmatter(text), name)
        # Decisions and the addendum: the same, through the mechanics.
        for name in ("decision-sheet.md", "assessment-addendum.md"):
            self.assertEqual(claude.neutral(claude_files[f"{claude.INPUTS_DIR}/{name}"]),
                             copilot[f"{paths.PLATFORM_INPUTS_DIR}/{name}"], name)
        # The rules, build and test, and the scope: every section of Copilot's instructions is in Claude Code's.
        mine = sections(copilot[paths.COPILOT_INSTRUCTIONS])
        theirs = {k: claude.neutral(v) for k, v in sections(claude_files[claude.INSTRUCTIONS]).items()}
        for title, body in mine.items():
            self.assertEqual(theirs.get(title), body, title)
        return copilot, claude_files

    def test_the_same_work_items_decisions_rules_and_no_scope(self):
        copilot, claude_files = self.check(model())
        self.assertNotIn("## Conversion scope", copilot[paths.COPILOT_INSTRUCTIONS])

    def test_the_same_scope(self):
        copilot, claude_files = self.check(scoped())
        self.assertIn("## Conversion scope", claude_files[claude.INSTRUCTIONS])

    def test_both_carry_the_rules_the_task_names(self):
        for engine in engines.ENGINES:
            files = render.render(model(), engine)
            text = files[paths.COPILOT_INSTRUCTIONS if engine == engines.COPILOT else claude.INSTRUCTIONS]
            for rule in ("## Never hide a warning or an error", "## Use only the tools this repository already has",
                         "## One commit per work item", "## Configuration files", "## Build and test",
                         "## Stay inside the repository", "## Tests are evidence; keep them as they are"):
                self.assertIn(rule, text, (engine, rule))


class ClaudeFiles(unittest.TestCase):
    def setUp(self):
        self.files = inputs.build(model(), None, engine=engines.CLAUDE)     # self-contained and free of secrets

    def test_where_claude_code_reads_them_and_nothing_of_copilots(self):
        self.assertIn(claude.INSTRUCTIONS, self.files)
        self.assertIn(claude.SETTINGS, self.files)
        self.assertIn(claude.MANIFEST, self.files)
        self.assertIn(".claude/skills/applying-container-local-timezone/SKILL.md", self.files)
        for agent in ("version-delta-analyst", "test-engineer", "architecture-critic"):
            self.assertIn(f".claude/agents/{agent}.md", self.files)
        self.assertFalse([p for p in self.files if p.startswith(".github/")])
        manifest = json.loads(self.files[claude.MANIFEST])
        self.assertEqual([f["path"] for f in manifest["files"]], sorted(p for p in self.files if p != claude.MANIFEST))

    def test_a_skill_has_claude_codes_frontmatter(self):
        text = self.files[".claude/skills/applying-container-local-timezone/SKILL.md"]
        head = text.split("\n---\n", 1)[0]
        self.assertTrue(head.startswith("---\nname: applying-container-local-timezone\ndescription: \""))
        self.assertNotIn("discovery:", text)
        self.assertNotIn(".github/", text)

    def test_the_plugins_helpers_keep_their_own_form_names_tools_and_attribution(self):
        critic = self.files[".claude/agents/architecture-critic.md"]
        self.assertIn("name: architecture-critic\n", critic)
        self.assertIn("tools: Read, Glob, Grep, Bash\n", critic)
        self.assertIn("Adapted from `agents/architecture-critic.md` in Anthropic's `code-modernization` plugin", critic)
        self.assertIn("tools: Read, Write, Edit, Glob, Grep, Bash\n", self.files[".claude/agents/test-engineer.md"])
        self.assertIn("Claude Code subagent (the plugin's own form)", self.files[".claude/agents/version-delta-analyst.md"])

    def test_the_instructions_give_the_plan_build_test_and_commit_per_work_item(self):
        text = self.files[claude.INSTRUCTIONS]
        self.assertIn("## How to run this conversion", text)
        plan = text.split("## How to run this conversion", 1)[1].split("\n## ", 1)[0]
        names = re.findall(r"^\d+\. `(applying-[^`]+)`", plan, re.MULTILINE)
        self.assertEqual(sorted(names), sorted(p.split("/")[2] for p in self.files if p.endswith("/SKILL.md")))
        # The ordering: sql-auth-from-secret runs before move-to-secret.
        self.assertLess(names.index("applying-sql-auth-from-secret"), names.index("applying-move-to-secret"))
        self.assertIn("Build with `dotnet build` and test with `dotnet test`", plan)
        self.assertIn("Commit only that work item's changes", plan)
        self.assertNotIn("upgrade tool's", text)

    def test_guardrails_in_settings_deny_push_and_history_rewriting(self):
        deny = json.loads(self.files[claude.SETTINGS])["permissions"]["deny"]
        for rule in ("Bash(git push *)", "Bash(git rebase *)", "Bash(git reset --hard *)", "Bash(git commit --amend *)",
                     "Bash(git filter-branch *)", "Bash(git checkout -b *)"):
            self.assertIn(rule, deny)
        self.assertFalse([r for r in deny if r.startswith("Edit(")])         # no scope, no edit denied

    def test_never_over_a_file_the_repository_has(self):
        m = model()
        m["files"] = ["CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json"]
        files = render.render(m, engines.CLAUDE)
        self.assertIn(claude.INSTRUCTIONS_ALTERNATIVE, files)
        self.assertIn(claude.SETTINGS_ALTERNATIVE, files)
        self.assertNotIn(claude.INSTRUCTIONS, files)
        self.assertNotIn(claude.SETTINGS, files)
        text = files[claude.INSTRUCTIONS_ALTERNATIVE]
        self.assertIn("This repository's own `CLAUDE.md` and `.claude/CLAUDE.md` also apply, unchanged.", text)
        m["files"] += [claude.INSTRUCTIONS_ALTERNATIVE]
        with self.assertRaises(claude.InputsCollide):
            render.render(m, engines.CLAUDE)


class ScopeInTheInstructions(unittest.TestCase):
    """The agent sees the scope where it reads first: in both engines' instructions, the decision sheet and the
    runbook, with who, when and why; no work item points into an excluded project; Claude Code enforces it; the
    verifier counts a change inside one as a scope violation."""

    def test_both_engines_instructions_name_the_excluded_projects_with_who_when_and_why(self):
        m = scoped()
        for engine in engines.ENGINES:
            files = inputs.build(m, None, engine=engine)
            text = files[paths.COPILOT_INSTRUCTIONS if engine == engines.COPILOT else claude.INSTRUCTIONS]
            scope = text.split("## Conversion scope", 1)[1].split("\n---\n", 1)[0]
            self.assertIn("Build and test only `in-scope.sln`", scope)
            self.assertIn("| Old | `src/Old/Old.csproj` |", scope)
            self.assertIn("| Legacy | `Legacy.csproj` |", scope)
            self.assertIn("Left out by Pat Example on 2026-11-18. Reason: retired next year.", scope)
            self.assertIn("Never change, retarget or fix", scope)
            self.assertIn("stop and say so", scope)

    def test_the_decision_sheet_lists_them_too(self):
        sheet = render.render(scoped())[f"{paths.PLATFORM_INPUTS_DIR}/decision-sheet.md"]
        self.assertIn("## Conversion scope", sheet)
        self.assertIn("| Old | `src/Old/Old.csproj` |", sheet)

    def test_no_work_item_points_at_an_excluded_projects_files(self):
        for engine in engines.ENGINES:
            files = render.render(scoped(), engine)
            for path, text in files.items():
                if "applying-" in path:
                    self.assertNotIn("src/Old/", text, path)

    def test_both_runbooks_carry_the_same_list(self):
        from app.engine import convert

        scope = {"excluded": ["Legacy.csproj", "src/Old/Old.csproj"], "build": "in-scope.sln", "decidedBy": "Pat Example",
                 "decidedAt": "2026-11-18T10:00:00+00:00", "reason": "retired next year",
                 "left": [{"path": "src/Old/Old.csproj", "name": "Old"}, {"path": "Legacy.csproj", "name": "Legacy"}]}
        for record in (ClaudeRunbook.RECORD, {k: v for k, v in ClaudeRunbook.RECORD.items() if k != "engine"}):
            text = convert.render_runbook({**record, "scope": scope})
            self.assertNotIn("${", text)
            self.assertIn("## Conversion scope: the projects left out", text)
            self.assertIn("| Old | `src/Old/Old.csproj` |", text)
            self.assertIn("Left out by Pat Example on 2026-11-18. Reason: retired next year.", text)
            self.assertIn("scope violation", text)
        self.assertNotIn("Conversion scope", convert.render_runbook(ClaudeRunbook.RECORD))

    def test_the_verifier_counts_any_change_inside_an_excluded_project_but_its_note(self):
        from app.engine import verifier
        from app.scope.service import owner

        every = ["src/A/A.csproj", "src/Old/Old.csproj"]
        out_of_scope = lambda path: owner(path, every) == "src/Old/Old.csproj"      # noqa: E731
        changed = [{"path": "src/A/A.cs", "change": "M"}, {"path": "src/Old/OUT-OF-SCOPE.md", "change": "M"},
                   {"path": "src/Old/Program.cs", "change": "M"}, {"path": "src/New.cs", "change": "R", "from": "src/Old/Moved.cs"}]
        self.assertEqual(verifier.scope_violations(changed, out_of_scope), ["src/Old/Moved.cs", "src/Old/Program.cs"])
        self.assertEqual(verifier.scope_violations(changed, None), [])
        failing = [{"id": "scope", "label": "Scope kept", "state": "fail", "detail": "scope violation: ..."},
                   {"id": "converted", "label": "Something converted", "state": "pass", "detail": "x"}]
        self.assertEqual(verifier.verdict(failing)[0], "NOT PROVEN")

    def test_claude_codes_settings_deny_edits_inside_excluded_projects(self):
        deny = json.loads(render.render(scoped(), engines.CLAUDE)[claude.SETTINGS])["permissions"]["deny"]
        self.assertIn("Edit(/src/Old/**)", deny)
        # A project at the repository's root cannot have its folder denied: only its own file.
        self.assertIn("Edit(/Legacy.csproj)", deny)
        self.assertNotIn("Edit(/**)", deny)

    def test_a_folder_that_also_holds_a_kept_project_is_not_denied_whole(self):
        m = scoped()
        m["scope"]["excluded"] = [{"path": "src/Host.csproj", "name": "Host"}]
        m["projects"].append({"path": "src/Host/Inner/Inner.csproj", "framework": "net8.0"})
        deny = json.loads(render.render(m, engines.CLAUDE)[claude.SETTINGS])["permissions"]["deny"]
        self.assertIn("Edit(/src/Host.csproj)", deny)
        self.assertNotIn("Edit(/src/**)", deny)


class ClaudeRunbook(unittest.TestCase):
    """The runbook and the opening message say how to run Claude Code in the worktree."""
    RECORD = {"repository": "accountsapi-net10", "engagement": "test-client-a", "branch": "conversion/1",
              "worktree": r"D:\runs\test-client-a\accountsapi-net10\conversions\1\wt", "solution": "AccountsApi.sln",
              "baseline": "e89bc6a147e456b730d664178d416f50bd532f31", "platform": {"commit": "0123456789abcdef", "dirty": False},
              "goal": "Make it ready for OpenShift.", "targetFramework": "net10.0", "engine": engines.CLAUDE,
              "instructions": claude.INSTRUCTIONS, "settings": claude.SETTINGS, "ownInstructions": ["CLAUDE.md"]}

    def test_how_to_start_claude_code_in_the_worktree(self):
        from app.engine import convert

        text = convert.render_runbook(self.RECORD)
        self.assertNotIn("${", text)
        self.assertIn("(Claude Code)", text.splitlines()[0])
        self.assertIn('cd "' + self.RECORD["worktree"] + '"\nclaude\n', text)
        self.assertIn(convert.opening_for(self.RECORD), text)
        self.assertIn("| `CLAUDE.md` | The repository's own, kept unchanged.", text)
        self.assertIn("Never choose \"Yes, and don't ask again\"", text)
        self.assertNotIn("Modernize", text)

    def test_the_opening_message_gives_claude_codes_mechanics_and_copilots_stays_as_it_was(self):
        from app.engine import convert

        opening = convert.opening_for(self.RECORD)
        self.assertIn("Follow .claude/CLAUDE.md: it gives the plan", opening)
        self.assertIn("Commit each work item on its own, naming it; never push, rebase or amend.", opening)
        self.assertNotIn(".github/", opening)
        copilot = {k: v for k, v in self.RECORD.items() if k not in ("engine", "instructions", "settings")}
        self.assertEqual(convert.opening_for(copilot), convert.opening_message("Make it ready for OpenShift.", "AccountsApi.sln"))
        # The four done checks are the same for both engines.
        self.assertEqual(opening.split("You are done only when", 1)[1],
                         convert.opening_for(copilot).split("You are done only when", 1)[1])


class WhichEngine(unittest.TestCase):
    """The repository owner's choice, else the engagement's default; every existing engagement keeps GitHub Copilot, and
    a conversion record from before engines were recorded is GitHub Copilot's."""

    def setUp(self):
        from app.db import SessionLocal
        from tests.support import ensure_test_engagement

        self.db = SessionLocal()
        self.engagement = ensure_test_engagement(self.db)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_an_engagement_created_without_a_choice_keeps_github_copilot(self):
        from types import SimpleNamespace

        self.db.flush()
        self.db.refresh(self.engagement)
        self.assertEqual(self.engagement.default_engine, engines.COPILOT)
        repository = SimpleNamespace(engagement_id=self.engagement.id, conversion_engine=None)
        self.assertEqual((engines.of_repository(self.db, repository), engines.source(self.db, repository)),
                         (engines.COPILOT, "engagement"))
        self.engagement.default_engine = engines.CLAUDE
        self.db.flush()
        self.assertEqual(engines.of_repository(self.db, repository), engines.CLAUDE)
        repository.conversion_engine = engines.COPILOT
        self.assertEqual((engines.of_repository(self.db, repository), engines.source(self.db, repository)),
                         (engines.COPILOT, "repository"))

    def test_the_database_refuses_an_unknown_engine(self):
        from sqlalchemy.exc import IntegrityError

        self.engagement.default_engine = "another-engine"
        with self.assertRaises(IntegrityError):
            self.db.flush()

    def test_a_record_without_an_engine_was_github_copilots(self):
        self.assertEqual(engines.of_record({"number": 1}), engines.COPILOT)
        self.assertEqual(engines.of_record({"engine": engines.CLAUDE}), engines.CLAUDE)
        self.assertEqual(engines.name(None), "GitHub Copilot")


class ContextIsolation(unittest.TestCase):
    def test_a_claude_md_or_claude_folder_above_the_worktree_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "runs" / "e" / "r" / "conversions" / "1" / "wt"
            worktree.mkdir(parents=True)
            self.assertEqual(claude.context_hazards(worktree, home=root / "home"), [])
            (root / "runs" / "CLAUDE.md").write_text("x", encoding="utf-8")
            (root / "runs" / "e" / ".claude").mkdir()
            found = claude.context_hazards(worktree, home=root / "home")
            self.assertIn(str((root / "runs" / "CLAUDE.md").resolve()), found)
            self.assertIn(str((root / "runs" / "e" / ".claude").resolve()), found)
            # The user's own .claude in their home folder is Claude Code's user configuration, not a project's.
            self.assertEqual(claude.context_hazards(worktree, home=root / "runs" / "e"), [str((root / "runs" / "CLAUDE.md").resolve())])
            # The worktree's own files are the repository's, never a hazard.
            (worktree / "CLAUDE.md").write_text("x", encoding="utf-8")
            self.assertNotIn(str((worktree / "CLAUDE.md").resolve()), claude.context_hazards(worktree, home=root / "home"))


if __name__ == "__main__":
    unittest.main()
