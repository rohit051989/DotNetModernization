"""Which test suites a change can affect: scripts\\run-suites.ps1 -Since <commit> or -Paths <paths>, and
scripts\\import-client-changes.ps1 for the paths a merge changed.

    python scripts\\select_suites.py --root <repository> --paths-file <file>    one changed path per line
    python scripts\\select_suites.py --root <repository> --all                  every suite

Prints JSON: {"suites": [{"name", "why"}], "none": why nothing runs, or null}, in the order run-suites.ps1 runs them.

The rules, by each changed path (relative to the repository, forward slashes):

- documentation: docs/, and any *.md file -> nothing;
- frontend/ -> the frontend tests and the type check;
- step registrations (steps/<step>/registration/, backend/app/steps/*.registration.json), job definitions
  (backend/app/jobs/), the catalog (catalog/), seed data (backend/app/seed/) and migrations (backend/alembic/) ->
  the seed and registration tests and the reproduce check;
- steps/<step>/ otherwise -> that step's tests: its C# test projects and its Python tests;
- backend/ -> the backend suite (it holds the seed and registration tests too: they run there, once);
- scripts/ -> the backend suite, which holds the scripts' tests;
- third_party/code-modernization/ -> its own suite;
- anything else -> every suite: no rule says what it can affect.

Standard library only: it runs before anything else is installed, and on a client's copy of the platform.
"""
import argparse
import json
import sys
from pathlib import Path

SEED_TESTS = ("tests.test_platform_seed", "tests.test_catalog_baseline", "tests.test_catalog_export",
              "tests.test_catalog_corrections")
SHOWN = 3   # paths named in a reason, before "and N more"


def suites(root: Path) -> list[dict]:
    """Every suite of the repository, in the order run-suites.ps1 runs them: {name, kind, step?, project?}."""
    out = [{"name": "backend", "kind": "backend"},
           {"name": "seed and registrations", "kind": "seed"},
           {"name": "reproduce", "kind": "reproduce"},
           {"name": "frontend tests", "kind": "frontend-tests"},
           {"name": "frontend type check", "kind": "frontend-types"}]
    steps = root / "steps"
    projects = sorted((p for p in steps.rglob("*Tests.csproj") if not {"bin", "obj"} & set(p.parts)),
                      key=lambda p: str(p).lower()) if steps.is_dir() else []
    for project in projects:
        out.append({"name": f"C# {project.stem}", "kind": "csharp", "step": project.relative_to(steps).parts[0],
                    "project": project.relative_to(root).as_posix()})
    for folder in sorted((p for p in steps.iterdir() if (p / "tests" / "__init__.py").is_file()),
                         key=lambda p: p.name.lower()) if steps.is_dir() else []:
        out.append({"name": f"step {folder.name}", "kind": "step", "step": folder.name})
    if (root / "third_party" / "code-modernization" / "scripts" / "tests").is_dir():
        out.append({"name": "third_party code-modernization", "kind": "third-party"})
    return out


def _seed(path: str) -> bool:
    parts = path.split("/")
    return (path.startswith(("backend/alembic/", "backend/app/seed/", "backend/app/jobs/", "catalog/"))
            or (len(parts) >= 3 and parts[0] == "steps" and parts[2] == "registration")
            or (path.startswith("backend/app/steps/") and path.endswith(".registration.json")))


def rules(path: str) -> list[tuple[str, str]]:
    """[(what it affects, the rule's words)] for one changed path. "what" is a suite kind, "step:<name>" for one step's
    tests, "none", or "all"."""
    path = path.replace("\\", "/").removeprefix("./")
    if path.startswith("docs/") or path.lower().endswith(".md"):
        return [("none", "documentation")]
    found = []
    if _seed(path):
        found += [("seed", "seed data, registrations, the catalog or migrations"),
                  ("reproduce", "seed data, registrations, the catalog or migrations")]
    if path.startswith("frontend/"):
        found += [("frontend-tests", "the frontend"), ("frontend-types", "the frontend")]
    elif path.startswith("steps/"):
        parts = path.split("/")
        if len(parts) >= 2 and not _seed(path):
            found.append((f"step:{parts[1]}", f"step {parts[1]}"))
    elif path.startswith("backend/"):
        found.append(("backend", "the backend"))
    elif path.startswith("scripts/"):
        found.append(("backend", "the scripts, whose tests are in the backend suite"))
    elif path.startswith("third_party/code-modernization/"):
        found.append(("third-party", "third_party/code-modernization"))
    elif not found:
        found.append(("all", "no rule says what it can affect"))
    return found


def _named(paths: list[str]) -> str:
    shown = ", ".join(paths[:SHOWN])
    return shown + (f" and {len(paths) - SHOWN} more" if len(paths) > SHOWN else "")


def select(paths: list[str], root: Path) -> dict:
    """{suites: [{name, why}], none}: the suites the changed paths can affect, each with why."""
    every = suites(root)
    paths = [p.strip() for p in paths if p.strip()]
    if not paths:
        return {"suites": [], "none": "nothing changed"}
    hits: dict[str, dict[str, list[str]]] = {}          # suite name -> {rule's words: [paths]}
    for path in paths:
        for what, words in rules(path):
            if what == "none":
                continue
            if what == "all":
                chosen = every
            elif what.startswith("step:"):
                chosen = [s for s in every if s.get("step") == what[5:] and s["kind"] in ("csharp", "step")]
                if not chosen:
                    continue                            # a step with no tests of its own
            else:
                chosen = [s for s in every if s["kind"] == what]
            for suite in chosen:
                hits.setdefault(suite["name"], {}).setdefault(words, []).append(path)
    # The seed and registration tests are part of the backend suite: run once, there.
    if "backend" in hits and "seed and registrations" in hits:
        for words, found in hits.pop("seed and registrations").items():
            if words not in hits["backend"]:
                hits["backend"].setdefault(f"{words} (its seed and registration tests)", []).extend(found)
    chosen = [{"name": s["name"], "why": "; ".join(f"{words}: {_named(found)}" for words, found in hits[s["name"]].items())}
              for s in every if s["name"] in hits]
    if chosen:
        return {"suites": chosen, "none": None}
    return {"suites": [], "none": f"only documentation changed ({_named(paths)}), or steps without tests of their own"}


def select_all(root: Path) -> dict:
    return {"suites": [{"name": s["name"], "why": "every suite"} for s in suites(root)
                       if s["kind"] != "seed"], "none": None}       # the backend suite holds the seed tests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts\\select_suites.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, help="the repository")
    parser.add_argument("--paths-file", help="the changed paths, one per line (UTF-8)")
    parser.add_argument("--all", action="store_true", help="every suite")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.all:
        result = select_all(root)
    else:
        text = Path(args.paths_file).read_text(encoding="utf-8-sig") if args.paths_file else ""
        result = select(text.splitlines(), root)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
