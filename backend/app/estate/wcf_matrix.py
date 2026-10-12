"""The two WCF client matrices, as data the estate reads — versioned, reviewed
files in steps/step-003-fingerprinting/schemas/, the same ones
outbound-invocation-inventory judges SOAP calls by
(29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10):

- ``support``: wcf-client-support-*.json, the runtime matrix — does the
  target's WCF client support a binding, security mode and credential type;
- ``platform``: wcf-client-platform-*.json, the platform matrix — does it
  work on Linux, and when not, what must change and who changes it.

Read fresh whenever a file changes, so a person's confirmation or a probe
result recorded in the file counts at once.
"""

import json
from functools import lru_cache
from pathlib import Path

MATRIX_DIR = Path(__file__).resolve().parents[3] / "steps" / "step-003-fingerprinting" / "schemas"
KINDS = ("support", "platform")


def _version(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in path.stem.rsplit("-", 1)[1].split("."))


def path_of(kind: str, version: str | None = None) -> Path | None:
    """The matrix file: the given version, else the newest."""
    files = sorted(MATRIX_DIR.glob(f"wcf-client-{kind}-*.json"), key=_version)
    if version is not None:
        files = [p for p in files if p.stem.endswith(f"-{version}")]
    return files[-1] if files else None


@lru_cache(maxsize=16)
def _read(path: str, mtime_ns: int) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(kind: str, version: str | None = None) -> dict | None:
    path = path_of(kind, version)
    return _read(str(path), path.stat().st_mtime_ns) if path else None


def entries(kind: str, version: str | None = None) -> dict[str, dict]:
    """Entry id -> entry."""
    return {e["id"]: e for e in (load(kind, version) or {}).get("entries", [])}


# What a probe's outcome would contradict, in each matrix's own words.
WORKS = {"support": ("supported", "supported_with_caveat"), "platform": ("compatible",)}
DOES_NOT_WORK = {"support": ("unsupported",), "platform": ("incompatible",)}


def probe_contradictions(kind: str, entry: dict) -> list[str]:
    """Where an entry's latest probe per scenario disagrees with its verdict:
    a failure where the entry says the call works, a pass where it says it
    does not. A runtime entry is not contradicted by a Linux failure that
    passed on Windows with the same client (attribution ``platform``): that
    failure is the platform matrix's to answer. The verdict stays as a person
    wrote it; the report stays a draft until a person revises or confirms the
    entry."""
    latest: dict = {}
    for probe in entry.get("probes", []):
        if probe.get("outcome") in ("passed", "failed"):
            latest[probe.get("scenario")] = probe
    verdict = entry.get("verdict")
    reasons = []
    for scenario, probe in sorted(latest.items(), key=lambda item: str(item[0])):
        if (probe["outcome"] == "failed" and verdict in WORKS[kind]
                and not (kind == "support" and probe.get("attribution") == "platform")):
            reasons.append(f"probe {scenario} ({probe.get('probedOn')}) failed: {probe.get('summary')}; the entry says {verdict}")
        elif probe["outcome"] == "passed" and verdict in DOES_NOT_WORK[kind]:
            reasons.append(f"probe {scenario} ({probe.get('probedOn')}) passed; the entry says {verdict}")
    return reasons


def version_key(version: str) -> tuple[int, ...]:
    """8.1.2, 8.1.2+a47960f, 10.0.0-preview.1 -> comparable numbers (the release part)."""
    core = version.split("+")[0].split("-")[0]
    return tuple(int(n) for n in core.split(".") if n.isdigit())


def evidence_covers(entry: dict) -> dict | None:
    """What an entry's probe evidence covers: the newest WCF client package it
    ran against, and the runtimes. None when no probe has run (not_probed is
    no evidence)."""
    covered = [p["covers"] for p in entry.get("probes", [])
               if p.get("outcome") in ("passed", "failed") and (p.get("covers") or {}).get("wcfClient")]
    if not covered:
        return None
    newest = max(covered, key=lambda c: version_key(c["wcfClient"]))
    return {"wcfClient": newest["wcfClient"], "runtimes": sorted({c["runtime"] for c in covered if c.get("runtime")}),
            "probes": len(covered)}


def evidence_predates(entry: dict, target_wcf_client: str | None) -> bool:
    """The entry's evidence covers an older WCF client than the one targeted."""
    covered = evidence_covers(entry)
    return bool(covered and target_wcf_client and version_key(covered["wcfClient"]) < version_key(target_wcf_client))


def target_wcf_client(matrix: dict | None, target_framework: str | None) -> str | None:
    """The WCF client version a matrix records for a target framework."""
    return ((matrix or {}).get("targets", {}).get(target_framework or "", {}) or {}).get("wcfClientVersion")


# ---------- confirmations: a person's decision, never extended by the tool ----------
#
# A confirmation records a person's decision about named entries. It is written
# only by record_decision, and only for the entry ids the decision names; the
# decision itself — who, when, and the instruction that authorised it, verbatim —
# is kept in the matrix file's "decisions". confirmation_violations finds any
# confirmed entry no recorded decision names.

DECISION_FIELDS = ("id", "by", "on", "instruction", "entries")


def _evidence_files(entry: dict) -> list[str]:
    return sorted({x["evidence"] for p in entry.get("probes", []) for x in [p, *p.get("controls", [])] if x.get("evidence")})


def _write(path: Path, matrix: dict) -> None:
    path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def record_decision(decision: dict) -> list[str]:
    """Confirm exactly the entries a person's decision names, by id, in the
    newest matrices, and record the decision beside them. An id no matrix has
    is refused; nothing is confirmed that the decision does not name."""
    missing = [f for f in DECISION_FIELDS if not decision.get(f)]
    if missing:
        raise ValueError(f"decision {decision.get('id')!r} lacks {missing}: a confirmation needs a person, a date, "
                         f"the instruction, and the entries it names")
    named = list(decision["entries"])
    files = {kind: path_of(kind) for kind in KINDS}
    matrices = {kind: json.loads(path.read_text(encoding="utf-8")) for kind, path in files.items() if path}
    ids = {kind: {e["id"] for e in m["entries"]} for kind, m in matrices.items()}
    unknown = [i for i in named if not any(i in kind_ids for kind_ids in ids.values())]
    if unknown:
        raise ValueError(f"decision {decision['id']} names entries no matrix has: {unknown}")
    confirmed = []
    for kind, matrix in matrices.items():
        mine = [i for i in named if i in ids[kind]]
        if not mine:
            continue
        recorded = {d["id"]: d for d in matrix.setdefault("decisions", [])}
        if decision["id"] in recorded and recorded[decision["id"]] != decision:
            raise ValueError(f"decision {decision['id']} is already recorded differently in {files[kind].name}")
        if decision["id"] not in recorded:
            matrix["decisions"].append(decision)
        for entry in matrix["entries"]:
            if entry["id"] in mine:
                entry["confirmation"] = {
                    "status": "confirmed", "by": decision["by"], "on": decision["on"], "decision": decision["id"],
                    "note": (decision.get("notes") or {}).get(entry["id"]) or decision.get("note"),
                    "evidence": _evidence_files(entry),
                }
                confirmed.append(entry["id"])
        _write(files[kind], matrix)
    return confirmed


def revert_confirmation(entry_id: str, on: str, reason: str) -> None:
    """Back to unconfirmed, keeping what was reverted and why."""
    for kind in KINDS:
        path = path_of(kind)
        matrix = json.loads(path.read_text(encoding="utf-8"))
        for entry in matrix["entries"]:
            if entry["id"] == entry_id and entry["confirmation"].get("status") == "confirmed":
                was = {k: entry["confirmation"].get(k) for k in ("by", "on", "decision", "note")}
                entry["confirmation"] = {"status": "unconfirmed", "by": None, "on": None, "note": None,
                                         "reverted": {"on": on, "reason": reason, "was": was}}
                _write(path, matrix)
                return
    raise ValueError(f"{entry_id} is not a confirmed entry")


def confirmation_violations(matrix: dict) -> list[str]:
    """Confirmed entries no recorded decision authorises: no decision, a
    decision the file does not hold, one that does not name the entry, or a
    different person or date."""
    decisions = {d["id"]: d for d in matrix.get("decisions", [])}
    problems = []
    for entry in matrix.get("entries", []):
        confirmation = entry.get("confirmation") or {}
        if confirmation.get("status") != "confirmed":
            continue
        decision = decisions.get(confirmation.get("decision") or "")
        if decision is None:
            problems.append(f"{entry['id']}: confirmed with no recorded decision")
        elif entry["id"] not in decision.get("entries", []):
            problems.append(f"{entry['id']}: decision {decision['id']} does not name it")
        elif (decision.get("by"), decision.get("on")) != (confirmation.get("by"), confirmation.get("on")):
            problems.append(f"{entry['id']}: confirmed as {confirmation.get('by')} on {confirmation.get('on')}, "
                            f"but decision {decision['id']} is {decision.get('by')} on {decision.get('on')}")
    return problems


UNDER_REVIEW = "under_review"


def live_verdict(kind: str, verdict: str | None, entry_id: str | None, target_wcf_client: str | None) -> dict:
    """One verdict as a scan recorded it, with what is live in the newest
    matrix: the entry's confirmation and the decision behind it, the probe
    evidence and what it covers, and — when a probe contradicts the entry —
    UNDER_REVIEW in place of the verdict, the unrevised one kept apart."""
    entry = entries(kind).get(entry_id or "")
    confirmation = (entry or {}).get("confirmation") or {}
    contradictions = probe_contradictions(kind, entry) if entry else []
    return {
        "verdict": UNDER_REVIEW if contradictions else verdict,
        "unrevisedVerdict": verdict if contradictions else None,
        "matrixEntry": entry_id,
        "matrixConfirmed": confirmation.get("status") == "confirmed" if entry else None,
        "confirmedBy": confirmation.get("by"),
        "confirmedOn": confirmation.get("on"),
        "decision": confirmation.get("decision"),
        "probeContradictions": contradictions,
        "evidenceCovers": evidence_covers(entry) if entry else None,
        "evidencePredatesTarget": evidence_predates(entry, target_wcf_client) if entry else False,
    }
