"""Render the engine inputs from the collected model (36-COPILOT-ENHANCED-CONVERSION Parts D, K and Q).

A pure function of `collect()`'s model: no clock, no database, no file reads beyond the static
templates, so the same discovery produces byte-identical files.

One content model, two renderers (Part Q): the work items, decisions, addendum, scope, build and test commands and
rules are produced here once. `render(model, engine)` gives GitHub Copilot's files below, or Claude Code's, which are
the same content in Claude Code's places through one table of engine mechanics (app.engine.inputs.claude).

GitHub Copilot's:

| Output | Where |
|---|---|
| One custom upgrade instruction per detected change and its chosen approach | `.github/upgrades/skills/applying-<resolution>.md` |
| The adapted plugin agents | `.github/skills/*.md` |
| Global instructions | `.github/copilot-instructions.md` |
| Assessment addendum | `.github/platform-inputs/assessment-addendum.md`, merged into the engine's assessment.md |
| Decision sheet | `.github/platform-inputs/decision-sheet.md` |

**Written for the engine, which reads only the branch (Part K).** Of the catalog, only engine-facing guidance and
names are used: an item's `engine_guidance` (what the change is and why), its resolution's `engine_guidance` (what
to do). Author-facing descriptions never reach a generated file. An item without guidance is emitted from its
resolution's guidance alone; a resolution without guidance cannot be applied, so its places are listed to leave
unchanged. Both are listed (`without_guidance`). The wording here avoids the platform's own vocabulary: the
self-containedness check (selfcontained.py) refuses any generated file that uses it.
"""
import re
from pathlib import Path

import yaml

from app.engine import engines, paths
from app.engine.inputs.collect import SILENT_ITEMS

GENERATOR_VERSION = "1.3.0"
TEMPLATES = Path(__file__).resolve().parent / "templates"
ADDENDUM_START = "<!-- platform-assessment-addendum:start -->"
ADDENDUM_END = "<!-- platform-assessment-addendum:end -->"
MAX_LIST = 200
NO_GUIDANCE = "no conversion guidance is written for this change yet"

RESOLUTION_NEEDS = yaml.safe_load((Path(__file__).resolve().parent / "resolution_parameters.yaml").read_text(encoding="utf-8"))

# dependency-assessment outcomes and verdicts, in the engine's words.
PACKAGE_OUTCOME = {
    "upgrade_safe": "upgrade, no code change", "upgrade_breaking": "upgrade, calling code changes",
    "no_compatible_version": "no version supports the target", "framework_provided": "remove: the framework provides it",
    "current": "already current", "unknown": "not determined",
}
RUNTIME_VERDICT = {
    "supported": "supported", "supported_with_caveat": "supported, with a caveat", "unsupported": "not supported",
    "unknown": "not established",
}
LINUX_VERDICT = {
    "compatible": "works on Linux", "requires_change": "needs a change to work on Linux",
    "incompatible": "does not work on Linux", "unknown": "not yet established on Linux: test the call from the container",
}


def _env_name(text: str) -> str:
    """A configuration key as an environment variable name: ":" becomes "__", anything else not a letter, digit
    or underscore becomes "_"."""
    text = (text or "").replace(":", "__")
    return re.sub(r"_{3,}", "__", re.sub(r"[^A-Za-z0-9_]", "_", text)).strip("_")[:80] or "VALUE"


def _occurrence_value(occ: dict) -> str:
    if occ.get("value"):
        return occ["value"]
    first = (occ.get("lines") or [{}])[0]
    return first.get("value") or Path(occ.get("file") or occ["project"]).stem


def _config_key(line: dict | None) -> str | None:
    """The configuration key a place's value sits under (registry 1.12.0: a path literal in a configuration file carries
    it as its member), or None for a literal in code or an XML attribute that is not a setting."""
    if not line or line.get("type") or not line.get("member") or "@" in line["member"]:
        return None
    return line["member"]


def plan_item(item: dict) -> dict:
    """How the chosen approach applies: the places it applies to, the places it cannot (left unchanged, with why),
    and the deployment parameters it needs — never a decision the engine has to stop for."""
    res = item["resolution"]
    needs = RESOLUTION_NEEDS.get(res["id"], {}) if res else {}
    apply, unresolved = [], []
    for occ in item["occurrences"]:
        value = _occurrence_value(occ)
        why = None
        if res is None:
            why = "no approach is defined for this change"
        elif not res.get("guidance"):
            why = NO_GUIDANCE
        for rule in needs.get("cannot_apply", []) if why is None else []:
            if "always" in rule:
                why = rule["always"]
            elif re.search(rule["value_matches"], value or "", re.I):
                why = rule["why"]
        (unresolved if why else apply).append({**occ, "why": why} if why else occ)
    parameters: dict[str, dict] = {}
    for p in needs.get("parameters", []):
        if p["per"] == "application":
            targets = [(p["name"], None, None)] if apply else []
        elif p["per"] == "project":
            targets = [(p["name"].replace("{PROJECT}", _env_name(Path(o["project"]).stem).upper()), o, None) for o in apply]
        elif "{KEY}" in p["name"]:
            # Named after the configuration key the code reads (FileContent__FilePath), one per key, at every place
            # it is set; a literal in code has no key yet, so it takes the fallback name.
            targets = []
            for o in apply:
                for line in o["lines"] or [None]:
                    key = _config_key(line)
                    name = (p["name"].replace("{KEY}", _env_name(key)) if key else
                            p["fallback"].replace("{VALUE}", _env_name((line or {}).get("value") or _occurrence_value(o))))
                    targets.append((name, o, line))
        else:
            targets = [(p["name"].replace("{VALUE}", _env_name(_occurrence_value(o))), o, None) for o in apply]
        for name, occ, line in targets:
            entry = parameters.setdefault(name, {"name": name, "kind": p["kind"], "what": p["what"], "places": []})
            if occ is not None:
                place = _site(occ, line or (occ["lines"] or [None])[0]).strip("`")
                if place not in entry["places"]:
                    entry["places"].append(place)
    return {"apply": apply, "unresolved": unresolved, "parameters": sorted(parameters.values(), key=lambda x: x["name"])}


def without_guidance(model: dict) -> list[dict]:
    """Detected changes missing engine-facing guidance, for the person preparing the inputs: {item, resolution,
    missing}. `item`: emitted from the resolution's guidance alone. `resolution`: not emitted; its places are listed
    to leave unchanged."""
    out = []
    for item in model["items"]:
        res = item["resolution"]
        if res is not None and not res.get("guidance"):
            out.append({"item": item["id"], "resolution": res["id"], "missing": "resolution"})
        elif not item.get("guidance"):
            out.append({"item": item["id"], "resolution": res["id"] if res else None, "missing": "item"})
    return out


def deployment_parameters(model: dict) -> list[dict]:
    """Every value to supply before deployment: {name, kind, what, changes, places}."""
    out: dict[str, dict] = {}
    for item in model["items"]:
        for p in plan_item(item)["parameters"]:
            entry = out.setdefault(p["name"], {**p, "changes": [], "places": []})
            entry["changes"] = sorted(set(entry["changes"]) | {item["name"]})
            entry["places"] = sorted(set(entry["places"]) | set(p["places"]))
    return [out[k] for k in sorted(out)]


def unresolved(model: dict) -> list[dict]:
    """Every place the chosen approach cannot apply: {item, change, resolution, place, value, why}. Left unchanged."""
    out = []
    for item in model["items"]:
        for occ in plan_item(item)["unresolved"]:
            out.append({"item": item["id"], "change": item["name"],
                        "resolution": item["resolution"]["id"] if item["resolution"] else None,
                        "place": _site(occ, (occ["lines"] or [None])[0]).strip("`"), "value": occ.get("value"),
                        "why": occ["why"]})
    return out


def skill_name(resolution_id: str) -> str:
    """Copilot skill names are kebab-case, start with a gerund and are at most 64 characters."""
    return ("applying-" + resolution_id)[:64].rstrip("-")


def _md(text) -> str:
    """A table cell: one line, no pipe."""
    return str(text if text is not None else "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def _site(occurrence: dict, line: dict | None = None) -> str:
    where = occurrence["file"] or occurrence["project"]
    return f"`{where}:{line['line']}`" if line else f"`{where}`"


def _generated_note(model: dict) -> str:
    return (f"> Generated for this repository at commit `{(model['repository']['commit'] or 'unknown')[:12]}`. "
            "Do not edit this file.")


generated_note = _generated_note


def commands(model: dict) -> dict:
    """The build and test commands, the same for every engine: with the conversion's own solution, in-scope.sln (every
    conversion has it, from 2026-11-23), else the repository's solution at its root (the first by name), else whatever
    the root builds."""
    solution = (model.get("scope") or {}).get("build")
    if not solution:
        roots = sorted(f for f in model.get("files") or [] if "/" not in f and f.lower().endswith((".sln", ".slnx")))
        solution = roots[0] if roots else None
    suffix = f" {solution}" if solution else ""
    return {"solution": solution, "build": f"dotnet build{suffix}", "test": f"dotnet test{suffix}"}


def upgrade_options(model: dict) -> list[dict]:
    """The answers at the engine's upgrade-options stage, with where each comes from. Used by the decision sheet
    and by the operator runbook, identically for every arm. `presumptive`: a default, not someone's decision."""
    eng = model["engagement"]
    frameworks = model["current_frameworks"]
    projects = [p for p in model["projects"] if p["framework"]]
    lift = eng["posture"] == "lift-and-shift"
    return [
        {"question": "Target framework", "answer": eng["target_framework"],
         "source": "the target framework of this upgrade", "presumptive": False},
        # Never all-at-once: one task per project in dependency order keeps every commit small, buildable and
        # attributable, which is what the verifier and the per-task commit strategy measure.
        {"question": "Upgrade strategy", "answer": "Bottom-up",
         "source": f"default: {len(projects)} project(s) on {', '.join(frameworks) or 'no framework'}; "
                   "leaf projects first, one task per project", "presumptive": True},
        {"question": "Project upgrade approach", "answer": "In-place" if lift else "Side-by-side",
         "source": f"the {eng['posture']} approach", "presumptive": True},
        {"question": "Technology modernization (Entity Framework, dependency injection, logging, configuration)",
         "answer": "None beyond what the instructions require: keep the current technologies" if lift
         else "As the instructions require",
         "source": f"the {eng['posture']} approach", "presumptive": True},
        {"question": "Package management (Central Package Management)", "answer": "Keep the current arrangement",
         "source": "default: no instruction changes how packages are managed", "presumptive": True},
        {"question": "Compatibility handling (unsupported APIs and packages)",
         "answer": "As each instruction says (decision sheet, Changes)",
         "source": "the approach chosen for each change, or its default", "presumptive": True},
    ]


def _status(chosen: bool) -> str:
    return "chosen" if chosen else "default"


# ---------------------------------------------------------------- per-change upgrade instructions

def _prerequisites(item: dict, present: set[str], by_id: dict) -> list[str]:
    lines = []
    for rule in item["ordering"]:
        other = by_id.get(rule["item"])
        if rule["item"] not in present or other is None or other["resolution"] is None:
            continue
        name = skill_name(other["resolution"]["id"])
        if rule["relation"] == "before":
            lines.append(f"- Apply this **before** `{name}` ({other['name']}).")
        elif rule["relation"] == "after":
            lines.append(f"- Apply `{name}` ({other['name']}) **first**; this one depends on it.")
        else:
            lines.append(f"- Apply **together with** `{name}` ({other['name']}), in the same task and commit: "
                         f"for one package, bump the version everywhere, then fix its call sites.")
    return lines


# The kinds of file an instruction names by path (36-COPILOT-ENHANCED-CONVERSION Part N). The pilot's agent could not
# find Build/ and created a root Dockerfile beside deploy/docker/Dockerfile: it is told where every one is.
FILE_KINDS = {
    "project settings": re.compile(r"(^|/)(Directory\.(Build|Packages)\.(props|targets)|nuget\.config|global\.json)$", re.I),
    "container": re.compile(r"(^|/)(Dockerfile[^/]*|[^/]*\.dockerfile|\.dockerignore|docker-compose[^/]*\.ya?ml|"
                            r"docker-entrypoint[^/]*)$", re.I),
    "build": re.compile(r"(^|/)build/|\.(bat|cmd|ps1|sh|cake)$|(^|/)(Jenkinsfile[^/]*|Makefile)$", re.I),
    "ci": re.compile(r"^\.github/workflows/|(^|/)azure-pipelines[^/]*\.ya?ml$|(^|/)\.gitlab-ci\.ya?ml$", re.I),
    "deployment": re.compile(r"(^|/)(deploy|deployment|deployments|k8s|kubernetes|openshift|helm|charts|manifests)/|"
                             r"(^|/)manifest[^/]*\.ya?ml$", re.I),
}
PACKAGE_KINDS = ("project settings",)


def concerned_files(model: dict, item: dict) -> list[str]:
    """Every existing file this item's instruction concerns, by repository path: the files of its places and of its
    impact, the project files of its projects, and the repository's files of the kinds it touches — for a package
    change its project settings, for every other change also its container, build, CI and deployment files."""
    existing = set(model.get("files") or [])
    if not existing:
        return []
    wanted = {o["file"] for o in item["occurrences"] if o.get("file")}
    wanted |= {o["project"] for o in item["occurrences"] if o.get("project")}
    wanted |= {e["file"] for e in item["impact"] if e.get("file")}
    kinds = PACKAGE_KINDS if item["id"].startswith("package-") else tuple(FILE_KINDS)
    wanted |= {f for f in existing if any(FILE_KINDS[k].search(f) for k in kinds)}
    # Never a file of a project outside the conversion's scope (Part O): no instruction points into one.
    left = {p["path"] for p in (model.get("scope") or {}).get("excluded") or []}
    if left:
        every = [p["path"] for p in model.get("projects") or []] + sorted(left)
        wanted = {f for f in wanted if _owner(f, every) not in left}
    return sorted(f for f in wanted & existing if not paths.is_under(f, paths.GENERATED_INPUT_PATHS))


def _owner(path: str, projects: list[str]) -> str | None:
    """The project a repository file belongs to: the one whose folder holds it most closely (app.scope.service.owner)."""
    best = None
    for project in projects:
        folder = project.rsplit("/", 1)[0] + "/" if "/" in project else ""
        if path.startswith(folder) and (best is None or len(folder) > len(best[0])):
            best = (folder, project)
    return best[1] if best else None


def tests_of(model: dict, item: dict) -> list[dict]:
    """The tests that exercise the code this item's instruction touches (test-coverage-assessment's mapping): every
    mapping from a file of its places or impact. Named in the instruction, so that no instruction conflicts with the
    rule never to delete or edit a test (Part N: conversion 2 removed FileLoggerProvider and its two tests)."""
    touched = {o["file"] for o in item["occurrences"] if o.get("file")} | {e["file"] for e in item["impact"] if e.get("file")}
    return [m for m in model.get("test_mappings") or [] if m["source_file"] in touched]


def _instruction(model: dict, item: dict, present: set[str], by_id: dict) -> str:
    res = item["resolution"]
    eng = model["engagement"]
    name = skill_name(res["id"])
    out = [
        "---",
        f"name: {name}",
        "description: >",
        f"  {_md(item['name'])}: {_md(res['name'])}. Custom upgrade instruction for this repository, for the upgrade",
        f"  to {eng['target_framework']} and OpenShift readiness. Activates during assessment, planning and execution",
        f"  of this upgrade, and for: {_md(item['name'])}; {_md(res['name'])}.",
        "metadata:",
        "  discovery: preload",
        "  traits: .NET | CSharp",
        "---",
        "",
        f"# {res['name']} — {item['name']}",
        "",
        _generated_note(model),
        f"> {'Chosen for this repository' if item['decided'] else 'The default approach for this change'}: apply it "
        "as written; do not stop to ask.",
    ]
    if item.get("guidance"):
        out += ["", "## The change", "", item["guidance"].strip()]
    out += ["", "## What to do", "", res["guidance"].strip()]
    if item["id"] == "windows-build-pipeline" and _built(model):
        out += ["", f"The Linux build pipeline builds {_built(model)}, not the repository's other solutions: the "
                "projects it leaves out are outside this conversion's scope and not part of the converted build."]
    prereq = _prerequisites(item, present, by_id)
    out += ["", "## Prerequisites", ""] + (prereq or ["- None among this repository's other instructions."])

    plan = plan_item(item)
    out += ["", "## Places", "", "Apply what to do above at these places, and only there:", ""]
    count = 0
    for occ in plan["apply"]:
        for line in occ["lines"] or [None]:
            if count >= MAX_LIST:
                break
            count += 1
            what = []
            if line and line.get("value"):
                what.append(f"`{_md(line['value'])}`")
            elif occ.get("value"):
                what.append(f"`{_md(occ['value'])}`")
            if line and line.get("member"):
                what.append(f"in `{_md(line.get('type') or '')}.{_md(line['member'])}`".replace("`.", "`"))
            found = f": {' '.join(what)}" if what else ""
            ambiguous = (line or {}).get("certainty") == "ambiguous" or occ["certainty"] == "possible"
            out.append(f"- {_site(occ, line)} ({occ['project']}){found}"
                       f"{' (this call site is ambiguous: confirm before changing)' if ambiguous else ''}")
    total = sum(max(1, len(o["lines"])) for o in plan["apply"])
    if total > count:
        out.append(f"- ... and {total - count} more of the same kind: find them by the same pattern.")
    out += ["",
            "If a listed place no longer contains it (an earlier task already changed it), change nothing there and "
            "record it as not applicable. If you find the same pattern somewhere not listed, apply the same change "
            "there and record it in the task's notes."]

    if plan["parameters"]:
        out += ["", "## Values this needs (deployment parameters)", "",
                "Nobody has supplied these values, and you must not invent them. Make the code read each one by name "
                "from configuration (environment variable, ConfigMap or Secret) and put only the name in any manifest "
                "or settings file. A person supplies them before deployment.", "",
                "| Name | Kind | What | Where |", "|---|---|---|---|"]
        for p in plan["parameters"]:
            out.append(f"| `{p['name']}` | {p['kind']} | {_md(p['what'])} | {_md(', '.join(p['places']) or 'the application')} |")
    if plan["unresolved"]:
        out += ["", "## Leave unchanged", "",
                "This approach cannot apply at these places. Do not change them, and do not choose another approach: "
                "record each as left unchanged in the task's notes.", ""]
        for occ in plan["unresolved"]:
            out.append(f"- {_site(occ, (occ['lines'] or [None])[0])} `{_md(occ.get('value'))}`: {occ['why']}")

    if res["id"] == "keep-existing-vault-delivery" and model.get("vault_delivery"):
        out += ["", "## The existing vault delivery", "",
                "These deployment files already deliver the vault secrets. Keep them as they are:", ""]
        out += [f"- `{v['file']}`: {v['description']}" for v in model["vault_delivery"]]

    tests = tests_of(model, item)
    if tests:
        out += ["", "## Tests that use this code", "",
                "These tests exercise the code this change touches. Keep every one of them, unchanged and passing. "
                "If the change would leave a test without code it uses, keep that code: the instruction never asks "
                "you to delete or edit a test unless it says a decision chose that.", ""]
        out += [f"- `{m['test_file']}`, `{m['test_class'].rsplit('.', 1)[-1]}`: "
                + ", ".join(f"`{x}`" for x in m["test_methods"]) + f" (uses `{m['production_type'].rsplit('.', 1)[-1]}`)"
                for m in tests[:MAX_LIST]]

    files = concerned_files(model, item)
    if files:
        out += ["", "## Files", "",
                "These files exist in this repository and concern this change. Open each one by this path; do not "
                "search for them. Never create a file listed here, or a second copy of one elsewhere: change it where "
                "it is.", ""]
        out += [f"- `{f}`" for f in files[:MAX_LIST]]
        if len(files) > MAX_LIST:
            out.append(f"- ... and {len(files) - MAX_LIST} more")
        if any(FILE_KINDS["deployment"].search(f) or FILE_KINDS["build"].search(f) for f in files):
            out += ["", "The deployment and build files listed are the application's working deployment and pipeline. "
                    "Change them in place and add beside them; never replace, remove or rewrite a mechanism they hold "
                    "(an init container, a ConfigMap, a script, a job) unless this instruction says a decision chose "
                    "that."]

    if item["impact"]:
        out += ["", "## Files this changes", "", "| Action | File | Project | Certainty |", "|---|---|---|---|"]
        for e in item["impact"][:MAX_LIST]:
            target = e["file"] or f"new: {e['proposed']}"
            out.append(f"| {e['action']} | `{_md(target)}` | {_md(e['project'])} | {_md(e['certainty'])} |")
        out += ["", "A change to a file not in this table needs a reason in the task's notes."]

    out += ["", "## Done when", "",
            "- [ ] Every listed place is changed, or recorded as not applicable with a reason",
            f"- [ ] {'The solution ' + _built(model) if _built(model) else 'The solution'} builds, from a build "
            "actually run",
            "- [ ] Every test that passed before still passes; no test was edited, deleted or weakened", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- addendum and decision sheet

# A package place in an instruction, as _instruction writes it: "- `file:line` (project): `value`". The value asks for
# a version in one of three ways (dependency-assessment 1.5.0): an upgrade "Package from -> to"; a vulnerability
# "Package from: severity; fixed in V"; a retired package's successor "Old from: package deprecated (...); replacement
# New V", which asks for New at V.
PACKAGE_PLACE = re.compile(r"^- `[^`]+` \((?P<project>[^)]+)\): `(?P<value>[^`]+)`", re.MULTILINE)
ASKED = (
    re.compile(r"^(?P<package>\S+) (?P<current>\S+) -> (?P<asked>\S+)$"),
    re.compile(r"^(?P<package>\S+) (?P<current>\S+): \w+; fixed in (?P<asked>\S+)$"),
    re.compile(r"^\S+ \S+: package deprecated \([^)]*\); replacement (?P<package>[^\s;]+) (?P<asked>\d[^\s;]*)$"),
)


def package_targets(files: dict[str, str]) -> list[dict]:
    """The version each package instruction asks for, read back from generated instruction texts ({path: text}):
    [{project, package, current, asked, instruction}]; `current` is None for a successor the project does not
    reference yet. The verifier judges a package upgrade against these (Part N), and prepare checks none has a
    known advisory."""
    out = []
    for path, text in sorted(files.items()):
        if not paths.work_item_name(path).startswith("applying-package-"):
            continue
        for place in PACKAGE_PLACE.finditer(text):
            for shape in ASKED:
                m = shape.match(place["value"].strip())
                if m:
                    out.append({"project": place["project"], "package": m["package"], "current": m.groupdict().get("current"),
                                "asked": m["asked"], "instruction": Path(path).name if Path(path).name != "SKILL.md"
                                else paths.work_item_name(path)})
                    break
    return out


def _soap_security(s: dict) -> str:
    return "; ".join(f"{b or 'unknown binding'}, {m or 'no'} security, {c or 'no'} client credential"
                     for b, m, c in s["security"]) or "binding not determined"


def addendum(model: dict) -> str:
    out = [ADDENDUM_START, "", "# Platform assessment addendum", "", _generated_note(model), "",
           "Findings from a deterministic scan of this repository that the upgrade tool's own assessment does not "
           "see. They are facts about this code, each with where it was found. Plan for them; do not drop them.", ""]

    out += ["## Changes required", "", "| Change | Approach | Instruction | Places | Files changed |", "|---|---|---|---|---|"]
    for item in model["items"]:
        res = item["resolution"]
        instruction = f"`{skill_name(res['id'])}`" if res is not None and res.get("guidance") else "none: leave unchanged"
        out.append(f"| {_md(item['name'])} | {_md(res['name'] if res else 'none')} | {instruction} | "
                   f"{sum(max(1, len(o['lines'])) for o in item['occurrences'])} | {len(item['impact'])} |")
    out += ["", "Each change with an instruction has a custom upgrade instruction under `.github/upgrades/skills/`, "
            "named in the table."]
    scope = model.get("scope") or {}
    if scope.get("excluded"):
        out += ["", "## Conversion scope", "",
                f"{len(scope['excluded'])} project(s) are outside this conversion's scope and left untouched; their "
                f"findings are not listed above. Build and test with {_built(model)}.", ""]
        out += [f"- `{p['path']}`" for p in scope["excluded"][:MAX_LIST]]

    out += ["", "## Framework deltas", ""]
    if model["deltas"]:
        for d in model["deltas"]:
            out += [f"### {d['id']}", "", d["description"], ""]
            if d.get("symptom"):
                out += [f"Symptom: `{d['symptom']}`", ""]
            for fix_file, consumers in d["sites"].items():
                out.append(f"- Fix at `{fix_file}`; seen by {', '.join(f'`{c}`' for c in consumers)}")
            if d.get("fix"):
                out += ["", f"Proven fix: {d['fix']}"]
            out.append("")
    else:
        out += ["No known breaking change between these .NET versions applies to this repository.", ""]

    out += ["## Behavioural deltas on Linux", "",
            "These compile and run but give a different result in a Linux container. Write a characterization "
            "test for each site before changing it (skill `writing-characterization-tests`).", ""]
    silent = [i for i in model["items"] if i["id"] in SILENT_ITEMS]
    for item in silent:
        out.append(f"- **{item['name']}**: {SILENT_ITEMS[item['id']]}.")
        for occ in item["occurrences"]:
            for line in occ["lines"] or [None]:
                out.append(f"  - {_site(occ, line)}" + (f" `{_md(line['value'])}`" if line and line.get("value") else ""))
    if not silent:
        out.append("- None found.")

    out += ["", "## Windows-only assumptions", ""]
    if model["outbound"]:
        out += ["| Kind | Host | On Linux | Why | Configured in |", "|---|---|---|---|---|"]
        rows: dict[tuple, set] = {}
        soap_hosts = {s["host"]: s for s in model["soap"]}
        for o in model["outbound"]:
            # A SOAP call's reasons are the support tables' bookkeeping: state its binding instead.
            why = (_soap_security(soap_hosts[o["host"]]) if o["mechanism"] == "soap_client" and o["host"] in soap_hosts
                   else "; ".join(o["reasons"]))
            key = (o["mechanism"].replace("_", " "), o["host"] or "unresolved", LINUX_VERDICT.get(o["linux"], o["linux"]), why)
            rows.setdefault(key, set()).update(b["file"] for b in o["bindings"] if b["file"])
        for (mechanism, host, linux, why), files in sorted(rows.items()):
            where = ", ".join(f"`{f}`" for f in sorted(files)) or "-"
            out.append(f"| {_md(mechanism)} | {_md(host)} | {_md(linux)} | {_md(why)} | {where} |")
    else:
        out.append("No outbound dependency needs a change to run on Linux.")
    for item in model["items"]:
        if item["id"] in ("windows-auth-connection-string", "unqualified-hostname", "hardcoded-windows-path", "registry-access"):
            places = ", ".join(_site(o, (o["lines"] or [None])[0]) for o in item["occurrences"])
            out.append(f"- {item['name']}: {places}")

    out += ["", "## Deploy parameters (Web Deploy SetParameters)", ""]
    bound = [(o, b) for o in model["outbound"] for b in o["bindings"] if b["deploy_parameter"]]
    if bound:
        for o, b in bound:
            out.append(f"- `{b['file']}` key `{b['key']}` ({b['environment']}): a value is set; values are never copied here")
    else:
        out.append("No SetParameters file binds an endpoint in this repository.")

    out += ["", "## SOAP backends", ""]
    if model["soap"]:
        out += ["| Host | Binding and security | .NET WCF client on the target | On Linux |", "|---|---|---|---|"]
        for s in model["soap"]:
            out.append(f"| {_md(s['host'] or 'unresolved')} | {_md(_soap_security(s))} | "
                       f"{_md(RUNTIME_VERDICT.get(s['runtime'], s['runtime']))} | {_md(LINUX_VERDICT.get(s['linux'], s['linux']))} |")
        out += ["", "Keep each client's binding, security mode and credential exactly as configured."]
    else:
        out.append("This repository calls no SOAP backend.")

    out += ["", "## Package upgrades and their dependencies", ""]
    if model["packages"]:
        out += ["Recommended versions are the latest supporting the target framework, from the organisation's feeds first. "
                "\"Before\" means bump on the current framework, before the retarget; \"after\" means after it.", "",
                "| Package | From | To | Change | Retarget | Projects |", "|---|---|---|---|---|---|"]
        for p in model["packages"]:
            out.append(f"| {p['package']} | {p['from']} | {p['to']} | {PACKAGE_OUTCOME.get(p['outcome'], p['outcome'])} | "
                       f"{p['retarget']} | {len(p['projects'])} |")
        if model["couplings"]["together"]:
            out += ["", "Packages that only resolve **together** (one task, one commit):", ""]
            out += [f"- {a} + {b}: {why}" for a, b, why in model["couplings"]["together"]]
        if model["couplings"]["depends"]:
            out += ["", "Packages that must be bumped **in order** (the second first):", ""]
            out += [f"- {a} after {b}: {why}" for a, b, why in model["couplings"]["depends"]]
        if model.get("version_drift"):
            out += ["", "**Version drift**: one package at different versions in different projects. Move every project to "
                    "the same recommended version, in one task per package:", ""]
            out += [f"- {d}" for d in model["version_drift"]]
        unknown = [p["package"] for p in model["packages"] if not p["dependencies_known"]]
        if unknown:
            out += ["", "Dependencies not known (couplings may be missing): " + ", ".join(unknown) + "."]
        out += ["", "Known gap: couplings are read from each package's direct dependencies only; an exact-version clash "
                "between two transitive pins (NU1107) is not visible here and appears only at restore."]
    else:
        out.append("No package upgrade is recommended.")
    out += ["", ADDENDUM_END, ""]
    return "\n".join(out)


def decision_sheet(model: dict) -> str:
    eng = model["engagement"]
    out = ["# Decision sheet", "", _generated_note(model), "",
           "The answers to give at the upgrade tool's upgrade-options stage, and the approach for each change. "
           "**Default** means nobody has chosen: the default approach is used and marked as such.", "",
           f"Target: {eng['target_framework']} on {eng['target_platform'] or 'an unrecorded platform'}; "
           f"approach: {eng['posture']}.", "", "## Upgrade options", "",
           "| Question | Answer | Source | Status |", "|---|---|---|---|"]
    for o in upgrade_options(model):
        out.append(f"| {_md(o['question'])} | {_md(o['answer'])} | {_md(o['source'])} | {_status(not o['presumptive'])} |")
    out += ["", "## Changes", "", "| Change | Approach | Status | Other approaches |", "|---|---|---|---|"]
    for item in model["items"]:
        res = item["resolution"]
        out.append(f"| {_md(item['name'])} | {_md(res['name'] if res else 'none defined')} | {_status(item['decided'])} | "
                   f"{_md(', '.join(a['name'] for a in item['alternatives']))} |")
    out += ["", "## Ordering", ""]
    by_id = {i["id"]: i for i in model["items"]}
    shown = []
    for i in model["items"]:
        for r in i["ordering"]:
            other = by_id.get(r["item"])
            if other is None or i["resolution"] is None or other["resolution"] is None:
                continue
            relation = {"before": "before", "after": "after"}.get(r["relation"], "together with")
            shown.append(f"- `{skill_name(i['resolution']['id'])}` runs {relation} `{skill_name(other['resolution']['id'])}`")
    out += shown or ["- No ordering constraint between this repository's changes."]

    out += ["", "## To supply before deployment", "",
            "Values a default approach needs that nobody has supplied. The conversion references each by name and "
            "never contains a value; a person supplies them in the deployment (ConfigMap, environment or Secret).", ""]
    params = deployment_parameters(model)
    if params:
        out += ["| Name | Kind | What | For | Where |", "|---|---|---|---|---|"]
        for p in params:
            out.append(f"| `{p['name']}` | {p['kind']} | {_md(p['what'])} | {_md(', '.join(p['changes']))} | "
                       f"{_md(', '.join(p['places']) or 'the application')} |")
    else:
        out.append("None.")
    out += scope_listing(model, "## Conversion scope")
    out += ["", "## Unresolved", "",
            "Places where the approach cannot apply. They are left unchanged by the conversion and need a decision "
            "afterwards.", ""]
    left = unresolved(model)
    if left:
        out += ["| Change | Place | Value | Why |", "|---|---|---|---|"]
        for u in left:
            out.append(f"| {_md(u['change'])} | `{_md(u['place'])}` | {_md(u['value'])} | {_md(u['why'])} |")
    else:
        out.append("None.")
    out.append("")
    return "\n".join(out)


def _built(model: dict) -> str:
    """The solution a conversion that leaves projects out builds and tests, its own, as text: "`in-scope.sln`", or
    ""."""
    built = (model.get("scope") or {}).get("build")
    return f"`{built}`" if built else ""


def scope_decided(scope: dict) -> str:
    """Who left the projects out, when and why, in one sentence."""
    who = scope.get("decidedBy")
    when = (scope.get("decidedAt") or "")[:10]
    said = "Left out" + (f" by {who}" if who else "") + (f" on {when}" if when else "") + "."
    reason = (scope.get("reason") or "").strip()
    return said + (f" Reason: {reason.rstrip('.')}." if reason else " No reason was given.")


def scope_listing(model: dict, heading: str) -> list[str]:
    """The projects outside the scope, by name and path, with who left them out, when and why: lines for the
    decision sheet (and the runbooks). [] when every project is in scope."""
    scope = model.get("scope") or {}
    if not scope.get("excluded"):
        return []
    out = ["", heading, "",
           f"{len(scope['excluded'])} project(s) are outside this conversion's scope: never changed, retargeted or fixed. "
           f"Build and test only {_built(model) or 'the conversion' + chr(39) + 's own solution'}.", "",
           scope_decided(scope), "", "| Project | Path |", "|---|---|"]
    out += [f"| {_md(p.get('name') or Path(p['path']).stem)} | `{_md(p['path'])}` |" for p in scope["excluded"][:MAX_LIST]]
    if len(scope["excluded"]) > MAX_LIST:
        out.append(f"| ... and {len(scope['excluded']) - MAX_LIST} more | each with its `OUT-OF-SCOPE.md` |")
    return out


def not_converted_lines(model: dict, heading: str = "## Not converted by this track") -> list[str]:
    """The projects this track does not convert (an SSIS .dtproj, any project that is not a .csproj or .vbproj), by
    path: never in in-scope.sln, never changed by the conversion. [] when there are none. The same list for both
    engines' instructions and the runbook."""
    listed = (model.get("scope") or {}).get("notConverted") or []
    if not listed:
        return []
    out = ["", heading, "",
           f"{len(listed)} project(s) are not .NET projects this conversion converts (an SSIS package project, a database "
           f"project, or another project that is not a .csproj or .vbproj). They are not in {_built(model) or 'the solution'}, "
           "and are not converted by this track: leave each exactly as it is.", "", "| Project | Path |", "|---|---|"]
    out += [f"| {_md(p.get('name') or Path(p['path']).stem)} | `{_md(p['path'])}` |" for p in listed[:MAX_LIST]]
    if len(listed) > MAX_LIST:
        out.append(f"| ... and {len(listed) - MAX_LIST} more | |")
    return out


def scope_section(model: dict) -> str:
    """The instructions' section for a conversion that leaves projects out (Part O), and the projects not converted by
    this track, or "": where the agent reads first, not only in the OUT-OF-SCOPE.md files it may never open."""
    scope = model.get("scope") or {}
    not_converted = not_converted_lines(model)
    if not scope.get("excluded"):
        return ("\n".join(not_converted) + "\n") if not_converted else ""
    c = commands(model)
    out = ["", "## Conversion scope", "",
           f"This conversion covers only some of this repository's projects. Build and test only {_built(model)} "
           f"(`{c['build']}`, `{c['test']}`), never the repository's other solutions: it lists exactly the projects in "
           "scope, wherever they live, each once. Do not add a project outside the scope to it.",
           "", "**Never change, retarget or fix a project outside the scope**, not even to make a build or a test pass: "
           "not its code, its project file, its packages or its tests. Each one has an `OUT-OF-SCOPE.md` in its folder "
           "and is left exactly as it is; it is not part of the converted build. If a change seems to need one of them, "
           "stop and say so, naming the project and why: this is the one case where you stop instead of deciding.",
           "", scope_decided(scope), "", "| Project | Path |", "|---|---|"]
    out += [f"| {_md(p.get('name') or Path(p['path']).stem)} | `{_md(p['path'])}` |" for p in scope["excluded"][:MAX_LIST]]
    if len(scope["excluded"]) > MAX_LIST:
        out.append(f"| ... and {len(scope['excluded']) - MAX_LIST} more | each with its `OUT-OF-SCOPE.md` |")
    return "\n".join(out + not_converted) + "\n"


DESIGN_HEADING = "## Design questions before converting"


def design_items(model: dict) -> list[dict]:
    """The work items whose chosen resolution changes the design (its catalog resolution's confirm_design), in work item
    order: [{name, title}]."""
    return [{"name": w["name"], "title": w["title"]} for w in work_items(model)
            if (w["item"]["resolution"] or {}).get("confirm_design")]


def design_items_in(instructions: str) -> list[str]:
    """The work items an instructions file's "Design questions before converting" section lists, by name; [] when it
    has none. Read by the runbook and the verifier from the inputs on the branch, for either engine's instructions."""
    _, found, rest = instructions.replace("\r\n", "\n").partition(DESIGN_HEADING + "\n")
    if not found:
        return []
    section = rest.split("\n## ", 1)[0]
    return re.findall(r"^- `([^`]+)`: ", section, re.MULTILINE)


def design_section(model: dict) -> str:
    """The instructions' rule for the work items that change the design, and their list, or "" when there is none. The
    rule only: the questions are the engine's to choose, from the code and the work item; none is written here. The
    same for every engine (Claude Code's instructions carry it through the mechanics table)."""
    flagged = design_items(model)
    if not flagged:
        return ""
    from app.engine import paths

    out = ["", DESIGN_HEADING, "",
           "These work items change the design or the architecture, not only the code. How to implement them is "
           "confirmed with the developer first:", ""]
    out += [f"- `{w['name']}`: {_md(w['title'])}" for w in flagged]
    out += ["",
            "- At the start of the conversion, **before changing any code**, ask the developer 3 to 5 questions for each "
            "work item above, all of them in one message: one round for every work item. This is the one time you stop "
            "for a decision.",
            "- Choose the questions yourself, from the code and the work item: how to implement the change (for example "
            "logging, exposing an API description, input validation). Each question names the default you will use if "
            "the developer does not choose. Do not ask about anything these instructions, a work item or the decision "
            "sheet already decide.",
            "- \"Use the defaults\" is an answer: it accepts every default. Then work through every work item without "
            "stopping again for these questions.",
            f"- Record every question, its default and the answer in `{paths.DESIGN_DECISIONS}` at the repository's root: "
            "a section for each work item, headed by its name (`## <work item name>`), holding a table "
            "`| Question | Default | Answer |` with one row per question. Commit it with the first work item."]
    return "\n".join(out) + "\n"


def build_section(model: dict) -> str:
    """The instructions' build and test commands, the same for every engine."""
    c = commands(model)
    return "\n".join(["", "## Build and test", "",
                      f"- Build with `{c['build']}` and test with `{c['test']}`, from the repository's root. Run both "
                      "after each change and before reporting done; these are the build and the tests the result is "
                      "judged by."]) + "\n"


def _applies(item: dict) -> bool:
    return item["resolution"] is not None and bool(item["resolution"].get("guidance")) and bool(plan_item(item)["apply"])


def work_items(model: dict) -> list[dict]:
    """The work items, one per change with an instruction, in the order to apply them: the model's order, moved only
    as far as an ordering constraint needs (an item that must run before another goes first). [{name, item, title}]"""
    items = [i for i in model["items"] if _applies(i)]
    ids = [i["id"] for i in items]
    after: dict[str, set] = {i: set() for i in ids}            # item -> the items that must come before it
    for i in items:
        for rule in i["ordering"]:
            other = rule["item"]
            if other not in after or other == i["id"]:
                continue
            if rule["relation"] == "before":
                after[other].add(i["id"])
            elif rule["relation"] == "after":
                after[i["id"]].add(other)
    ordered, placed = [], set()
    while len(ordered) < len(ids):
        ready = [i for i in ids if i not in placed and after[i] <= placed]
        nxt = ready[0] if ready else next(i for i in ids if i not in placed)     # a cycle: keep the model's order
        ordered.append(nxt)
        placed.add(nxt)
    by_id = {i["id"]: i for i in items}
    return [{"name": skill_name(by_id[i]["resolution"]["id"]), "item": by_id[i],
             "title": f"{by_id[i]['resolution']['name']} ({by_id[i]['name']})"} for i in ordered]


def render(model: dict, engine: str = engines.COPILOT) -> dict[str, str]:
    """{repository-relative path: text} for every generated input of `engine` except the manifest."""
    files = _copilot(model)
    if engines.check(engine) == engines.CLAUDE:
        from app.engine.inputs import claude
        return claude.render(model, files, work_items(model))
    return files


def _copilot(model: dict) -> dict[str, str]:
    files: dict[str, str] = {}
    by_id = {i["id"]: i for i in model["items"]}
    present = set(by_id)
    for item in model["items"]:
        if not _applies(item):
            continue                # nothing to apply: listed as unresolved in the decision sheet
        files[f"{paths.UPGRADE_SKILLS_DIR}/{skill_name(item['resolution']['id'])}.md"] = _instruction(model, item, present, by_id)
    for template in sorted((TEMPLATES / "skills").glob("*.md")):
        files[f"{paths.SKILLS_DIR}/{template.name}"] = template.read_text(encoding="utf-8")
    instructions = (TEMPLATES / "copilot-instructions.md").read_text(encoding="utf-8")
    # Before the attribution at the end: sections of this repository's rules, like the others.
    head, mark, tail = instructions.partition("\n---\n")
    instructions = head.rstrip("\n") + "\n" + build_section(model) + design_section(model) + scope_section(model) + mark + tail
    files[paths.COPILOT_INSTRUCTIONS] = instructions
    files[f"{paths.PLATFORM_INPUTS_DIR}/assessment-addendum.md"] = addendum(model)
    files[f"{paths.PLATFORM_INPUTS_DIR}/decision-sheet.md"] = decision_sheet(model)
    return {k: v.replace("\r\n", "\n") for k, v in sorted(files.items())}
