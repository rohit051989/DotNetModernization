"""Estate coverage and the re-review trigger —
26-STEP-005-PATTERN-DISCOVERY.md A5 and Part D "Decision context and
re-review".
"""


def build_coverage(repositories_in_engagement: int, repositories_included: int) -> dict:
    """A5. Step 5 runs over whatever has classification results and is
    honest in the artifact about what it saw.

    `partialEstate: true` is not a warning state, it is the expected one.
    It is recorded so a human at step 6 — and the re-review trigger below
    — can tell how much of the estate a cluster was measured against: a
    three-member cluster at coverage 0.10 and one at 1.00 are different
    pieces of evidence and the artifact must not flatten that.
    """
    pending = repositories_in_engagement - repositories_included
    ratio = round(repositories_included / repositories_in_engagement, 3) if repositories_in_engagement else 0.0
    return {
        "repositories_in_engagement": repositories_in_engagement,
        "repositories_included": repositories_included,
        "repositories_pending": pending,
        "coverage_ratio": ratio,
        "partial_estate": pending > 0,
    }


def rereview_decision(existing: dict | None, member_count: int, coverage_ratio: float, min_rereview_members: int) -> tuple[bool, str | None]:
    """Whether a previously-resolved cluster's evidence has grown enough
    to be worth another look.

        needs_rereview = member_count > max(decided_at_member_count * 3,
                                            min_rereview_members)

    The floor exists because the multiplier alone is useless at the
    bottom of the range: a singleton rejected at member_count 1 would
    trip re-review at 4 members, which for a rejected one-off is noise.
    The multiplier handles clusters that were already substantial; the
    floor handles the ones that were not.

    **This is not automatic reversal and must never become one.** The
    human decided correctly on the information available; nothing about
    that decision has become wrong. What changed is the information, and
    saying so is the whole of this function's job. Clearing the flag is
    step 6's action; re-deciding rewrites decided_at_* so the next
    trigger measures from the new baseline.
    """
    if existing is None:
        return False, None
    # A cluster still at `candidate` was never decided, so there is
    # nothing to revisit.
    if existing["status"] == "candidate":
        return False, None
    decided_members = existing.get("decided_at_member_count")
    if decided_members is None:
        return False, None

    if member_count <= max(decided_members * 3, min_rereview_members):
        # Preserve a flag an earlier run raised and step 6 has not yet
        # cleared: shrinking back under the threshold does not un-ask the
        # question, and silently dropping it would lose a queued review.
        return bool(existing.get("needs_rereview")), existing.get("rereview_reason")

    decided_coverage = existing.get("decided_at_coverage")
    coverage_then = f"{float(decided_coverage):.2f}" if decided_coverage is not None else "unknown"
    return True, (
        f"{existing['status']} at {decided_members} member(s), coverage {coverage_then}; "
        f"now {member_count} member(s) at coverage {coverage_ratio:.2f}."
    )
