"""Seeds synthetic project_fingerprints + fingerprint_signals rows for the
two sample gRPC projects, standing in for step 3 (which is stubbed --
no .NET SDK confirmed on this machine yet, so it never actually runs).

Without this, project_fingerprints / fingerprint_signals stay empty and
step 5 (which reads only those tables) will always report zero candidates,
regardless of whether the job engine mechanics work. This script exists so
you can see step 5's real clustering algorithm run against real-shaped
data -- it is a stand-in for step 3's output, not a replacement for
building step 3 for real later.

The two projects are seeded with ~80% overlapping signal names (both are
WebApplication.CreateBuilder + AddGrpc() + MapGrpcService, same target
framework, same hosting model) so step 5's weighted-Jaccard structural
pass (threshold_strong=0.6) should cluster them together.

Usage (from backend/, venv activated, AFTER register_repo_and_run.py has
completed so the `projects` rows for BillingGrpcService/InventoryGrpcService
exist):
    python e2e_run/seed_fingerprints.py
"""
import uuid

import psycopg
from psycopg.types.json import Json

DATABASE_URL = "postgresql://catalog:catalog_dev_pw@localhost:5433/modernization_catalog"
ENGAGEMENT_ID = "client-a-ocp4"

# (project name substring to match, unique namespace signal name/value)
PROJECTS = [
    ("BillingGrpcService", "BILLING_NAMESPACE", "BillingGrpcService.Services"),
    ("InventoryGrpcService", "INVENTORY_NAMESPACE", "InventoryGrpcService.Services"),
]

# Shared across both projects -- this is the deliberate overlap.
SHARED_SIGNALS = [
    # (signal_name, category, signal_type, value, source_type)
    ("WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT", "ENTRY_POINT", "ENTRY_POINT", "WebApplication.CreateBuilder(args)", "SOURCE_CODE"),
    ("GRPC_ASPNETCORE_PACKAGE", "PACKAGE_DEPENDENCY", "PACKAGE", "Grpc.AspNetCore 2.63.0", "PACKAGE_REFERENCE"),
    ("GRPC_SERVICE_BASE_CLASS", "SOURCE_CONSTRUCT", "BASE_CLASS", "*.BillingBase / *.InventoryBase", "SOURCE_CODE"),
    ("GRPC_SERVICE_MAPPING", "HOSTING_INDICATOR", "INVOCATION", "app.MapGrpcService<...>()", "SOURCE_CODE"),
    ("PROTO_FILE_PRESENT", "FILE_INDICATOR", "FILE_PRESENCE", "Protos/*.proto", "FILE_STRUCTURE"),
    ("NET6_TARGET_FRAMEWORK", "FRAMEWORK_REFERENCE", "ASSEMBLY", "net6.0", "PROJECT_FILE"),
    ("WEB_SDK_PROJECT", "PROJECT_METADATA", "CONFIG_ELEMENT", "Microsoft.NET.Sdk.Web", "PROJECT_FILE"),
    ("KESTREL_IMPLICIT_HOSTING", "HOSTING_INDICATOR", "INVOCATION", "builder.Build() / app.Run()", "SOURCE_CODE"),
]


def main():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for name_substr, uniq_signal_name, uniq_signal_value in PROJECTS:
                cur.execute(
                    """
                    SELECT p.id, p.repository_id
                    FROM projects p
                    JOIN repositories r ON r.id = p.repository_id
                    WHERE r.engagement_id = %s AND p.name ILIKE %s
                    """,
                    (ENGAGEMENT_ID, f"%{name_substr}%"),
                )
                row = cur.fetchone()
                if row is None:
                    print(f"SKIP {name_substr}: no matching project row found -- did steps 1/2 run for real yet?")
                    continue
                project_id, repository_id = row

                cur.execute("DELETE FROM fingerprint_signals WHERE project_id = %s", (project_id,))
                cur.execute("DELETE FROM project_fingerprints WHERE project_id = %s", (project_id,))

                cur.execute(
                    """
                    INSERT INTO project_fingerprints (
                        project_id, repository_id, fingerprint_status, scanner_version,
                        analysis_capabilities, project_sdk, nullable_enabled, implicit_usings,
                        signal_count, evidence_count, category_summary, fingerprinted_at
                    ) VALUES (%s, %s, 'complete', 'synthetic-seed-1.0.0', %s, 'Microsoft.NET.Sdk.Web',
                              true, true, %s, %s, %s, now())
                    """,
                    (
                        project_id,
                        repository_id,
                        Json({"seeded": True, "note": "stand-in for step 3, which is stubbed"}),
                        len(SHARED_SIGNALS) + 1,
                        len(SHARED_SIGNALS) + 1,
                        Json({"ENTRY_POINT": 1, "HOSTING_INDICATOR": 2, "PACKAGE_DEPENDENCY": 1}),
                    ),
                )

                all_signals = list(SHARED_SIGNALS) + [
                    (uniq_signal_name, "SOURCE_CONSTRUCT", "NAMESPACE", uniq_signal_value, "SOURCE_CODE")
                ]
                for signal_name, category, signal_type, value, source_type in all_signals:
                    cur.execute(
                        """
                        INSERT INTO fingerprint_signals (
                            id, project_id, repository_id, signal_name, signal_category,
                            signal_type, value, source_type, source_path, occurrence_count,
                            evidence, extractor, extraction_confidence
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, 'synthetic-seed', 0.95)
                        """,
                        (
                            str(uuid.uuid4()),
                            project_id,
                            repository_id,
                            signal_name,
                            category,
                            signal_type,
                            value,
                            source_type,
                            "Program.cs",
                            Json([]),
                        ),
                    )
                print(f"OK   {name_substr}: seeded {len(all_signals)} signals for project_id={project_id}")
        conn.commit()


if __name__ == "__main__":
    main()
