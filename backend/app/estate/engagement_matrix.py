"""A client's WCF client matrix probe evidence and confirmations, with its
engagement — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10, the probe
evidence boundary.

The platform ships to each client as code; the matrices ship with it and hold
platform knowledge only (entries confirmed on the platform's own sample
evidence). A probe run in the client's environment, and a confirmation a person
makes there on that evidence, are the client's data. They live in the
database with the engagement, and the SOAP report reads the shipped matrix
with the engagement's confirmations and probes applied on top, as engagement
decisions overlay the shipped catalog. Nothing here ever writes a matrix file.

A confirmation names its entries (the decision, as for the shipped matrices:
the tool never extends it) and the evidence it rests on. When that evidence
is gone or no longer matches its hash, the entry shows "evidence missing", and
the engagement's report is not ready for the client.
"""

import datetime
import hashlib
import json

from sqlalchemy.orm import Session

from app import models
from app.estate import wcf_matrix


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_evidence(db: Session, engagement_id: str, evidence_id: str, document: dict, *, scenario: str, where: str,
                    outcome: str, matrix_entries: list[str], probed_on: datetime.date, error_type: str | None = None,
                    attribution: str | None = None, covers: dict | None = None, control_of: str | None = None) -> str:
    """Store one probe's evidence with the engagement; returns its sha256."""
    content = json.dumps({**document, "source": {"engagement": engagement_id}}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    sha = _sha(content)
    db.add(models.EngagementProbeEvidence(
        engagement_id=engagement_id, id=evidence_id, scenario=scenario, where=where, outcome=outcome, error_type=error_type,
        attribution=attribution, control_of=control_of, covers=covers, matrix_entries=matrix_entries, content=content,
        sha256=sha, probed_on=probed_on))
    db.flush()
    return sha


def evidence_intact(row: models.EngagementProbeEvidence | None) -> bool:
    return row is not None and row.content is not None and _sha(row.content) == row.sha256


def _kind(entry_id: str) -> str:
    return "platform" if "/linux/" in entry_id else "support"


def record_decision(db: Session, engagement_id: str, decision: dict) -> list[str]:
    """Confirm, for this engagement only, exactly the shipped matrix entries a
    person's decision names, each on the engagement's evidence bearing on it.

    decision: id, by, on (date), instruction (verbatim), entries (ids),
    evidence ({entry id: [evidence ids]}), notes ({entry id: text}, optional)."""
    missing = [f for f in ("id", "by", "on", "instruction", "entries", "evidence") if not decision.get(f)]
    if missing:
        raise ValueError(f"decision {decision.get('id')!r} lacks {missing}")
    named = list(decision["entries"])
    shipped = {kind: wcf_matrix.entries(kind) for kind in wcf_matrix.KINDS}
    unknown = [e for e in named if e not in shipped[_kind(e)]]
    if unknown:
        raise ValueError(f"decision {decision['id']} names entries the shipped matrices do not have: {unknown}")
    stray = sorted(set(decision["evidence"]) - set(named))
    if stray:
        raise ValueError(f"decision {decision['id']} gives evidence for entries it does not name: {stray}")
    for entry_id in named:
        ids = decision["evidence"].get(entry_id) or []
        if not ids:
            raise ValueError(f"{entry_id}: a client confirmation rests on the engagement's evidence, and none is given")
        for evidence_id in ids:
            row = db.get(models.EngagementProbeEvidence, (engagement_id, evidence_id))
            if not evidence_intact(row):
                raise ValueError(f"{entry_id}: evidence {evidence_id} is missing or no longer matches its hash")
            if entry_id not in row.matrix_entries:
                raise ValueError(f"{entry_id}: evidence {evidence_id} does not bear on it")
    on = decision["on"] if isinstance(decision["on"], datetime.date) else datetime.date.fromisoformat(decision["on"])
    for entry_id in named:
        db.add(models.EngagementMatrixConfirmation(
            engagement_id=engagement_id, matrix_kind=_kind(entry_id), entry_id=entry_id, decision_id=decision["id"],
            decided_by=decision["by"], decided_on=on, instruction=decision["instruction"], named_entries=named,
            evidence_ids=list(decision["evidence"][entry_id]), note=(decision.get("notes") or {}).get(entry_id)))
    db.flush()
    return named


def revert(db: Session, engagement_id: str, entry_id: str, by: str, reason: str) -> None:
    """The live confirmation of an entry back to none, kept with who and why."""
    row = (db.query(models.EngagementMatrixConfirmation)
           .filter_by(engagement_id=engagement_id, entry_id=entry_id, reverted_at=None).one_or_none())
    if row is None:
        raise ValueError(f"{entry_id} has no confirmation in engagement {engagement_id}")
    row.reverted_at = datetime.datetime.now(datetime.timezone.utc)
    row.reverted_by, row.reverted_reason = by, reason
    db.flush()


def overlay(db: Session, engagement_id: str) -> dict:
    """The engagement's confirmations and probes, by shipped entry id."""
    evidence = {row.id: row for row in db.query(models.EngagementProbeEvidence).filter_by(engagement_id=engagement_id)}
    probes: dict[str, list[dict]] = {}
    for row in sorted(evidence.values(), key=lambda r: (r.probed_on, r.id)):
        if row.control_of:
            continue
        record = {
            "probedOn": row.probed_on.isoformat(), "scenario": row.scenario, "where": row.where, "outcome": row.outcome,
            "errorType": row.error_type, "covers": row.covers, "attribution": row.attribution,
            "source": {"engagement": engagement_id}, "evidenceRef": {"engagement": engagement_id, "id": row.id},
            "evidenceMissing": not evidence_intact(row),
            "controls": [{"where": c.where, "outcome": c.outcome, "errorType": c.error_type, "covers": c.covers,
                          "evidenceRef": {"engagement": engagement_id, "id": c.id}, "evidenceMissing": not evidence_intact(c)}
                         for c in evidence.values() if c.control_of == row.id],
        }
        for entry_id in row.matrix_entries:
            probes.setdefault(entry_id, []).append(record)
    confirmations = {}
    for row in db.query(models.EngagementMatrixConfirmation).filter_by(engagement_id=engagement_id, reverted_at=None):
        missing = [i for i in row.evidence_ids if not evidence_intact(evidence.get(i))]
        confirmations[row.entry_id] = {
            "status": "confirmed", "by": row.decided_by, "on": row.decided_on.isoformat(), "decision": row.decision_id,
            "note": row.note, "source": {"engagement": engagement_id}, "evidenceRefs": row.evidence_ids, "evidenceMissing": missing,
        }
    return {"engagement": engagement_id, "confirmations": confirmations, "probes": probes}


def apply(kind: str, entries: dict[str, dict], applied: dict | None) -> dict[str, dict]:
    """The shipped entries with an engagement's overlay on top: its probes
    added to each entry's, and its confirmation where the shipped matrix has
    none. A shipped confirmation is platform knowledge and stays."""
    if not applied:
        return entries
    result = {}
    for entry_id, entry in entries.items():
        extra = applied["probes"].get(entry_id)
        confirmation = applied["confirmations"].get(entry_id)
        if extra or confirmation:
            entry = {**entry, "probes": [*entry.get("probes", []), *(extra or [])]}
            if confirmation and (entry.get("confirmation") or {}).get("status") != "confirmed":
                entry["confirmation"] = confirmation
        result[entry_id] = entry
    return result


def evidence_missing(entry: dict) -> bool:
    """A confirmation, or a probe, whose engagement evidence is gone or changed."""
    confirmation = entry.get("confirmation") or {}
    return bool(confirmation.get("evidenceMissing")) or any(p.get("evidenceMissing") for p in entry.get("probes", []))
