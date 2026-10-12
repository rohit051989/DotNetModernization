"""Calibrating impact-analysis against a hand analysis — the oracle.

An oracle (tests/fixtures/impact_oracle/*.yaml) lists, for one repository and
one scenario of decisions, the files a person found to change, create and
delete. This runs impact-analysis on the same repository from frozen inputs —
the upstream artifacts and integration edges captured beside the oracle, the
catalog's impact rules from the catalog export (catalog/items/) and the
oracle's decisions — and compares file by file.

impact-analysis's action per file is every work item's under its effective
resolution, structural and client (client from the frozen integration edges,
matched as dependency-and-context-map matches them), folded to the oracle's
vocabulary: delete if any work item deletes it, change if any updates or
rewrites it, new for a create, review if review is all it gets.

**Review is an abstention**, not a claim and not agreement: a rule that moves
files to review must not gain precision by it. So:

- recall: of the oracle's files, how many impact-analysis claims (changes,
  creates, deletes) — a file it only reviews is not found;
- precision: of the files impact-analysis claims, how many the oracle lists;
- review: the files impact-analysis only reviews, and their rate among every
  file it lists, held under a ceiling;
- agreement: the same folded action. A review-only file is neither agreement
  nor disagreement.

Every disagreement must carry a classification in the oracle — what is wrong
(`class`), why (`reason`) and the work expected to resolve it
(`resolved_by`: `reachability-analysis`, `supporting-item:<id>` or
`recipe:<id>` from 35-RECIPE-WCF-SERVICE-REST.md, or `out-of-scope`). The
report projects recall per tag, so each discovery pick's effect can be
measured as it lands; recall in scope leaves out the oracle's files tagged
out-of-scope.

Run from backend/ (the step must be published):

    python -m app.impact.calibration                       # the WCF oracle
    python -m app.impact.calibration --oracle <file.yaml>

tests/test_impact_calibration.py makes it a regression test.
"""

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.impact import client as client_impact

CODE = Path(__file__).resolve().parents[3]
FIXTURES = CODE / "backend" / "tests" / "fixtures" / "impact_oracle"
CATALOG_EXPORT = CODE / "catalog" / "items"
EXE = CODE / "steps" / "step-003-fingerprinting" / "publish" / "impact-analysis" / "ImpactAnalysis.Cli.exe"
DEFAULT_ORACLE = FIXTURES / "wcf-net10-rest.yaml"

CHANGE = {"update", "rewrite"}
CLASSES = ("rule_missing", "rule_wrong", "oracle_wrong", "scope", "vocabulary")
OUT_OF_SCOPE = "out-of-scope"


def valid_tag(tag: str | None) -> bool:
    return tag in ("reachability-analysis", OUT_OF_SCOPE) or bool(tag) and tag.split(":", 1)[0] in ("supporting-item", "recipe") \
        and len(tag.split(":", 1)) == 2 and bool(tag.split(":", 1)[1])


@dataclass
class Row:
    path: str
    oracle: str | None              # change, new, delete — or None: not in the oracle
    impact: str | None              # change, new, delete, review — or None: not listed
    detail: list[str] = field(default_factory=list)   # work item · resolution · action [· client]
    classification: dict | None = None

    @property
    def abstains(self) -> bool:
        """impact-analysis only asks for review of a file the oracle leaves alone."""
        return self.oracle is None and self.impact == "review"

    @property
    def agrees(self) -> bool:
        return self.oracle is not None and self.oracle == self.impact

    @property
    def disagrees(self) -> bool:
        return not self.agrees and not self.abstains


@dataclass
class Result:
    rows: list[Row]
    oracle_files: int
    found: int
    claimed: int
    claimed_in_oracle: int
    reviewed: int
    in_scope_files: int
    in_scope_found: int
    stale_classifications: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.found / self.oracle_files if self.oracle_files else 1.0

    @property
    def recall_in_scope(self) -> float:
        return self.in_scope_found / self.in_scope_files if self.in_scope_files else 1.0

    @property
    def precision(self) -> float:
        return self.claimed_in_oracle / self.claimed if self.claimed else 1.0

    @property
    def review_rate(self) -> float:
        listed = self.claimed + self.reviewed
        return self.reviewed / listed if listed else 0.0

    @property
    def agreeing(self) -> int:
        return sum(1 for r in self.rows if r.agrees)

    @property
    def disagreements(self) -> list[Row]:
        return [r for r in self.rows if r.disagrees]

    @property
    def unclassified(self) -> list[Row]:
        return [r for r in self.disagreements if r.classification is None]

    @property
    def untagged(self) -> list[Row]:
        return [r for r in self.disagreements if r.classification is not None and not valid_tag(r.classification.get("resolved_by"))]

    def projected_recall(self) -> dict[str, tuple[int, float]]:
        """Per resolved_by tag: the oracle files it would bring in, and recall if it did."""
        missing = defaultdict(int)
        for r in self.disagreements:
            if r.oracle is not None and r.impact in (None, "review") and r.classification:
                missing[r.classification.get("resolved_by")] += 1
        return {tag: (n, (self.found + n) / self.oracle_files) for tag, n in sorted(missing.items(), key=lambda kv: str(kv[0]))}


def _catalog(item_ids: set[str]) -> dict:
    """The live, active resolutions and their impact rules, from the export."""
    items = []
    for item_id in sorted(item_ids):
        path = CATALOG_EXPORT / f"{item_id}.yaml"
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        resolutions = [
            {"id": r["id"], "name": r["name"], "isDefault": bool(r.get("is_default")),
             "consumerImpact": r["consumer_impact"], "rules": r.get("impact_rules") or []}
            for r in doc.get("resolutions", [])
            if not r.get("deleted") and r.get("status", "active") == "active"
        ]
        items.append({"itemId": item_id, "name": doc["name"], "resolutions": resolutions})
    return {"items": items}


def _fold(actions: set[str]) -> str:
    if "delete" in actions:
        return "delete"
    if actions & CHANGE:
        return "change"
    if "create" in actions:
        return "new"
    return "review"


def run(oracle_path: Path = DEFAULT_ORACLE, transform_catalog=None) -> Result:
    """transform_catalog: an optional function over the catalog JSON before the
    run — the regression test uses it to show a weakened rule is caught."""
    oracle = yaml.safe_load(oracle_path.read_text(encoding="utf-8"))
    inputs = oracle_path.parent / oracle["inputs"]
    repo = CODE.parent / oracle["repository"]
    occurrences = json.loads((inputs / "item-occurrences.json").read_text(encoding="utf-8"))
    item_ids = {i["itemId"] for p in occurrences["projects"] for i in p["items"]}
    if not EXE.exists():
        raise RuntimeError(f"{EXE} not found: publish impact-analysis first "
                           "(dotnet publish src/Fingerprinting.Impact.Cli -c Release -o publish/impact-analysis)")

    catalog = _catalog(item_ids)
    if transform_catalog is not None:
        catalog = transform_catalog(catalog)
    with tempfile.TemporaryDirectory(prefix="impact-calibration-") as tmp:
        tmp = Path(tmp)
        (tmp / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        (tmp / "decisions.json").write_text(json.dumps(oracle.get("decisions") or {}), encoding="utf-8")
        args = [str(EXE), "--repo", str(repo), "--inventory", str(inputs / "solution-project-inventory.json"),
                "--occurrences", str(inputs / "item-occurrences.json"), "--entry-points", str(inputs / "entry-point-inventory.json"),
                "--test-coverage", str(inputs / "test-coverage.json"), "--outbound", str(inputs / "outbound-invocation-inventory.json"),
                "--catalog", str(tmp / "catalog.json"), "--decisions", str(tmp / "decisions.json"), "--out", str(tmp / "out")]
        done = subprocess.run(args, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"impact-analysis standalone run failed:\n{done.stderr}")
        artifact = json.loads((tmp / "out" / "impact-analysis.json").read_text(encoding="utf-8"))
    edges = json.loads((inputs / "integration-edges.json").read_text(encoding="utf-8"))
    rules = {r["id"]: r["rules"] for i in catalog["items"] for r in i["resolutions"]}

    # Every work item under its effective resolution: structural entries, then client.
    actions: dict[str, set[str]] = {}
    detail: dict[str, list[str]] = {}

    def add(path, action, what):
        actions.setdefault(path, set()).add(action)
        detail.setdefault(path, []).append(what)

    for work in artifact["workItems"]:
        resolution = next(r for r in work["resolutions"] if r["effective"])
        own = {e["filePath"] for e in resolution["entries"] if e["filePath"]}
        for e in resolution["entries"]:
            add(e["filePath"] or e["proposedPath"], e["action"], f"{work['itemId']} · {resolution['resolutionId']} · {e['action']}")
        rule = client_impact.client_rule(rules.get(resolution["resolutionId"]) or [])
        if rule is not None:
            for caller in client_impact.callers(own, edges):
                add(caller, rule["action"], f"{work['itemId']} · {resolution['resolutionId']} · {rule['action']} · client")

    impact = {path: _fold(a) for path, a in actions.items()}
    expected = {**{p: "change" for p in oracle.get("change") or []}, **{p: "new" for p in oracle.get("new") or []},
                **{p: "delete" for p in oracle.get("delete") or []}}
    classifications = oracle.get("classifications") or {}
    rows = []
    for path in sorted(set(expected) | set(impact)):
        row = Row(path, expected.get(path), impact.get(path), sorted(detail.get(path, [])))
        if row.disagrees:
            row.classification = classifications.get(path)
        rows.append(row)

    disagreeing = {r.path for r in rows if r.disagrees}
    claims = {p for p, a in impact.items() if a != "review"}
    in_scope = [p for p in expected if (classifications.get(p) or {}).get("resolved_by") != OUT_OF_SCOPE]
    return Result(
        rows=rows, oracle_files=len(expected), found=sum(1 for p in expected if p in claims),
        claimed=len(claims), claimed_in_oracle=sum(1 for p in claims if p in expected),
        reviewed=sum(1 for a in impact.values() if a == "review"),
        in_scope_files=len(in_scope), in_scope_found=sum(1 for p in in_scope if p in claims),
        stale_classifications=sorted(p for p in classifications if p not in disagreeing),
    )


def summary(result: Result) -> str:
    return (f"Recall {result.found}/{result.oracle_files} = {result.recall:.1%} · "
            f"in scope {result.in_scope_found}/{result.in_scope_files} = {result.recall_in_scope:.1%} · "
            f"precision {result.claimed_in_oracle}/{result.claimed} = {result.precision:.1%} · "
            f"review {result.reviewed} file(s), {result.review_rate:.1%} of those listed · "
            f"{result.agreeing} agree, {len(result.disagreements)} disagree · "
            f"{len(result.unclassified)} unclassified, {len(result.untagged)} untagged")


def report(result: Result) -> str:
    lines = ["| File | Oracle | impact-analysis | Agree | Class | Resolved by | Reason |", "|---|---|---|---|---|---|---|"]
    for r in result.rows:
        c = r.classification or {}
        verdict = "yes" if r.agrees else "abstains" if r.abstains else "**no**"
        lines.append(f"| `{r.path}` | {r.oracle or '—'} | {r.impact or '—'} | {verdict} | "
                     f"{c.get('class', '' if not r.disagrees else '**unclassified**')} | {c.get('resolved_by', '')} | {c.get('reason', '')} |")
    lines += ["", "| Resolved by | Oracle files it would bring in | Recall if it did |", "|---|---|---|"]
    lines += [f"| {tag} | {n} | {recall:.1%} |" for tag, (n, recall) in result.projected_recall().items()]
    stale = result.stale_classifications
    lines += ["", *([f"Classified but no longer disagreeing (remove from the oracle): {', '.join(stale)}", ""] if stale else []),
              summary(result)]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare impact-analysis with a hand analysis.")
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    print(report(run(parser.parse_args().oracle)))


if __name__ == "__main__":
    main()
