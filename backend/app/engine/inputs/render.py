"""Render the engine inputs from the collected model (36-COPILOT-ENHANCED-CONVERSION Parts D and K).

A pure function of `collect()`'s model: no clock, no database, no file reads beyond the static
templates, so the same discovery produces byte-identical files.

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

from app.engine import paths
from app.engine.inputs.collect import SILENT_ITEMS

GENERATOR_VERSION = "1.2.0"
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

    if item["impact"]:
        out += ["", "## Files this changes", "", "| Action | File | Project | Certainty |", "|---|---|---|---|"]
        for e in item["impact"][:MAX_LIST]:
            target = e["file"] or f"new: {e['proposed']}"
            out.append(f"| {e['action']} | `{_md(target)}` | {_md(e['project'])} | {_md(e['certainty'])} |")
        out += ["", "A change to a file not in this table needs a reason in the task's notes."]

    out += ["", "## Done when", "",
            "- [ ] Every listed place is changed, or recorded as not applicable with a reason",
            "- [ ] The solution builds, from a build actually run",
            "- [ ] Every test that passed before still passes; no test was edited, deleted or weakened", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- addendum and decision sheet

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


def render(model: dict) -> dict[str, str]:
    """{repository-relative path: text} for every generated input except the manifest."""
    files: dict[str, str] = {}
    by_id = {i["id"]: i for i in model["items"]}
    present = set(by_id)
    for item in model["items"]:
        if item["resolution"] is None or not item["resolution"].get("guidance") or not plan_item(item)["apply"]:
            continue                # nothing to apply: listed as unresolved in the decision sheet
        files[f"{paths.UPGRADE_SKILLS_DIR}/{skill_name(item['resolution']['id'])}.md"] = _instruction(model, item, present, by_id)
    for template in sorted((TEMPLATES / "skills").glob("*.md")):
        files[f"{paths.SKILLS_DIR}/{template.name}"] = template.read_text(encoding="utf-8")
    files[paths.COPILOT_INSTRUCTIONS] = (TEMPLATES / "copilot-instructions.md").read_text(encoding="utf-8")
    files[f"{paths.PLATFORM_INPUTS_DIR}/assessment-addendum.md"] = addendum(model)
    files[f"{paths.PLATFORM_INPUTS_DIR}/decision-sheet.md"] = decision_sheet(model)
    return {k: v.replace("\r\n", "\n") for k, v in sorted(files.items())}
