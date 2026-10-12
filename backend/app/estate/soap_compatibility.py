"""The SOAP backend compatibility report — 31-DEPENDENCY-AND-CONTEXT-MAP.md
Part J: for each SOAP backend, will the call still work after the move to
the engagement's target .NET?

Per backend host (the endpoint register's grouping, Part C1), each calling
application's SOAP client, per environment binding: the binding, the
effective security mode and credential type (declared, or the binding's
default), and two verdicts from outbound-invocation-inventory —
**runtime**, does the target's WCF client support it (the WCF client support
matrix), and **platform**, does it work on Linux (the WCF client platform
matrix). Then what must change, and who can make it:

- ``we``: the calling application's side — its configuration or code,
  inside this migration;
- ``backend_owner``: the service's side — another binding, another security
  mode, another credential. When an estate repository serves the host
  (the register matched it, or a person annotated it), that owner is this
  migration too, and the report says so; otherwise another team must act;
- ``we_or_backend_owner``: either, not yet known which — Windows credentials
  negotiate Kerberos on Linux, which we can configure on the calling side,
  or the owner offers another credential. A probe in a Kerberos environment
  decides.

What must change on the platform side, and who, comes from the platform
matrix entry each verdict rests on (its ``fix``), never from a rule here.
The run records facts and the matrix entries each verdict rests on. Whether a
person has confirmed an entry, and what the probes found, is read when the
report is served (app/routers/estate.py), from the matrix files themselves —
a confirmation made after the run counts at once, and a report resting on an
unconfirmed entry is marked a draft, not for the client.

**Under review.** An entry a probe contradicts is not shown as its verdict
until a reviewer revises it: the verdict reads ``under_review``, the changes it
implied are withdrawn, and every total counts it apart (``review``,
``summarize``). Each change records the entry it came from (``source``) so
that only that entry's changes are withdrawn.
"""

from app.estate import analysis, wcf_matrix

UNDER_REVIEW = "under_review"
RUNTIME_RANK = {"unsupported": 0, "unknown": 1, "not_assessed": 1, "supported_with_caveat": 2, "supported": 3}
PLATFORM_RANK = {"incompatible": 0, "requires_change": 1, "unknown": 2, "compatible": 3}

WE = "we"
BACKEND_OWNER = "backend_owner"
WE_OR_BACKEND_OWNER = "we_or_backend_owner"


def load_matrix(version: str | None = None) -> dict | None:
    """The WCF client support (runtime) matrix: the given version, else the newest."""
    return wcf_matrix.load("support", version)


def _address(binding: dict) -> str | None:
    if not binding.get("host"):
        return binding.get("placeholder")
    port = f":{binding['port']}" if binding.get("port") else ""
    return f"{binding.get('scheme') or ''}://{binding['host']}{port}{binding.get('path') or ''}"


def changes_for(environment: dict, owner: str, serving: list[str]) -> list[dict]:
    """What must change for one environment binding, and who makes each change."""
    soap = environment.get("soap") or {}
    runtime = environment.get("runtimeVerdict")
    mode, binding = soap.get("securityMode"), soap.get("binding")
    owner_note = (f"the service is in this migration ({', '.join(serving)})" if owner == analysis.THIS_MIGRATION
                  else "another team owns the service")
    changes = []
    if runtime is None:
        return [{"who": WE, "change": "rescan this repository: it was scanned before outbound-invocation-inventory 1.4.0, "
                                      "so its runtime verdict was never given", "note": None, "source": "runtime"}]
    if runtime == "unsupported":
        entry = environment.get("runtimeMatrixEntry") or ""
        whole_binding = entry.endswith("/*/*")
        changes.append({
            "who": BACKEND_OWNER,
            "change": (f"the service must also offer a binding the .NET WCF client has ({binding} has none): "
                       f"basicHttpBinding, wsHttpBinding or netTcpBinding" if whole_binding else
                       f"the service must offer {binding} with a security mode the .NET WCF client supports — Transport or "
                       f"TransportWithMessageCredential over HTTPS, not {mode}"),
            "note": owner_note, "source": "runtime",
        })
        changes.append({"who": WE, "change": "repoint this client's binding and security to the endpoint the service then offers",
                        "note": None, "source": "runtime"})
    elif runtime == "unknown" and environment.get("runtimeMatrixEntry"):
        # An entry that says unknown: unprobed, not unread (matrices 1.1.0, the wildcard rule).
        changes.append({"who": WE, "change": "probe this binding, security mode and credential before relying on it: the WCF client "
                                             "support matrix records it as unprobed",
                        "note": "; ".join(environment.get("runtimeReasons") or []) or None, "source": "runtime"})
    elif runtime == "unknown":
        changes.append({"who": WE, "change": "read this client's binding and security by hand: the inventory could not resolve them",
                        "note": "; ".join(environment.get("runtimeReasons") or []) or None, "source": "runtime"})
    elif runtime == "supported_with_caveat":
        caveats = [r.removeprefix("caveat: ") for r in environment.get("runtimeReasons") or [] if r.startswith("caveat: ")]
        changes.append({"who": WE, "change": "check the caveat before relying on it", "note": "; ".join(caveats) or None,
                        "source": "runtime"})

    # The platform side: what the platform matrix entry says must change, and who.
    entry = wcf_matrix.entries("platform").get(environment.get("platformMatrixEntry") or "")
    if entry and entry.get("fix"):
        fix = entry["fix"]
        note = entry.get("caveat") if fix["who"] == WE_OR_BACKEND_OWNER else owner_note if fix["who"] == BACKEND_OWNER else None
        changes.append({"who": fix["who"], "change": fix["change"], "note": note, "source": "platform"})
    # And this environment's own configuration (an unqualified host name).
    for reason in environment.get("linuxReasons") or []:
        if reason.startswith("unqualified hostname"):
            changes.append({"who": WE, "change": f"change this environment's configuration: {reason}", "note": None,
                            "source": "configuration"})
    return changes


def build(register: dict) -> dict:
    """From build_register's grouped calls: one row per backend host with SOAP callers."""
    hosts = []
    for key, calls in sorted(register.get("callsByKey", {}).items()):
        soap_calls = [c for c in calls if c["mechanism"] == "soap_client"]
        if not soap_calls:
            continue
        serving = sorted({s["repository_slug"] for c in soap_calls for s in c.get("servers") or []})
        owner = analysis.THIS_MIGRATION if serving else analysis.ANOTHER_TEAM
        callers, entries = [], set()
        for call in sorted(soap_calls, key=lambda c: (c["repository_slug"], c["project_path"], analysis.contract_of(c) or "", c["id"])):
            block = analysis._block(call)
            environments = []
            for env in sorted(call.get("environment_bindings") or [], key=lambda b: (b.get("environment") or "", b.get("sourceFile") or "")):
                soap = env.get("soap") or {"binding": block.get("binding"), "securityMode": block.get("securityMode"),
                                           "clientCredentialType": block.get("clientCredentialType"),
                                           "securitySource": block.get("securitySource")}
                for field in ("runtimeMatrixEntry", "platformMatrixEntry"):
                    if env.get(field):
                        entries.add(env[field])
                environments.append({
                    "environment": env.get("environment") or "default",
                    "address": _address(env),
                    "sourceFile": env.get("sourceFile"),
                    "deployParameter": env.get("deployParameter"),
                    "binding": soap.get("binding"),
                    "securityMode": soap.get("securityMode"),
                    "credentialType": "None" if soap.get("securityMode") == "None" else soap.get("clientCredentialType"),
                    "securitySource": soap.get("securitySource"),
                    "runtime": {"verdict": env.get("runtimeVerdict") or "not_assessed",
                                "reasons": env.get("runtimeReasons") or ([] if env.get("runtimeVerdict") else
                                                                         ["scanned before outbound-invocation-inventory 1.4.0"]),
                                "matrixEntry": env.get("runtimeMatrixEntry")},
                    "platform": {"verdict": env.get("linuxVerdict") or call.get("linux_verdict"), "reasons": env.get("linuxReasons") or [],
                                 "matrixEntry": env.get("platformMatrixEntry")},
                    "changes": changes_for(env, owner, serving),
                })
            callers.append({
                "invocationId": call["id"], "application": call["repository_slug"], "projectPath": call["project_path"],
                "contract": block.get("contract"), "endpointName": block.get("endpointName"), "clientType": block.get("clientType"),
                "operations": sorted({o.get("operation") for o in call.get("operations") or [] if o.get("operation")}),
                "environments": environments,
            })
        all_envs = [e for c in callers for e in c["environments"]]
        hosts.append({
            "host": key,
            "servedBy": serving,
            "backendOwner": owner,
            "callingApplications": sorted({c["application"] for c in callers}),
            "worstRuntime": min((e["runtime"]["verdict"] for e in all_envs), key=lambda v: RUNTIME_RANK.get(v, 1), default="unknown"),
            "worstPlatform": min((e["platform"]["verdict"] or "unknown" for e in all_envs), key=lambda v: PLATFORM_RANK.get(v, 2),
                                 default="unknown"),
            "changeOwners": sorted({ch["who"] for e in all_envs for ch in e["changes"]}),
            "matrixEntries": sorted(entries),
            "callers": callers,
        })
    hosts.sort(key=lambda h: (RUNTIME_RANK.get(h["worstRuntime"], 1), PLATFORM_RANK.get(h["worstPlatform"], 2), h["host"]))
    return {"hosts": hosts}


def _host_totals(host: dict) -> dict:
    """A host's worst verdicts and change owners, without anything under review."""
    envs = [e for c in host["callers"] for e in c["environments"]]
    runtime = [e["runtime"]["verdict"] for e in envs if e["runtime"]["verdict"] != UNDER_REVIEW]
    platform = [e["platform"]["verdict"] or "unknown" for e in envs if e["platform"]["verdict"] != UNDER_REVIEW]
    return {
        **host,
        "worstRuntime": min(runtime, key=lambda v: RUNTIME_RANK.get(v, 1)) if runtime else UNDER_REVIEW,
        "worstPlatform": min(platform, key=lambda v: PLATFORM_RANK.get(v, 2)) if platform else UNDER_REVIEW,
        "changeOwners": sorted({ch["who"] for e in envs for ch in e["changes"]}),
        "underReview": sum(1 for e in envs if e.get("underReview")),
    }


def review(hosts: list[dict], contradicted: dict[str, list[str]]) -> list[dict]:
    """The hosts with every verdict resting on a contradicted matrix entry
    (entry id -> the probe contradictions) shown as under review: the verdict
    reads UNDER_REVIEW (the unrevised one kept as ``unrevisedVerdict`` for the
    reviewer), the changes that entry implied are withdrawn, and the host's
    totals are recomputed without it."""
    reviewed = []
    for host in hosts:
        callers = []
        for caller in host["callers"]:
            environments = []
            for env in caller["environments"]:
                env = {**env, "underReview": []}
                for side in ("runtime", "platform"):
                    entry = env[side].get("matrixEntry")
                    if entry in contradicted:
                        env[side] = {**env[side], "verdict": UNDER_REVIEW, "unrevisedVerdict": env[side]["verdict"]}
                        env["changes"] = [c for c in env["changes"] if c.get("source") != side]
                        env["underReview"] += [f"{entry}: {reason}" for reason in contradicted[entry]]
                environments.append(env)
            callers.append({**caller, "environments": environments})
        reviewed.append(_host_totals({**host, "callers": callers}))
    reviewed.sort(key=lambda h: (RUNTIME_RANK.get(h["worstRuntime"], 1), PLATFORM_RANK.get(h["worstPlatform"], 2), h["host"]))
    return reviewed


def summarize(hosts: list[dict]) -> dict:
    """Every total, with what is under review counted apart, never as its unrevised verdict."""
    return {
        "hosts": len(hosts),
        "runtimeUnsupported": sum(1 for h in hosts if h["worstRuntime"] == "unsupported"),
        "platformIncompatible": sum(1 for h in hosts if h["worstPlatform"] == "incompatible"),
        "backendOwnerMustChange": sum(1 for h in hosts if BACKEND_OWNER in h["changeOwners"]),
        "underReview": sum(1 for h in hosts if h.get("underReview")),
    }
