"""The engine input generator (36-COPILOT-ENHANCED-CONVERSION Part D).

    python -m app.engine.inputs generate --engagement test-client-a --repository eshoponweb --out <worktree>
    python -m app.engine.inputs merge-addendum --worktree <worktree>
    python -m app.engine.inputs check --worktree <worktree> [--repository-root <checkout>]

`generate` produces, for one repository and engagement, everything the engine reads: one custom upgrade
instruction per detected item and its resolution, the adapted plugin skills, the global instructions,
the assessment addendum and the decision sheet, plus `.github/platform-inputs/inputs-manifest.json`
with a sha256 per file. Generated, never hand-edited: change the source data and regenerate.

Nothing is written unless two checks pass. The secret check (app.engine.inputs.secrets): no generated file may
look like it holds a secret, and none may contain any value from the repository's own configuration that the step 5
rules treat as secret. The self-containedness check (app.engine.inputs.selfcontained, Part K): no generated file may
refer to a platform document, a platform or absolute local path, a lifecycle step or the platform's vocabulary,
because the engine reads only the branch.

A detected change without engine-facing guidance is printed by `generate` and listed in the experiment's runbook
(`render.without_guidance`), never in the branch: the list names the platform's own ids.

`merge-addendum` puts the addendum into the engine's own `assessment.md` (after the engine writes it,
before planning), between markers, replacing an earlier merge.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from app.engine import paths
from app.engine.inputs import secrets, selfcontained
from app.engine.inputs import render as rendering
from app.engine.inputs.render import ADDENDUM_END, ADDENDUM_START, GENERATOR_VERSION

MANIFEST = f"{paths.PLATFORM_INPUTS_DIR}/inputs-manifest.json"


class SecretFound(Exception):
    def __init__(self, findings: list[dict]):
        self.findings = findings
        super().__init__("; ".join(f"{f['file']}: {f['check']} ({f['detail']})" for f in findings[:10]))


class NotSelfContained(Exception):
    def __init__(self, findings: list[dict]):
        self.findings = findings
        super().__init__("; ".join(f"{f['file']}:{f['line']}: {f['check']} ({f['match']})" for f in findings[:20])
                         + (f"; and {len(findings) - 20} more" if len(findings) > 20 else ""))


def manifest(model: dict, files: dict[str, str]) -> str:
    """What was generated and from which commit, with a sha256 per file. It is in the branch too, so it carries no
    platform name or id: which engagement and repository it belongs to is where the branch lives."""
    return json.dumps({
        "generator": {"version": GENERATOR_VERSION},
        "source": {"commit": model["repository"]["commit"]},
        "files": [{"path": p, "sha256": hashlib.sha256(t.encode("utf-8")).hexdigest()} for p, t in sorted(files.items())],
    }, indent=2, sort_keys=True) + "\n"


def build(model: dict, repository_root: Path | None) -> dict[str, str]:
    """{path: text} for every input including the manifest. Raises SecretFound or NotSelfContained; either way
    nothing has been written."""
    files = rendering.render(model)
    findings = secrets.check(files, repository_root)
    if findings:
        raise SecretFound(findings)
    files[MANIFEST] = manifest(model, files)
    loose = selfcontained.check(files, model.get("vocabulary"), repository_root)
    if loose:
        raise NotSelfContained(loose)
    return files


def write(files: dict[str, str], out: Path) -> None:
    """Each file with the line endings the repository's git settings expect in its working tree (Part M), so opening
    it never shows it as modified. The text, its manifest hash and the committed blob are the same whatever the
    ending: git stores text normalised."""
    from app.conversion.gitops import expected_eols

    eols = expected_eols(out, sorted(files))
    for rel, text in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline=eols[rel])


APPLIED_ITEMS = ("package-upgrade-safe", "package-provided-by-framework")


def without_applied(model: dict, applied: list[dict]) -> dict:
    """The model without what the platform already applied on the branch (36-COPILOT-ENHANCED-CONVERSION Part N):
    `applied` is [{item, project, package, to}] — a package bumped (package-upgrade-safe) or removed
    (package-provided-by-framework). A vulnerability goes too when its package was bumped to the version that fixes
    it. An item with no place left is dropped, and so is a package move with no project left."""
    from app.engine.verifier.packages import version_key

    done = {(a["item"], a["project"], a["package"].lower()) for a in applied}
    bumped = {(a["project"], a["package"].lower()): a.get("to") for a in applied if a["item"] == "package-upgrade-safe"}
    items = []
    for item in model["items"]:
        left = []
        for occ in item["occurrences"]:
            package = (occ.get("value") or "").split(" ", 1)[0].lower()
            if (item["id"], occ["project"], package) in done:
                continue
            fixed = re.search(r"; fixed in (\S+)$", occ.get("value") or "")
            to = bumped.get((occ["project"], package))
            if item["id"] == "package-vulnerable" and fixed and to and version_key(to) >= version_key(fixed.group(1)):
                continue
            left.append(occ)
        if left:
            items.append({**item, "occurrences": left})
    packages = [p for p in model.get("packages", [])
                if any((project, p["package"].lower()) not in bumped for project in p["projects"])]
    # The retarget, when the platform made it, and each framework delta it fixed at a file.
    if any(a["item"] == "target-framework-retarget" for a in applied):
        items = [i for i in items if i["id"] != "target-framework-retarget"]
    fixed = {(a["package"], a["project"]) for a in applied if a["item"] == "framework-delta"}
    deltas = []
    for d in model.get("deltas", []):
        sites = {f: c for f, c in d["sites"].items() if (d["id"], f) not in fixed}
        if sites:
            deltas.append({**d, "sites": sites})
    return {**model, "items": items, "packages": packages, "deltas": deltas}


def model_for(db, engagement_id: str, slug: str, applied: list[dict] | None = None):
    """(the collected model, less what was `applied`; the repository)."""
    from app import models
    from app.engine.inputs.collect import collect

    repository = (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=slug)
                  .filter(models.Repository.deleted_at.is_(None)).one())
    model = collect(db, repository)
    return (without_applied(model, applied) if applied else model), repository


def generate(db, engagement_id: str, slug: str, out: Path, missing: list | None = None,
             applied: list[dict] | None = None) -> dict[str, str]:
    """Writes the inputs into `out`. `missing`, when given, receives the changes without engine-facing guidance.
    `applied`: what the platform already applied on the branch, left out of the inputs (without_applied)."""
    model, repository = model_for(db, engagement_id, slug, applied)
    files = build(model, Path(repository.local_path))
    write(files, out)
    if missing is not None:
        missing.extend(rendering.without_guidance(model))
    return files


def merge_addendum(worktree: Path) -> Path:
    addendum = (worktree / paths.PLATFORM_INPUTS_DIR / "assessment-addendum.md").read_text(encoding="utf-8")
    found = sorted((worktree / paths.ENGINE_STATE_DIR).glob("*/assessment.md"))
    if len(found) != 1:
        raise LookupError(f"expected one .github/upgrades/<scenario>/assessment.md, found {len(found)}: "
                          "run this after the engine writes its assessment")
    target = found[0]
    text = target.read_text(encoding="utf-8")
    if ADDENDUM_START in text and ADDENDUM_END in text:
        head, _, rest = text.partition(ADDENDUM_START)
        _, _, tail = rest.partition(ADDENDUM_END)
        text = head.rstrip("\n") + "\n\n" + addendum.strip("\n") + tail
    else:
        text = text.rstrip("\n") + "\n\n" + addendum
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def _inputs_in(worktree: Path) -> dict[str, str]:
    files = {}
    for prefix in paths.GENERATED_INPUT_PATHS:
        target = worktree / prefix.rstrip("/")
        for f in ([target] if target.is_file() else sorted(target.rglob("*")) if target.is_dir() else []):
            if f.is_file():
                files[f.relative_to(worktree).as_posix()] = f.read_text(encoding="utf-8", errors="replace")
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.engine.inputs", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--engagement", required=True)
    g.add_argument("--repository", required=True, help="repository slug")
    g.add_argument("--out", required=True, type=Path, help="the worktree (or any folder) to write the inputs into")
    m = sub.add_parser("merge-addendum")
    m.add_argument("--worktree", required=True, type=Path)
    c = sub.add_parser("check")
    c.add_argument("--worktree", required=True, type=Path)
    c.add_argument("--repository-root", type=Path)
    args = parser.parse_args(argv)

    if args.command == "generate":
        from app.db import SessionLocal
        db = SessionLocal()
        missing: list[dict] = []
        try:
            files = generate(db, args.engagement, args.repository, args.out, missing)
        except SecretFound as err:
            print(f"Refused: a generated file would contain a secret value. Nothing was written. {err}", file=sys.stderr)
            return 1
        except NotSelfContained as err:
            print(f"Refused: a generated file is not self-contained. Nothing was written. {err}", file=sys.stderr)
            return 1
        finally:
            db.close()
        print(f"{len(files)} files written to {args.out}; no secret value found; every file self-contained")
        for rel in files:
            print(f"  {rel}")
        for m in missing:
            print(f"  without engine-facing guidance ({m['missing']}): {m['item']} / {m['resolution']}")
        return 0
    if args.command == "merge-addendum":
        try:
            target = merge_addendum(args.worktree)
        except (LookupError, FileNotFoundError) as err:
            print(str(err), file=sys.stderr)
            return 1
        print(f"addendum merged into {target}")
        return 0
    findings = secrets.check(_inputs_in(args.worktree), args.repository_root)
    for f in findings:
        print(f"{f['file']}: {f['check']} ({f['detail']})")
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0
