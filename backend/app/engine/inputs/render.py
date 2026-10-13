"""Render the engine inputs from the collected model (36-COPILOT-ENHANCED-CONVERSION Part D).

A pure function of `collect()`'s model: no clock, no database, no file reads beyond the static
templates, so the same discovery produces byte-identical files.

| Output | Where |
|---|---|
| One custom upgrade instruction per detected item and its resolution | `.github/upgrades/skills/applying-<resolution>.md` |
| The adapted plugin agents | `.github/skills/*.md` |
| Global instructions | `.github/copilot-instructions.md` |
| Assessment addendum | `.github/platform-inputs/assessment-addendum.md`, merged into the engine's assessment.md |
| Decision sheet | `.github/platform-inputs/decision-sheet.md` |
"""
import re
from pathlib import Path

import yaml

from app.engine import paths
from app.engine.inputs.collect import SILENT_ITEMS

GENERATOR_VERSION = "1.1.0"
TEMPLATES = Path(__file__).resolve().parent / "templates"
ADDENDUM_START = "<!-- platform-assessment-addendum:start -->"
ADDENDUM_END = "<!-- platform-assessment-addendum:end -->"
MAX_LIST = 200


RESOLUTION_NEEDS = yaml.safe_load((Path(__file__).resolve().parent / "resolution_parameters.yaml").read_text(encoding="utf-8"))


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


def plan_item(item: dict) -> dict:
    """How the item's resolution applies: the places it applies to, the places it cannot (left unchanged, with
    why), and the deployment parameters it needs — never a decision the engine has to stop for."""
    res = item["resolution"]
    needs = RESOLUTION_NEEDS.get(res["id"], {}) if res else {}
    apply, unresolved = [], []
    for occ in item["occurrences"]:
        value = _occurrence_value(occ)
        why = None
        if res is None:
            why = "the item has no resolution in the catalog"
        for rule in needs.get("cannot_apply", []):
            if "always" in rule:
                why = rule["always"]
            elif re.search(rule["value_matches"], value or "", re.I):
                why = rule["why"]
        (unresolved if why else apply).append({**occ, "why": why} if why else occ)
    parameters: dict[str, dict] = {}
    for p in needs.get("parameters", []):
        if p["per"] == "application":
            targets = [(p["name"], None)] if apply else []
        elif p["per"] == "project":
            targets = [(p["name"].replace("{PROJECT}", _env_name(Path(o["project"]).stem).upper()), o) for o in apply]
        else:
            targets = [(p["name"].replace("{VALUE}", _env_name(_occurrence_value(o))), o) for o in apply]
        for name, occ in targets:
            entry = parameters.setdefault(name, {"name": name, "kind": p["kind"], "what": p["what"], "places": []})
            if occ is not None:
                place = _site(occ, (occ["lines"] or [None])[0]).strip("`")
                if place not in entry["places"]:
                    entry["places"].append(place)
    return {"apply": apply, "unresolved": unresolved, "parameters": sorted(parameters.values(), key=lambda x: x["name"])}


def deployment_parameters(model: dict) -> list[dict]:
    """Every value to supply before deployment, across the work items: {name, kind, what, items, places}."""
    out: dict[str, dict] = {}
    for item in model["items"]:
        for p in plan_item(item)["parameters"]:
            entry = out.setdefault(p["name"], {**p, "items": [], "places": []})
            entry["items"] = sorted(set(entry["items"]) | {item["id"]})
            entry["places"] = sorted(set(entry["places"]) | set(p["places"]))
    return [out[k] for k in sorted(out)]


def unresolved(model: dict) -> list[dict]:
    """Every place a default resolution cannot apply: {item, resolution, place, value, why}. Left unchanged."""
    out = []
    for item in model["items"]:
        for occ in plan_item(item)["unresolved"]:
            out.append({"item": item["id"], "resolution": item["resolution"]["id"] if item["resolution"] else None,
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
    repo = model["repository"]
    return (f"> Generated by the Modernization Platform (input generator {GENERATOR_VERSION}) from discovery of "
            f"`{repo['slug']}` at `{(repo['commit'] or 'unknown')[:12]}` for engagement `{model['engagement']['id']}`. "
            f"Do not edit: change the source data and regenerate.")


def upgrade_options(model: dict) -> list[dict]:
    """The answers at the engine's upgrade-options stage, with where each comes from. Used by the
    decision sheet and by the operator runbook, identically for every arm."""
    eng = model["engagement"]
    frameworks = model["current_frameworks"]
    projects = [p for p in model["projects"] if p["framework"]]
    lift = eng["posture"] == "lift-and-shift"
    return [
        {"question": "Target framework", "answer": eng["target_framework"],
         "source": "engagement target_framework", "presumptive": False},
        # Never all-at-once: one task per project in dependency order keeps every commit small, buildable and
        # attributable, which is what the verifier and the per-task commit strategy measure.
        {"question": "Upgrade strategy", "answer": "Bottom-up",
         "source": f"platform default: {len(projects)} project(s) on {', '.join(frameworks) or 'no framework'}; "
                   "leaf projects first, one task per project", "presumptive": True},
        {"question": "Project upgrade approach", "answer": "In-place" if lift else "Side-by-side",
         "source": f"engagement posture {eng['posture']}", "presumptive": True},
        {"question": "Technology modernization (Entity Framework, dependency injection, logging, configuration)",
         "answer": "None beyond what the work items require: keep the current technologies" if lift
         else "As the work items require",
         "source": f"engagement posture {eng['posture']}", "presumptive": True},
        {"question": "Package management (Central Package Management)", "answer": "Keep the current arrangement",
         "source": "platform default: no package-management change is a work item", "presumptive": True},
        {"question": "Compatibility handling (unsupported APIs and packages)",
         "answer": "As each work item's resolution says (decision sheet, work items)",
         "source": "engagement decisions, or each item's default resolution where undecided", "presumptive": True},
    ]


# ---------------------------------------------------------------- per-item upgrade instructions

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


def _instruction(model: dict, item: dict, present: set[str], by_id: dict) -> str:
    res = item["resolution"]
    eng = model["engagement"]
    status = ("DECIDED: the engagement's approved decision" if item["decided"] else
              "PRESUMPTIVE: the engagement has not decided this item; this is the catalog's default resolution")
    name = skill_name(res["id"])
    triggers = ", ".join(sorted({item["name"], res["name"], item["id"], res["id"]}))
    out = [
        "---",
        f"name: {name}",
        "description: >",
        f"  {_md(item['name'])}: {_md(res['name'])}. Platform-generated custom upgrade instruction for this",
        f"  repository, for the upgrade to {eng['target_framework']} and OpenShift readiness. Activates during",
        f"  assessment, planning and execution of this upgrade, and for: {_md(triggers)}.",
        "metadata:",
        "  discovery: preload",
        "  traits: .NET | CSharp",
        "---",
        "",
        f"# {res['name']} — {item['name']}",
        "",
        _generated_note(model),
        f"> Item `{item['id']}`, resolution `{res['id']}`. **{status}.**",
        "",
        "## Problem",
        "",
        item["problem"] or item["name"],
        "",
        "## Resolution",
        "",
        res["description"] or res["name"],
    ]
    if res.get("target"):
        out += ["", f"Target state: {res['target']}."]
    if res.get("notes"):
        out += ["", f"Note: {res['notes']}"]
    if item["alternatives"]:
        out += ["", "Other resolutions in the catalog, **not** to be applied unless the engagement decides so: "
                + "; ".join(f"`{a['id']}` ({a['name']})" for a in item["alternatives"]) + "."]
    prereq = _prerequisites(item, present, by_id)
    out += ["", "## Prerequisites", ""] + (prereq or ["- None among this repository's work items."])

    plan = plan_item(item)
    out += ["", "## Steps", "",
            "Apply exactly this transformation, and only at the places listed. For each line below:", ""]
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
            found = " ".join(what) if what else f"this item ({item['name']})"
            out.append(f"- If {_site(occ, line)} ({occ['project']}) still contains {found}, then: {_md(res['description']).rstrip('.')}"
                       f"{' (call site is ambiguous: confirm before changing)' if (line or {}).get('certainty') == 'ambiguous' or occ['certainty'] == 'possible' else ''}.")
    total = sum(max(1, len(o["lines"])) for o in plan["apply"])
    if total > count:
        out.append(f"- ... and {total - count} more of the same kind: find them by the same pattern.")
    out += ["- If a listed place no longer contains it (already changed by an earlier task), change nothing there "
            "and record it as not applicable.",
            "- If you find the same pattern somewhere not listed, apply the same change there and record it as a gap."]

    if plan["parameters"]:
        out += ["", "## Values this needs (deployment parameters)", "",
                "Nobody has supplied these values, and you must not invent them. Make the code read each one by name "
                "from configuration (environment variable, ConfigMap or Secret) and put only the name in any manifest "
                "or settings file. They are listed for a person to supply before deployment.", "",
                "| Name | Kind | What | Where |", "|---|---|---|---|"]
        for p in plan["parameters"]:
            out.append(f"| `{p['name']}` | {p['kind']} | {_md(p['what'])} | {_md(', '.join(p['places']) or 'the application')} |")
    if plan["unresolved"]:
        out += ["", "## Leave unchanged", "",
                "This resolution cannot apply at these places. Do not change them, and do not choose an alternative: "
                "record each as unresolved in the task's progress notes.", ""]
        for occ in plan["unresolved"]:
            out.append(f"- {_site(occ, (occ['lines'] or [None])[0])} `{_md(occ.get('value'))}`: {occ['why']}")

    if item["impact"]:
        out += ["", "## Files this changes (impact analysis)", "", "| Action | File | Project | Certainty | Why |", "|---|---|---|---|---|"]
        for e in item["impact"][:MAX_LIST]:
            target = e["file"] or f"new: {e['proposed']}"
            out.append(f"| {e['action']} | `{_md(target)}` | {_md(e['project'])} | {_md(e['certainty'])} | {_md('; '.join(e['reasons']))} |")
        out += ["", "A change to a file not in this table needs a reason in the task's progress notes."]

    out += ["", "## Example", "",
            "The catalog holds no before-and-after example for this resolution yet. Follow the steps literally."]
    out += ["", "## Done when", "",
            "- [ ] Every listed place is changed, or recorded as not applicable with a reason",
            "- [ ] The solution builds, from a build actually run",
            "- [ ] Every test that passed before still passes; no test was edited, deleted or weakened", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- addendum and decision sheet

def addendum(model: dict) -> str:
    eng, repo = model["engagement"], model["repository"]
    out = [ADDENDUM_START, "", "# Platform assessment addendum", "", _generated_note(model), "",
           "Findings from the Modernization Platform's deterministic discovery of this repository, which the "
           "engine's own assessment cannot see. They are facts about this code, each with where it was found. "
           "Plan for them; do not drop them.", ""]

    out += ["## Work items", "", "| Item | Resolution | Status | Places | Files changed |", "|---|---|---|---|---|"]
    for item in model["items"]:
        res = item["resolution"]
        out.append(f"| {_md(item['name'])} (`{item['id']}`) | {_md(res['name'] if res else 'none')} "
                   f"(`{skill_name(res['id']) if res else '-'}`) | {'decided' if item['decided'] else 'presumptive'} | "
                   f"{sum(max(1, len(o['lines'])) for o in item['occurrences'])} | {len(item['impact'])} |")
    out += ["", "Each work item has a custom upgrade instruction under `.github/upgrades/skills/`, named in the table."]

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
        out += ["None of the platform's known framework deltas for this version pair is present.", ""]

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
        out += ["| Mechanism | Host | Linux verdict | Why | Configured in |", "|---|---|---|---|---|"]
        rows: dict[tuple, set] = {}
        for o in model["outbound"]:
            key = (o["mechanism"], o["host"] or "unresolved", o["linux"], "; ".join(o["reasons"]))
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
        out += ["| Host | Runtime verdict | Why |", "|---|---|---|"]
        for s in model["soap"]:
            out.append(f"| {_md(s['host'] or 'unresolved')} | {_md(s['runtime'])} | {_md('; '.join(s['reasons']))} |")
        unconfirmed = [s for s in model["soap"] if s["runtime"] and "unconfirmed" in s["runtime"]]
        out += ["", f"Unconfirmed matrix entries: {len(unconfirmed)}."]
    else:
        out.append("This repository calls no SOAP backend. Unconfirmed matrix entries: none.")

    out += ["", "## Package upgrades and their dependencies", ""]
    if model["packages"]:
        out += ["Recommended versions are the latest supporting the target framework, from the client's feeds first. "
                "\"Before\" means bump on the current framework, before the retarget; \"after\" means after it.", "",
                "| Package | From | To | Outcome | Retarget | Projects |", "|---|---|---|---|---|---|"]
        for p in model["packages"]:
            out.append(f"| {p['package']} | {p['from']} | {p['to']} | {p['outcome']} | {p['retarget']} | {len(p['projects'])} |")
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
           "The operator's answers at the engine's upgrade-options stage, and the engagement's decision for each "
           "work item. **Presumptive** means the engagement has not decided it: the platform's or the catalog's "
           "default is used and labelled as such.", "",
           f"Engagement `{eng['id']}`: target {eng['target_framework']} on {eng['target_platform'] or 'an unrecorded platform'}, "
           f"posture {eng['posture']}.", "", "## Upgrade options", "",
           "| Question | Answer | Source | Status |", "|---|---|---|---|"]
    for o in upgrade_options(model):
        out.append(f"| {_md(o['question'])} | {_md(o['answer'])} | {_md(o['source'])} | {'presumptive' if o['presumptive'] else 'decided'} |")
    out += ["", "## Work items", "", "| Item | Resolution | Status | Alternatives |", "|---|---|---|---|"]
    for item in model["items"]:
        res = item["resolution"]
        out.append(f"| {_md(item['name'])} (`{item['id']}`) | {_md(res['name'] if res else 'no resolution')} | "
                   f"{'decided' if item['decided'] else 'presumptive'} | "
                   f"{_md(', '.join(a['name'] for a in item['alternatives']))} |")
    out += ["", "## Ordering", ""]
    rules = [(i, r) for i in model["items"] for r in i["ordering"]]
    present = {i["id"] for i in model["items"]}
    shown = [f"- `{i['id']}` runs {r['relation'] if r['relation'] != 'together' else 'together with'} `{r['item']}`"
             for i, r in rules if r["item"] in present]
    out += shown or ["- No ordering constraint between this repository's work items."]

    out += ["", "## To supply before deployment", "",
            "Values a default resolution needs that nobody has supplied. The conversion references each by name and "
            "never contains a value; a person supplies them in the deployment (ConfigMap, environment or Secret).", ""]
    params = deployment_parameters(model)
    if params:
        out += ["| Name | Kind | What | For | Where |", "|---|---|---|---|---|"]
        for p in params:
            out.append(f"| `{p['name']}` | {p['kind']} | {_md(p['what'])} | {_md(', '.join(p['items']))} | "
                       f"{_md(', '.join(p['places']) or 'the application')} |")
    else:
        out.append("None.")
    out += ["", "## Unresolved", "",
            "Places where the default resolution cannot apply. They are left unchanged by the conversion and need a "
            "decision afterwards.", ""]
    left = unresolved(model)
    if left:
        out += ["| Item | Place | Value | Why |", "|---|---|---|---|"]
        for u in left:
            out.append(f"| `{u['item']}` | `{_md(u['place'])}` | {_md(u['value'])} | {_md(u['why'])} |")
    else:
        out.append("None.")
    out.append("")
    return "\n".join(out)


def render(model: dict) -> dict[str, str]:
    """{repository-relative path: text} for every generated input except the manifest."""
    files: dict[str, str] = {}
    by_id = {i["id"]: i for i in model["items"]}
    present = set(by_id)
    for item in model["items"]:
        if item["resolution"] is None or not plan_item(item)["apply"]:
            continue                # nothing to change: listed as unresolved in the decision sheet
        files[f"{paths.UPGRADE_SKILLS_DIR}/{skill_name(item['resolution']['id'])}.md"] = _instruction(model, item, present, by_id)
    for template in sorted((TEMPLATES / "skills").glob("*.md")):
        files[f"{paths.SKILLS_DIR}/{template.name}"] = template.read_text(encoding="utf-8")
    files[paths.COPILOT_INSTRUCTIONS] = (TEMPLATES / "copilot-instructions.md").read_text(encoding="utf-8")
    files[f"{paths.PLATFORM_INPUTS_DIR}/assessment-addendum.md"] = addendum(model)
    files[f"{paths.PLATFORM_INPUTS_DIR}/decision-sheet.md"] = decision_sheet(model)
    return {k: v.replace("\r\n", "\n") for k, v in sorted(files.items())}

