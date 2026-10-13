"""Impact rules — 33-IMPACT-ANALYSIS.md Parts D, E and K.

Each resolution carries the rules that say what converting an item that way
touches. They are catalog data on the resolution (`item_resolutions.
impact_rules`), authored beside it in catalog_items.yaml (or, for a migrated
resolution, in pattern_migration.RESOLUTION_IMPACT), seeded through the
never-overwrite baseline and included in the catalog export — so the delivery
team corrects what a resolution touches as data, not code. impact-analysis
(steps/step-003-fingerprinting/src/Fingerprinting.Impact) evaluates them.

A rule:

    - id: contracts            # unique within the resolution; later rules build on it
      from: impl               # "seed", an earlier rule's id, or a list of them
      traverse: implemented_interfaces   # one primitive (Part E) ...
      filter: { has_attribute: ServiceContract }
      action: delete           # update | rewrite | delete | review
      reason: "WCF service contract is replaced by controller routes"

    - id: impl
      from: seed
      select: self             # ... or `select: self`: the seed's evidence files

    - id: controllers          # ... or `create`: a new file per item of `for_each`
      create: "REST controller per service contract"
      for_each: contracts
      proposed_path: "{project.dir}/Controllers/{type.base_name}Controller.cs"
      action: create

**An action describes what happens to the file.** `delete` means the whole
file goes. `config_elements` reaches elements within a config file, so its
action is never `delete`: removing an element updates the file, and the
element is recorded in the entry's details. Where a type-based rule deletes
a type whose file declares others, impact-analysis records the file as
updated, naming what it loses.

**Being an item's evidence does not mean its conversion edits that file the
same way.** Evidence can be code (Program.cs, a code-behind class) or a file
the conversion makes obsolete (an .svc, .asmx or .aspx). A `select: self`
rule that rewrites code says which files it means with
`filter: { extension: .cs }`; obsolete evidence gets its own rule, usually a
delete. A `create` whose proposed path names no type (`{project.dir}/Program.cs`)
creates one file per project; a proposed file that already exists is
recorded as an update of it.

`client_call_sites` is the one primitive impact-analysis does not evaluate:
traversal never leaves the repository there, so callers come from
dependency-and-context-map's integration edges at the end of each estate
run, labelled `client`.

A resolution without rules gets DEFAULT_RULES — the seed's own evidence
files, `update` — so every work item has at least its evidence as impact.
"""

import re

PRIMITIVES = (
    "implemented_interfaces", "implementations_of", "signature_types", "declaring_files", "referencing_files",
    "config_elements", "convention_files", "referencing_tests", "project_file", "project_files", "entry_points",
    "hosting_project", "deploy_parameter_files", "client_call_sites", "version_declaration",
)
ACTIONS = ("update", "rewrite", "delete", "create", "review")
FILTERS = ("has_attribute", "in_project", "namespace_prefix", "excludes_generated", "extension")
CONVENTION_KINDS = ("svc", "asmx", "reference", "wsdl", "webforms_markup")
PATH_PLACEHOLDERS = ("{project.dir}", "{node.project.dir}", "{node.environment}", "{type.name}", "{type.base_name}", "{type.resource}")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

DEFAULT_RULES = [
    {"id": "evidence", "from": "seed", "select": "self", "action": "update",
     "reason": "Default rule: the work item's own evidence files. This resolution declares no impact rules of its own."},
]


def _sources(rule: dict) -> list:
    source = rule.get("from")
    return source if isinstance(source, list) else [source]


def validate(rules: list) -> list[str]:
    """Problems with a resolution's rules; empty when they are valid."""
    if not isinstance(rules, list):
        return ["impact rules must be a list"]
    problems = []
    seen: list[str] = []
    for index, rule in enumerate(rules):
        where = f"rule {index + 1}"
        if not isinstance(rule, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not SLUG.match(rule_id):
            problems.append(f"{where}: id must be a lowercase slug")
        elif rule_id in seen or rule_id == "seed":
            problems.append(f"{where}: id '{rule_id}' is not unique")
        where = f"rule '{rule_id}'"
        action = rule.get("action")
        # none: a traversal that only leads to later rules (hosting_project, to
        # place controllers in the host) — nothing happens to the files it reaches.
        if action == "none" and "traverse" not in rule:
            problems.append(f"{where}: action none is for a traversal that later rules build on")
        elif action not in ACTIONS and action != "none":
            problems.append(f"{where}: action {action!r} is not one of {', '.join(ACTIONS)}")
        modes = [m for m in ("select", "traverse", "create") if m in rule]
        if len(modes) != 1:
            problems.append(f"{where}: exactly one of select, traverse or create")
        elif modes[0] == "create":
            if action != "create":
                problems.append(f"{where}: a create rule's action is create")
            if not str(rule.get("create") or "").strip():
                problems.append(f"{where}: create needs a description")
            if rule.get("for_each") not in seen:
                problems.append(f"{where}: for_each must name an earlier rule")
            path = rule.get("proposed_path")
            if not isinstance(path, str) or not path.strip():
                problems.append(f"{where}: create needs a proposed_path")
            else:
                unknown = sorted(set(re.findall(r"\{[^}]+\}", path)) - set(PATH_PLACEHOLDERS))
                if unknown:
                    problems.append(f"{where}: unknown placeholder(s) {', '.join(unknown)} in proposed_path")
        else:
            if action == "create":
                problems.append(f"{where}: only a create rule has action create")
            for source in _sources(rule):
                if source != "seed" and source not in seen:
                    problems.append(f"{where}: from '{source}' is neither seed nor an earlier rule")
            if modes[0] == "select" and rule["select"] != "self":
                problems.append(f"{where}: select must be self")
            if modes[0] == "traverse":
                primitive = rule["traverse"]
                if primitive not in PRIMITIVES:
                    problems.append(f"{where}: traverse '{primitive}' is not a primitive ({', '.join(PRIMITIVES)})")
                if primitive == "convention_files" and rule.get("kind") not in CONVENTION_KINDS:
                    problems.append(f"{where}: convention_files needs kind: {' | '.join(CONVENTION_KINDS)}")
                if primitive == "project_files" and not str(rule.get("pattern") or "").strip():
                    problems.append(f"{where}: project_files needs a pattern, e.g. App.config or Properties/*.json")
                if primitive == "config_elements" and not str(rule.get("path") or "").strip():
                    problems.append(f"{where}: config_elements needs a path, e.g. system.serviceModel/services")
                # An action describes what happens to the file. An element is
                # part of a config file: removing it updates the file.
                if primitive == "config_elements" and action == "delete":
                    problems.append(f"{where}: config_elements reaches elements within a file, and removing one updates "
                                    "the file: use action update and say what is removed in the reason")
        for name in (rule.get("filter") or {}):
            if name not in FILTERS:
                problems.append(f"{where}: filter '{name}' is not one of {', '.join(FILTERS)}")
        if isinstance(rule_id, str):
            seen.append(rule_id)
    return problems


def checked(rules: list | None, where: str) -> list:
    """The rules, or a ValueError naming every problem."""
    rules = rules or []
    problems = validate(rules)
    if problems:
        raise ValueError(f"{where}: invalid impact rules:\n  " + "\n  ".join(problems))
    return rules
