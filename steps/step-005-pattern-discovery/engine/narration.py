"""Cluster narration — 26-STEP-005-PATTERN-DISCOVERY.md Part E.

Separate, optional, LLM-produced. Invoked via Claude Code headless with
structured output.

The five constraints in Part E are hard requirements, and each one is
enforced here rather than merely requested of the model:

1. **Never sees, and never proposes, a classification.** The prompt is
   built from the signature, facets, member paths and proximity matches
   only. `_redact()` is what guarantees this: nothing about pattern
   matching, catalog status, target states or step 6 actions reaches the
   model, and `similar_patterns` is deliberately excluded from the
   payload it sees (see `_cluster_payload`).

2. **Output is advisory.** Nothing here writes to the clusters artifact,
   the clusters table, or `patterns`. Narration lands in its own artifact
   keyed by cluster_id, for step 6's UI to show as an editable
   suggestion.

3. **Failure warns rather than fails the step.** Every failure mode —
   CLI missing, non-zero exit, timeout, unparseable output, a cluster the
   model skipped, a response that fails validation — degrades to
   `naming_source: "none"` for the affected clusters and a warning. There
   is no raise path out of `narrate()`.

4. **No source code.** The payload is assembled field by field from
   values the caller already holds; no file is ever read, and project
   paths are sent as paths, never as content.

5. **`enable_narration: false` means fully deterministic.** The caller
   skips this module entirely; it has no other effect on the run.
"""

import json
import re
import shutil
import subprocess

ARTIFACT_TYPE = "pattern-candidate-narration"
ARTIFACT_VERSION = "1.0.0"

_CONFIDENCE_VALUES = ("low", "medium", "high")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_SYSTEM_PROMPT = """You name structural shapes found in .NET codebases.

You are given a cluster: a set of static-analysis SIGNAL NAMES that a group of
projects all share, some project metadata facets, and a sample of project file
paths. Your job is to give that shape a short human-readable name and
description, so a person reviewing a list of shapes can tell them apart.

Rules:
- Describe ONLY the shape in front of you, from the signals and facets given.
- Do NOT say whether this is a good or bad pattern, whether it should become a
  catalog pattern, how it should be modernized, what it should be migrated to,
  or what anyone should do about it. You are naming, not deciding, not advising.
- Do NOT invent evidence. If the signals are thin, say so in the description and
  set confidence "low".
- suggested_name: a noun phrase, at most 8 words. Sentence case.
- suggested_description: 1-2 sentences describing what the signals indicate,
  in plain English.
- suggested_pattern_id: a lowercase kebab-case slug, at most 6 words.
- confidence: "low", "medium" or "high" — how well the signals pin the shape.

Return ONLY a JSON array, one object per cluster, no prose and no code fence:
[{"cluster_id": "...", "suggested_name": "...", "suggested_description": "...",
  "suggested_pattern_id": "...", "confidence": "..."}]"""


def _cluster_payload(cluster: dict, max_member_paths: int) -> dict:
    """What the model is allowed to see, built field by field.

    An allowlist, not a denylist: a new field added to the cluster dict
    elsewhere in this step does not silently start being sent to the
    model. That is the difference between this being a constraint and
    being a convention.

    `similar_patterns` is present in the cluster and deliberately NOT
    sent. Part E's first constraint is that narration never sees a
    classification — and "this shape is 0.62 similar to
    console-batch-job" is exactly that. Feeding it in would also bias the
    naming toward the existing catalog, which defeats the point of
    discovery: the cluster exists precisely because the catalog did not
    cover it.
    """
    return {
        "cluster_id": cluster["cluster_id"],
        "facets": dict(cluster["canonical_signature"]["facets"]),
        "signals": list(cluster["canonical_signature"]["signals"]),
        "member_count": cluster["member_count"],
        "repository_count": cluster["repository_count"],
        # Paths only — names of files on disk, never their contents.
        "sample_project_paths": [m["project_path"] for m in cluster["members"][:max_member_paths]],
    }


def _extract_json_array(text: str) -> list | None:
    """The CLI may wrap the JSON in a code fence or a sentence despite the
    instruction not to. Recover what we can rather than discarding a
    usable response, but never guess at malformed JSON."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _redact(entry: dict, cluster_id: str, model_version: str) -> tuple[dict | None, str | None]:
    """Validate and normalise one model response.

    Everything the model returns is untrusted input, so each field is
    checked and coerced rather than copied through. A response that fails
    validation is dropped to `naming_source: "none"` for that cluster —
    the step still succeeds, and step 6 shows the signature instead,
    which is exactly what it does when narration is disabled.
    """
    name = entry.get("suggested_name")
    description = entry.get("suggested_description")
    if not isinstance(name, str) or not name.strip():
        return None, "suggested_name missing or not a string"
    if not isinstance(description, str) or not description.strip():
        return None, "suggested_description missing or not a string"

    confidence = entry.get("confidence")
    if confidence not in _CONFIDENCE_VALUES:
        confidence = "low"

    slug = entry.get("suggested_pattern_id")
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        # A slug proposal only; step 6 validates it anyway (Part E). Derive
        # one rather than reject an otherwise good name.
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or None

    return (
        {
            "cluster_id": cluster_id,
            "suggested_name": name.strip()[:120],
            "suggested_description": description.strip()[:600],
            "suggested_pattern_id": slug,
            "confidence": confidence,
            "naming_source": "claude-code",
            "model_version": model_version,
        },
        None,
    )


def unnamed(cluster_id: str) -> dict:
    """Part E: failure to narrate is not a step failure. The entry still
    exists so step 6 can tell "we tried and got nothing" apart from "this
    cluster is not in the narration artifact at all"."""
    return {
        "cluster_id": cluster_id,
        "suggested_name": None,
        "suggested_description": None,
        "suggested_pattern_id": None,
        "confidence": None,
        "naming_source": "none",
        "model_version": None,
    }


def _invoke(command: str, model: str, prompt: str, timeout_seconds: int) -> tuple[str | None, str | None]:
    """Claude Code headless. Returns (stdout, error_message)."""
    executable = shutil.which(command)
    if executable is None:
        return None, f"narration command '{command}' not found on PATH"

    argv = [
        executable,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "text",
        # Narration reads nothing and writes nothing. Denying the file and
        # execution tools makes constraint 4 ("no source code") a property
        # of the invocation rather than a promise about the prompt: even
        # if the signal names or paths in the payload were read as an
        # instruction to go and open a file, there is no tool to do it
        # with.
        "--allowedTools",
        "",
    ]
    try:
        completed = subprocess.run(
            argv,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, f"narration timed out after {timeout_seconds}s"
    except OSError as exc:
        return None, f"narration could not be invoked: {type(exc).__name__}: {exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return None, f"narration exited {completed.returncode}: {detail[-1] if detail else 'no output'}"
    return completed.stdout, None


def narrate(clusters: list[dict], config: dict) -> tuple[list[dict], list[dict]]:
    """Returns (entries, warnings). Never raises, never partially fails the
    step — see constraint 3 in the module docstring.

    Entries are returned for every cluster, in cluster_id order, so the
    narration artifact and the clusters artifact always agree on their
    key set.
    """
    warnings: list[dict] = []
    ordered = sorted(clusters, key=lambda c: c["cluster_id"])
    if not ordered:
        return [], warnings

    narration_config = config.get("narration") or {}
    command = narration_config.get("command", "claude")
    model = narration_config.get("model", "claude-sonnet-5")
    timeout_seconds = int(narration_config.get("timeout_seconds", 120))
    max_member_paths = int(narration_config.get("max_member_paths", 5))

    payload = [_cluster_payload(c, max_member_paths) for c in ordered]
    prompt = _SYSTEM_PROMPT + "\n\nClusters:\n" + json.dumps(payload, indent=2, ensure_ascii=False)

    stdout, error = _invoke(command, model, prompt, timeout_seconds)
    if error is not None:
        warnings.append({"code": "NARRATION_UNAVAILABLE", "message": error})
        return [unnamed(c["cluster_id"]) for c in ordered], warnings

    parsed = _extract_json_array(stdout or "")
    if parsed is None:
        warnings.append(
            {"code": "NARRATION_UNPARSEABLE", "message": "narration output was not a JSON array; no names recorded"}
        )
        return [unnamed(c["cluster_id"]) for c in ordered], warnings

    by_id = {}
    for entry in parsed:
        if isinstance(entry, dict) and isinstance(entry.get("cluster_id"), str):
            by_id[entry["cluster_id"]] = entry

    entries, rejected, missing = [], [], []
    for cluster in ordered:
        cid = cluster["cluster_id"]
        raw = by_id.get(cid)
        if raw is None:
            missing.append(cid)
            entries.append(unnamed(cid))
            continue
        normalised, reason = _redact(raw, cid, model)
        if normalised is None:
            rejected.append(f"{cid} ({reason})")
            entries.append(unnamed(cid))
            continue
        entries.append(normalised)

    if missing:
        warnings.append(
            {
                "code": "NARRATION_INCOMPLETE",
                "message": f"no narration returned for {len(missing)} cluster(s): {', '.join(sorted(missing))}",
            }
        )
    if rejected:
        warnings.append(
            {
                "code": "NARRATION_REJECTED",
                "message": f"narration failed validation for {len(rejected)} cluster(s): {', '.join(sorted(rejected))}",
            }
        )
    return entries, warnings


def status_for(entries: list[dict], warnings: list[dict], enabled: bool) -> tuple[str, str | None]:
    """The run-level narration outcome: (status, reason).

    A step diagnostic alone was not enough. At fleet scale it is easy to
    miss, and a human arriving at step 6 would see unnamed clusters with
    no indication why — which reads as "the platform has nothing to say
    about this shape" rather than "the narrator could not be reached".
    Those call for completely different actions, so the status is
    recorded on the run and rendered beside the clusters.

    - `disabled`  — narration was switched off. Not a failure; the step is
                    fully deterministic and step 6 shows signatures.
    - `failed`    — narration ran and named nothing.
    - `partial`   — some clusters named, some not. The interesting case:
                    it means the narrator was reachable, so the reason is
                    about the response rather than the connection.
    - `succeeded` — every cluster named.
    """
    if not enabled:
        return "disabled", "narration is disabled in config (enable_narration: false)"
    if not entries:
        return "succeeded", None

    named = sum(1 for e in entries if e["naming_source"] == "claude-code")
    # Warning messages are already written for a human; joining them beats
    # inventing a second, vaguer phrasing of the same fact.
    reason = "; ".join(w["message"] for w in warnings) or None

    if named == 0:
        return "failed", reason or "narration returned no usable names"
    if named < len(entries):
        return "partial", reason or f"{len(entries) - named} of {len(entries)} cluster(s) were not named"
    return "succeeded", None


def build_artifact(
    engagement_id: str,
    entries: list[dict],
    enabled: bool,
    status: str,
    reason: str | None,
) -> dict:
    return {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "engagement_id": engagement_id,
        "narration_enabled": enabled,
        "narration_status": status,
        "narration_reason": reason,
        "narrated_cluster_count": sum(1 for e in entries if e["naming_source"] == "claude-code"),
        "cluster_count": len(entries),
        "clusters": sorted(entries, key=lambda e: e["cluster_id"]),
    }
