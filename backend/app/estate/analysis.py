"""Lifecycle step 11's analysis — 31-DEPENDENCY-AND-CONTEXT-MAP.md Parts C to F.

Pure functions over plain dicts: no database, no I/O. app/steps/estate_map.py
loads the per-repository rows, calls these, and writes tables and artifacts.
Every function returns collections in a stable order, so the artifacts built
from them are deterministic.

Input row shapes (as estate_map loads them):

- call: {id, repository_id, repository_slug, project_id, project_path, mechanism,
  scheme, host, port, path, resolution, placeholder, linux_verdict, linux_reasons,
  detail, environment_bindings}
- entry point: {id, repository_id, repository_slug, project_id, project_path, kind,
  origin, handler_type, handler_member, detail}
- project: {id, repository_id, repository_slug, relative_path, name, assembly_name,
  root_namespace}
"""

import hashlib
import re
from collections import Counter, defaultdict

# ---------- hosts ----------

# Development addresses. A loopback host is not a team: it is where a
# developer ran the other side. Such calls are grouped by the repository that
# serves them, when that is known, else by port — never all into one
# "localhost" conversation.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "(localdb)", "(local)", "."}

VERDICT_RANK = {"incompatible": 0, "requires_change": 1, "unknown": 2, "compatible": 3}

# Bindings only the service's owner can replace: the client cannot call a
# NetTcp service over anything but NetTcp until the service offers another.
OWNER_ONLY_BINDINGS = {"nettcpbinding", "netnamedpipebinding", "netmsmqbinding", "netpeertcpbinding", "nettcprelaybinding"}
WINDOWS_CREDENTIALS = {"windows", "ntlm", "negotiate", "kerberos"}


def normalise_host(host: str | None) -> str | None:
    if host is None:
        return None
    value = host.strip().lower().rstrip(".")
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return value or None


def is_loopback(host: str | None) -> bool:
    return host is not None and (host in LOOPBACK_HOSTS or host.startswith("127.") or host.startswith("(localdb)"))


def worst_verdict(verdicts) -> str | None:
    ranked = [v for v in verdicts if v in VERDICT_RANK]
    return min(ranked, key=VERDICT_RANK.get) if ranked else None


def _block(call: dict) -> dict:
    return (call.get("detail") or {}).get("block") or {}


def contract_of(call: dict) -> str | None:
    return _block(call).get("contract")


def binding_of(call: dict) -> str | None:
    binding = _block(call).get("binding")
    return None if binding in (None, "unknown") else binding


THIS_MIGRATION = "this_migration"
ANOTHER_TEAM = "another_team"


def backend_change_owner(call: dict) -> str:
    """Who must make the backend change (C2): a service this migration
    contains — the call matched an entry point of the estate — or another
    team's service."""
    return THIS_MIGRATION if call.get("servers") else ANOTHER_TEAM


def backend_change_reasons(call: dict) -> list[str]:
    """Why only the endpoint's owner can make this call work on Linux (Part
    C2): a binding the client cannot change unilaterally, or Windows-integrated
    service security. Empty when the fix is in the caller's own code.

    Worded by ownership: for a service inside this migration the change is
    ours to plan — sequence the service before or with its callers; for
    another team's service it is a request to them, with a lead time that
    should start now."""
    reasons = []
    owner = backend_change_owner(call)
    serving = sorted({s["repository_slug"] for s in call.get("servers") or []})
    who = (f"the service ({', '.join(serving)}) is inside this migration: plan its change with its callers"
           if owner == THIS_MIGRATION else "another team owns the service: ask them, and start now")
    binding = binding_of(call)
    if binding and binding.lower() in OWNER_ONLY_BINDINGS:
        reasons.append(f"{binding}: the service must offer an HTTP-based binding before callers can move — {who}")
    credential = (_block(call).get("clientCredentialType") or "").lower()
    if credential in WINDOWS_CREDENTIALS:
        reasons.append(f"Windows-integrated service security (clientCredentialType {_block(call).get('clientCredentialType')}): "
                       f"the service must accept another credential — {who}")
    return reasons


# ---------- production-host grouping (Part C1) ----------


def production_binding(call: dict, production_environment: str | None) -> dict | None:
    """The call's binding for the engagement's production environment that
    names a host — one per configuration file, so the first by file and key
    when several do. None when there is no production environment set or
    the call has no such binding."""
    if not production_environment:
        return None
    wanted = production_environment.strip().lower()
    bindings = sorted(call.get("environment_bindings") or [], key=lambda b: (b.get("sourceFile") or "", b.get("keyPath") or ""))
    for binding in bindings:
        if (binding.get("environment") or "").lower() == wanted and normalise_host(binding.get("host")):
            return binding
    return None


def grouping(call: dict, production_environment: str | None) -> dict:
    """Where the register files this call: {host, port, path, grouped_by,
    other_hosts}. By the production environment's host (and that binding's
    port and path) when the call has a production binding — one service is
    one row whichever environment file a repository's default points at —
    else by the endpoint as found."""
    binding = production_binding(call, production_environment)
    if binding is not None:
        host, port, path, grouped_by = normalise_host(binding["host"]), binding.get("port"), binding.get("path"), "production_environment"
    else:
        host, port, path, grouped_by = normalise_host(call.get("host")), call.get("port"), call.get("path"), "host"
    others: dict = defaultdict(set)
    for b in call.get("environment_bindings") or []:
        other = normalise_host(b.get("host"))
        if other and other != host:
            others[other].add(b.get("environment") or "default")
    own = normalise_host(call.get("host"))
    if own and own != host and own not in others:
        others[own].add("as found in code")
    return {"host": host, "port": port, "path": path, "grouped_by": grouped_by, "other_hosts": others}


# ---------- servers: what the estate's entry points expose ----------


def _address_path(address: str | None) -> str | None:
    """'net.tcp://localhost:{port}/Account' -> '/account'."""
    if not address:
        return None
    match = re.match(r"^[a-z.+-]+://[^/]*(/.*)?$", address.strip(), re.IGNORECASE)
    if not match:
        return None
    return (match.group(1) or "/").rstrip("/").lower() or "/"


def _svc_path(host_file: str | None) -> str | None:
    """'src/Hosting.Iis/Account.svc:1' -> '/account.svc': an IIS-hosted .svc
    is addressed by its file name under the application root."""
    if not host_file:
        return None
    name = host_file.split(":")[0].replace("\\", "/").split("/")[-1]
    return f"/{name.lower()}" if name.lower().endswith(".svc") else None


def build_servers(entry_points: list[dict]) -> list[dict]:
    """One server per WCF contract per project, and one per HTTP route per
    project: what a call can be matched against. Each carries the entry
    point it links to (the lowest id among that contract's operations, so the
    link is stable across rescans of the same code)."""
    soap: dict = {}
    http: dict = {}
    for ep in sorted(entry_points, key=lambda e: e["id"]):
        detail = ep.get("detail") or {}
        if ep["kind"] == "wcf_operation" and detail.get("contract"):
            key = (ep["project_id"], detail["contract"])
            server = soap.setdefault(key, {
                "kind": "soap", "contract": detail["contract"], "paths": set(), "bindings": set(),
                "repository_id": ep["repository_id"], "repository_slug": ep["repository_slug"],
                "project_id": ep["project_id"], "project_path": ep["project_path"],
                "entry_point_id": ep["id"], "handler": ep.get("handler_type"),
            })
            for endpoint in detail.get("endpoints") or []:
                path = _address_path(endpoint.get("address")) if endpoint.get("address") else _svc_path(endpoint.get("hostedAt") or detail.get("hostFile"))
                if path:
                    server["paths"].add(path)
                if endpoint.get("binding"):
                    server["bindings"].add(endpoint["binding"])
        elif ep["kind"] in ("http_controller_action", "http_minimal_api"):
            template = detail.get("mappedTemplate") or detail.get("routeTemplate")
            if not template:
                continue
            route = "/" + template.strip("/").lower()
            key = (ep["project_id"], route)
            http.setdefault(key, {
                "kind": "http", "route": route, "segments": route.strip("/").split("/"),
                "repository_id": ep["repository_id"], "repository_slug": ep["repository_slug"],
                "project_id": ep["project_id"], "project_path": ep["project_path"],
                "entry_point_id": ep["id"], "handler": ep.get("handler_type"),
            })
    return [soap[k] for k in sorted(soap, key=str)] + [http[k] for k in sorted(http, key=str)]


def _segment_matches(route_segment: str, call_segment: str) -> bool:
    if route_segment.startswith("{") and route_segment.endswith("}"):
        return True
    if call_segment.startswith("{") and call_segment.endswith("}"):
        return True
    return route_segment == call_segment


_HOLES = ("{…}", "{...}")


def _http_route_matches(server: dict, path: str) -> bool:
    call = path.strip("/").lower().split("/")
    route = server["segments"]
    if call == [""] or route == [""]:
        return False  # the root path matches anything; too weak to link
    if call[0] in _HOLES:
        # A prefix step 5 could not read — a base address from configuration
        # ({Services:Orders:Url}/api/orders): the rest must end the route.
        rest = call[1:]
        if not rest or all(s in _HOLES for s in rest) or len(rest) > len(route):
            return False
        return all(c in _HOLES or _segment_matches(r, c) for r, c in zip(route[len(route) - len(rest):], rest))
    # A call segment of {…} is "something step 5 could not read": it may
    # stand for several segments, so it matches the remaining route.
    for i, segment in enumerate(call):
        if segment in ("{…}", "{...}"):
            return len(route) >= i
        if i >= len(route) or not _segment_matches(route[i], segment):
            return False
    return len(call) == len(route)


def _top_folder(path: str | None) -> str:
    parts = (path or "").split("/")
    return parts[0] if len(parts) > 2 else ""


def http_matchable(call: dict, served_by: dict | None, host: str | None = None) -> tuple[bool, str | None]:
    """Whether an HTTP call's routes may be matched to the estate's: on a
    loopback address (where the other side is a developer's own run of it),
    or on a host a person annotated as served by one of the estate's
    repositories. A real host serving /api/orders is otherwise far more
    likely someone else's. `host` is where the register files the call (its
    production host when it has one). Returns (matchable, why not)."""
    host = host or normalise_host(call.get("host"))
    if is_loopback(normalise_host(call.get("host"))) or served_by is not None:
        return True, None
    if host is None:
        return False, "the endpoint's host is not resolved"
    return False, f"{host} is neither a local address nor annotated as served by an estate repository"


def _rank(server: dict, call: dict) -> int:
    """Same solution folder, then same repository, then elsewhere."""
    if server["repository_id"] == call["repository_id"]:
        return 0 if _top_folder(server["project_path"]) == _top_folder(call["project_path"]) else 1
    return 2


def match_servers(call: dict, servers: list[dict], served_by: dict | None = None) -> tuple[list[dict], str | None]:
    """The estate's servers that answer this call, and how they were found.
    SOAP: the call's contract and path, on any host — a contract name is
    specific enough to trust across repositories. HTTP: the route template,
    on a loopback host, or on a host annotated as served by a repository
    (`served_by`: {repository_id, repository_slug}) against that repository's
    routes only. Candidates are ranked same solution folder, then same
    repository, then elsewhere; only the best rank is kept."""
    contract = contract_of(call)
    path = (call.get("path") or "").rstrip("/").lower() or None
    found: list[dict] = []
    how = None
    if call["mechanism"] == "soap_client" and contract:
        same_contract = [s for s in servers if s["kind"] == "soap" and s["contract"] == contract]
        found = [s for s in same_contract if path and path in s["paths"]]
        how = "contract and path"
        if not found and same_contract:
            found, how = same_contract, "contract"
    elif call["mechanism"] == "http_client" and path and is_loopback(normalise_host(call.get("host"))):
        found = [s for s in servers if s["kind"] == "http" and _http_route_matches(s, path)]
        how = "route template on a local address"
    elif call["mechanism"] == "http_client" and path and served_by is not None:
        found = [s for s in servers if s["kind"] == "http" and s["repository_id"] == served_by["repository_id"]
                 and _http_route_matches(s, path)]
        how = f"route template on a host annotated as served by {served_by['repository_slug']}"
    if not found:
        return [], None

    best = min(_rank(s, call) for s in found)
    kept = [s for s in found if _rank(s, call) == best]
    # One server per project is enough to link: an HTTP call matches many
    # routes of the same API project only if they share a template.
    unique = {(s["project_id"], s.get("contract") or s.get("route")): s for s in kept}
    return [unique[k] for k in sorted(unique, key=str)], how


# ---------- the endpoint register (Part C) ----------


def _target(server: dict, call_repository_id) -> dict:
    return {
        "repositoryId": str(server["repository_id"]),
        "repositorySlug": server["repository_slug"],
        "projectId": str(server["project_id"]),
        "projectPath": server["project_path"],
        "entryPointId": server["entry_point_id"],
        "served": server.get("contract") or server.get("route"),
        "sameRepository": server["repository_id"] == call_repository_id,
    }


def build_register(calls: list[dict], entry_points: list[dict], production_environment: str | None = None,
                   served_by: dict | None = None) -> dict:
    """{hosts: [...], unresolved: [...], unused_excluded: n}. Used calls only
    (B3); a call with no host is listed under unresolved, never guessed.
    `production_environment` is the engagement's setting (C1); `served_by`
    maps an annotated host to {repository_id, repository_slug} (C4)."""
    servers = build_servers(entry_points)
    served_by = served_by or {}
    used = [c for c in calls if c.get("usage", "used") == "used"]
    unused = len(calls) - len(used)

    resolved, unresolved = [], []
    for call in sorted(used, key=lambda c: c["id"]):
        group = grouping(call, production_environment)
        if group["host"] is None:
            unresolved.append({
                "repositorySlug": call["repository_slug"], "projectPath": call["project_path"], "mechanism": call["mechanism"],
                "contract": contract_of(call), "placeholder": call.get("placeholder"), "resolution": call.get("resolution"),
                "invocationId": call["id"],
            })
            continue
        # Loopback matching is unchanged; a real host may be annotated. The
        # path is the grouped endpoint's: a call with no default value takes
        # its production binding's.
        filed = {**call, "path": group["path"]}
        annotated = None if is_loopback(group["host"]) else served_by.get(group["host"])
        found, how = match_servers(filed, servers, annotated)
        resolved.append({**filed, "host_n": group["host"], "port_n": group["port"], "grouped_by": group["grouped_by"],
                         "other_hosts": group["other_hosts"], "servers": found, "match": how})

    # A loopback port already tied to a server by one call of a repository
    # is that server for the repository's other calls on the same port.
    port_server: dict = {}
    for call in resolved:
        if is_loopback(call["host_n"]) and call["servers"] and call.get("port_n"):
            port_server.setdefault((call["repository_id"], call["port_n"]), call["servers"])
    for call in resolved:
        if is_loopback(call["host_n"]) and not call["servers"] and (call["repository_id"], call.get("port_n")) in port_server:
            call["servers"] = port_server[(call["repository_id"], call.get("port_n"))]
            call["match"] = "same local port as a matched call"

    groups: dict[str, list[dict]] = defaultdict(list)
    for call in resolved:
        groups[register_key(call)].append(call)

    hosts = [_host_row(key, group, production_environment) for key, group in groups.items()]
    key_by_invocation = {call["id"]: key for key, group in groups.items() for call in group}
    hosts.sort(key=lambda h: (not h["requiresBackendChange"], -h["callingRepositoryCount"], h["host"]))
    unresolved.sort(key=lambda u: (u["repositorySlug"], u["projectPath"], u["mechanism"], u["invocationId"]))
    # keyByInvocation: which row each call is filed under — for carrying
    # annotations (C4); not written to the artifact.
    return {"hosts": hosts, "unresolved": unresolved, "unusedExcluded": unused, "keyByInvocation": key_by_invocation}


def carry_annotations(register: dict, as_found: dict, annotated: list[str]) -> dict[str, list[str]]:
    """
    Annotations a settings change would otherwise orphan (C4): an annotated
    host that is no longer a row, whose calls the production grouping moved
    under a production row, is carried to that row — to each, when the calls
    went to several. `as_found` is the register built with no production
    environment. Returns annotated host -> production rows. A human's
    conversation record is never dropped because of a setting.
    """
    called = {h["host"] for h in register["hosts"]}
    now, before = register["keyByInvocation"], as_found["keyByInvocation"]
    carried: dict[str, list[str]] = {}
    for host in annotated:
        if host in called:
            continue
        targets = sorted({now[i] for i, key in before.items() if key == host and i in now and now[i] != host})
        if targets:
            carried[host] = targets
    return carried


def register_key(call: dict) -> str:
    """The register's unit of conversation. A real host is itself (port does
    not split it, C1). A loopback host served by one repository of the
    estate is that repository ('localhost@wcf'); otherwise its port
    ('localhost:5433'), since on a developer machine the port is all that
    tells two services apart."""
    host = call["host_n"]
    if not is_loopback(host):
        return host
    serving = {s["repository_slug"] for s in call["servers"]}
    label = "(localdb)" if host.startswith("(localdb)") else "localhost"
    if len(serving) == 1:
        return f"{label}@{next(iter(serving))}"
    port = call.get("port_n", call.get("port"))
    return f"{label}:{port}" if port else label


def _grouping_note(calls: list[dict], production_environment: str | None) -> str | None:
    """Said on a row not (wholly) keyed by the production host."""
    without = sum(1 for c in calls if c.get("grouped_by", "host") == "host")
    if without == 0:
        return None
    if not production_environment:
        return "No production environment is set for the engagement: grouped by the host as found."
    if without == len(calls):
        return f"No '{production_environment}' binding: grouped by the host as found."
    return f"{without} of {len(calls)} call(s) have no '{production_environment}' binding and were grouped by the host as found."


def _host_row(key: str, calls: list[dict], production_environment: str | None = None) -> dict:
    services: dict = defaultdict(list)
    for call in calls:
        services[((call.get("path") or "").lower(), contract_of(call) or "")].append(call)

    service_rows = []
    for (path, contract), group in sorted(services.items()):
        targets = {}
        for call in group:
            for server in call["servers"]:
                t = _target(server, call["repository_id"])
                targets[(t["projectId"], t["served"])] = t
        service_rows.append({
            "path": path,
            "contract": contract or None,
            "ports": sorted({p for c in group if (p := c.get("port_n", c.get("port")))}),
            "schemes": sorted({c["scheme"] for c in group if c.get("scheme")}),
            "mechanisms": sorted({c["mechanism"] for c in group}),
            "bindings": sorted({b for c in group if (b := binding_of(c))}),
            "callingRepositories": sorted({c["repository_slug"] for c in group}),
            "callingProjects": sorted({f"{c['repository_slug']}:{c['project_path']}" for c in group}),
            "worstVerdict": worst_verdict(c["linux_verdict"] for c in group),
            "requiresBackendChange": any(backend_change_reasons(c) for c in group),
            "backendChangeOwner": (
                None if not any(backend_change_reasons(c) for c in group) else THIS_MIGRATION if targets else ANOTHER_TEAM
            ),
            "internal": bool(targets),
            "internalTargets": [targets[k] for k in sorted(targets)],
            "matchedBy": sorted({c["match"] for c in group if c.get("match")}),
        })

    by_environment: dict = defaultdict(list)
    for call in calls:
        for binding in call.get("environment_bindings") or []:
            if binding.get("linuxVerdict"):
                by_environment[binding.get("environment") or "default"].append(binding["linuxVerdict"])
    reasons = sorted({r for c in calls for r in backend_change_reasons(c)})
    owners = {backend_change_owner(c) for c in calls if backend_change_reasons(c)}
    other_hosts: dict = defaultdict(set)
    for call in calls:
        for other, environments in (call.get("other_hosts") or {}).items():
            if other != key:
                other_hosts[other] |= environments
    return {
        "host": key,
        "groupedBy": "production_environment" if any(c.get("grouped_by") == "production_environment" for c in calls) else "host",
        "productionEnvironment": production_environment,
        "groupingNote": _grouping_note(calls, production_environment),
        "otherHosts": [{"host": h, "environments": sorted(other_hosts[h])} for h in sorted(other_hosts)],
        "loopback": is_loopback(calls[0]["host_n"]),
        "classification": "internal" if all(s["internal"] for s in service_rows) else "external",
        "services": service_rows,
        "callingRepositoryCount": len({c["repository_slug"] for c in calls}),
        "callingRepositories": sorted({c["repository_slug"] for c in calls}),
        "callingProjectCount": len({(c["repository_slug"], c["project_path"]) for c in calls}),
        "callingProjects": sorted({f"{c['repository_slug']}:{c['project_path']}" for c in calls}),
        "mechanisms": sorted({c["mechanism"] for c in calls}),
        "bindings": sorted({b for c in calls if (b := binding_of(c))}),
        "ports": sorted({p for c in calls if (p := c.get("port_n", c.get("port")))}),
        "worstVerdict": worst_verdict(c["linux_verdict"] for c in calls),
        "verdictByEnvironment": {env: worst_verdict(v) for env, v in sorted(by_environment.items())},
        "requiresBackendChange": bool(reasons),
        # C2 by ownership: 'this_migration' (a service inside this
        # migration must change) or 'another_team'; another team wins a mix.
        "backendChangeOwner": None if not owners else ANOTHER_TEAM if ANOTHER_TEAM in owners else THIS_MIGRATION,
        "backendChangeReasons": reasons,
        "invocationCount": len(calls),
    }


# ---------- integration edges (Part I) ----------

# Entry points a call can reach, by the operation they serve.
INTEGRATION_KINDS = ("wcf_operation", "asmx_web_method", "http_controller_action", "http_minimal_api", "grpc_service_method")
HTTP_ENTRY_KINDS = ("http_controller_action", "http_minimal_api")
INTERNAL_CALLER_FOUND = "internal_caller_found"
# Never "unused": an operation nothing in the estate calls may still be
# called from outside it.
NO_INTERNAL_CALLER_FOUND = "no_internal_caller_found"


def _http_template(detail: dict) -> str | None:
    template = detail.get("mappedTemplate") or detail.get("routeTemplate")
    return "/" + template.strip("/").lower() if template else None


def entry_operation(ep: dict) -> tuple[str, bool]:
    """(label, matchable): what the entry point serves, as a caller names it,
    and whether a call can be matched to it at all (an HTTP action with no
    route template — conventional routing — cannot)."""
    detail = ep.get("detail") or {}
    kind = ep["kind"]
    if kind == "wcf_operation":
        return f"{detail.get('contract')}.{detail.get('operation') or ep.get('handler_member')}", bool(detail.get("contract"))
    if kind == "asmx_web_method":
        return f"{detail.get('servicePath')} {detail.get('method')}", bool(detail.get("servicePath"))
    if kind == "grpc_service_method":
        return f"{detail.get('service')}/{detail.get('method')}", bool(detail.get("service"))
    template = _http_template(detail)
    return f"{(detail.get('verb') or 'ANY').upper()} {template or '(no route template)'}", template is not None


def call_operation_label(call: dict, op: dict) -> str:
    if call["mechanism"] == "http_client":
        if op.get("resolution") == "unresolved" and not op.get("path"):
            return "(unresolved request)"
        return f"{op.get('verb') or '?'} {op.get('path') or '?'}"
    if not op.get("operation"):
        return "(unresolved operation)"
    contract = contract_of(call)
    return f"{contract}.{op['operation']}" if contract and call["mechanism"] == "soap_client" else (
        f"{contract}/{op['operation']}" if contract else op["operation"])


def _soap_candidates(call: dict, op: dict, entry_points: list[dict]) -> tuple[list[tuple[dict, str, float]], str | None]:
    contract, name = contract_of(call), op.get("operation")
    path = (call.get("path") or "").rstrip("/").lower() or None
    found = []
    for ep in entry_points:
        detail = ep.get("detail") or {}
        if ep["kind"] == "wcf_operation" and contract and detail.get("contract") == contract:
            served = detail.get("operation") or ep.get("handler_member")
            # A generated client's FooAsync calls the Foo operation.
            if served != name and f"{served}Async" != name:
                continue
            paths = {_address_path(e.get("address")) if e.get("address") else _svc_path(e.get("hostedAt") or detail.get("hostFile"))
                     for e in detail.get("endpoints") or []}
            if path and path in paths:
                found.append((ep, "contract_operation_and_path", 0.95))
            else:
                found.append((ep, "contract_and_operation", 0.85))
        elif ep["kind"] == "asmx_web_method" and path and (detail.get("servicePath") or "").lower() == path:
            if detail.get("method") == name or f"{detail.get('method')}Async" == name:
                found.append((ep, "service_path_and_method", 0.9))
    if found:
        return found, None
    if not contract:
        return [], "the client's contract is not known"
    return [], f"no entry point in the estate serves {contract}.{name}"


def _http_candidates(call: dict, op: dict, entry_points: list[dict], served_by: dict | None,
                     host: str | None = None) -> tuple[list[tuple[dict, str, float]], str | None]:
    matchable, why_not = http_matchable(call, served_by, host)
    if not matchable:
        return [], why_not
    path = (op.get("path") or "").rstrip("/").lower()
    if not path:
        return [], "the request path is not resolved"
    verb = op.get("verb")
    base = 0.9 if served_by is None else 0.85
    method = "verb_and_route_template" if served_by is None else "verb_and_route_template_on_annotated_host"
    found = []
    for ep in entry_points:
        if ep["kind"] not in HTTP_ENTRY_KINDS:
            continue
        if served_by is not None and ep["repository_id"] != served_by["repository_id"]:
            continue
        template = _http_template(ep.get("detail") or {})
        if template is None or not _http_route_matches({"segments": template.strip("/").split("/")}, path):
            continue
        served_verb = ((ep.get("detail") or {}).get("verb") or "ANY").upper()
        if verb and served_verb not in ("ANY", verb):
            continue
        confidence = base - (0.2 if op.get("resolution") == "partial" else 0) - (0.1 if served_verb == "ANY" or not verb else 0)
        segments = template.strip("/").split("/")
        literal = sum(1 for s in segments if not s.startswith("{"))
        found.append((ep, method, round(confidence, 2), served_verb == verb, literal, len(segments) == len(path.strip("/").split("/"))))
    if not found:
        return [], f"no entry point in the {'repository annotated as serving the host' if served_by else 'estate'} serves {verb or '?'} {op.get('path')}"
    # The most specific: an exact verb over ANY, then the most literal
    # segments, then a route as long as the call (a trailing {…} may stand
    # for nothing, but /items/{…} is likelier /items/{id} than /items).
    best_verb = max(f[3] for f in found)
    found = [f for f in found if f[3] == best_verb]
    most_literal = max(f[4] for f in found)
    found = [f for f in found if f[4] == most_literal]
    if any(f[5] for f in found):
        found = [f for f in found if f[5]]
    return [(ep, m, c) for ep, m, c, *_ in found], None


def _grpc_candidates(call: dict, op: dict, entry_points: list[dict]) -> tuple[list[tuple[dict, str, float]], str | None]:
    service, name = contract_of(call), op.get("operation")
    found = [(ep, "service_and_method", 0.95) for ep in entry_points
             if ep["kind"] == "grpc_service_method" and (ep.get("detail") or {}).get("service") == service
             and (ep.get("detail") or {}).get("method") == name]
    return (found, None) if found else ([], f"no entry point in the estate serves {service}/{name}")


def build_integration(calls: list[dict], entry_points: list[dict], production_environment: str | None = None,
                      served_by: dict | None = None) -> dict:
    """Operation-level edges: each invoked operation step 5 recorded, matched
    to the step 4 entry point that serves it — SOAP by contract and operation
    (and path, when the address says), HTTP by verb and route template (on a
    local address or an annotated host only), gRPC by service and method.
    Same-repository edges are kept and flagged. Of several candidates only
    the best ranked are kept (same folder, same repository, elsewhere); a
    tie lowers the confidence. Returns {edges, unmatched, entryPoints}."""
    served_by = served_by or {}
    edges, unmatched = [], []
    for call in sorted(calls, key=lambda c: c["id"]):
        if call.get("usage", "used") != "used" or call["mechanism"] not in ("soap_client", "http_client", "grpc_client"):
            continue
        host = grouping(call, production_environment)["host"]
        annotated = None if host is None or is_loopback(host) else served_by.get(host)
        for op in call.get("operations") or []:
            label = call_operation_label(call, op)
            site = op.get("callSite") or {}
            base = {"invocationId": call["id"], "mechanism": call["mechanism"], "operation": label,
                    "callerRepositoryId": str(call["repository_id"]), "callerRepositorySlug": call["repository_slug"],
                    "callerProjectId": str(call["project_id"]), "callerProjectPath": call["project_path"],
                    "callSite": {"filePath": site.get("filePath"), "lineStart": site.get("lineStart")}}
            if op.get("resolution") == "unresolved" and not (op.get("operation") or op.get("path")):
                unmatched.append({**base, "reason": f"operation not resolved statically: {op.get('reason') or 'no reason given'}",
                                  "resolution": "unresolved"})
                continue
            if call["mechanism"] == "soap_client":
                found, why = _soap_candidates(call, op, entry_points)
            elif call["mechanism"] == "http_client":
                found, why = _http_candidates(call, op, entry_points, annotated, host)
            else:
                found, why = _grpc_candidates(call, op, entry_points)
            if not found:
                unmatched.append({**base, "reason": why, "resolution": op.get("resolution")})
                continue
            best = min(_rank(ep, call) for ep, _, _ in found)
            kept = sorted([f for f in found if _rank(f[0], call) == best], key=lambda f: f[0]["id"])
            for ep, method, confidence in kept:
                if len(kept) > 1:
                    confidence = min(confidence, 0.5)  # ambiguous: several entry points answer equally
                # One edge per call site, operation and entry point: two
                # invocations of one client (a code and a config endpoint)
                # claiming the same call site are one call.
                edge_key = "\n".join([str(call["project_id"]), str(site.get("filePath")), str(site.get("lineStart")), label, ep["id"]])
                edges.append({
                    **base,
                    "edgeId": hashlib.sha256(edge_key.encode()).hexdigest()[:32],
                    "calleeRepositoryId": str(ep["repository_id"]), "calleeRepositorySlug": ep["repository_slug"],
                    "calleeProjectId": str(ep["project_id"]), "calleeProjectPath": ep["project_path"],
                    "entryPointId": ep["id"], "entryPointKind": ep["kind"], "served": entry_operation(ep)[0],
                    "matchMethod": method, "confidence": confidence,
                    "sameRepository": ep["repository_id"] == call["repository_id"],
                })
    # Calls are walked in invocation id order, so the first invocation kept
    # for an edge is the lowest; the others are listed beside it.
    unique: dict = {}
    for e in edges:
        if e["edgeId"] in unique:
            unique[e["edgeId"]]["invocationIds"].append(e["invocationId"])
        else:
            unique[e["edgeId"]] = {**e, "invocationIds": [e["invocationId"]]}
    edges = [unique[k] for k in sorted(unique, key=lambda k: (unique[k]["callerRepositorySlug"], unique[k]["callerProjectPath"],
                                                              unique[k]["callSite"]["filePath"] or "", unique[k]["callSite"]["lineStart"] or 0, k))]
    seen_unmatched: dict = {}
    for u in unmatched:
        key = (u["callerProjectId"], u["callSite"]["filePath"], u["callSite"]["lineStart"], u["operation"], u["reason"])
        seen_unmatched.setdefault(key, u)
    unmatched = sorted(seen_unmatched.values(), key=lambda u: (u["callerRepositorySlug"], u["callerProjectPath"], u["callSite"]["filePath"] or "",
                                                               u["callSite"]["lineStart"] or 0, u["operation"], u["invocationId"]))

    by_entry: dict = defaultdict(list)
    for e in edges:
        by_entry[e["entryPointId"]].append(e)
    entries = []
    for ep in sorted(entry_points, key=lambda e: (e["repository_slug"], e["project_path"], e["id"])):
        if ep["kind"] not in INTEGRATION_KINDS:
            continue
        label, matchable = entry_operation(ep)
        callers = by_entry.get(ep["id"], [])
        entries.append({
            "entryPointId": ep["id"], "kind": ep["kind"], "operation": label, "matchable": matchable,
            "repositoryId": str(ep["repository_id"]), "repositorySlug": ep["repository_slug"],
            "projectId": str(ep["project_id"]), "projectPath": ep["project_path"],
            "internalCaller": INTERNAL_CALLER_FOUND if callers else NO_INTERNAL_CALLER_FOUND,
            "callerCount": len({(c["callerProjectId"], c["callSite"]["filePath"], c["callSite"]["lineStart"]) for c in callers}),
            "crossRepositoryCallerCount": len({(c["callerProjectId"], c["callSite"]["filePath"], c["callSite"]["lineStart"])
                                               for c in callers if not c["sameRepository"]}),
        })
    return {"edges": edges, "unmatched": unmatched, "entryPoints": entries}


def integration_by_application(integration: dict) -> list[dict]:
    """The integration view (Part I3): per application (project), the
    operations it calls — matched or not, and why not — and the operations of
    its that the estate calls, with whether an internal caller was found."""
    apps: dict = {}

    def app(repository_slug, project_path, repository_id, project_id):
        return apps.setdefault((repository_slug, project_path), {
            "repositorySlug": repository_slug, "projectPath": project_path, "repositoryId": repository_id,
            "projectId": project_id, "calls": {}, "exposes": []})

    for e in integration["edges"]:
        a = app(e["callerRepositorySlug"], e["callerProjectPath"], e["callerRepositoryId"], e["callerProjectId"])
        key = (e["callSite"]["filePath"] or "", e["callSite"]["lineStart"] or 0, e["operation"], e["invocationId"])
        entry = a["calls"].setdefault(key, {"operation": e["operation"], "mechanism": e["mechanism"], "invocationId": e["invocationId"],
                                            "callSite": e["callSite"], "targets": [], "unmatchedReason": None})
        entry["targets"].append({k: e[k] for k in ("entryPointId", "served", "calleeRepositorySlug", "calleeProjectPath",
                                                   "matchMethod", "confidence", "sameRepository")})
    for u in integration["unmatched"]:
        a = app(u["callerRepositorySlug"], u["callerProjectPath"], u["callerRepositoryId"], u["callerProjectId"])
        key = (u["callSite"]["filePath"] or "", u["callSite"]["lineStart"] or 0, u["operation"], u["invocationId"])
        a["calls"].setdefault(key, {"operation": u["operation"], "mechanism": u["mechanism"], "invocationId": u["invocationId"],
                                    "callSite": u["callSite"], "targets": [], "unmatchedReason": u["reason"]})
    callers_of: dict = defaultdict(list)
    for e in integration["edges"]:
        callers_of[e["entryPointId"]].append({k: e[k] for k in ("callerRepositorySlug", "callerProjectPath", "callSite", "operation",
                                                                "matchMethod", "confidence", "sameRepository")})
    for ep in integration["entryPoints"]:
        a = app(ep["repositorySlug"], ep["projectPath"], ep["repositoryId"], ep["projectId"])
        a["exposes"].append({**ep, "callers": callers_of.get(ep["entryPointId"], [])})

    out = []
    for key in sorted(apps):
        a = apps[key]
        out.append({**a, "calls": [a["calls"][k] for k in sorted(a["calls"])],
                    "exposes": sorted(a["exposes"], key=lambda x: (x["operation"], x["entryPointId"]))})
    return out


# ---------- the package estate (Part D) ----------


def _version_key(version: str | None):
    parts = re.split(r"[.\-+]", version or "")
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts]


def build_package_estate(assessments: list[dict]) -> list[dict]:
    """One row per package id across the estate. `assessments` are step 6's
    package_assessments rows with repository_slug and project_path added."""
    by_id: dict = defaultdict(list)
    for a in assessments:
        by_id[a["package_id"].lower()].append(a)
    rows = []
    for uses in by_id.values():
        names = Counter(a["package_id"] for a in uses)
        versions = Counter(a["current_version"] for a in uses if a.get("current_version"))
        per_repository: dict = defaultdict(set)
        for a in uses:
            if a.get("current_version"):
                per_repository[a["repository_slug"]].add(a["current_version"])
        recommended = Counter(a["recommended_version"] for a in uses if a.get("recommended_version"))
        members = {}
        for a in uses:
            for m in a.get("breaking_members") or []:
                members[(m.get("type"), m.get("member") or "", m.get("change"))] = {
                    "type": m.get("type"), "member": m.get("member"), "change": m.get("change")}
        rows.append({
            "packageId": sorted(names, key=lambda n: (-names[n], n))[0],
            "repositoryCount": len({a["repository_slug"] for a in uses}),
            "repositories": sorted({a["repository_slug"] for a in uses}),
            "projectCount": len({(a["repository_slug"], a["project_path"]) for a in uses}),
            "projects": sorted({f"{a['repository_slug']}:{a['project_path']}" for a in uses}),
            "versionsInUse": {v: versions[v] for v in sorted(versions, key=_version_key)},
            "estateDrift": len(versions) > 1,
            # Repositories disagree with each other — the case step 6's
            # per-repository drift cannot see (Newtonsoft.Json 12 here, 13 there).
            "crossRepositoryDrift": len({frozenset(v) for v in per_repository.values()}) > 1,
            # The version most uses were recommended; ties to the highest.
            "recommendedVersion": sorted(recommended, key=lambda v: (-recommended[v], [(-x[0], -x[1], x[2]) for x in _version_key(v)]))[0] if recommended else None,
            "outcomes": dict(sorted(Counter(a["outcome"] for a in uses).items())),
            "breakingMembers": [members[k] for k in sorted(members, key=lambda k: (k[0] or "", k[1], k[2] or ""))],
            "flags": {
                "deprecated": any(a.get("deprecated") for a in uses),
                "vulnerable": any(a.get("vulnerable") for a in uses),
                "notInClientFeed": any(a.get("not_in_client_feed") for a in uses),
            },
            "feedSources": sorted({a["feed_source"] for a in uses if a.get("feed_source")}),
        })
    rows.sort(key=lambda r: (-r["repositoryCount"], -r["projectCount"], r["packageId"].lower()))
    return rows


# ---------- the dependency graph (Part E) ----------


def build_graph(projects: list[dict], references: list[dict], packages: list[dict], client_feed_packages: set) -> dict:
    """Nodes are projects; intra-repository edges come from project references
    and cross-repository edges from a package id that names a project in
    another repository (its assembly name or project name). Packages answered
    by a client feed are the likeliest internal packages; the match is the
    same for any package, the flag says which it was."""
    by_id = {p["id"]: p for p in projects}
    edges: dict = {}
    for ref in references:
        source, target = by_id.get(ref["source_project_id"]), by_id.get(ref["referenced_project_id"])
        if source and target:
            edges[(source["id"], target["id"], "project_reference")] = {
                "from": source["id"], "to": target["id"], "kind": "project_reference",
                "crossRepository": source["repository_id"] != target["repository_id"], "via": None, "clientFeed": False}

    provides: dict = defaultdict(list)
    for p in projects:
        for name in {p.get("assembly_name"), p.get("name")}:
            if name:
                provides[name.lower()].append(p)
    for pkg in packages:
        consumer = by_id.get(pkg["project_id"])
        if consumer is None:
            continue
        for provider in provides.get(pkg["package_name"].lower(), []):
            if provider["repository_id"] == consumer["repository_id"]:
                continue  # inside one repository that is a project reference's job
            edges[(consumer["id"], provider["id"], "internal_package")] = {
                "from": consumer["id"], "to": provider["id"], "kind": "internal_package", "crossRepository": True,
                "via": pkg["package_name"], "clientFeed": pkg["package_name"].lower() in client_feed_packages}

    edge_list = [edges[k] for k in sorted(edges, key=lambda k: (str(k[0]), str(k[1]), k[2]))]

    # Shared libraries (E2): depended on from two or more repositories.
    consumers: dict = defaultdict(set)
    for e in edge_list:
        consumers[e["to"]].add(e["from"])
    shared = []
    for target, sources in consumers.items():
        repos = {by_id[s]["repository_id"] for s in sources}
        if len(repos) >= 2:
            shared.append({"projectId": target, "consumerRepositoryCount": len(repos), "consumerProjectCount": len(sources),
                           "consumers": sorted(sources, key=str)})
    shared.sort(key=lambda s: (-s["consumerRepositoryCount"], -s["consumerProjectCount"], str(s["projectId"])))

    return {"edges": edge_list, "sharedLibraries": shared, "cycles": find_cycles([p["id"] for p in projects], edge_list, by_id)}


def find_cycles(nodes: list, edges: list[dict], by_id: dict) -> list[dict]:
    """Every strongly connected component with more than one project, or a
    project that depends on itself (E3) — Tarjan, iterative."""
    graph: dict = defaultdict(list)
    for e in edges:
        graph[e["from"]].append(e["to"])
    index, low, on_stack, stack, components, counter = {}, {}, set(), [], [], [0]

    for root in sorted(nodes, key=str):
        if root in index:
            continue
        work = [(root, iter(sorted(graph[root], key=str)))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is not None:
                if child not in index:
                    index[child] = low[child] = counter[0]
                    counter[0] += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph[child], key=str))))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1 or node in graph[node]:
                    components.append(sorted(component, key=str))

    cycles = []
    for members in sorted(components, key=lambda m: [str(x) for x in m]):
        cycles.append({
            "cycleId": hashlib.sha256("\n".join(str(m) for m in members).encode()).hexdigest()[:16],
            "members": members,
            "crossRepository": len({by_id[m]["repository_id"] for m in members}) > 1,
        })
    return cycles


# ---------- origin reconciliation (E4) ----------


def reconcile_origins(entry_points: list[dict], projects: list[dict]) -> list[dict]:
    """A `framework`-origin entry point whose handler type lives in a project
    of another repository is the estate's own code (step 4 could not see
    across repositories). Matched by namespace: the longest root namespace or
    assembly name of another repository's project that prefixes the handler
    type at a dot boundary. Step 4's rows are never changed."""
    prefixes = []
    for p in projects:
        for name in {p.get("root_namespace"), p.get("assembly_name")}:
            if name:
                prefixes.append((name, p))
    prefixes.sort(key=lambda x: (-len(x[0]), x[0], str(x[1]["id"])))
    out = []
    for ep in sorted(entry_points, key=lambda e: e["id"]):
        handler = ep.get("handler_type") or ""
        if ep.get("origin") != "framework" or not handler:
            continue
        for name, project in prefixes:
            if project["repository_id"] == ep["repository_id"]:
                continue
            if handler == name or handler.startswith(name + "."):
                out.append({
                    "entryPointId": ep["id"], "originalOrigin": "framework", "reconciledOrigin": "application",
                    "declaringRepositoryId": str(project["repository_id"]), "declaringProjectId": str(project["id"]),
                    "reason": f"handler {handler} is declared by {project['repository_slug']}:{project['relative_path']} ({name})",
                })
                break
    return out


# ---------- the context map (Part F) ----------


def _dsl_id(prefix: str, value: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return f"{prefix}_{ident}"[:60] + "_" + hashlib.sha256(value.encode()).hexdigest()[:6]


def _dsl_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


_MECHANISM_LABEL = {"soap_client": "SOAP", "http_client": "HTTP", "database": "Database", "secret_store": "Secret store",
                    "message_queue": "Messaging", "file_share": "File share", "grpc_client": "gRPC"}


def build_context_map(engagement_name: str, repositories: list[str], hosts: list[dict]) -> dict:
    """Structurizr DSL for a system-landscape view: the estate's repositories
    as software systems inside one 'Engagement estate' group (one box per
    repository keeps fifty legible), external hosts as External systems, and
    relationships labelled by mechanism and binding. Internal hosts become
    repository-to-repository relationships. Returns the model too, so the UI
    can draw it without parsing DSL."""
    repo_ids = {slug: _dsl_id("repo", slug) for slug in sorted(repositories)}
    systems = [{"id": repo_ids[slug], "name": slug, "kind": "repository"} for slug in sorted(repositories)]
    relationships = []
    external_ids = {}
    for host in sorted(hosts, key=lambda h: h["host"]):
        if host.get("noLongerCalled"):
            continue
        label = ", ".join(_MECHANISM_LABEL.get(m, m) for m in host["mechanisms"])
        if host["bindings"]:
            label += " over " + ", ".join(host["bindings"])
        if host["classification"] == "internal":
            for service in host["services"]:
                for target in service["internalTargets"]:
                    for caller in service["callingRepositories"]:
                        if caller == target["repositorySlug"]:
                            continue  # a repository calling itself is not a context-level relationship
                        relationships.append({"from": repo_ids[caller], "to": repo_ids[target["repositorySlug"]], "label": label})
            continue
        ident = external_ids.setdefault(host["host"], _dsl_id("ext", host["host"]))
        systems.append({"id": ident, "name": host["host"], "kind": "external", "loopback": host["loopback"],
                        "requiresBackendChange": host["requiresBackendChange"]})
        for caller in host["callingRepositories"]:
            projects = sum(1 for p in host["callingProjects"] if p.startswith(caller + ":"))
            relationships.append({"from": repo_ids[caller], "to": ident, "label": f"{label} — {projects} project(s)"})
    unique = {(r["from"], r["to"], r["label"]): r for r in relationships}
    relationships = [unique[k] for k in sorted(unique)]

    lines = ["workspace {", "  model {", f'    group "{_dsl_text(engagement_name)} estate" {{']
    for s in systems:
        if s["kind"] == "repository":
            lines.append(f'      {s["id"]} = softwareSystem "{_dsl_text(s["name"])}" "Repository in the engagement" {{ tags "Estate" }}')
    lines.append("    }")
    for s in systems:
        if s["kind"] == "external":
            tags = '"External"' + (' "Development address"' if s["loopback"] else "") + (' "Backend change"' if s["requiresBackendChange"] else "")
            lines.append(f'    {s["id"]} = softwareSystem "{_dsl_text(s["name"])}" "External" {{ tags {tags} }}')
    for r in relationships:
        lines.append(f'    {r["from"]} -> {r["to"]} "{_dsl_text(r["label"])}"')
    lines += [
        "  }",
        "  views {",
        "    systemLandscape estate {",
        "      include *",
        "      autolayout lr",
        "    }",
        "    styles {",
        '      element "Estate" { background #6d28d9 color #ffffff }',
        '      element "External" { background #737373 color #ffffff }',
        '      element "Backend change" { border dashed }',
        "    }",
        "  }",
        "}",
    ]
    return {"dsl": "\n".join(lines) + "\n", "systems": systems, "relationships": relationships}
