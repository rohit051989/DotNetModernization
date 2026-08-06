# 00 — Project Overview

## Why this exists

We are bidding for a .NET modernization program: 50+ repositories, an estimated
600+ applications, plus several hundred SSIS packages. Target platform is Linux on
OpenShift Container Platform 4 (OCP4), migrating from Windows and IIS.

The transformation engine is bought (GitHub Copilot app modernization). The
**platform** is what we build around it. Of a 51-step migration lifecycle, the
engine owns 5 steps. The catalog is the foundation for most of the other 46.

## Why the catalog is built first

Every downstream capability depends on it:

- Fingerprinting classifies applications **against catalog patterns**.
- Target-state governance selects **from catalog options** and records the decision.
- Accelerators are bound to a **(pattern, approved target state)** pair.
- The dashboard reports coverage **by pattern**.

Getting the data model wrong here propagates everywhere. Building it standalone,
with a UI, lets us validate the shape before the platform wraps around it.

## The three-layer model

This is the core design idea. Keep the layers strictly separated.

```
Layer 1  PATTERN                    client-agnostic, reusable forever
         "WCF service hosted in IIS using System.ServiceModel"
            |
            +-- Layer 2  TARGET STATE OPTIONS      grows across clients
            |            "CoreWCF on .NET 10"      impact: none   effort: medium
            |            "gRPC rewrite"            impact: high   effort: high
            |            "REST rewrite"            impact: high   effort: high
            |
            +-- Layer 3  DECISION RECORD           engagement-specific
                         Engagement: Client A
                         Selected: CoreWCF on .NET 10
                         Rationale: external SOAP consumers cannot change contract
                         Approver: J. Smith, Lead Architect
```

Layer 1 and 2 are our intellectual property and compound across engagements.
Layer 3 belongs to a specific client program.

A pattern ships with **one** target state option initially — the one this client
needs. The schema supports many from day one so the catalog can grow without
migration when a later client picks differently.

## Build scope

**In scope now:**
- PostgreSQL schema for patterns, target state options, engagements, decision records
- FastAPI backend with CRUD over all four, plus catalog export/import
- React UI shell with a working **Catalog** tab (browse, create, edit)
- Seed data: 8 patterns with target state options, and one sample engagement with
  decision records demonstrating approved and parked states

**Explicitly not in scope:** repository scanning, dependency graphs, wave planning,
orchestration, engine integration, authentication.

The UI shell should show future tabs as disabled placeholders — Repositories,
Applications, Dependencies, Waves, Dashboard — so the direction of travel is
visible in the demo without implying they work.

## Success criteria

1. `docker compose up` starts Postgres; backend and frontend start with documented
   PowerShell commands.
2. Seed script populates 8 patterns, their target state options, one engagement,
   and its decision records.
3. The Catalog tab lists patterns, opens a detail view showing target state options
   with impact and effort, and supports creating and editing both.
4. Decision records are visible per engagement, including parked patterns awaiting
   a decision.
5. `GET /api/catalog/export` returns deterministic JSON suitable for committing to
   git and diffing in a pull request.

## Reading order for implementation

1. `01-ENVIRONMENT-SETUP.md` — get the machine ready
2. `02-DATA-MODEL.md` — schema and constraints
3. `03-BACKEND-SPEC.md` — API surface
4. `05-SEED-CATALOG-DATA.md` — the data to load
5. `04-FRONTEND-SPEC.md` — UI
6. `06-BUILD-ORDER-AND-PROMPTS.md` — the sequence and the prompts to use
