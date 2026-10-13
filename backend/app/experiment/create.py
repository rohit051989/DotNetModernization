"""Create an experiment folder and its experiment.yaml (36-COPILOT-ENHANCED-CONVERSION Part F). No AI involved: a
person supplies every value on the command line and the platform fills the template
(templates/experiment.yaml.tmpl).

    python -m app.experiment.create --engagement test-client-a --repository accountsapi-net10 --name accountsapi-net10
        --baseline e89bc6a --title "..." --goal "..." --generation 2
        --canary-file src/... --canary-find "..." --canary-replace "..." --canary-why "..."
        [--baseline-plan 90bc71e0] [--arm3-ref conversion/90bc71e0 --arm3-scope "version upgrade only"]
        [--sibling-link EnterprisePackages] [--sequence-note "..."] [--model "..."] [--runs 2] [--force]

The folder is <RUNS_DIR>/<engagement>/experiments/<name>/ (app.experiment.location). The command is recorded in the
file's header, so the file can always be produced again the same way.
"""
import argparse
import json
import sys
from pathlib import Path
from string import Template

import yaml

from app.experiment import instrument, lookups
from app.experiment.location import experiment_dir

TEMPLATE = Path(__file__).resolve().parent / "templates" / "experiment.yaml.tmpl"


def _powershell(argument: str) -> str:
    """One argument as Windows PowerShell 5.1 passes it to python unchanged: single-quoted when it needs quoting,
    a single quote doubled, and a double quote written \\" (5.1 strips a bare one from a native argument)."""
    if argument and all(c.isalnum() or c in "-_./:\\" for c in argument):
        return argument
    return "'" + argument.replace("'", "''").replace('"', '\\"') + "'"


def _scalar(value) -> str:
    """A YAML scalar: JSON is valid YAML, and quotes any string safely."""
    return json.dumps(value, ensure_ascii=False)


def render(args: argparse.Namespace, command: str, platform_commit: str, lookups_sha256: str) -> str:
    arm3 = ""
    if args.arm3_ref:
        arm3 = (f"  - arm: 3\n    name: Platform codemods\n    ref: {_scalar(args.arm3_ref)}\n"
                f"    scope: {_scalar(args.arm3_scope or 'version upgrade only')}\n")
    text = Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        command=command, name=_scalar(args.name), title=_scalar(args.title), engagement=_scalar(args.engagement),
        repository=_scalar(args.repository), baseline_commit=_scalar(args.baseline), platform_commit=_scalar(platform_commit),
        package_lookups_sha256=_scalar(lookups_sha256),
        baseline_plan=_scalar(args.baseline_plan), generation=args.generation,
        sequence_note=_scalar(args.sequence_note), goal=_scalar(args.goal), model=_scalar(args.model),
        sibling_links=_scalar(args.sibling_link or []), runs=args.runs, arm3=arm3,
        canary_file=_scalar(args.canary_file), canary_find=_scalar(args.canary_find),
        canary_replace=_scalar(args.canary_replace), canary_why=_scalar(args.canary_why),
        max_minutes=args.max_minutes, max_attempts=args.max_attempts)
    yaml.safe_load(text)                  # it must parse
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.experiment.create", description=__doc__.split("\n\n")[0])
    parser.add_argument("--engagement", required=True)
    parser.add_argument("--repository", required=True, help="repository slug")
    parser.add_argument("--name", required=True, help="the experiment's folder name")
    parser.add_argument("--baseline", required=True, help="the baseline commit")
    parser.add_argument("--title", required=True)
    parser.add_argument("--goal", default="Upgrade this solution to .NET 10 and make the application ready to run on OpenShift.")
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--sequence-note")
    parser.add_argument("--baseline-plan")
    parser.add_argument("--arm3-ref")
    parser.add_argument("--arm3-scope")
    parser.add_argument("--sibling-link", action="append")
    parser.add_argument("--model")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--canary-file", required=True)
    parser.add_argument("--canary-find", required=True)
    parser.add_argument("--canary-replace", required=True)
    parser.add_argument("--canary-why", required=True)
    parser.add_argument("--max-minutes", type=int, default=240)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="replace an existing experiment.yaml")
    parser.add_argument("--out", type=Path, help="write experiment.yaml into this folder instead (to compare a "
                                                 "regenerated file with the one in use)")
    args = parser.parse_args(argv)

    try:
        platform_commit = instrument.require_clean()
    except RuntimeError as error:
        print(f"not created: {error}", file=sys.stderr)
        return 1
    # The frozen package lookups are in the experiment's own folder, even when writing elsewhere with --out.
    snapshot = experiment_dir(args.engagement, args.name) / lookups.FILE
    if not snapshot.exists():
        print(f"not created: {snapshot} is missing. Freeze the package lookups first: python -m app.experiment.lookups "
              f"freeze --engagement {args.engagement} --repository {args.repository} --name {args.name}", file=sys.stderr)
        return 1
    lookups_sha256 = lookups.sha256(snapshot.read_bytes())
    folder = args.out.resolve() if args.out else experiment_dir(args.engagement, args.name)
    target = folder / "experiment.yaml"
    if target.exists() and not args.force:
        print(f"{target} exists: pass --force to replace it", file=sys.stderr)
        return 1
    # The recorded command is the one that makes the file in use: --force and --out are not part of it.
    given = argv if argv is not None else sys.argv[1:]
    shown = [a for i, a in enumerate(given) if a not in ("--force", "--out") and (i == 0 or given[i - 1] != "--out")]
    command = "python -m app.experiment.create " + " ".join(_powershell(a) for a in shown)
    folder.mkdir(parents=True, exist_ok=True)
    target.write_text(render(args, command, platform_commit, lookups_sha256), encoding="utf-8", newline="\n")
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
