"""The engine input generator (36-COPILOT-ENHANCED-CONVERSION Part D).

    python -m app.engine.inputs generate --engagement test-client-a --repository eshoponweb --out <worktree>
    python -m app.engine.inputs merge-addendum --worktree <worktree>
    python -m app.engine.inputs check --worktree <worktree> [--repository-root <checkout>]

`generate` produces, for one repository and engagement, everything the engine reads: one custom upgrade
instruction per detected item and its resolution, the adapted plugin skills, the global instructions,
the assessment addendum and the decision sheet, plus `.github/platform-inputs/inputs-manifest.json`
with a sha256 per file. Generated, never hand-edited: change the source data and regenerate.

Nothing is written unless the secret check passes (app.engine.inputs.secrets): no generated file may
look like it holds a secret, and none may contain any value from the repository's own configuration
that the step 5 rules treat as secret.

`merge-addendum` puts the addendum into the engine's own `assessment.md` (after the engine writes it,
before planning), between markers, replacing an earlier merge.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.engine import paths
from app.engine.inputs import secrets
from app.engine.inputs import render as rendering
from app.engine.inputs.render import ADDENDUM_END, ADDENDUM_START, GENERATOR_VERSION

MANIFEST = f"{paths.PLATFORM_INPUTS_DIR}/inputs-manifest.json"


class SecretFound(Exception):
    def __init__(self, findings: list[dict]):
        self.findings = findings
        super().__init__("; ".join(f"{f['file']}: {f['check']} ({f['detail']})" for f in findings[:10]))


def manifest(model: dict, files: dict[str, str]) -> str:
    return json.dumps({
        "generator": {"name": "app.engine.inputs", "version": GENERATOR_VERSION},
        "source": {"engagement": model["engagement"]["id"], "repository": model["repository"]["slug"],
                   "commit": model["repository"]["commit"]},
        "files": [{"path": p, "sha256": hashlib.sha256(t.encode("utf-8")).hexdigest()} for p, t in sorted(files.items())],
    }, indent=2, sort_keys=True) + "\n"


def build(model: dict, repository_root: Path | None) -> dict[str, str]:
    """{path: text} for every input including the manifest. Raises SecretFound."""
    files = rendering.render(model)
    findings = secrets.check(files, repository_root)
    if findings:
        raise SecretFound(findings)
    files[MANIFEST] = manifest(model, files)
    return files


def write(files: dict[str, str], out: Path) -> None:
    for rel, text in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


def generate(db, engagement_id: str, slug: str, out: Path) -> dict[str, str]:
    from app import models
    from app.engine.inputs.collect import collect

    repository = (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=slug)
                  .filter(models.Repository.deleted_at.is_(None)).one())
    files = build(collect(db, repository), Path(repository.local_path))
    write(files, out)
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
        try:
            files = generate(db, args.engagement, args.repository, args.out)
        except SecretFound as err:
            print(f"Refused: a generated file would contain a secret value. Nothing was written. {err}", file=sys.stderr)
            return 1
        finally:
            db.close()
        print(f"{len(files)} files written to {args.out}; no secret value found")
        for rel in files:
            print(f"  {rel}")
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
