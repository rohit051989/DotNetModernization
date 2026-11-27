"""Everything the input generator needs, read from discovery and the catalog (36-COPILOT-ENHANCED-CONVERSION
Part D). One JSON-serialisable model, sorted, so rendering is a pure function of it and two runs over the
same data produce the same files.

Only what discovery stored is read. Of the catalog, only engine-facing text is read: each item's and resolution's
`engine_guidance` (36-COPILOT-ENHANCED-CONVERSION Part K), and names. Author-facing descriptions, target descriptions
and notes are never read here, so they cannot reach a generated file; an item's description is parsed only for its
ordering rules, which become prerequisites written by the renderer. Discovery already follows the secrets rules (29-ENTRY-POINT-AND-OUTBOUND-
INVENTORIES C5, 21-APPLICATION-FINGERPRINTING Part G): a connection string is a name, a sensitive key is a
key path. Nothing here opens a configuration file; the generator's secret check reads them only to prove
their values did not leak (app.engine.inputs.secrets). The repository's YAML files are read for the deployment
mechanisms it already has (app.engine.deployment_assets), and only their file names and kinds are kept.
"""
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.conversion import planner

# "Conversion ordering (docs/28 Part E): ... runs BEFORE x / runs AFTER x / runs as ONE UNIT with x / runs FIRST".
# FIRST (2026-11-25): before every other change of the repository, for a change that prepares the projects others
# retarget (the SDK-style project file).
ORDERING = re.compile(r"(?i)runs\s+(?:as\s+)?(?:(BEFORE|AFTER|ONE UNIT with)\s+([a-z0-9-]+)|(FIRST)\b)")

# Version and platform changes that compile and run but give a different result: the delta categories
# the plugin's uplift_checks judges (Behavioral-silent). Item ids whose occurrences are such deltas on the
# move to a Linux container. Everything else found is listed, not judged.
SILENT_ITEMS = {
    "datetime-now-usage": "Local time is the container's (UTC by default), not the Windows server's zone",
    "encoding-default": "The default encoding differs between .NET Framework on Windows and .NET on Linux",
}


def _ordering(description: str | None) -> list[dict]:
    rules = []
    for paragraph in (description or "").split("\n"):
        if not paragraph.lower().startswith("conversion ordering"):
            continue
        for relation, other, first in ORDERING.findall(paragraph):
            if first:
                rules.append({"relation": "first", "item": None})
                continue
            rules.append({"relation": {"BEFORE": "before", "AFTER": "after"}.get(relation.upper(), "together"),
                          "item": other})
    return rules


def _lines(evidence: list | None) -> list[dict]:
    out = []
    for e in evidence or []:
        if e.get("line_start") is None:
            continue
        # `signal`: which signal located the line, for an item whose places differ by it (render.plan_item: the
        # signed-in user's checks versus other directory lookups, 2026-11-26).
        out.append({"line": e["line_start"], "value": e.get("value"), "member": e.get("member"),
                    "type": e.get("declaring_type"), "certainty": e.get("certainty"), "signal": e.get("signal_name")})
    return sorted(out, key=lambda x: (x["line"], x["value"] or ""))


KEEP_VAULT_DELIVERY = "keep-existing-vault-delivery"

# solution-discovery's project_format, in the engine's words.
PROJECT_FORMAT = {"legacy_msbuild": "old-style", "sdk_style": "SDK-style", "unknown": "unknown"}


def _in_scope_entry(project: str, bindings: list | None, sites: list | None, in_scope, excluded: set) -> tuple[bool, list]:
    """(keep the outbound entry, its in-scope bindings). A binding counts where its configuration file is in scope, a
    call site where its source file is; one with no file belongs to the entry's project. An entry is kept when it has an
    in-scope binding or an in-scope call site (related issue 3: a descoped repository's addendum listed configuration
    files of dozens of projects outside the scope)."""
    def owned(entry: dict) -> bool:
        path = (entry or {}).get("sourceFile")
        return in_scope(path) if path else project not in excluded
    kept = [b for b in bindings or [] if owned(b)]
    calls = [s for s in sites or [] if owned(s)]
    if not bindings and not sites:
        return project not in excluded, kept
    return bool(kept or calls), kept


def assembly_references(db: Session, repository_id, excluded: set, declared: dict[str, set], target: str | None) -> list[dict]:
    """The in-scope projects' assembly references that no declared package stands for (dependency-hierarchy's
    assembly_reference edges; a framework assembly is the target framework's own and not listed). Each: {project, name,
    version, kind, path, exists, package, verdict, why, lookup}. `kind`: "packages folder" (a HintPath into
    packages/<id>.<version>/: that NuGet package, not declared), "repository" (a DLL in the repository), "GAC", or
    "outside the repository". `verdict`: "package" (look it up and declare it as that package), "windows-only" (needs a
    replacement on Linux: compatibility/windows_only_assemblies.yaml) or "unknown" (check it builds and loads on Linux)."""
    from app.compatibility import assemblies

    rows = db.execute(text("""
        SELECT p.relative_path, a.name, a.detail->'assembly'->>'version', a.detail->'assembly'->>'location',
               a.detail->'assembly'->>'path', a.detail->'assembly'->>'exists'
        FROM hierarchy_edges e
        JOIN hierarchy_nodes pn ON pn.repository_id = e.repository_id AND pn.node_id = e.from_node AND pn.node_type = 'project'
        JOIN projects p ON p.id = pn.project_id
        JOIN hierarchy_nodes a ON a.repository_id = e.repository_id AND a.node_id = e.to_node AND a.node_type = 'assembly'
        WHERE e.repository_id = :r AND e.kind = 'assembly_reference'
        ORDER BY p.relative_path, a.name"""), {"r": repository_id}).all()
    out = []
    for project, name, version, location, path, exists in rows:
        if project in excluded or location == "framework":
            continue
        package = paths_restored_package(path)
        if package and package[0].lower() in declared.get(project, set()):
            continue                                    # the declared package stands for it
        windows = assemblies.windows_only(name)
        if package:
            kind, verdict = "packages folder", "package"
            why = f"the NuGet package {package[0]} {package[1]}, referenced by path but not declared"
        else:
            kind = {"repository": "repository", "gac": "GAC", "outside_repository": "outside the repository"}.get(
                location or "", location or "unknown")
            verdict, why = ("windows-only", windows) if windows else ("unknown", None)
        if package and windows:
            verdict, why = "windows-only", f"{why}; {windows}"
        out.append({"project": project, "name": name, "version": version, "kind": kind, "path": path,
                    "exists": None if exists is None else exists == "true",
                    "package": {"id": package[0], "version": package[1]} if package else None,
                    "verdict": verdict, "why": why,
                    "lookup": _lookup(db, package[0], package[1], target) if package else None})
    return out


def packages_config(db: Session, repository_id, excluded: set) -> list[dict]:
    """Each in-scope packages.config project's packages, and whether the move to PackageReference keeps each as a direct
    reference (packages-config, 2026-11-25), from dependency-hierarchy's packages_config and package_dependency edges.
    A package another listed package depends on is left out only when restore resolves the version packages.config
    pinned; otherwise it is kept at the pinned version, since restore takes the lowest version the ranges allow and a
    pinned, higher one is often a security fix. Each: {project, packages: [{id, version, action, why}]}, `action`
    "keep" (a direct dependency, or restore would resolve another version), "leave out" (restore resolves the pinned
    version) or "keep (not known)" (a listed package's own dependencies could not be checked)."""
    from app.engine.verifier.packages import version_key

    declared: dict[str, dict[str, dict]] = {}
    for project, node, name, version, deps_checked in db.execute(text("""
            SELECT p.relative_path, k.node_id, k.name, k.detail->'package'->>'version',
                   k.detail->'package'->>'dependenciesResolution' IS NOT NULL
            FROM hierarchy_edges e
            JOIN hierarchy_nodes pn ON pn.repository_id = e.repository_id AND pn.node_id = e.from_node AND pn.node_type = 'project'
            JOIN projects p ON p.id = pn.project_id
            JOIN hierarchy_nodes k ON k.repository_id = e.repository_id AND k.node_id = e.to_node AND k.node_type = 'package'
            WHERE e.repository_id = :r AND e.kind = 'packages_config'
            ORDER BY p.relative_path, lower(k.name)"""), {"r": repository_id}):
        if project not in excluded:
            declared.setdefault(project, {})[name.lower()] = {"node": node, "id": name, "version": version,
                                                              "checked": bool(deps_checked)}
    depends: dict[str, list[tuple[str, str]]] = {}          # package node -> [(dependency id, version restore chooses)]
    for node, name, version in db.execute(text("""
            SELECT e.from_node, d.name, d.detail->'package'->>'version' FROM hierarchy_edges e
            JOIN hierarchy_nodes d ON d.repository_id = e.repository_id AND d.node_id = e.to_node
            WHERE e.repository_id = :r AND e.kind = 'package_dependency'"""), {"r": repository_id}):
        depends.setdefault(node, []).append((name.lower(), version))

    out = []
    for project, packages in sorted(declared.items()):
        unchecked = sorted(p["id"] for p in packages.values() if not p["checked"])
        listed = []
        for key, package in sorted(packages.items()):
            through = [(other, version) for other in packages.values() if other is not package
                       for dep, version in depends.get(other["node"], []) if dep == key and version]
            pinned = package["version"]
            if through and pinned:
                chosen = max((v for _, v in through), key=version_key)       # every range must hold: the highest minimum
                names = ", ".join(f"`{o['id']}` {o['version']}" for o, _ in through)
                if version_key(chosen) == version_key(pinned):
                    action, why = "leave out", f"restore resolves the same version through {names}"
                else:
                    action, why = "keep", f"restore would resolve {chosen} through {names}"
            elif unchecked:
                action, why = "keep (not known)", ("the dependencies of " + ", ".join(f"`{u}`" for u in unchecked)
                                                   + " could not be checked")
            else:
                action, why = "keep", "no other package listed here depends on it"
            listed.append({"id": package["id"], "version": pinned, "action": action, "why": why})
        out.append({"project": project, "packages": listed})
    return out


# The SSIS resolutions that reimplement a package in C# (catalog: ssis-package). Their place is the code that loads and
# runs the package, not the package project: the .dtproj and .dtsx are the specification, read and never changed.
SSIS_ITEM = "ssis-package"
SSIS_REIMPLEMENTING = ("csharp-worker-container", "csharp-sql-pushdown")
SSIS_RUNTIME = "Microsoft.SqlServer.ManagedDTS"


def ssis_places(db: Session, repository_id, excluded: set, files: list[str], item: dict, references: list[dict]) -> None:
    """For an ssis-package item whose chosen resolution reimplements the package: its places become the code that
    executes the package (registry 1.16.0's SSIS_PACKAGE_EXECUTION, with the member, and each in-scope project that
    references the SSIS runtime by path); its impact lists the .dtproj and each .dtsx as `reference` (read, never
    changed), the executing files and project files as `update`, and as `create` the new code (a path pattern per
    package) and the test project beside each executing project, certainty `expected`. No executing code in scope: left
    as it was."""
    res = item.get("resolution") or {}
    if item["id"] != SSIS_ITEM or res.get("id") not in SSIS_REIMPLEMENTING:
        return
    places: list[dict] = []
    for project, source, value, evidence in db.execute(text("""
            SELECT p.relative_path, s.source_path, s.value, s.evidence FROM fingerprint_signals s
            JOIN projects p ON p.id = s.project_id
            WHERE s.repository_id = :r AND s.signal_name = 'SSIS_PACKAGE_EXECUTION'
            ORDER BY p.relative_path, s.source_path, s.value"""), {"r": repository_id}):
        if project in excluded:
            continue
        lines = [{"line": e.get("lineStart"), "value": value, "member": e.get("member"), "type": e.get("declaringType"),
                  "certainty": None} for e in evidence or [] if e.get("lineStart") is not None]
        found = next((o for o in places if o["project"] == project and o["file"] == source), None)
        if found is None:
            places.append({"project": project, "file": source, "value": value, "certainty": "confirmed", "lines": lines})
        else:
            found["lines"] = sorted(found["lines"] + lines, key=lambda x: (x["line"], x["value"] or ""))
    executing = {o["project"] for o in places}
    for project in sorted({a["project"] for a in references if a["name"].split(",")[0].strip().lower() == SSIS_RUNTIME.lower()}
                          - executing):
        places.append({"project": project, "file": None, "value": f"references {SSIS_RUNTIME}", "certainty": "confirmed",
                       "lines": []})
    if not places:
        return
    packages = sorted({o["project"] for o in item["occurrences"]})
    impact = []
    for dtproj in packages:
        folder = dtproj.rsplit("/", 1)[0] + "/" if "/" in dtproj else ""
        for f in [dtproj] + sorted(f for f in files if f.startswith(folder) and f.lower().endswith(".dtsx")):
            impact.append({"project": dtproj, "resolution": res["id"], "action": "reference", "file": f, "proposed": None,
                           "certainty": "confirmed", "reasons": ["the package is the specification: read it, never change it"]})
    stems = sorted({f.rsplit("/", 1)[-1][:-len(".dtsx")] for f in files if f.lower().endswith(".dtsx")
                    and any(f.startswith(d.rsplit("/", 1)[0] + "/") for d in packages if "/" in d)}) or ["Package"]
    for project in sorted({o["project"] for o in places}):
        folder = project.rsplit("/", 1)[0] if "/" in project else ""
        name = project.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        updated = sorted({o["file"] for o in places if o["project"] == project and o["file"]}) + [project]
        for f in updated:
            impact.append({"project": project, "resolution": res["id"], "action": "update", "file": f, "proposed": None,
                           "certainty": "confirmed", "reasons": ["it loads or runs the package, or references the SSIS runtime"]})
        for stem in stems:
            impact.append({"project": project, "resolution": res["id"], "action": "create", "file": None,
                           "proposed": f"{folder + '/' if folder else ''}{stem}/*.cs", "certainty": "expected",
                           "reasons": [f"the C# that does what {stem}.dtsx does"]})
        parent = folder.rsplit("/", 1)[0] + "/" if "/" in folder else ""
        impact.append({"project": project, "resolution": res["id"], "action": "create", "file": None,
                       "proposed": f"{parent}{name}.Tests/{name}.Tests.csproj", "certainty": "expected",
                       "reasons": ["its unit tests, a test project beside it that joins the conversion's solution"]})
    item["occurrences"] = places
    item["impact"] = impact
    item["package_projects"] = packages


PACKAGE_REPLACEMENT = "package-replacement-required"
NO_SUGGESTED = "no suggested replacement"


def framework_only_packages(occurrences: dict[str, list[dict]], references: list[dict]) -> None:
    """Gap 4 (2026-11-26). A package version whose only assets are .NET Framework ones is not support for the target
    framework: it resolves only through NuGet's .NET Framework fallback (NU1701) and still needs .NET Framework at run
    time. An undeclared one referenced by path (a HintPath into packages/) gets the verdict "fallback-only" and becomes a
    place of the package replacement item, on its project file; a declared one is already a place of it
    (dependency-assessment finds no compatible version). Either names the known replacement
    (compatibility/framework_only_packages.yaml) where the publisher names none. Changes `occurrences` and `references`
    in place."""
    from app.compatibility import assemblies
    from app.conversion.frameworks import FALLBACK_ONLY

    found = occurrences.setdefault(PACKAGE_REPLACEMENT, [])
    for a in references:
        if a["verdict"] != "package" or not (a.get("lookup") or {}).get("fallback_only"):
            continue
        a["verdict"] = "fallback-only"
        package = a["package"]
        replacement = assemblies.known_replacement(package["id"], package["version"])
        a["replacement"] = replacement
        value = (f"{package['id']} {package['version']}: {FALLBACK_ONLY}; "
                 + (f"replacement {replacement}" if replacement else NO_SUGGESTED))
        if not any(o["project"] == a["project"] and (o.get("value") or "").split(" ")[0].lower() == package["id"].lower()
                   for o in found):
            found.append({"project": a["project"], "file": a["project"], "value": value, "certainty": "confirmed",
                          "lines": []})
    for o in found:
        value = o.get("value") or ""
        if value.endswith(NO_SUGGESTED):
            package_id, _, rest = value.partition(" ")
            replacement = assemblies.known_replacement(package_id, rest.split(":")[0].strip())
            if replacement:
                o["value"] = value[: -len(NO_SUGGESTED)] + f"replacement {replacement}"
    if not found:
        occurrences.pop(PACKAGE_REPLACEMENT)
    else:
        found.sort(key=lambda o: (o["project"], o.get("file") or "", o.get("value") or ""))


# Gap 5 (2026-11-26): the image and manifest items, and the application items whose chosen approach decides whether a
# .NET Framework application lands in a container on the target framework.
CONTAINER_ITEMS = ("missing-dockerfile", "missing-ocp4-manifests", "missing-health-endpoint")
HOSTING_ITEMS = ("asmx-service", "aspnet-webforms", "fx-aspnet-mvc", "wcf-service", "wcf-service-host",
                 "console-batch-job", "windows-service", "ssis-package")


def containers_needed(items: list[dict], frameworks: dict[str, str | None]) -> list[dict]:
    """A .NET Framework application needs an image and manifests only when its conversion lands it in a container on the
    target framework: an application item on its project whose chosen approach is container-ready, and none that keeps
    it on Windows. Detection cannot know the decision, so it raises the image and manifest items on every such
    application, and the conversion keeps them only there. A modern application keeps them as before. Their phase
    (platform and deployment) puts them after the application's own conversion."""
    from app.conversion import frameworks as fw

    moving: dict[str, bool] = {}
    for item in items:
        res = item.get("resolution")
        if item["id"] not in HOSTING_ITEMS or not res:
            continue
        for o in item["occurrences"]:
            moving[o["project"]] = moving.get(o["project"], True) and bool(res.get("container_ready"))
    out = []
    for item in items:
        if item["id"] in CONTAINER_ITEMS:
            kept = [o for o in item["occurrences"]
                    if not fw.is_netfx(frameworks.get(o["project"]) or "") or moving.get(o["project"], False)]
            if not kept:
                continue
            item = {**item, "occurrences": kept}
        out.append(item)
    return out


# 1c (2026-11-26): what keeps a consumer of a class library on .NET Framework: a chosen approach that leaves the project
# on .NET Framework, or runs the existing application beside its new one (the incremental adapters).
LIBRARY_ITEM = "fx47-class-library"
BRIDGE = "netstandard20-bridge"
DIRECT = "net10-class-library"
STAYS_ON_FRAMEWORK = frozenset({
    "keep-old-style-project", "keep-packages-config", "aspnetcore-incremental-adapters",
    "msmq-usage-remain-windows-hosted", "package-replacement-remain-windows-hosted", "keep-project-on-windows",
    "wcf-service-remain-windows-hosted", "wcf-host-remain-windows-hosted", "windows-service-remain-windows-hosted",
    "linq-to-sql-remain-windows-hosted", "system-web-in-library-remain-windows-hosted", "wif-remain-windows-hosted",
    "windows-workflow-remain-windows-hosted",
})


def class_library_recommendations(items: list[dict], references: list[tuple[str, str]], left_out: set[str]) -> list[dict]:
    """Each .NET Framework class library of the conversion (the library item's places) with the resolution its
    consumers call for: the direct retarget when every consumer is in scope and moving to the target framework, the
    bridge when one stays on .NET Framework (left out of the scope or not converted by this track, a chosen approach
    that keeps it there, or a library itself on the bridge). [{project, recommended, reason, consumers, staying}]"""
    library = next((i for i in items if i["id"] == LIBRARY_ITEM), None)
    if library is None:
        return []
    libraries = sorted({o["project"] for o in library["occurrences"]})
    consumers: dict[str, list[str]] = {}
    for source, target in references:
        if target in libraries and source not in consumers.setdefault(target, []):
            consumers[target].append(source)
    stays: dict[str, str] = {}
    for item in items:
        res = item.get("resolution") or {}
        if res.get("id") in STAYS_ON_FRAMEWORK:
            for o in item["occurrences"]:
                stays.setdefault(o["project"], f"{item['name']}: {res['name']}")
    for project in sorted(left_out):
        stays.setdefault(project, "outside this conversion's scope")
    bridged: set[str] = set()
    changed = True
    while changed:              # a library on the bridge keeps building for .NET Framework, and so must its own libraries
        changed = False
        for lib in libraries:
            if lib not in bridged and any(c in stays or c in bridged for c in consumers.get(lib, [])):
                bridged.add(lib)
                changed = True
    out = []
    for lib in libraries:
        users = sorted(consumers.get(lib, []))
        staying = [{"project": c, "why": stays.get(c) or "a class library on the bridge"} for c in users
                   if c in stays or c in bridged]
        if staying:
            reason = (f"{len(staying)} of its {len(users)} consumer(s) stay on .NET Framework, so it must keep building "
                      "for .NET Framework: " + "; ".join(f"`{s['project']}` ({s['why']})" for s in staying))
        elif users:
            reason = f"all {len(users)} consumer(s) are in this conversion's scope and move to the target framework"
        else:
            reason = "no project in the repository references it"
        out.append({"project": lib, "recommended": BRIDGE if staying else DIRECT, "reason": reason,
                    "consumers": users, "staying": staying})
    return out


def adopt_recommendation(db: Session, items: list[dict], libraries: list[dict], notes: dict[str, str]) -> list[dict]:
    """With no recorded decision, the library item's approach is the recommended one: the direct retarget when every
    library's consumers move, otherwise the bridge, which every consumer can build against. A recorded decision is never
    overridden: the decision sheet shows the recommendation beside it."""
    library = next((i for i in items if i["id"] == LIBRARY_ITEM), None)
    if library is None or library["decided"] or not libraries:
        return items
    wanted = DIRECT if all(lib["recommended"] == DIRECT for lib in libraries) else BRIDGE
    if (library.get("resolution") or {}).get("id") == wanted:
        return items
    chosen = db.get(models.ItemResolution, wanted)
    if chosen is None or chosen.deleted_at is not None or chosen.status != "active" or chosen.item_id != LIBRARY_ITEM:
        return items
    previous = library["resolution"]
    alternatives = [a for a in library["alternatives"] if a["id"] != wanted]
    if previous:
        alternatives.append({"id": previous["id"], "name": previous["name"], "default": True})
    library = {**library, "recommended": True, "alternatives": sorted(alternatives, key=lambda a: a["id"]), "resolution": {
        "id": chosen.id, "name": chosen.name, "guidance": chosen.engine_guidance, "consumer_impact": chosen.consumer_impact,
        "container_ready": chosen.container_ready, "phase": chosen.phase,
        **({"engagement_note": notes[chosen.id]} if notes.get(chosen.id) else {}),
        **({"confirm_design": True} if chosen.confirm_design else {})}}
    return [library if i["id"] == LIBRARY_ITEM else i for i in items]

def windows_only_left(items: list[dict], references: list[dict]) -> list[dict]:
    """Gap 3 (2026-11-25): a Windows-only assembly that another chosen resolution in this conversion replaces (its entry's
    `replaced_by` in compatibility/windows_only_assemblies.yaml) is not the Windows-only item's: its reference's verdict
    names the work item that replaces it, and the item keeps only the assemblies left, per project (each occurrence's
    value), listed for its decision (`assemblies`). An item with none left is dropped. Returns the items."""
    from app.compatibility import assemblies
    from app.engine.inputs.render import skill_name

    chosen = {i["resolution"]["id"] for i in items if i.get("resolution") and i["resolution"].get("guidance")}
    for a in references:
        if a["verdict"] != "windows-only":
            continue
        replacing = [r for r in assemblies.replaced_by(a["name"]) if r in chosen]
        if replacing:
            a["verdict"], a["replaced_by"] = "replaced", skill_name(replacing[0])
    left: dict[str, list[str]] = {}
    for a in references:
        if a["verdict"] == "windows-only" and a["name"] not in left.setdefault(a["project"], []):
            left[a["project"]].append(a["name"])
    out = []
    for item in items:
        if item["id"] == "windows-only-assembly-reference":
            occurrences = [{**o, "value": "; ".join(left[o["project"]])} for o in item["occurrences"] if left.get(o["project"])]
            if not occurrences:
                continue
            item = {**item, "occurrences": occurrences,
                    "assemblies": sorted({n for o in occurrences for n in o["value"].split("; ")})}
        out.append(item)
    return out


def paths_restored_package(path: str | None) -> tuple[str, str] | None:
    from app.engine import paths
    return paths.restored_package(path)


def _lookup(db: Session, package_id: str, version: str, target: str | None) -> dict:
    """What dependency-assessment's lookups already know of an undeclared package (package_lookup_cache, every feed):
    {known, current_supported, newest_supporting}. Read only: nothing is fetched here, so a package no scan looked up
    is `known: False`, and declaring it lets the next scan assess it."""
    from app.conversion import frameworks

    rows = db.execute(text("SELECT versions, metadata FROM package_lookup_cache WHERE lower(package_id) = lower(:p)"),
                      {"p": package_id}).all()
    if not rows or not target:
        return {"known": bool(rows), "current_supported": None, "newest_supporting": None, "fallback_only": False}
    metadata: dict = {}
    for _, meta in rows:
        for v, m in (meta or {}).items():
            metadata.setdefault(v, m)

    def supported(v: str):
        try:
            return frameworks.supports(metadata.get(v) or {}, target).supported if v in metadata else None
        except ValueError:
            return None
    candidates = sorted((v for v in metadata if supported(v)), key=_version_key)
    def fallback_only(v: str) -> bool:
        try:
            return v in metadata and frameworks.supports(metadata[v] or {}, target).fallback_only
        except ValueError:
            return False
    return {"known": True, "current_supported": supported(version),
            "newest_supporting": candidates[-1] if candidates else None,
            # Gap 4: the referenced version's only assets are .NET Framework ones (frameworks.FALLBACK_ONLY).
            "fallback_only": fallback_only(version)}


def _version_key(version: str) -> tuple:
    core, _, pre = version.partition("-")
    parts = [int(x) if x.isdigit() else 0 for x in core.split(".")]
    return (*parts, *([0] * (4 - len(parts))), pre == "", pre)


def _repository_files(repository: models.Repository) -> list[str]:
    import subprocess

    commit = repository.ingest_commit_sha or "HEAD"
    done = subprocess.run(["git", "-C", repository.local_path, "ls-tree", "-r", "--name-only", commit],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return sorted(done.stdout.splitlines()) if done.returncode == 0 else []


def collect(db: Session, repository: models.Repository) -> dict:
    """The model. A project left out of the conversion's scope (app.scope, Part O) is not in it: not its findings, its
    packages, its framework deltas, its tests, its outbound and SOAP entries' configuration files nor its assembly
    references. `scope` says which were left out and the solution that builds the rest."""
    from app.scope import service as scope_service

    engagement = db.get(models.Engagement, repository.engagement_id)
    r = repository.id
    scope = scope_service.for_conversion(db, repository)
    excluded = set(scope["excluded"])
    every = db.execute(text("SELECT relative_path FROM projects WHERE repository_id = :r"), {"r": r}).scalars().all()
    in_scope = lambda path: not excluded or scope_service.owner(path, every) not in excluded   # noqa: E731

    # Each in-scope project's format (old-style or SDK-style) and whether it manages packages with packages.config, as
    # solution-discovery recorded them: the addendum states both, and a packages.config project heading to .NET 5 and
    # later makes "keep the current package arrangement" a default that cannot work (render.upgrade_options).
    project_frameworks = {p: f for p, f in db.execute(text(
        "SELECT relative_path, target_framework_raw FROM projects WHERE repository_id = :r"), {"r": r})}
    projects = [dict(path=p, framework=f, format=PROJECT_FORMAT.get(fmt, "unknown"), packages_config=bool(pc))
                for p, f, fmt, pc in db.execute(text("""
        SELECT relative_path, target_framework_raw, project_format,
               has_packages_config OR package_management_style IN ('packages_config', 'mixed') FROM projects
        WHERE repository_id = :r ORDER BY relative_path"""), {"r": r})
                if p not in excluded]
    current = sorted({p["framework"] for p in projects if p["framework"]})

    # The project dependency graph, in scope only: {project: [the projects it references]} (solution-discovery's
    # ProjectReference declarations). Within a phase, a project's referenced projects are converted first (render.work_items).
    project_graph: dict[str, list[str]] = {}
    for source, target in db.execute(text("""
            SELECT s.relative_path, t.relative_path FROM project_references r
            JOIN projects s ON s.id = r.source_project_id JOIN projects t ON t.id = r.referenced_project_id
            WHERE s.repository_id = :r ORDER BY 1, 2"""), {"r": r}):
        if source not in excluded and target not in excluded and target not in project_graph.get(source, []):
            project_graph.setdefault(source, []).append(target)

    # An item the engagement decided is not applicable (app.items.applicability) is no work: nothing about it goes into
    # either engine's inputs. Its findings are kept apart, for the verifier to count separately.
    from app.items import applicability
    not_applicable = applicability.not_applicable(db, engagement.id)
    set_aside: dict[str, list[dict]] = {}

    occurrences: dict[str, list[dict]] = {}
    for item_id, project, file_path, value, certainty, evidence in db.execute(text("""
            SELECT o.item_id, p.relative_path, o.file_path, o.value, o.certainty, o.evidence
            FROM item_occurrences o JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :r AND o.detection_state = 'found'
            ORDER BY o.item_id, p.relative_path, o.file_path NULLS FIRST, o.value NULLS FIRST"""), {"r": r}):
        if project in excluded:
            continue
        found = {"project": project, "file": file_path, "value": value, "certainty": certainty, "lines": _lines(evidence)}
        (set_aside if item_id in not_applicable else occurrences).setdefault(item_id, []).append(found)

    decisions = {item_id: resolution_id for item_id, resolution_id in db.execute(text("""
        SELECT item_id, resolution_id FROM engagement_decisions
        WHERE engagement_id = :e AND status <> 'superseded' AND resolution_id IS NOT NULL"""), {"e": engagement.id})}

    impact: dict[str, list[dict]] = {}
    for item_id, project, resolution_id, action, file_path, proposed, certainty, reasons in db.execute(text("""
            SELECT w.item_id, w.project_path, w.resolution_id, w.action, w.file_path, w.proposed_path, w.certainty, w.reasons
            FROM work_item_impacts w JOIN impact_summaries s ON s.repository_id = w.repository_id
             AND s.item_id = w.item_id AND s.project_path = w.project_path AND s.resolution_id = w.resolution_id
            WHERE w.repository_id = :r AND w.source = 'structural' AND s.effective
            ORDER BY w.item_id, w.project_path, COALESCE(w.file_path, w.proposed_path), w.action"""), {"r": r}):
        if project in excluded:
            continue
        impact.setdefault(item_id, []).append({
            "project": project, "resolution": resolution_id, "action": action, "file": file_path,
            "proposed": proposed, "certainty": certainty,
            "reasons": sorted({(x.get("reason") if isinstance(x, dict) else str(x)) or "" for x in reasons or []})})

    # Part N: the repository's own deployment mechanisms (kept, never replaced, unless a decision says so) and the
    # tests that exercise each source file (named in every instruction that touches it).
    files = _repository_files(repository)
    from app.engine import deployment_assets
    vault = deployment_assets.vault_delivery(
        deployment_assets.read_commit(Path(repository.local_path), repository.ingest_commit_sha or "HEAD", files))
    test_mappings = [dict(source_file=s, production_type=pt, test_file=tf, test_class=tc, test_methods=sorted(tm or []))
                     for s, pt, tf, tc, tm in db.execute(text("""
        SELECT source_file, production_type, test_file, test_class, test_methods FROM test_mappings
        WHERE repository_id = :r ORDER BY source_file, test_file, test_class"""), {"r": r}) if in_scope(tf)]

    # The engagement's notes on resolutions (engagement guidance): each carried after its resolution's master guidance.
    notes = {resolution_id: note for resolution_id, note in db.execute(text("""
        SELECT resolution_id, note FROM engagement_resolution_notes WHERE engagement_id = :e AND note IS NOT NULL"""),
        {"e": engagement.id})}

    # Assembly references no declared package stands for (related issue 2): old-style projects reference most third-party
    # code by HintPath, which no package assessment sees.
    declared: dict[str, set] = {}
    for project, package in db.execute(text("""
            SELECT p.relative_path, lower(pp.package_name) FROM project_packages pp JOIN projects p ON p.id = pp.project_id
            WHERE p.repository_id = :r"""), {"r": r}):
        declared.setdefault(project, set()).add(package)
    references = assembly_references(db, r, excluded, declared, engagement.target_framework)
    # Gap 4 (2026-11-26): a package whose only assets are .NET Framework ones loads on the target framework only through
    # NuGet's fallback (NU1701): a place of the package replacement item, with its known replacement where there is one.
    if PACKAGE_REPLACEMENT not in not_applicable:
        framework_only_packages(occurrences, references)

    items = []
    for item_id in sorted(occurrences):
        item = db.get(models.CatalogItem, item_id)
        resolutions = (db.query(models.ItemResolution).filter_by(item_id=item_id)
                       .filter(models.ItemResolution.deleted_at.is_(None)).order_by(models.ItemResolution.id).all())
        default = next((x for x in resolutions if x.is_default), None)
        decided = decisions.get(item_id)
        chosen = next((x for x in resolutions if x.id == decided), None) if decided else default
        if not decided and item_id == "enterprise-vault-secret-reference" and vault:
            # A working vault delivery is kept, never replaced, unless a decision says so.
            chosen = next((x for x in resolutions if x.id == KEEP_VAULT_DELIVERY), chosen)
        items.append({
            "id": item_id, "name": item.name, "category": item.category, "scope": item.scope,
            "guidance": item.engine_guidance, "ordering": _ordering(item.description),
            "decided": decided is not None,
            "resolution": None if chosen is None else {
                "id": chosen.id, "name": chosen.name, "guidance": chosen.engine_guidance,
                "consumer_impact": chosen.consumer_impact, "container_ready": chosen.container_ready,
                # Where its work item stands in the plan (render.PHASES, render.work_items); unset is said so.
                "phase": chosen.phase,
                # The engagement's note, after the master guidance; it adds to it and never stands in for it.
                **({"engagement_note": notes[chosen.id]} if notes.get(chosen.id) else {}),
                # Changes the design: the engine asks how to implement it before any code (render.design_section).
                **({"confirm_design": True} if chosen.confirm_design else {})},
            "alternatives": [{"id": x.id, "name": x.name, "default": x.is_default} for x in resolutions
                             if chosen is None or x.id != chosen.id],
            "occurrences": occurrences[item_id],
            "impact": impact.get(item_id, []),
        })

    # Package moves and their couplings, as the conversion planner computes them (34-CONVERSION Part E).
    to_tfm = engagement.target_framework
    packages, couplings, drift = [], {"together": [], "depends": []}, []
    if len(current) == 1:
        found, moves, _ = planner.package_moves(db, r, current[0], to_tfm, [], drift, excluded_projects=excluded)
        together, depends = planner.couplings(moves)
        for key, p in sorted(found.items()):
            placement, why = planner._place({"support": {p["package_id"]: p["support"]}}, current[0], to_tfm)
            packages.append({"package": p["package_id"], "from": p["from"], "to": p["to"], "outcome": p["outcome"],
                             "projects": sorted({o[1] for o in p["occurrences"]}), "retarget": placement, "why": why,
                             "dependencies_known": p["dependencies_known"]})
        couplings = {"together": [list(t) for t in together], "depends": [list(d) for d in depends]}

    deltas = []
    for delta in planner.load_deltas():
        if len(current) != 1 or not planner._crosses(current[0], to_tfm, delta["breaks_from"]):
            continue
        sites = {k: v for k, v in planner._delta_findings(db, r, delta).items() if in_scope(k)}
        if sites:
            deltas.append({"id": delta["id"], "symptom": delta.get("symptom"), "description": delta["description"],
                           "fix": (delta.get("fix") or {}).get("basis"), "sites": {k: sorted(v) for k, v in sorted(sites.items())}})

    # Names, key paths and verdicts only: never a value (a binding's deploy parameter is recorded as present). Only what
    # is in the conversion's scope: a binding in an in-scope configuration file, an entry with an in-scope binding or
    # call site (_in_scope_entry); the Windows-only, deploy parameter and SOAP sections all read these.
    outbound = []
    for m, h, lv, rv, rs, every_binding, project, sites in db.execute(text("""
            SELECT o.mechanism, o.endpoint_host, o.linux_verdict, o.runtime_verdict, o.linux_reasons, o.environment_bindings,
                   p.relative_path, o.call_sites
            FROM outbound_invocations o JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :r AND o.usage = 'used' AND o.linux_verdict <> 'compatible'
            ORDER BY o.mechanism, o.endpoint_host NULLS LAST, o.linux_verdict"""), {"r": r}):
        keep, bindings = _in_scope_entry(project, every_binding, sites, in_scope, excluded)
        if not keep:
            continue
        entry = dict(mechanism=m, host=h, linux=lv, runtime=rv, reasons=sorted(rs or []), bindings=sorted(
            ({"environment": b.get("environment"), "file": b.get("sourceFile"), "key": b.get("keyPath"),
              "linux": b.get("linuxVerdict"), "deploy_parameter": b.get("deployParameter") is not None}
             for b in bindings or []), key=lambda b: (b["file"] or "", b["key"] or "", b["environment"] or "")))
        if entry not in outbound:
            outbound.append(entry)
    soap = []
    for h, rv, lv, every_binding, project, sites in db.execute(text("""
            SELECT o.endpoint_host, o.runtime_verdict, o.linux_verdict, o.environment_bindings, p.relative_path, o.call_sites
            FROM outbound_invocations o JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :r AND o.runtime_verdict IS NOT NULL ORDER BY o.endpoint_host NULLS LAST"""), {"r": r}):
        keep, bindings = _in_scope_entry(project, every_binding, sites, in_scope, excluded)
        if not keep:
            continue
        security = sorted({(s.get("binding"), s.get("securityMode"), s.get("clientCredentialType"))
                           for s in ((b or {}).get("soap") for b in bindings or []) if s}, key=lambda x: tuple(v or "" for v in x))
        entry = dict(host=h, runtime=rv, linux=lv, security=[list(x) for x in security])
        if entry not in soap:
            soap.append(entry)

    pinned_packages = packages_config(db, r, excluded)
    # Gap 2: the SSIS C# resolutions change the code that runs the package; gap 3: an assembly another chosen resolution
    # replaces is not the Windows-only item's (2026-11-25).
    for item in items:
        ssis_places(db, r, excluded, files, item, references)
    items = windows_only_left(items, references)
    # Gap 5: the image and manifests of a .NET Framework application only when its chosen approach moves it to a
    # container on the target framework.
    items = containers_needed(items, project_frameworks)
    # 1c: each .NET Framework class library's bridge or direct retarget, from its consumers; adopted when nobody decided.
    every_reference = [(s, t) for s, t in db.execute(text("""
            SELECT s.relative_path, t.relative_path FROM project_references r
            JOIN projects s ON s.id = r.source_project_id JOIN projects t ON t.id = r.referenced_project_id
            WHERE s.repository_id = :r ORDER BY 1, 2"""), {"r": r})]
    left_out = set(excluded) | {p["path"] for p in scope.get("notConverted") or []}
    libraries = class_library_recommendations(items, every_reference, left_out)
    items = adopt_recommendation(db, items, libraries, notes)

    # The platform's own vocabulary, which no generated file may contain (selfcontained.py).
    from app.engine.inputs import selfcontained
    vocabulary = selfcontained.vocabulary(db)

    return {
        # Every file in the repository at the discovered commit: each instruction names the existing files it concerns
        # (render.concerned_files), so the engine opens them by path and never searches for them or recreates one.
        "files": files,
        "vault_delivery": [{"file": v.file, "kind": v.kind, "description": v.description} for v in vault],
        "test_mappings": test_mappings,
        "engagement": {"id": engagement.id, "target_framework": to_tfm, "target_platform": engagement.target_platform,
                       "posture": engagement.default_posture, "conventions": engagement.conventions},
        "repository": {"slug": repository.slug, "commit": repository.ingest_commit_sha},
        "projects": projects, "current_frameworks": current, "references": project_graph,
        "items": items, "packages": packages, "couplings": couplings, "version_drift": sorted(set(drift)), "deltas": deltas,
        "outbound": outbound, "soap": soap, "vocabulary": vocabulary, "assembly_references": references,
        "packages_config": pinned_packages,
        # 1c (2026-11-26): each .NET Framework class library's recommended resolution, from its consumers, and why.
        "class_libraries": libraries,
        # Items decided not applicable, with their findings: read by the verifier only (rediscovery), never rendered.
        "not_applicable": [{"id": item_id, "occurrences": found} for item_id, found in sorted(set_aside.items())],
        # Part O: the projects left out ({path, name}), and when there are any, who left them out, when and why, named
        # in every engine's instructions, the decision sheet and the runbook.
        # Projects this track does not convert (an SSIS .dtproj, any project that is not .csproj or .vbproj): never in
        # in-scope.sln, listed by path in both engines' instructions and the runbook.
        "scope": {"excluded": scope["left"], "build": scope["build"], "notConverted": scope.get("notConverted") or [],
                  **({k: scope.get(k) for k in ("decidedBy", "decidedAt", "reason")} if scope["left"] else {})},
    }
