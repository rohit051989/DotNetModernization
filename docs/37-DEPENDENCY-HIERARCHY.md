# 37 — Dependency hierarchy

The `dependency-hierarchy` discovery step builds each repository's dependency graph: its projects, the packages they
use (and those packages' own dependencies), and the assembly references no package declares, joined by edges that
record their kind. The repository page's **Structure** section shows it as a node-link graph or an indented tree.

It is a graph, not a tree. A shared library with several parents is one node; every edge is recorded once.

---

## Part A — Place in the lifecycle

| | |
|---|---|
| Step | `dependency-hierarchy` (`17-LIFECYCLE-STEPS.md`, v2.5), job `phase0-repository-discovery` v18 |
| Runs after | `dependency-assessment`, whose classification of each declared package it reads |
| Runs before | `item-detection`, which does not depend on it |
| Owner | `P`, deterministic, no LLM |
| Inputs (required, wired) | `solution-project-inventory` ^2.0.0; `dependency-assessment` ^1.5.0 (before its 1.7.1 the step recorded its 1.6.0 artifact as 1.5.0, and those records remain; both carry what is read here) |
| Output | `dependency-hierarchy@1.0.0` (Part C), and the tables of Part D |
| Program | `steps/step-003-fingerprinting/src/Fingerprinting.Hierarchy` (graph builder) and `Fingerprinting.Hierarchy.Cli` (published to `publish/dependency-hierarchy/DependencyHierarchy.Cli.exe` by `bootstrap.ps1` stage 6) |
| Registration | `steps/step-003-fingerprinting/registration/dependency-hierarchy.json` |

Read-only against the repository. Nothing is restored, built or downloaded into it. The step shares
`dependency-assessment`'s feed resolution (NuGet's own configuration loader), credentials and lookup cache
(`package_lookup_cache`).

### Does `dependency-assessment` read packages.config?

**Yes, and it did before this step existed.** `solution-discovery` reads each project's `packages.config` beside the
project file (`project_parser._parse_packages_config`), and records each entry with `declaration_source:
packages_config`. `dependency-assessment` assesses those entries like any other direct package. It finds their
declaring line in packages.config (`PackageDeclarations`) and records `versionSource: packages_config`. This step
reads them through `dependency-assessment`'s artifact, and draws them as `packages_config` edges.

---

## Part B — How the graph is built

### B1. Nodes

| Type | Id | What it carries |
|---|---|---|
| Project | `project:<repository-relative path>` | kind (B2) and why; target frameworks; SDK-style or legacy; package management (PackageReference, packages.config, mixed, none) |
| Package | `package:<id>@<version>` (lower case, normalised version) | version; origin, internal or external (B3), and why; the feed that answered; transitive or declared; the producing repository of an internal package where estate consolidation knows it; `dependency-assessment`'s findings for a declared package (outcome, reason, outdated, deprecated, vulnerable); the version's known advisories from the feed's metadata (transitive packages too) |
| Assembly reference | `assembly:<location>:<path or name>` | the simple name and version from the Include; where it points: a DLL in the repository, a DLL outside it, the GAC, or .NET Framework itself; whether the HintPath's file exists |

A package at two versions is two nodes. A ProjectReference to a file that is not in the repository is a project node
marked **not checked**, with the reason.

### B2. Kinds of project

Read from the project file alone, in this order. Each kind is recorded with its basis.

1. **Other**: not a C#, VB or F# project (database, shared, Docker Compose, …), or a project file that could not be parsed.
2. **Test**: `IsTestProject` true, the legacy test project type GUID, a test package (Microsoft.NET.Test.Sdk, xunit,
   NUnit, MSTest), or a test framework assembly reference. Checked before application: a test project's OutputType is
   often Exe.
3. **Application**: OutputType Exe, WinExe or AppContainerExe; the Web, Worker or BlazorWebAssembly SDK; or a legacy
   ASP.NET, MVC, WCF service or web site project type GUID.
4. **Library**: everything else.

`item-detection` computes each project's *role* for the catalog separately. This kind is for the picture.

### B3. Internal or external

Decided once per package id, from the first project (in path order) that uses it:

1. Estate consolidation found the repository that produces it (`dependency_edges`, kind `internal_package`, by
   `via_package`): **internal**, naming that repository and project.
2. No feed lists it, but restore installed it (it is in the project's assets file) and nuget.org is the project's only
   source: **external**, as an unlisted nuget.org package.
3. No feed answered: **unknown**, and the node is not checked, with each feed's answer.
4. The project declares no client feed, so nuget.org answered as the fallback: **external**.
5. A client feed answered, and the public comparison is on: **external** if nuget.org has the package too (a client
   feed that mirrors nuget.org), **internal** if it does not.
6. A client feed answered, and the public comparison is off (`COMPARE_PUBLIC_NUGET_FEED=false`): **internal**, with
   the basis saying nuget.org was not consulted. A client feed that proxies nuget.org then makes every package look
   internal; the basis says so on each.

### B4. Edges

| Kind | From → to | Source |
|---|---|---|
| `project_reference` | project → project | ProjectReference, as `solution-discovery` resolved it, with its line in the project file |
| `package_reference` | project → package | PackageReference with a version in the project file |
| `central_package_version` | project → package | PackageReference whose version is in Directory.Packages.props (central package management) |
| `packages_config` | project → package | an entry in packages.config |
| `assembly_reference` | project → assembly | a `<Reference>`, with its line. A HintPath into NuGet's `packages` folder for a package the project declares is that package's assembly: the package node stands for it, and no assembly node is made |
| `package_dependency` | package → package | the package's own dependency (below) |

A package's own dependencies come from:
- **the project's restored `obj/project.assets.json`**, where it exists and has the package at the version in use:
  what restore chose, for the project's framework. Resolution `assets_file`. A file restore wrote before the project
  last changed can be stale.
- otherwise **the feed's metadata**: the nuspec dependency group nearest the project's target framework (NuGet's
  framework reducer), each dependency at the lowest listed version its range allows — what restore would choose, not
  what it chose. Resolution `feed_metadata`. Each such edge records the frameworks it was found for, because one package
  version can depend on different packages per framework.

### B5. Guards

- **Cycles.** A package being followed is not followed again while it is being followed. After the graph is built,
  one depth-first pass marks every edge back to a node still on the path as `closesCycle`, and records the cycle once
  (as the node ids around it, from the smallest). Project reference cycles are found the same way.
- **Depth.** A package's dependencies are followed at most `max_package_depth` levels (12) below the project that
  declares it. A package reached again more shallowly is followed further. One left at the limit says so
  (`dependenciesNotCheckedReason`).
- **Size.** At most `max_packages` (5000) package nodes. Past it, nothing new is added, the run warns, and the package
  whose dependencies were cut says so.
- **Not checked, with the reason.** A package no feed answers, a version that cannot be resolved, dependencies that
  cannot be read, an unknown target framework, a missing HintPath file, a missing referenced project, a project over
  its time limit (B6). Nothing unresolved is silently dropped.

### B6. Progress, time limits and speed

Like every discovery step, it reports progress (phases `read`, `resolve`, `graph`, `write`, `database`, item by item),
writes `timing-profile.json`, and resolves each project within the engine's per-project limit (`STEP_PROJECT_SECONDS`).
A project over its limit keeps what was found and is marked not checked, with the reason. The step carries on.

A cold lookup cache costs a feed round trip per package, and a repository's closure runs to hundreds of packages.
Before the walk follows a node's dependencies, their lookups are made together, at most `lookup_concurrency` (8) at a
time, each by its own `PackageLookup` over one synchronised cache. The walk then reads the answers from the cache.
eShopOnWeb (11 projects, 288 packages): 268 s one at a time against an empty cache, 42 s with this, 1.3 s with a warm
cache. Output is byte-identical in every case.

Configuration (job definition, all optional): `compare_public_feed` (from `COMPARE_PUBLIC_NUGET_FEED`),
`lookup_cache_ttl_hours` (24), `lookup_offline` (the job's parameter), `max_package_depth` (12), `max_packages`
(5000), `lookup_concurrency` (8).

### B7. Roots

The roots are the projects in the repository's inventory that no other project in the repository references. They are
usually the applications. In a repository whose test projects reference the applications, the test projects are the
roots instead: eShopOnWeb's are its four test projects and docker-compose.

---

## Part C — The artifact, `dependency-hierarchy@1.0.0`

Schema: `steps/step-003-fingerprinting/schemas/dependency-hierarchy-1.0.0.schema.json` (written by
`make_dependency_hierarchy_schema_1_0_0.py`). Every artifact is validated against it before it is written. Serialised
through `DeterministicJson`: keys sorted, nodes by id, edges by (from, to, kind). Two runs against the same repository
and lookup cache write the same bytes.

Top level: `limits`, `summary` (projects by kind; packages, internal, external and transitive; assembly references;
edges by kind; roots; cycles; not checked; the longest path from a root), `roots`, `nodes`, `edges`, `cycles` and
`warnings`. A node is `checked`, or `not_checked` with a `notCheckedReason`; a node carries only the detail of its own
type (`project`, `package` or `assembly`).

---

## Part D — Tables

| Table | Key | Columns beside `detail` (the artifact's node or edge, as written) |
|---|---|---|
| `hierarchy_nodes` | (repository_id, node_id) | node_type, name, status, is_root, project_id, step_execution_id |
| `hierarchy_edges` | (repository_id, from_node, to_node, kind) | resolution, closes_cycle |

Migration `e2b6f4a8c1d5`: two new tables, nothing existing changes. Each run replaces the repository's rows in one
transaction (COPY), with the lookup cache entries it fetched. Both cascade with the repository. A hard delete of a
repository removes them (`app/deletion` finds them by `repository_id`), and the demo reset clears them.

---

## Part E — The Structure section

The repository page's **Structure** section (`frontend/src/pages/repositories/structure/`). The section that was
called "Structure & fingerprint" is now **Projects & fingerprint**.

**API** (`backend/app/routers/hierarchy.py`, read-only; every call takes the view, `transitive` and `show`):

| | |
|---|---|
| `GET /api/repositories/{id}/hierarchy` | the summary and the roots. 409 until the step has run |
| `GET …/hierarchy/children?node=&offset=&limit=` | one page (20 by default) of a node's children under the view, projects first, with each edge |
| `GET …/hierarchy/search?q=` | up to 20 nodes whose name contains the query, each with a shortest path from a root under the view. When there is none, the reason: only reachable through transitive packages, hidden by the filter, or no root reaches it |
| `GET …/hierarchy/node?node=` | a node's details: its first 20 parents with their edges (and how many there are), and its work items |

Each node comes with what its badges need: kind, origin or location, version, frameworks, legacy, transitive,
findings, work items (a project's found occurrences; a package's package-item occurrences that name its id and
version), `referenced_by` (its parents) and `child_count` (its children under the view).

**Behaviour:**
- It opens showing only the roots. Each node has **+** to expand its children and **−** to collapse them. Clicking a
  node opens its details; nothing expands on a double click.
- Children load when a node is expanded, a page at a time, never the whole graph. Each node shows its first 20
  children, then **+N more**, 20 at a time.
- A shared node is drawn once: expanding a second parent draws an edge to the node already there. A node with more than
  one parent shows **referenced by N**.
- Collapsing hides what only that node led to. Expanding again shows the same picture without asking the server again.
- **Graph**: React Flow, laid out top to bottom by dagre. Only what is on screen is laid out and drawn. After an
  expansion the view moves to the node and its new children.
- **Tree**: the same graph, the same + and −, as an indented tree for very large repositories. A tree repeats a shared
  node under each expanded parent, and shows an edge back to a node above it on the branch, without following it.
  Graph or tree is remembered in the browser.
- **Search** by name. Choosing a match expands every node on its path from a root, pins the match under its parent
  whatever page it is on, centres it, and opens its details.
- **Transitive packages** (off by default) shows packages' own dependencies. **Show**: everything; internal only
  (projects and internal packages); external only (projects and external packages); projects only. Assembly references
  show under everything.
- **Legend**: each kind of project, internal package, external package and assembly reference (dashed). Edge styles by
  kind: ProjectReference solid violet, PackageReference solid slate, central version dotted, packages.config dashed
  amber, assembly reference dash-dot, package dependency light dashed. An edge that closes a cycle is red.
- **Badges**: target framework (in the node's subtitle), legacy, not checked, vulnerable (with severity), outdated,
  deprecated, the number of work items, referenced by N.
- **Details**: the path with the editor link (`SourceLink`: the person's editor, or copy); where each parent declares
  it, at its line; target framework, project format and package management; kind with its basis; version, origin with
  its basis, feed and producer; how its own dependencies were found; parents; work items; and
  `dependency-assessment`'s status with its reason. That last comes from the artifact the page already holds: a
  project's status and skip reason with its outcome counts, a declared package's outcome, recommended version and reason
  per project. A transitive package or an assembly reference says why it was not assessed.

**Library**: `@xyflow/react` 12.12.0 (React Flow, MIT) and `@dagrejs/dagre` 3.1.1 (MIT), installed from the configured
npm registry. React Flow is maintained, renders nodes as React components (so + and −, badges and the editor link are
ordinary components), and draws only what is in view. Dagre is the layered top-to-bottom layout React Flow's own
examples use for trees and DAGs. elkjs, the main alternative layout, is EPL-2.0, not MIT. React Flow's attribution
link is left in place.

---

## Part H — Proof at scale

`backend/tests/fixtures/synthetic_repository.py` writes a 170-project repository into an empty folder outside this
repository:
- 20 applications (SDK-style web and worker, and legacy ASP.NET);
- 115 libraries in four layers with nested project references, and core libraries every layer above shares;
- 30 test projects;
- 5 projects that are not code;
- legacy projects with packages.config, and assembly references to a DLL in the repository, to the GAC and to .NET
  Framework, and into the packages folder;
- a folder under central package management;
- a reference to a missing project;
- a client feed of internal packages and copies of external ones, with nuspec dependencies.

It also writes `expected-graph.json`. After registering and scanning it,
`python -m tests.fixtures.synthetic_repository --check <folder> <repository id>` compares the graph in the database
with it: every project with its kind, every declared edge once and nothing more, and the missing reference not checked.

Measured on this machine (2026-10-22):
- **Through the engine**: dependency-hierarchy took 6 s; its timing profile says 4.7 s, 3.1 s of it resolving.
- **The graph**: 171 project nodes (the missing one included), 65 roots, 26 package nodes (6 internal, 20 external,
  9 transitive), 5 assembly references, 733 edges, depth 17.
- **The check**: 0 differences. `SynthCo.Core.Common` is one node with 77 parents.
- **In the UI**: expanding a node, request and layout included, about 250 ms.

Tests: `steps/step-003-fingerprinting/tests/Fingerprinting.Dependencies.Tests/DependencyHierarchyTests.cs` (graph
building), `backend/tests/test_dependency_hierarchy.py` (the API's reads), and
`frontend/src/pages/repositories/structure/*.test.tsx` (expand, collapse, the 20-item rule, shared nodes, the view).
