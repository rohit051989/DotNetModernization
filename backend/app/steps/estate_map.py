"""Lifecycle step 11 — dependency-and-context-map. 31-STEP-011-ESTATE-DEPENDENCY-MAP.md.

Engagement-scoped, in phase0-estate-consolidation. Reads the per-repository
rows of steps 2, 4, 5 and 6 straight from the database for every in-scope
repository (Part B1) — artifact resolution cannot reach another job's
artifacts — and records, per repository, the step execution whose rows it
read. Writes the endpoint register, the package estate, the dependency graph
and origin reconciliations (replaced per run), and four deterministic
artifacts, each carrying coverage (Part B2).

endpoint_annotations is human data: this step reads it only to keep a host a
human annotated but nothing calls any more, as no_longer_called (Part C4).

The analysis is app/estate/analysis.py; this module loads and writes.
"""

import datetime
import json
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.estate import analysis
from app.items import coupling
from app.workflow.adapters.base import compute_checksum
from app.workflow.contract import StepContext, StepOutput, StepResult

STEP_NAME = "dependency-and-context-map"
# endpoint-register 1.1.0 (additive): production-host grouping and the
# served-by annotations. integration-map is new with step 1.1.0.
# endpoint-register 1.2.0 (additive): carried annotations (step 1.2.0).
# endpoint-register 1.3.0 (additive): backendChangeOwner (step 1.3.0).
ARTIFACT_VERSIONS = {"endpoint-register": "1.3.0", "package-estate": "1.0.0", "dependency-graph": "1.0.0",
                     "context-map": "1.0.0", "integration-map": "1.0.0"}

# The per-repository steps whose rows this step reads, and what it needs
# from each. A repository is included once all four have completed.
SOURCE_STEPS = ("solution-discovery", "entry-point-inventory", "outbound-invocation-inventory", "dependency-assessment")


def _open_session(database_url: str):
    engine = create_engine(database_url)
    return sessionmaker(bind=engine)(), engine


# ---------- loading ----------


def _source_executions(db: Session, repository_id) -> dict[str, str]:
    """The newest completed, not carried-forward execution of each source
    step for this repository: the run whose rows are in the tables now."""
    rows = db.execute(text("""
        select distinct on (s.step_name) s.step_name, s.id
        from wf_step_executions s
        join wf_job_executions j on j.id = s.job_execution_id
        join wf_job_instances i on i.id = j.job_instance_id
        where i.parameters->>'repository_id' = :r and s.step_name = any(:steps)
          and s.batch_status = 'COMPLETED' and s.exit_status = 'COMPLETED' and not s.carried_forward
        order by s.step_name, s.ended_at desc
    """), {"r": str(repository_id), "steps": list(SOURCE_STEPS)}).all()
    return {name: str(execution_id) for name, execution_id in rows}


def load_estate(db: Session, engagement_id: str) -> dict:
    repositories = (
        db.query(models.Repository)
        .filter(models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None),
                models.Repository.retirement_status == "active")
        .order_by(models.Repository.slug)
        .all()
    )
    sources, included = {}, []
    for repo in repositories:
        executions = _source_executions(db, repo.id)
        sources[repo.id] = executions
        if all(step in executions for step in SOURCE_STEPS):
            included.append(repo)
    slugs = {r.id: r.slug for r in included}
    ids = list(slugs)

    projects = [
        {"id": p.id, "repository_id": p.repository_id, "repository_slug": slugs[p.repository_id], "relative_path": p.relative_path,
         "name": Path(p.relative_path).stem, "assembly_name": p.assembly_name, "root_namespace": p.root_namespace}
        for p in db.query(models.Project).filter(models.Project.repository_id.in_(ids)).order_by(models.Project.relative_path)
    ]
    paths = {p["id"]: p["relative_path"] for p in projects}
    references = [
        {"source_project_id": r.source_project_id, "referenced_project_id": r.referenced_project_id}
        for r in db.query(models.ProjectReference).filter(models.ProjectReference.source_project_id.in_(list(paths)))
        if r.referenced_project_id is not None
    ]
    packages = [
        {"project_id": p.project_id, "package_name": p.package_name}
        for p in db.query(models.ProjectPackage).filter(models.ProjectPackage.project_id.in_(list(paths)))
        if p.package_name
    ]
    calls = [
        {"id": o.id, "repository_id": o.repository_id, "repository_slug": slugs[o.repository_id], "project_id": o.project_id,
         "project_path": paths.get(o.project_id, ""), "mechanism": o.mechanism, "usage": o.usage, "scheme": o.endpoint_scheme,
         "host": o.endpoint_host, "port": o.endpoint_port, "path": o.endpoint_path, "resolution": o.resolution,
         "placeholder": o.placeholder, "linux_verdict": o.linux_verdict, "linux_reasons": o.linux_reasons, "detail": o.detail,
         "environment_bindings": o.environment_bindings, "operations": o.operations or []}
        for o in db.query(models.OutboundInvocation).filter(models.OutboundInvocation.repository_id.in_(ids))
    ]
    entry_points = [
        {"id": e.id, "repository_id": e.repository_id, "repository_slug": slugs[e.repository_id], "project_id": e.project_id,
         "project_path": paths.get(e.project_id, ""), "kind": e.kind, "origin": e.origin, "handler_type": e.handler_type,
         "handler_member": e.handler_member, "detail": e.detail}
        for e in db.query(models.EntryPoint).filter(models.EntryPoint.repository_id.in_(ids))
    ]
    assessments = [
        {"repository_slug": slugs[a.repository_id], "project_path": paths.get(a.project_id, ""), "package_id": a.package_id,
         "current_version": a.current_version, "recommended_version": a.recommended_version, "outcome": a.outcome,
         "deprecated": a.deprecated, "vulnerable": a.vulnerable, "not_in_client_feed": a.not_in_client_feed,
         "breaking_members": a.breaking_members, "feed_source": a.feed_source}
        for a in db.query(models.PackageAssessment).filter(models.PackageAssessment.repository_id.in_(ids))
    ]
    return {
        "repositories": repositories, "included": included, "sources": sources, "projects": projects,
        "references": references, "packages": packages, "calls": calls, "entry_points": entry_points,
        "assessments": assessments,
    }


def coverage(in_engagement: int, included: int) -> dict:
    return {
        "repositoriesInEngagement": in_engagement,
        "repositoriesIncluded": included,
        "repositoriesPending": in_engagement - included,
        "coverageRatio": round(included / in_engagement, 2) if in_engagement else 0.0,
        "partialEstate": included < in_engagement,
    }


# ---------- the run ----------


def served_by_annotations(db: Session, engagement_id: str, included) -> dict:
    """Hosts a person annotated as served by one of the estate's included
    repositories (C4): host -> {repository_id, repository_slug}."""
    slugs = {r.id: r.slug for r in included}
    return {
        a.host: {"repository_id": a.served_by_repository_id, "repository_slug": slugs[a.served_by_repository_id]}
        for a in db.query(models.EndpointAnnotation).filter(models.EndpointAnnotation.engagement_id == engagement_id,
                                                              models.EndpointAnnotation.served_by_repository_id.is_not(None))
        if a.served_by_repository_id in slugs
    }


def build(db: Session, engagement_id: str) -> dict:
    """Everything the step produces for one engagement, as plain data."""
    data = load_estate(db, engagement_id)
    engagement = db.get(models.Engagement, engagement_id)
    production_environment = engagement.production_environment if engagement else None
    served_by = served_by_annotations(db, engagement_id, data["included"])
    register = analysis.build_register(data["calls"], data["entry_points"], production_environment, served_by)

    # Annotations the production grouping would orphan are carried to the
    # production row that took their calls (C4). A carried served_by applies
    # there too, unless that row is annotated itself.
    annotated = sorted(a.host for a in db.query(models.EndpointAnnotation).filter(models.EndpointAnnotation.engagement_id == engagement_id))
    carried: dict[str, list[str]] = {}
    if production_environment:
        as_found = analysis.build_register(data["calls"], data["entry_points"], None, served_by)
        carried = analysis.carry_annotations(register, as_found, annotated)
        extra = {target: served_by[host] for host, targets in carried.items() if host in served_by
                 for target in targets if target not in served_by}
        if extra:
            served_by = {**served_by, **extra}
            register = analysis.build_register(data["calls"], data["entry_points"], production_environment, served_by)

    called = {h["host"] for h in register["hosts"]}
    register["noLongerCalled"] = [h for h in annotated if h not in called and h not in carried]
    register["carriedAnnotations"] = [{"fromHost": host, "toHost": target} for host, targets in sorted(carried.items()) for target in targets]
    for row in register["hosts"]:
        row["annotationCarriedFrom"] = sorted(host for host, targets in carried.items() if row["host"] in targets)
    register["productionEnvironment"] = production_environment
    register["servedByAnnotations"] = {h: v["repository_slug"] for h, v in sorted(served_by.items())}
    integration = analysis.build_integration(data["calls"], data["entry_points"], production_environment, served_by)

    client_feed = {a["package_id"].lower() for a in data["assessments"] if a.get("feed_source") == "client_feed"}
    graph = analysis.build_graph(data["projects"], data["references"], data["packages"], client_feed)
    reconciliations = analysis.reconcile_origins(data["entry_points"], data["projects"])
    context_map = analysis.build_context_map(engagement.client_name if engagement else engagement_id,
                                             [r.slug for r in data["included"]], register["hosts"])
    return {
        "data": data,
        "coverage": coverage(len(data["repositories"]), len(data["included"])),
        "register": register,
        "packages": analysis.build_package_estate(data["assessments"]),
        "graph": graph,
        "reconciliations": reconciliations,
        "context": context_map,
        "integration": integration,
    }


def write_tables(db: Session, engagement_id: str, result: dict, step_execution_id) -> None:
    """Replaces this engagement's rows in every step 11 table except
    endpoint_annotations, which only humans write."""
    for model in (models.EstateSource, models.EndpointRegisterService, models.EndpointRegisterHost, models.PackageEstateRow,
                  models.DependencyEdge, models.SharedLibrary, models.DependencyCycle, models.OriginReconciliation,
                  models.IntegrationEdge, models.IntegrationEntryPoint):
        db.query(model).filter(model.engagement_id == engagement_id).delete(synchronize_session=False)

    data = result["data"]
    for repo in data["repositories"]:
        for step, execution_id in sorted(data["sources"][repo.id].items()):
            db.add(models.EstateSource(engagement_id=engagement_id, repository_id=repo.id, step_name=step,
                                       step_execution_id=execution_id, estate_step_execution_id=step_execution_id))

    for host in result["register"]["hosts"]:
        db.add(models.EndpointRegisterHost(
            engagement_id=engagement_id, host=host["host"], classification=host["classification"], loopback=host["loopback"],
            calling_repository_count=host["callingRepositoryCount"], calling_repositories=host["callingRepositories"],
            calling_project_count=host["callingProjectCount"], calling_projects=host["callingProjects"],
            mechanisms=host["mechanisms"], bindings=host["bindings"], ports=host["ports"], worst_verdict=host["worstVerdict"],
            verdict_by_environment=host["verdictByEnvironment"], requires_backend_change=host["requiresBackendChange"],
            backend_change_reasons=host["backendChangeReasons"], invocation_count=host["invocationCount"],
            grouped_by=host["groupedBy"], other_hosts=host["otherHosts"], annotation_carried_from=host["annotationCarriedFrom"],
            step_execution_id=step_execution_id,
        ))
        for service in host["services"]:
            db.add(models.EndpointRegisterService(
                engagement_id=engagement_id, host=host["host"], path=service["path"], contract=service["contract"] or "",
                ports=service["ports"], mechanisms=service["mechanisms"], bindings=service["bindings"],
                calling_repositories=service["callingRepositories"], calling_projects=service["callingProjects"],
                worst_verdict=service["worstVerdict"], requires_backend_change=service["requiresBackendChange"],
                internal=service["internal"], internal_targets=service["internalTargets"],
            ))
    for host in result["register"]["noLongerCalled"]:
        db.add(models.EndpointRegisterHost(engagement_id=engagement_id, host=host, classification="external",
                                           no_longer_called=True, step_execution_id=step_execution_id))

    for row in result["packages"]:
        db.add(models.PackageEstateRow(
            engagement_id=engagement_id, package_id=row["packageId"], repository_count=row["repositoryCount"],
            repositories=row["repositories"], project_count=row["projectCount"], projects=row["projects"],
            versions_in_use=row["versionsInUse"], estate_drift=row["estateDrift"], cross_repository_drift=row["crossRepositoryDrift"],
            recommended_version=row["recommendedVersion"],
            outcomes=row["outcomes"], breaking_members=row["breakingMembers"], flags=row["flags"],
        ))
    for edge in result["graph"]["edges"]:
        db.add(models.DependencyEdge(engagement_id=engagement_id, from_project_id=edge["from"], to_project_id=edge["to"],
                                     edge_kind=edge["kind"], cross_repository=edge["crossRepository"], via_package=edge["via"],
                                     client_feed=edge["clientFeed"]))
    for shared in result["graph"]["sharedLibraries"]:
        db.add(models.SharedLibrary(engagement_id=engagement_id, project_id=shared["projectId"],
                                    consumer_repository_count=shared["consumerRepositoryCount"],
                                    consumer_project_count=shared["consumerProjectCount"],
                                    consumers=[str(c) for c in shared["consumers"]]))
    for cycle in result["graph"]["cycles"]:
        db.add(models.DependencyCycle(engagement_id=engagement_id, cycle_id=cycle["cycleId"],
                                      member_project_ids=[str(m) for m in cycle["members"]], cross_repository=cycle["crossRepository"]))
    for r in result["reconciliations"]:
        db.add(models.OriginReconciliation(
            engagement_id=engagement_id, entry_point_id=r["entryPointId"], original_origin=r["originalOrigin"],
            reconciled_origin=r["reconciledOrigin"], declaring_repository_id=r["declaringRepositoryId"],
            declaring_project_id=r["declaringProjectId"], reason=r["reason"],
        ))
    for e in result["integration"]["edges"]:
        db.add(models.IntegrationEdge(
            engagement_id=engagement_id, edge_id=e["edgeId"], mechanism=e["mechanism"], caller_repository_id=e["callerRepositoryId"],
            caller_project_id=e["callerProjectId"], invocation_id=e["invocationId"], call_site_file=e["callSite"]["filePath"] or "",
            call_site_line=e["callSite"]["lineStart"] or 0, operation=e["operation"], callee_repository_id=e["calleeRepositoryId"],
            callee_project_id=e["calleeProjectId"], entry_point_id=e["entryPointId"], match_method=e["matchMethod"],
            confidence=e["confidence"], same_repository=e["sameRepository"],
        ))
    for ep in result["integration"]["entryPoints"]:
        db.add(models.IntegrationEntryPoint(
            engagement_id=engagement_id, entry_point_id=ep["entryPointId"], repository_id=ep["repositoryId"],
            project_id=ep["projectId"], kind=ep["kind"], operation=ep["operation"], matchable=ep["matchable"],
            internal_caller=ep["internalCaller"], caller_count=ep["callerCount"],
            cross_repository_caller_count=ep["crossRepositoryCallerCount"],
        ))
    db.flush()


def artifacts(engagement_id: str, result: dict) -> dict[str, dict]:
    """The five artifacts (Part G): deterministic — sorted keys and
    collections, ids rather than times — and each carrying coverage and the
    per-repository sources it was built from."""
    data = result["data"]
    projects = {p["id"]: p for p in data["projects"]}
    sources = [
        {"repositoryId": str(r.id), "repositorySlug": r.slug, "included": r in data["included"],
         "stepExecutions": dict(sorted(data["sources"][r.id].items()))}
        for r in data["repositories"]
    ]

    def project_ref(project_id) -> dict:
        p = projects[project_id]
        return {"projectId": str(project_id), "repositorySlug": p["repository_slug"], "projectPath": p["relative_path"]}

    def header(artifact_type: str) -> dict:
        return {"artifactType": artifact_type, "artifactVersion": ARTIFACT_VERSIONS[artifact_type], "engagementId": engagement_id,
                "coverage": result["coverage"], "sources": sources}

    register = result["register"]
    graph = result["graph"]
    integration = result["integration"]
    return {
        "endpoint-register": {
            **header("endpoint-register"),
            "summary": {
                "hosts": len(register["hosts"]),
                "requiresBackendChange": sum(1 for h in register["hosts"] if h["requiresBackendChange"]),
                "requiresChangeByAnotherTeam": sum(1 for h in register["hosts"] if h["backendChangeOwner"] == analysis.ANOTHER_TEAM),
                "requiresChangeInThisMigration": sum(1 for h in register["hosts"] if h["backendChangeOwner"] == analysis.THIS_MIGRATION),
                "internal": sum(1 for h in register["hosts"] if h["classification"] == "internal"),
                "external": sum(1 for h in register["hosts"] if h["classification"] == "external"),
                "unresolved": len(register["unresolved"]),
                "unusedExcluded": register["unusedExcluded"],
                "noLongerCalled": len(register["noLongerCalled"]),
                "groupedByProductionHost": sum(1 for h in register["hosts"] if h["groupedBy"] == "production_environment"),
                "carriedAnnotations": len(register["carriedAnnotations"]),
            },
            "carriedAnnotations": register["carriedAnnotations"],
            "productionEnvironment": register["productionEnvironment"],
            "servedByAnnotations": register["servedByAnnotations"],
            "hosts": register["hosts"],
            "unresolved": register["unresolved"],
            "noLongerCalled": register["noLongerCalled"],
        },
        "package-estate": {
            **header("package-estate"),
            "summary": {"packages": len(result["packages"]), "estateDrift": sum(1 for p in result["packages"] if p["estateDrift"]),
                        "crossRepositoryDrift": sum(1 for p in result["packages"] if p["crossRepositoryDrift"])},
            "packages": result["packages"],
        },
        "dependency-graph": {
            **header("dependency-graph"),
            "summary": {
                "projects": len(data["projects"]), "edges": len(graph["edges"]),
                "crossRepositoryEdges": sum(1 for e in graph["edges"] if e["crossRepository"]),
                "sharedLibraries": len(graph["sharedLibraries"]), "cycles": len(graph["cycles"]),
                "originReconciliations": len(result["reconciliations"]),
            },
            "nodes": [project_ref(p["id"]) for p in sorted(data["projects"], key=lambda p: (p["repository_slug"], p["relative_path"]))],
            "edges": [{**e, "from": project_ref(e["from"]), "to": project_ref(e["to"])} for e in graph["edges"]],
            "sharedLibraries": [
                {"project": project_ref(s["projectId"]), "consumerRepositoryCount": s["consumerRepositoryCount"],
                 "consumerProjectCount": s["consumerProjectCount"], "consumers": [project_ref(c) for c in s["consumers"]]}
                for s in graph["sharedLibraries"]
            ],
            "cycles": [{**c, "members": [project_ref(m) for m in c["members"]]} for c in graph["cycles"]],
            "originReconciliations": result["reconciliations"],
        },
        "context-map": {
            **header("context-map"),
            "format": "structurizr-dsl",
            "dsl": result["context"]["dsl"],
            "systems": result["context"]["systems"],
            "relationships": result["context"]["relationships"],
        },
        "integration-map": {
            **header("integration-map"),
            "summary": {
                "edges": len(integration["edges"]),
                "crossRepositoryEdges": sum(1 for e in integration["edges"] if not e["sameRepository"]),
                "sameRepositoryEdges": sum(1 for e in integration["edges"] if e["sameRepository"]),
                "operationsUnmatched": len(integration["unmatched"]),
                "operationsUnresolved": sum(1 for u in integration["unmatched"] if u["resolution"] == "unresolved"),
                "entryPoints": len(integration["entryPoints"]),
                "entryPointsInternalCallerFound": sum(1 for e in integration["entryPoints"]
                                                      if e["internalCaller"] == analysis.INTERNAL_CALLER_FOUND),
                "entryPointsNoInternalCallerFound": sum(1 for e in integration["entryPoints"]
                                                        if e["internalCaller"] == analysis.NO_INTERNAL_CALLER_FOUND),
            },
            "edges": integration["edges"],
            "unmatched": integration["unmatched"],
            "entryPoints": integration["entryPoints"],
            "applications": analysis.integration_by_application(integration),
        },
    }


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # UUIDs


def run(context: StepContext) -> StepResult:
    engagement_id = context.parameters.get("engagement_id")
    if not engagement_id:
        return StepResult(exit_status="FAILED", exit_message="parameters.engagement_id is required for dependency-and-context-map")
    if not context.database_url:
        return StepResult(exit_status="FAILED", exit_message="database_url is required")

    db, engine = _open_session(context.database_url)
    try:
        if db.get(models.Engagement, engagement_id) is None:
            return StepResult(exit_status="FAILED", exit_message=f"engagement '{engagement_id}' does not exist")
        result = build(db, engagement_id)
        write_tables(db, engagement_id, result, context.step_execution_id)
        # Part S: which clients are internal comes from this run's
        # integration edges, so derived decisions are brought in step here.
        for leader in coupling.leader_items(db):
            coupling.rederive(db, engagement_id, leader)
        db.commit()

        output_dir = Path(context.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = []
        for artifact_type, body in artifacts(engagement_id, result).items():
            path = output_dir / f"{artifact_type}.json"
            path.write_text(json.dumps(_jsonable(body), sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            outputs.append(StepOutput(
                artifact_type=artifact_type, artifact_version=ARTIFACT_VERSIONS[artifact_type], uri=path.as_uri(),
                checksum=compute_checksum(path.as_uri()),
                metadata={"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
            ))

        cov, register, graph = result["coverage"], result["register"], result["graph"]
        backend = sum(1 for h in register["hosts"] if h["requiresBackendChange"])
        return StepResult(
            exit_status="COMPLETED",
            exit_message=(
                f"Estate of {cov['repositoriesIncluded']} of {cov['repositoriesInEngagement']} repositories: "
                f"{len(register['hosts'])} host(s) in the endpoint register ({backend} need a backend change, "
                f"{sum(1 for h in register['hosts'] if h['classification'] == 'internal')} internal), "
                f"{len(register['unresolved'])} unresolved endpoint(s); {len(result['packages'])} package(s), "
                f"{sum(1 for p in result['packages'] if p['estateDrift'])} with estate drift; "
                f"{sum(1 for e in graph['edges'] if e['crossRepository'])} cross-repository edge(s), "
                f"{len(graph['sharedLibraries'])} shared librar(ies), {len(graph['cycles'])} cycle(s); "
                f"{len(result['integration']['edges'])} integration edge(s)."
            ),
            metrics={"read_count": cov["repositoriesIncluded"], "write_count": len(register["hosts"]) + len(result["packages"]),
                     "skip_count": cov["repositoriesPending"], "commit_count": 1},
            outputs=outputs,
        )
    finally:
        db.close()
        engine.dispose()
