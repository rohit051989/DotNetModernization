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
  path (declare it as a package), a package built only for .NET Framework (it "loads on the target framework only
  through .NET Framework fallback (NU1701)": replaced, never declared as it is, with its known replacement where there
  is one), needs a replacement on Linux (a Windows-only assembly), or unknown (check it builds and loads on Linux). A
  package whose only assets are .NET Framework ones (`lib/net45` and the like) reported as "the newest version known
  to support" the target framework is a gap.

**The decision sheet** (`decision-sheet.md`): the answers for the engine's upgrade options (target framework, strategy,
package management and the rest), the approach for each change, marked chosen (a person decided) or default, the class
libraries' recommended approach (below), any warnings, the ordering between changes, the values to supply before
deployment, and the places an approach cannot apply.

**Class libraries: bridge or direct retarget.** For each .NET Framework class library the decision sheet recommends an
approach from the projects that reference it, with the reason: the direct retarget when every consumer is in scope and
moves to the target framework, the .NET Standard 2.0 bridge when one stays on .NET Framework (left out of the scope, not
converted by this track, an approach that keeps it there such as "Remain Windows-hosted" or the incremental adapters,
or a library itself on the bridge). With no recorded decision the conversion follows it: the direct retarget when every
library's consumers move, otherwise the bridge, which every consumer builds against. A recorded decision is never
overridden: the sheet says "Decided" and marks each library whose recommendation differs. A recommendation that ignores
a consumer left out of the scope, or a recorded decision the conversion did not follow, is a gap.

**The work items**, one per change with an instruction. Each holds what the change is, what to do, the frameworks it
concerns (the target framework, and each project's current framework, with its SDK-style short form), its
prerequisites, its places, the deployment values it needs, the tests that use its code, and the files it may change.

**The plan's order.** Every work item has a phase, from its catalog resolution: 1 project format, 2 replace
framework-only dependencies, 3 libraries, 4 retarget and host applications, 5 platform and deployment, 6 decisions a
person still has to make. The plan goes by phase, and within a phase each project's referenced projects first. So a
work item that removes an API only .NET Framework has (LINQ to SQL, System.Web, WIF, Windows Workflow, directory
services, a Windows-only assembly, the Event Log) comes before that library's bridge or retarget, which cannot build
while the API is still used, and the bridge's or retarget's Prerequisites name it; a class library's bridge comes
before the application that references it moves; an SSIS reimplementation comes before the job that runs the package is
retargeted; and a package replacement comes before the safe bump of the same package. The one exception: a rewrite of
LINQ to SQL to EF Core needs the target framework, so it is one task with the library's direct retarget ("Apply
**together with**", in the same task and commit). Claude Code's plan lists the steps in that order, each with its phase; the decision
sheet's Ordering lists the same order for both engines; and each work item's Prerequisites say its phase and name the
earlier work items it follows ("it changes the same project first", "it changes a project this one references"). A
work item that comes before one it depends on, or a Prerequisites section that names neither its phase nor what it
follows, is a gap.

An old-style project file and packages.config each have their own work item (convert to an SDK-style project; move to
PackageReference), done in one task, in phase 1: Claude Code's plan lists them as its first step, "in one task and one
commit", and each says "Apply **together with**" the other. The
PackageReference work item has a table, "The packages", of what each project's packages.config pins and what each
becomes: kept as a direct reference at its pinned version, or left out when restore resolves that same version through
another listed package. A package pinned higher than restore would choose is kept, at its version.

A classic ASP.NET web project (System.Web: .svc, .asmx, MVC, Web API 2, Web Forms) gets neither work item: it has no
supported SDK-style form on .NET Framework, so its WCF, ASMX or MVC work item makes it SDK-style, and moves its
packages, in its move to ASP.NET Core. An old-style project file or packages.config work item that lists a web project
is a gap. A project with `.svc` or `.asmx` files is a web service project even without web.config or a web project
type GUID: it gets the WCF or ASMX work item, and a ".NET Framework 4.7 class library" work item that lists it is a
gap too.

Guidance names no framework version: it says "the target framework" and "the project's current framework", and each
work item's Frameworks section gives the values. A version written into a work item's text, other than the
`netstandard2.0` a .NET Standard bridge targets, is a gap.

A change kept unchanged (stays on Windows, stays on .NET Framework, kept out of the move) has a short work item of its
own: leave it as it is, change nothing, and record it as left unchanged with the reason it names. It gives no warning.

**Engagement guidance.** An engagement can add to the master catalog without forking it. A note on a resolution
appears in that work item's "What to do" after the master guidance, under "**For this engagement:**", with a line
saying the note is followed where the two disagree; the master text above it is the catalog's current text. The
engagement's conventions (logging, naming, error format) appear in the top-level instructions of both engines, under
"This engagement's conventions", and the design-question rule says not to ask about what they decide. A note in another
engagement's conversion, a work item whose master text is missing because a note stands in for it, or a resolution with
only a note and no warning, is a gap: a note adds to guidance, it never replaces it, so a resolution on the allow-list
still warns.

**Phase not set.** A work item whose catalog resolution has no phase says "phase not set" in its Prerequisites, in
Claude Code's plan and in the decision sheet; it is placed with phase 5, and preparation's warning names it, until an
admin sets the phase in the resolution's form.

**An SSIS package reimplemented in C#.** Its work item's places are the code that loads and runs the package (the
member calling `LoadPackage` or `Execute`, and each in-scope project referencing the SSIS runtime), not the package
project. "Files this changes" lists the `.dtproj` and each `.dtsx` as reference (read, never changed), the executing
files and project file as update, and as create the new code (a path pattern per package) and a test project beside the
executing project. The `.dtproj` is not in the addendum's table of in-scope projects. A place in the `.dtproj`, or a
`.dtproj` marked update, is a gap.

**Files.** Each work item's "Files" lists the files of its own in-scope projects and the repository's own pipeline,
build and deployment files, never a file of another project (in scope or not).

**APIs only .NET Framework has, in a class library.** LINQ to SQL (`System.Data.Linq`, a `DataContext`, `.dbml` files),
System.Web in a library (`HttpContext`, an `IHttpModule`, `System.Web.Configuration`), Windows Identity Foundation
(`System.IdentityModel.Services`) and Windows Workflow (`System.Activities`, a workflow `.xaml`) each raise their own
change, one place per file. Each default is a rewrite (EF Core; the System.Web adapters, then an interface for what
they do not cover; ASP.NET Core authentication; plain code), and the rewrites are under the design questions. "Remain
Windows-hosted" is offered for each, never the default. On a library on the bridge every replacement stays buildable
for both its current framework and `netstandard2.0`. The EF Core rewrite cannot (current EF Core does not run on .NET
Framework), so it requires the direct retarget with all the library's consumers, and choosing it with the bridge
raises a warning, in the decision sheet's Warnings and in preparation's `incomplete`. The bridge and the retarget say
that a .NET Framework-only use still left is a compile error to report, never one to stub. A library's own System.Web
use is never the classic MVC / Web API change: that change needs an application (its Global.asax, web.config or a
self-hosting `Main`), and an incremental-adapters work item that lists only a library is a gap.

**The identity-claims work item.** Its places are the signed-in user's identity and group checks
(`WindowsIdentity.GetCurrent`, `UserPrincipal.Current`, `IsInRole`), each listed once; a directory query for other
users or groups is under "Leave unchanged" (a token cannot carry it) and in the decision sheet's Unresolved. A place
listed twice, or a lookup of other users among the places to change, is a gap.

**An application on .NET Framework moving to a container.** When a .NET Framework application's chosen approach lands
it in a container on the target framework (a WCF or ASMX service rewritten or moved to CoreWCF, a Windows Service or a
batch job to a container), it gets the Dockerfile and OpenShift manifest work items, in phase 5, after its own
conversion; a web application (`.svc`, `.asmx`, `.aspx`, Global.asax) also gets the health endpoint work item. One
that stays on Windows gets none of them. The manifests' liveness and readiness probes call the paths the health
endpoint work item creates (`/health/live`, `/health/ready`, port 8080); a worker or job with no HTTP endpoint gets
`tcpSocket` or `exec` probes, a CronJob none. A converted service with no way to be deployed, or probes on paths the
application does not serve, is a gap.

**Claim types are not hostnames.** A URI used as a claim type or an XML namespace (`http://<name>/claims/role`, a
`new Claim(...)` argument, a `DataContract` namespace) is an identifier, not an endpoint: the fully qualified hostname
work item never lists one.

**Linux behaviour.** A call to the Windows Event Log raises "Windows Event Log usage" (write the same text to standard
error); a path joined with a backslash raises "Path built with a backslash" (`Path.Combine`; file names are
case-sensitive on Linux). The CronJob work item mounts a writable volume at each path the job writes (OpenShift runs it
as an arbitrary user), sets `concurrencyPolicy: Forbid` unless overlapping runs are safe, and limits the job history.
The build section says a new test project for in-scope code is created beside the project it tests and joins the
conversion's solution.

**Decisions to answer first.** A reference to an assembly that only loads on Windows raises "Reference to an assembly
that only loads on Windows". Until a person records its decision (the replacement, or keeping the project on Windows),
the engine is told not to touch those references, and the warning below says so. Answer it before running the
conversion. An assembly another chosen resolution replaces (the SSIS runtime, under a C# reimplementation of the
package) is not that item's: the addendum's verdict says "replaced by" the work item that removes it, and the warning
names only the assemblies left. A warning that asks about a replaced assembly is a gap.

**`RUNBOOK.md`.** It opens by sending GitHub Copilot users to section A and Claude Code users to section B. Section A:
open the solution, send the first message, standard replies, a stuck terminal, when the agent stops, verify. Section B:
start Claude Code at the worktree's root, send the first message, permission prompts, an interrupted session, check
each work item was committed, verify. Each says to expect the design questions first when there are any.

**Gaps are recorded, not hidden.** `last-prepare.json` holds the last preparation's outcome (`status`: prepared,
refreshed, kept or failed, with `message` and `details`), and two warnings shown on the Conversion tab: `warnings`
(secret values named by reference instead of quoted) and `incomplete` ("Inputs incomplete": each change that has no
instruction yet, each default answer that would keep something that cannot work on the target, each decision a person
must make first, and each choice that cannot work with another, such as EF Core in a library on the bridge). A failed preparation is also shown under the repository's header.

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
