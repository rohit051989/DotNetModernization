# Reviewing a prepared conversion

For anyone asked to check a prepared conversion before it is run: a person at an installation, or an AI assistant
working for them. It says what a correct preparation contains, what is missing on purpose, who decides what, and how
to report a real gap. Read it before judging a preparation; most of what looks missing at first is absent by design.

A conversion is prepared by the last step of a repository's scan (or by "Start the next conversion"). It is a branch
and a worktree of the repository, the platform's own commits on it, and a folder of records beside it. Nothing in the
repository is converted yet: the engine (GitHub Copilot or Claude Code) does that when a developer runs it.

## Where to look

| What | Where |
|---|---|
| The worktree and its branch | the Conversion tab, or `conversion.json` (`worktree`, `branch`) in the folder below |
| The conversion's folder | `<RUNS_DIR>/<engagement>/<repository>/conversions/<number>/`: `conversion.json`, `RUNBOOK.md` |
| What the last preparation did | `<RUNS_DIR>/<engagement>/<repository>/conversions/last-prepare.json`, shown on the Conversion tab |
| GitHub Copilot's inputs | in the worktree: `.github/copilot-instructions.md`, `.github/upgrades/skills/applying-*.md` (one per work item), `.github/skills/*.md`, `.github/platform-inputs/` (`assessment-addendum.md`, `decision-sheet.md`, `inputs-manifest.json`) |
| Claude Code's inputs | in the worktree: `.claude/CLAUDE.md` (or `.claude/rules/conversion-instructions.md` where the repository has its own), `.claude/skills/applying-*/SKILL.md`, `.claude/agents/*.md`, `.claude/settings.json` (or `settings.local.json`), `.claude/conversion/` (`assessment-addendum.md`, `decision-sheet.md`) |

`RUNS_DIR` is in the owner's `backend\.env`. The worktree and the run folder are on the machine the repository was
registered on; elsewhere the Conversion tab shows the records as that machine last published them.

## What a correct preparation contains

**Both engines' inputs, with the same content.** Every conversion is prepared for GitHub Copilot and for Claude Code
from one content model. The work items, the addendum and the decision sheet say the same things in both; only where
each engine reads them differs. A difference in content between the two is a gap. The Conversion tab says if one
engine could not be prepared (Claude Code under a repository's own `CLAUDE.md` or `.claude` folder, named) and why.

**`in-scope.sln` at the worktree's root.** The solution the conversion builds and tests: exactly the .NET projects in
scope (`.csproj`, `.vbproj`), each once, wherever they live. A project left out of scope is not in it; neither is a
project this track does not convert (an SSIS `.dtproj`, a database project), which the instructions list separately as
"not converted by this track". The build and test commands in the instructions use it.

**The scope.** When projects were left out, the instructions have a "Conversion scope" section naming each one, who
left them out, when and why, and each excluded project's folder has an `OUT-OF-SCOPE.md`. Claude Code's settings deny
edits inside them.

**The addendum** (`assessment-addendum.md`), every section limited to in-scope files:

- Changes required: each change, its approach, and its instruction (a work item) or "no instruction yet" (below).
- Framework deltas and behavioural deltas on Linux, with where each is fixed.
- Windows-only assumptions, deploy parameters and SOAP backends: only configuration files of in-scope projects. A file
  of an excluded project here is a gap.
- Package upgrades and their dependencies.
- Assembly references no package declares: each in-scope project's format (old-style or SDK-style) and whether it uses
  packages.config, then each assembly referenced by path or from the GAC with a verdict: a NuGet package referenced by
  path (declare it as a package), needs a replacement on Linux (a Windows-only assembly), or unknown (check it builds
  and loads on Linux).

**The decision sheet** (`decision-sheet.md`): the answers for the engine's upgrade options (target framework, strategy,
package management and the rest), the approach for each change, marked chosen (a person decided) or default, the
ordering between changes, the values to supply before deployment, and the places an approach cannot apply.

**The work items**, one per change with an instruction. Each holds what the change is, what to do, the frameworks it
concerns (the target framework, and each project's current framework, with its SDK-style short form), its
prerequisites, its places, the deployment values it needs, the tests that use its code, and the files it may change.
An old-style project file and packages.config each have their own work item (convert to an SDK-style project; move to
PackageReference), done in one task, before any retarget that needs them.

**Decisions to answer first.** A reference to an assembly that only loads on Windows raises "Reference to an assembly
that only loads on Windows". Until a person records its decision (the replacement, or keeping the project on Windows),
the engine is told not to touch those references, and the warning below says so. Answer it before running the
conversion.

**`RUNBOOK.md`.** It opens by sending GitHub Copilot users to section A and Claude Code users to section B. Section A:
open the solution, send the first message, standard replies, a stuck terminal, when the agent stops, verify. Section B:
start Claude Code at the worktree's root, send the first message, permission prompts, an interrupted session, check
each work item was committed, verify. Each says to expect the design questions first when there are any.

**Gaps are recorded, not hidden.** `last-prepare.json` holds the last preparation's outcome (`status`: prepared,
refreshed, kept or failed, with `message` and `details`), and two warnings shown on the Conversion tab: `warnings`
(secret values named by reference instead of quoted) and `incomplete` ("Inputs incomplete": each change that has no
instruction yet, each default answer that would keep something that cannot work on the target, each decision a person
must make first). A failed preparation is also shown under the repository's header.

## What is absent by design, and not a gap

**Design questions are not written into the inputs.** Some resolutions change the design, not only the code (a SOAP
service becoming a REST API, a UI rewrite, a new hosting model): the catalog flags them "Confirm the design before
implementing". For each work item whose resolution is flagged, the instructions have a section, "Design questions before
converting", listing those work items and the rule: at the start of the conversion, before changing any code, the
agent asks the developer 3 to 5 questions per work item, in one round, each naming the default it will use; "Use the
defaults" accepts them all. The agent chooses the questions from the code; none is written in advance. It records every
question, default and answer in `CONVERSION-DECISIONS.md` at the worktree's root, committed with the first work item.
The verifier reports a gap if a flagged work item was changed with no answers recorded.

**"No instruction yet" for a resolution on the guidance allow-list.** Every resolution in the catalog either has
engine guidance or is on a reviewed allow-list (`backend/app/seed/data/engine_guidance_allowlist.yaml`), each entry with
its reason. A conversion that chooses an allow-listed resolution tells the engine "no instruction yet: do not change; a
person supplies it", and the warning repeats the reason. That is on purpose, not a defect; writing the guidance is
the fix, through the catalog (below).

Also absent by design: no setting or secret value (each is named by its file, key and line); no platform document, path
or term (the engine reads only the branch); no change to a project outside the scope.

## Two roles

- **Engine guidance is the standard way each kind of change is done.** It lives in the catalog, on each item (what
  the change is and why) and each resolution (what to do), the same for every engagement. The client's subject-matter
  expert reviews it once; an admin edits it in the catalog's item and resolution forms. It names frameworks by role
  ("the target framework", "the project's current framework"), never a version: each work item supplies the real
  values.
- **Design questions settle each conversion's details**: the shape of an API, the names a team uses, what to log. The
  developer running the conversion answers them, at its start, and the answers stay in that branch.

A gap in the standard way belongs in the guidance; a choice for one repository belongs in the design answers.

## Reporting a real gap

When something is missing or wrong that is not absent by design, write a hand-off for the people who fix the platform.
Change nothing yourself: no code, setting, catalog row or file. A good hand-off has:

1. **Symptom**: what you saw, where (the file in the worktree, the line in `last-prepare.json`).
2. **Evidence**: the exact text, the files, the records you read; the platform commit (`PLATFORM_SOURCE.json`, or the
   preparation's record).
3. **Root cause**: why it happens, as far as you can tell from the platform's own code and records.
4. **Suggested fix**: what would make it right, and how to prove it.

Use neutral names: "the repository", "client A", hosts as `client-a.example`. Nothing from the client's code: no
class, file, project, namespace or host name of theirs, no values, no excerpts. Describe a shape ("an old-style
console job referencing the SSIS runtime by path"), not their code.
