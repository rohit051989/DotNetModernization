"""A conversion plan for one repository — 34-CONVERSION-ARCHITECTURE.md C4:
the recipes expanded over the repository into units, in a total order, each
with the units it depends on (Part E, "Failure policy").

**Units.** One retarget unit (recipe framework-retarget, step F01) for every
framework declaration together; before it, one unit per framework delta the
retarget crosses and per place discovery found it (step D01,
framework_deltas.yaml); and the package units — every upgrade_safe and
upgrade_breaking package dependency-assessment found:

- a package that moves alone: one unit per occurrence (recipe
  package-upgrade-safe-bump). Occurrences sharing a declaration (one central
  <PackageVersion>, one $(AspNetVersion)) are one move: the first unit edits
  it, the rest depend on it and find it done;
- packages that only resolve together (below): one atomic unit, every
  declaration edited in one commit;
- any move that includes an upgrade_breaking package: one atomic unit of
  recipe package-upgrade-breaking-adapt, `assisted` (Part F) — the code needs
  adapting, which the deterministic runner does not do. Left for T1b.

**Packages together or in order** — from each version's nuspec dependencies,
recorded by dependency-assessment (package_lookup_cache, `dependencies`):

1. A's new version requires plan package B above B's current version. If B
   also crosses a major version, they only resolve together: one unit (the
   Ardalis.Specification pair, MSTest's adapter and framework). Otherwise A
   depends on B, and B goes first.
2. A and B both raise a shared third-party dependency D. Of one family
   (Azure.Core between two Azure packages; Swashbuckle.AspNetCore.SwaggerGen
   between two Swashbuckle ones): one unit. Of different families: the one
   that raises D less depends on the one that raises it more, which goes
   first; raising it to the same version: one unit. Framework-family
   dependencies (Microsoft.Extensions.*, System.*) are left out: every
   package of the framework's generation moves them, and the runtime unifies
   them, so they would join everything to everything.

**Packages the target framework provides** (dependency-assessment's framework_provided): one unit per project and
package, removing the reference (recipe remove-framework-provided-package), after the retarget.

**Already on the target.** When every project already targets the engagement's framework there is no retarget
unit, and nothing waits on one.

**Around the retarget.** Every commit must build. A package version that
drops the current framework cannot be bumped before the retarget; a current
version that does not support the target cannot stay through it.
dependency-assessment's framework-support data decides, per move:

- the recommended version drops the current framework → after the retarget;
- the current version does not support the target → before the retarget,
  which depends on it;
- both → no order builds; recorded, placed after, expected to fail;
- neither: free to go either side. Placed before, on the baseline framework,
  so the retarget's own commit changes the framework and nothing else;
- not known → after, where the recommended version (chosen by
  dependency-assessment for the target framework) is known to fit.

A move placed before that depends on one placed after goes after too. Every
unit placed after depends on the retarget. Within each side, dependencies
come before dependents. The ordering — couplings, placements, reasons — is
recorded on the plan (`ordering`), and on every unit (`order_reason`,
`depends_on`).

    python -m app.conversion.planner --repository eshoponweb
"""

import argparse
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.conversion import frameworks, gitops, msbuild, recipes
from app.db import SessionLocal

CODE = Path(__file__).resolve().parents[3]
RUNS = settings.runs_path
DELTAS_FILE = Path(__file__).with_name("framework_deltas.yaml")

# Dependencies of the framework's own generation: moved by every package of
# that generation, unified by the runtime. Not a coupling between two packages.
FRAMEWORK_FAMILY = ("microsoft.extensions.", "system.", "microsoft.netcore.", "microsoft.bcl.", "microsoft.win32.",
                    "netstandard.library", "runtime.")


def _inventory(db: Session, repository_id) -> dict:
    """The latest solution-project-inventory of the repository: the projects
    with their target_framework_source (an artifact field, not a column)."""
    for (uri,) in db.execute(text("SELECT uri FROM wf_artifacts WHERE artifact_type = 'solution-project-inventory' "
                                  "ORDER BY created_at DESC LIMIT 50")):
        path = Path(unquote(urlparse(uri).path).lstrip("/"))
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("repository_id") == str(repository_id):
                return data
    raise LookupError("no solution-project-inventory for this repository: run discovery first")


def _unit_test_projects(db: Session, repository_id) -> list[str]:
    """Projects test-coverage-assessment classified as unit test projects."""
    rows = db.execute(text("""
        SELECT DISTINCT project_path FROM test_classes
        WHERE repository_id = :r AND test_type = 'unit' ORDER BY 1"""), {"r": repository_id}).scalars().all()
    if not rows:
        raise LookupError("test-coverage-assessment found no unit test project: the baseline cannot run")
    return list(rows)


def _solution(db: Session, repository_id, must_include: list[str]) -> str:
    """The solution to build: the one holding every unit test project and the most projects."""
    rows = db.execute(text("""
        SELECT s.relative_path, array_agg(p.relative_path) FROM solutions s
        JOIN solution_projects sp ON sp.solution_id = s.id JOIN projects p ON p.id = sp.project_id
        WHERE s.repository_id = :r GROUP BY s.relative_path"""), {"r": repository_id}).all()
    fitting = [(len(projects), path) for path, projects in rows if set(must_include) <= set(projects)]
    if not fitting:
        raise LookupError("no solution holds every unit test project")
    return sorted(fitting, key=lambda t: (-t[0], t[1]))[0][1]


def _support(db: Session, package_id: str, version: str, tfm: str) -> dict:
    s = frameworks.supports(frameworks.version_metadata(db, package_id, version), tfm)
    return {"supported": s.supported, "basis": s.basis}


def _place(group: dict, from_tfm: str, to_tfm: str) -> tuple[str, str]:
    drops, unsupported, unknown = [], [], []
    for pkg, info in sorted(group["support"].items()):
        if info["recommended"][from_tfm]["supported"] is False:
            drops.append(f"{pkg} {info['to']}")
        # Not known to support the target counts as not supporting it: the
        # safe move is onto the recommended version, known to fit.
        if info["current"][to_tfm]["supported"] is not True:
            unsupported.append(f"{pkg} {info['from']}")
        if info["recommended"][from_tfm]["supported"] is None:
            unknown.append(f"{pkg} {info['to']}")
    if drops and unsupported:
        return "after", (f"no order builds: {', '.join(drops)} drop(s) {from_tfm} and {', '.join(unsupported)} "
                         f"is not known to support {to_tfm}. Placed after the retarget; expected to fail")
    if drops:
        return "after", f"{', '.join(drops)} drop(s) {from_tfm}: bumped after the retarget"
    if unsupported and not unknown:
        return "before", (f"{', '.join(unsupported)} is not known to support {to_tfm}, and the recommended version "
                          f"supports both: bumped before the retarget, which needs it")
    if unknown:
        return "after", (f"{', '.join(unknown)} not known to support {from_tfm} (no compatible dependency group, "
                         f"lib/ref not examined): placed after the retarget, where the recommended version "
                         f"(chosen for {to_tfm}) is known to fit")
    return "before", (f"supports both {from_tfm} and {to_tfm}, current and recommended: bumped first, on the baseline "
                      f"framework, so the retarget commit changes the framework alone")


# ---------- packages together or in order ----------


def family(package_id: str) -> str:
    """Azure.Identity -> azure; Microsoft.EntityFrameworkCore.SqlServer -> microsoft.entityframeworkcore."""
    parts = package_id.lower().split(".")
    return ".".join(parts[:2]) if parts[0] in ("microsoft", "system") and len(parts) > 1 else parts[0]


def _v(version: tuple[int, ...]) -> str:
    return ".".join(str(n) for n in version)


@dataclass
class PackageMove:
    """One package dependency-assessment recommends moving: from, to, and
    each version's dependency minimums ({id: version}), per framework, merged
    (None when the dependencies were never recorded)."""
    package_id: str
    from_version: str
    to_version: str
    outcome: str
    before: dict[str, tuple[int, ...]] | None = None
    after: dict[str, tuple[int, ...]] | None = None


def couplings(moves: list[PackageMove]) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """(together, depends): pairs of package ids, lowercase, with the reason —
    `together` only resolve together; in `depends`, the first depends on the
    second, which goes first. Rules 1 and 2 of the module docstring."""
    by_id = {m.package_id.lower(): m for m in moves}
    together, depends = [], []
    for a in sorted(by_id.values(), key=lambda m: m.package_id.lower()):
        for dep, minimum in sorted((a.after or {}).items()):
            b = by_id.get(dep)
            if b is None or b is a:
                continue
            current = frameworks.parse_version(b.from_version)
            if minimum <= current:
                continue
            new_major = frameworks.parse_version(b.to_version)[:1] > current[:1]
            reason = f"{a.package_id} {a.to_version} requires {b.package_id} >= {_v(minimum)}, above its {b.from_version}"
            # One family released together (MSTest.TestAdapter and MSTest.TestFramework, 4.4.1 -> 4.5.1): the newer
            # one beside the older is not a combination its publisher shipped, and the test adapter, for one,
            # discovers no test with a framework newer than itself. They move as one.
            released_together = family(a.package_id) == family(b.package_id) and a.to_version == b.to_version
            if new_major:
                together.append((a.package_id.lower(), dep, f"{reason}, and {b.package_id} moves to a new major version"))
            elif released_together:
                together.append((a.package_id.lower(), dep, f"{reason}; one family ({family(a.package_id)}), released "
                                                           f"together at {a.to_version}"))
            else:
                depends.append((a.package_id.lower(), dep, reason))

    # Rule 2: a third-party dependency both upgrades raise.
    users: dict[str, list[tuple[PackageMove, tuple[int, ...], tuple[int, ...]]]] = {}
    for m in by_id.values():
        for dep, minimum in (m.after or {}).items():
            was = (m.before or {}).get(dep)
            if dep in by_id or dep.startswith(FRAMEWORK_FAMILY) or was is None or minimum <= was:
                continue
            users.setdefault(dep, []).append((m, was, minimum))
    for dep, raised in sorted(users.items()):
        raised.sort(key=lambda r: r[0].package_id.lower())
        for i, (a, a_was, a_to) in enumerate(raised):
            for b, b_was, b_to in raised[i + 1:]:
                pair = f"{a.package_id} and {b.package_id} both raise {dep}"
                detail = f"({_v(a_was)} -> {_v(a_to)}, {_v(b_was)} -> {_v(b_to)})"
                if family(a.package_id) == family(b.package_id):
                    together.append((a.package_id.lower(), b.package_id.lower(),
                                     f"{pair} {detail}; they are one family ({family(a.package_id)}), released together"))
                elif a_to == b_to:
                    together.append((a.package_id.lower(), b.package_id.lower(), f"{pair} to the same version {detail}"))
                else:
                    low, high, need = (a, b, a_to) if a_to < b_to else (b, a, b_to)
                    depends.append((low.package_id.lower(), high.package_id.lower(),
                                    f"{low.package_id} {low.to_version} needs {dep} >= {_v(need)}, which "
                                    f"{high.package_id} {high.to_version} brings {detail}"))
    return together, depends


class _Union:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # A package id names the set, never a "decl:" key.
            keep, other = sorted((ra, rb), key=lambda r: (r.startswith("decl:"), r))
            self.parent[other] = keep


def _strongly_connected(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's components, for merging a dependency cycle into one move."""
    index, low, stack, on, out, counter = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(edges.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on.discard(w)
                component.append(w)
                if w == v:
                    break
            out.append(sorted(component))

    for v in sorted(nodes):
        if v not in index:
            visit(v)
    return out


def _topological(nodes: list[str], edges: dict[str, set[str]], key) -> list[str]:
    """Dependencies first (edges: node -> what it depends on), ties by `key`."""
    remaining = {n: {d for d in edges.get(n, ()) if d in nodes} for n in nodes}
    order = []
    while remaining:
        ready = sorted((n for n, deps in remaining.items() if not deps), key=key)
        if not ready:
            raise ValueError(f"dependency cycle among {sorted(remaining)}")
        order.append(ready[0])
        del remaining[ready[0]]
        for deps in remaining.values():
            deps.discard(ready[0])
    return order


# ---------- framework deltas ----------


def load_deltas() -> list[dict]:
    return yaml.safe_load(DELTAS_FILE.read_text(encoding="utf-8"))["deltas"]


def _crosses(from_tfm: str, to_tfm: str, breaks_from: str) -> bool:
    _, f = frameworks._parse(from_tfm)
    _, t = frameworks._parse(to_tfm)
    _, b = frameworks._parse(breaks_from)
    return f < b <= t


def _delta_findings(db: Session, repository_id, delta: dict) -> dict[str, list[str]]:
    """Where discovery found a delta: {file to fix: [consuming files]}."""
    found: dict[str, list[str]] = {}
    for value, source in db.execute(text("""
            SELECT value, source_path FROM fingerprint_signals
            WHERE repository_id = :r AND signal_name = :s ORDER BY value, source_path"""),
            {"r": repository_id, "s": delta["signal"]}):
        found.setdefault(value, []).append(source)
    return found


# ---------- the plan ----------


@dataclass
class _Move:
    """A unit-to-be over packages: one declaration moved per occurrence, or
    several packages that move at once."""
    key: str
    packages: list[str] = field(default_factory=list)          # lowercase ids
    reasons: list[str] = field(default_factory=list)            # why they are together
    placement: str = ""
    order_reason: str = ""
    depends: dict[str, str] = field(default_factory=dict)       # move key -> reason


def _occurrences(db: Session, repository_id, exclusions: list[dict], drift: list[str] | None = None) -> tuple[dict, list[str]]:
    """{package id lowercase: {package_id, from, to, outcome, occurrences: [(occurrence id, project)]}},
    from dependency-assessment's assessments and item-detection's occurrences. Version drift (one package at
    different versions in different projects) raises, unless `drift` is given: then it is recorded there and the
    lowest current version is kept, so a report can describe the move without a plan."""
    excluded = {e["package_id"].lower() for e in exclusions}
    packages: dict[str, dict] = {}
    skipped = []
    for package_id, current, recommended, outcome, project in db.execute(text("""
            SELECT a.package_id, a.current_version, a.recommended_version, a.outcome, p.relative_path
            FROM package_assessments a JOIN projects p ON p.id = a.project_id
            WHERE a.repository_id = :r AND a.outcome IN ('upgrade_safe', 'upgrade_breaking')
            ORDER BY a.package_id, p.relative_path"""), {"r": repository_id}):
        if package_id.lower() in excluded:
            skipped.append(package_id)
            continue
        entry = packages.setdefault(package_id.lower(), {"package_id": package_id, "from": current, "to": recommended,
                                                         "outcome": outcome, "occurrences": []})
        if (entry["from"], entry["to"]) != (current, recommended):
            # Version drift. With one recommended version each project's own declaration moves from its own current
            # version (an occurrence carries it; a shared declaration cannot drift), and the move's `from` is the
            # lowest. Two recommendations are a conflict, consolidated before a plan.
            if drift is not None:
                drift.append(f"{package_id}: {entry['from']} in one project, {current} in {project}; both move to "
                             f"{recommended or entry['to']}")
            elif recommended != entry["to"]:
                raise ValueError(f"{package_id}: {entry['from']} -> {entry['to']} in one project, {current} -> {recommended} "
                                 f"in {project}: version drift is consolidated before a conversion plan")
            if frameworks.parse_version(current or "0") < frameworks.parse_version(entry["from"] or "0"):
                entry["from"] = current
        if outcome == "upgrade_breaking":
            entry["outcome"] = outcome
        entry["occurrences"].append([None, project, current])

    # The occurrence ids item-detection gave them: package-upgrade-safe's value
    # names the package; package-upgrade-breaking's evidence does.
    for occurrence_id, item_id, value, evidence, project in db.execute(text("""
            SELECT o.id, o.item_id, o.value, o.evidence, p.relative_path FROM item_occurrences o
            JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :r AND o.detection_state = 'found'
              AND o.item_id IN ('package-upgrade-safe', 'package-upgrade-breaking')"""), {"r": repository_id}):
        names = {value.split(" ", 1)[0]} if value else {(e.get("value") or "").split(" ", 1)[0] for e in evidence or []}
        for name in names:
            entry = packages.get(name.lower())
            if entry is None:
                continue
            for occurrence in entry["occurrences"]:
                if occurrence[1] == project and occurrence[0] is None:
                    occurrence[0] = str(occurrence_id)
    return packages, skipped


def package_moves(db: Session, repository_id, from_tfm: str, to_tfm: str,
                  exclusions: list[dict], drift: list[str] | None = None) -> tuple[dict, list[PackageMove], list[str]]:
    """(packages, moves, skipped): each package dependency-assessment recommends moving, with its
    occurrences, framework support and whether its dependencies are known, and the PackageMove
    `couplings` reads. Shared with the engine input generator (app.engine.inputs), which reports
    the same couplings without making a plan."""
    packages, skipped = _occurrences(db, repository_id, exclusions, drift)
    moves_in: list[PackageMove] = []
    for key, p in sorted(packages.items()):
        merged_before, merged_after, known = {}, {}, True
        for tfm in (from_tfm, to_tfm):
            b = frameworks.dependency_minimums(frameworks.version_metadata(db, p["package_id"], p["from"]), tfm)
            a = frameworks.dependency_minimums(frameworks.version_metadata(db, p["package_id"], p["to"]), tfm)
            known &= b is not None and a is not None
            for target, minimums in ((merged_before, b or {}), (merged_after, a or {})):
                for dep, v in minimums.items():
                    target[dep] = max(target.get(dep, v), v)
        p["dependencies_known"] = known
        p["support"] = {"from": p["from"], "to": p["to"],
                        "current": {t: _support(db, p["package_id"], p["from"], t) for t in (from_tfm, to_tfm)},
                        "recommended": {t: _support(db, p["package_id"], p["to"], t) for t in (from_tfm, to_tfm)}}
        moves_in.append(PackageMove(p["package_id"], p["from"], p["to"], p["outcome"], merged_before, merged_after))
    return packages, moves_in, skipped


def create(db: Session, slug: str, exclusions: list[dict], layout: str = "in_place") -> models.ConversionPlan:
    repository = db.query(models.Repository).filter_by(slug=slug).filter(models.Repository.deleted_at.is_(None)).one()
    engagement = db.get(models.Engagement, repository.engagement_id)
    root = Path(repository.local_path)
    to_tfm = engagement.target_framework
    recipes.sync(db)

    inventory = _inventory(db, repository.id)
    projects = [p for p in inventory["projects"] if p.get("target_framework_raw")]
    current = sorted({p["target_framework_raw"] for p in projects})
    if len(current) != 1:
        raise ValueError(f"projects target {', '.join(current)}: this proof retargets one framework")
    from_tfm = current[0]
    declarations = msbuild.framework_declarations(root, projects)
    unit_tests = _unit_test_projects(db, repository.id)

    plan_id = uuid.uuid4()
    plan_dir = RUNS / repository.engagement_id / slug / "conversion" / str(plan_id)[:8]
    plan = models.ConversionPlan(
        id=plan_id, repository_id=repository.id, engagement_id=repository.engagement_id,
        legacy_commit=gitops.head(root), target_layout=layout, target_framework=to_tfm,
        recipes=[{"id": r["id"], "version": r["version"]} for r in recipes.load()],
        exclusions=exclusions, branch=f"conversion/{str(plan_id)[:8]}", worktree_path=str(plan_dir / "target"),
    )
    db.add(plan)
    db.flush()

    # ---- the packages, their declarations and their couplings
    packages, moves_in, skipped = package_moves(db, repository.id, from_tfm, to_tfm, exclusions)
    for key, p in sorted(packages.items()):
        p["declarations"] = {}
        for occurrence in p["occurrences"]:
            d = msbuild.version_declaration(root, occurrence[1], p["package_id"])
            p["declarations"].setdefault(d.key, d)
    together, depends = couplings(moves_in)

    union = _Union()
    for key, p in packages.items():
        union.find(key)
        for declaration in p["declarations"]:
            union.join(key, f"decl:{declaration}")   # a shared declaration moves once, for all its packages
    for a, b, _ in together:
        union.join(a, b)
    # Merge dependency cycles: what cannot go one before the other goes together.
    edges: dict[str, set[str]] = {}
    for a, b, _ in depends:
        edges.setdefault(union.find(a), set()).add(union.find(b))
    for component in _strongly_connected(sorted({union.find(k) for k in packages}), edges):
        for other in component[1:]:
            union.join(component[0], other)

    moves: dict[str, _Move] = {}
    for key in sorted(packages):
        moves.setdefault(union.find(key), _Move(key=union.find(key))).packages.append(key)
    for a, b, reason in together:
        moves[union.find(a)].reasons.append(reason)  # not a JSON column: a planner _Move
    for a, b, reason in depends:
        ra, rb = union.find(a), union.find(b)
        if ra == rb:
            moves[ra].reasons.append(f"a dependency cycle: {reason}")  # not a JSON column: a planner _Move
        else:
            moves[ra].depends.setdefault(rb, reason)

    # ---- placement around the retarget
    for move in moves.values():
        move.placement, move.order_reason = _place(
            {"support": {packages[k]["package_id"]: packages[k]["support"] for k in move.packages}}, from_tfm, to_tfm)
    changed = True
    while changed:   # a move needing one placed after goes after too
        changed = False
        for move in moves.values():
            if move.placement == "before":
                late = [d for d in move.depends if moves[d].placement == "after"]
                if late:
                    move.placement = "after"
                    first = moves[late[0]]
                    move.order_reason += (f"; moved after the retarget: it depends on "
                                          f"{', '.join(packages[k]['package_id'] for k in first.packages)}, placed after")
                    changed = True

    name = lambda key: min(packages[k]["package_id"].lower() for k in moves[key].packages)   # noqa: E731
    before = _topological([k for k, m in moves.items() if m.placement == "before"],
                          {k: set(m.depends) for k, m in moves.items()}, name)
    after = _topological([k for k, m in moves.items() if m.placement == "after"],
                         {k: set(m.depends) for k, m in moves.items()}, name)

    # ---- framework deltas the retarget crosses
    delta_units = []
    for delta in load_deltas():
        if not _crosses(from_tfm, to_tfm, delta["breaks_from"]):
            continue
        for file, consumers in sorted(_delta_findings(db, repository.id, delta).items()):
            delta_units.append((delta, file, consumers))

    # ---- the units
    remove_step = recipes.step(db, "remove-framework-provided-package")
    safe_step = recipes.step(db, "package-upgrade-safe-bump")
    adapt_step = recipes.step(db, "package-upgrade-breaking-adapt")
    delta_step = recipes.step(db, "framework-retarget", "D01")
    retarget_step = recipes.step(db, "framework-retarget", "F01")
    sequence = 0
    first_unit: dict[str, int] = {}            # move key -> the sequence of the unit that edits it
    retarget_needs: list[dict] = []

    def add(unit_id, step, target, order_reason, depends_on, occurrence_ids, approach=None, automation=None):
        nonlocal sequence
        sequence += 1
        db.add(models.ConversionUnit(
            unit_id=f"{plan_id}:{unit_id}", plan_id=plan_id, recipe_id=step.recipe_id, step_id=step.step_id,
            approach_id=approach[0] if approach else step.approach_id,
            approach_version=approach[1] if approach else step.approach_version,
            occurrence_ids=occurrence_ids, target=target, sequence=sequence, order_reason=order_reason,
            depends_on=sorted(depends_on, key=lambda d: d["sequence"]),
            automation_class=automation or step.automation_class))
        return sequence

    def bump(key: str, project: str) -> dict:
        p = packages[key]
        own = next((o[2] for o in p["occurrences"] if o[1] == project), p["from"])   # this project's version (drift)
        d = msbuild.version_declaration(root, project, p["package_id"])
        shared = {packages[k]["package_id"]: packages[k]["to"] for k in packages if
                  any(dk == d.key for dk in packages[k]["declarations"])}
        for other in d.shared_with:
            shared.setdefault(other, "not in this plan")
        return {"package_id": p["package_id"], "from": own, "to": p["to"], "project": project,
                "declaration": {"file": d.file, "kind": d.kind, "name": d.name, "shared_with": d.shared_with},
                "shared_recommendations": shared}

    def add_move(key: str, retarget_sequence: int | None):
        move = moves[key]
        depends_on = [{"sequence": first_unit[d], "reason": reason} for d, reason in move.depends.items()]
        if retarget_sequence is not None:
            depends_on.append({"sequence": retarget_sequence, "reason": f"placed after the retarget: {move.order_reason}"})
        ids = sorted(move.packages)
        breaking = [packages[k]["package_id"] for k in ids if packages[k]["outcome"] == "upgrade_breaking"]
        n_declarations = len({dk for k in ids for dk in packages[k]["declarations"]})
        occurrence_ids = [o[0] for k in ids for o in packages[k]["occurrences"] if o[0]]
        if breaking or n_declarations > 1:
            # Every project of every package: a package declared in several project files moves in all of them at
            # once, so the solution never mixes two of its versions.
            bumps = [bump(k, o[1]) for k in ids for o in sorted(packages[k]["occurrences"], key=lambda o: o[1])]
            title = ", ".join(f"{b['package_id']} {b['from']} -> {b['to']} ({b['project']})" for b in bumps)
            one_package = len({b["package_id"].lower() for b in bumps}) == 1
            target = {"bumps": bumps, "group_reason": "; ".join(move.reasons) or (
                          f"declared in {len(bumps)} project files" if one_package else "they share a declaration"),
                      "title": (f"Together: {title}" if len(bumps) > 1 else title)}
            if breaking:
                target["breaking"] = breaking
                first_unit[key] = add(f"package-upgrade-breaking-adapt:F01:{key}", adapt_step, target,
                                      f"{move.order_reason}. Assisted: {', '.join(breaking)} change(s) API the code calls "
                                      f"(dependency-assessment); left for T1b", depends_on, occurrence_ids)
            else:
                first_unit[key] = add(f"package-upgrade-safe-bump:F01:{key}", safe_step, target, move.order_reason,
                                      depends_on, occurrence_ids)
            return
        occurrences = sorted(((packages[k]["package_id"], o[1], o[0], k) for k in ids for o in packages[k]["occurrences"]),
                             key=lambda o: (o[0].lower(), o[1]))
        for package_id, project, occurrence_id, k in occurrences:
            moved = bump(k, project)
            target = {**moved, "occurrence_id": occurrence_id,
                      "title": f"{package_id} {moved['from']} -> {moved['to']} ({project})"}
            own = list(depends_on)
            if key in first_unit:
                own = [{"sequence": first_unit[key], "reason": f"shares {target['declaration']['file']} "
                                                              f"({target['declaration']['kind']} {target['declaration']['name']}), "
                                                              f"edited by unit {first_unit[key]}"}]
            s = add(f"package-upgrade-safe-bump:F01:{occurrence_id or k + ':' + project}", safe_step, target,
                    move.order_reason, own, [occurrence_id] if occurrence_id else [])
            first_unit.setdefault(key, s)

    for key in before:
        add_move(key, None)
        # The retarget needs a move whose current version is not known to
        # support the target; the rest only go first by choice.
        if any(packages[k]["support"]["current"][to_tfm]["supported"] is not True for k in moves[key].packages):
            retarget_needs.append({"sequence": first_unit[key], "reason": moves[key].order_reason})
    for delta, file, consumers in delta_units:
        fix = delta["fix"]
        s = add(f"framework-retarget:D01:{delta['id']}:{file}", delta_step,
                {"delta_id": delta["id"], "breaks_from": delta["breaks_from"], "signal": delta["signal"], "file": file,
                 "consumers": consumers, "title": f"Framework delta {delta['id']}: {file}"},
                f"framework delta {delta['id']}: breaks from {delta['breaks_from']} ({delta['symptom']}); fixed before "
                f"the retarget, building on both frameworks", [], [],
                approach=(fix["approach_id"], fix["approach_version"]), automation=fix["automation_class"])
        retarget_needs.append({"sequence": s, "reason": f"framework delta {delta['id']} in {file}: without it {to_tfm} "
                                                        f"does not build ({delta['symptom']})"})
    files = ", ".join(d.file for d in declarations)
    retarget = None
    if from_tfm != to_tfm:      # already on the target: there is nothing to retarget
        retarget = add("framework-retarget:F01:repository", retarget_step,
                       {"from": from_tfm, "to": to_tfm, "declarations": [d.__dict__ for d in declarations],
                        "title": f"Retarget {from_tfm} -> {to_tfm} ({files}, global.json)"},
                       (f"after every framework delta fix and every package whose current version lacks {to_tfm}; "
                        f"before every package placed after it"), retarget_needs, [])
    for key in after:
        add_move(key, retarget)

    # ---- packages the target framework provides: removed, one unit per project and package, after the retarget
    for occurrence_id, value, project in db.execute(text("""
            SELECT o.id, o.value, p.relative_path FROM item_occurrences o JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :r AND o.detection_state = 'found' AND o.item_id = 'package-provided-by-framework'
            ORDER BY p.relative_path, o.value"""), {"r": repository.id}):
        m = re.match(r"^(\S+) (\S+): provided by (.+)$", value or "")
        if not m or m.group(1).lower() in {e["package_id"].lower() for e in exclusions}:
            continue
        target = {"package_id": m.group(1), "version": m.group(2), "project": project, "provided_by": m.group(3),
                  "occurrence_id": str(occurrence_id), "title": f"Remove {m.group(1)} {m.group(2)} ({project})"}
        depends_on = [{"sequence": retarget, "reason": f"{to_tfm} provides it, so it goes after the retarget"}] if retarget else []
        add(f"remove-framework-provided-package:F01:{occurrence_id}", remove_step, target,
            f"provided by {m.group(3)}: the reference is redundant", depends_on, [str(occurrence_id)])

    plan.ordering = {
        "from": from_tfm, "to": to_tfm, "solution": _solution(db, repository.id, unit_tests), "unit_test_projects": unit_tests,
        "left_out": skipped,
        "together": [{"packages": [a, b], "reason": r} for a, b, r in together],
        "depends": [{"dependent": a, "dependency": b, "reason": r} for a, b, r in depends],
        "dependencies_not_recorded": sorted(p["package_id"] for p in packages.values() if not p["dependencies_known"]),
        "moves": [{"packages": [packages[k]["package_id"] for k in moves[m].packages], "placement": moves[m].placement,
                   "reason": moves[m].order_reason, "together_because": moves[m].reasons,
                   "first_unit": first_unit[m], "support": {packages[k]["package_id"]: packages[k]["support"]
                                                            for k in moves[m].packages}}
                  for m in before + after],
        "framework_deltas": [{"delta": d["id"], "file": f, "consumers": c} for d, f, c in delta_units],
        "retarget": retarget is not None,
    }
    db.flush()
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a conversion (34-CONVERSION-ARCHITECTURE.md C4).")
    parser.add_argument("--repository", required=True, help="Repository slug")
    parser.add_argument("--exclude-package", action="append", default=[],
                        help="A package id left out of the plan — a person's planning decision, recorded with its reason")
    parser.add_argument("--exclude-reason", default="")
    args = parser.parse_args()
    if args.exclude_package and not args.exclude_reason:
        raise SystemExit("--exclude-package needs --exclude-reason")
    db = SessionLocal()
    try:
        plan = create(db, args.repository, [{"package_id": p, "reason": args.exclude_reason} for p in args.exclude_package])
        db.commit()
        print(f"Plan {plan.id}: {plan.ordering['from']} -> {plan.ordering['to']}, branch {plan.branch}")
        print(f"  build {plan.ordering['solution']}; unit tests {', '.join(plan.ordering['unit_test_projects'])}")
        for u in db.query(models.ConversionUnit).filter_by(plan_id=plan.id).order_by(models.ConversionUnit.sequence):
            needs = ",".join(str(d["sequence"]) for d in u.depends_on)
            print(f"  {u.sequence:>3} {u.automation_class:<13} {u.target.get('title')}" + (f"   <- {needs}" if needs else ""))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
