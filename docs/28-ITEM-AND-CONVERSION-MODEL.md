# 28 — Item & Conversion Model

The redesign that replaces pattern classification with item detection, occurrence
mapping and conversion. Supersedes the three-layer pattern catalog in
`02-DATA-MODEL.md` and `24-PATTERN-CLASSIFICATION.md`, and the Track A step
decomposition in the architecture document.

Read alongside `17-LIFECYCLE-STEPS.md` v2.0, which carries the revised 35-step
register this model produces.

**Two halves.** Parts A to G define the **catalog** — what needs doing and where.
Parts H to N define **conversion** — how it gets done. Parts H to L are the contract
the delivery team builds accelerators against; treat that half as settled and version
it if it changes.


---

## Section index

| Part | Covers |
|---|---|
| Part A | What changes and why |
| Part B | The model |
| Part C | Two-state readiness |
| Part D | `catalog_items` |
| Part E | Detection with occurrence projection |
| Part F | Resolutions and decisions |
| Part G | `item_occurrences` |
| Part H | Coverage views |
| Part I | Conversion: five decisions taken |
| Part J | `conversion_approaches` |
| Part K | Invocation |
| Part L | `ConversionContext` |
| Part M | `ConversionResult` |
| Part N | Checks |
| Part O | Worked examples |
| Part P | Tables |
| Part Q | Migration |
| Part R | What this replaces |
| Part S | Settled decisions |

---

## Part A — What changes and why

The old catalog answered *"what kind of application is this?"* — one winner per
project, elected through scoring, conflicts and ambiguity resolution.

The new catalog answers *"what needs doing to this project, and where?"* — a list of
occurrences, each mappable to a decision and a conversion.

That single change removes most of the complexity. There is no election, so no
scoring resolution, no conflicts, no ambiguity margin, no primary selection.

### Removed entirely

`classification_role` · `classification_family` · `classification_value` ·
`conflicts_with` · `compatible_with` · `anchor_signals` · `priority` · `thresholds` ·
match scoring · confidence factors · the eight classification statuses ·
`is_primary_selected` · `rejection_reason` · `relationship_source` ·
`ambiguity_margin` · role patterns as catalog entries

### Retained

Detection rule grammar (`all`, `any`, `atLeast`, `none`, `metadata`) · rule ids ·
signal-registry validation on write · evidence linkage · master/client separation ·
engagement overlay for scoping

### Added

`scope` · `occurrence_source` projection · two-state readiness · extractor
declarations · `item_resolutions` · `engagement_decisions` · `item_occurrences`

---

---

## Part B — The model

```
catalog item          a thing that needs work        "Serilog file sink"
  └── resolutions     the options for it             "console JSON only" | "OTLP exporter"
        └── decision  what this client chose         engagement-scoped
              └── conversion approach                how to actually do it
                    └── executions                   per project, recorded
```

Detection produces **occurrences**: item × project × file. Occurrences joined to
decisions joined to approaches form the **work list**, which is the unit everything
else counts, groups, estimates and iterates.

### Scope

One item type, one attribute:

| Scope | Decided | Converted | Example |
|---|---|---|---|
| `application` | Once per project | One invocation over the project | WCF → CoreWCF |
| `occurrence` | Once per item | Per file or per batch of files | Remove Serilog file sink |

### Two conversion steps

- **Step A — application-scope conversions.** Runs first. These reshape the project;
  occurrence-scope edits must land on the reshaped result.
- **Step B — occurrence-scope conversions.** Runs second.

Both are generic iterators over the work list. **Fifty findings do not become fifty
lifecycle steps** — they become fifty rows in `conversion_approaches`. Adding an
accelerator is a registry insert, not a job definition change.

---

---

## Part C — Two-state readiness

Everything is `ready` or `not_ready`, with a structured reason. No third state.

| Entity | `not_ready` reason codes |
|---|---|
| **Signal** | `extractor_not_implemented` |
| **Catalog item** | `signal_mapping_pending` · `signal_not_ready` |
| **Blocking signal** (inside an item's reason) | `extractor_not_implemented` · `signal_not_registered` |

An item under authoring is not a separate state — it is `not_ready` with reason
`signal_mapping_pending`, because its detection has nothing to match yet: no signal
and no `solution-discovery` metadata condition.

A blocking signal is `signal_not_registered` when the item names a signal that is not
in the registry at all. It is kept distinct from `extractor_not_implemented` so the
backlog can tell "register this signal" apart from "build this extractor". Its
`expected_extractor` is whichever extractor declares the name, or null if none does.

### Propagation

A signal is `ready` when its expected extractor is `implemented` and lists the signal
in `emits`. An item is `ready` when its detection is **satisfiable** — by signals, by
`solution-discovery` metadata conditions, or both — and **every** signal it references is `ready`.

Metadata conditions count as mapped. `solution-discovery` always runs, so an item detected purely by
project metadata (`structuralType: ssis_project`) is ready. *Revised in review: an
earlier draft made metadata-only items permanently `signal_mapping_pending`.*

Recompute item readiness whenever any signal's state changes. An item drops to
`not_ready` automatically if a signal it depends on loses its extractor, and promotes
automatically when one lands. Nobody edits the item.

**Only `ready` items are evaluated during detection.** A `not_ready` item is inert
and visible on the UI as pending — this is prevention rather than detection, which is
why no emission tracking or zero-emission flagging is needed.

### Structured reason

Computed, refreshed on every signal state change:

```json
{
  "state": "not_ready",
  "reason_code": "signal_not_ready",
  "blocking_signals": [
    { "signal": "SERILOG_FILE_SINK_CONFIG",
      "reason_code": "extractor_not_implemented",
      "expected_extractor": "LoggingExtractor" }
  ]
}
```

Grouping `blocking_signals` by `expected_extractor` and counting the items each would
unblock gives the extractor build order directly.

### Extractor declarations

Readiness is unanswerable without knowing which extractors can emit what. So each
extractor declares its emittable signals at registration.

**A registered signal that no extractor claims is a hard error**, not a warning —
it catches the case where someone registers a signal in anticipation and forgets the
extractor. "Claims" means the signal's expected extractor lists it in `emits` or
`planned_emits`. The check runs before every write that could break it: registry
sync, signal registration, and an extractor declaration that drops a signal.

An extractor declaration carries a `status` and two lists:

| Field | Meaning |
|---|---|
| `status: implemented` | The extractor ships in `application-fingerprinting` today |
| `status: planned` | Declared ahead of its code |
| `emits` | Signals it emits — ready only while `status` is `implemented` |
| `planned_emits` | On an implemented extractor: signals it will gain but does not emit yet |

That is what reconciles the hard error with `extractor_not_implemented`. A signal can be
registered ahead of its extraction code without being unclaimed, in one of two ways:

- **a new extractor**: in `emits` of a `planned` extractor
- **an extractor that already ships, gaining a signal**: in `planned_emits`

Either way the signal is claimed, so there is no hard error, but it stays `not_ready`
/ `extractor_not_implemented`. It promotes when the extractor flips to `implemented`,
or when the name moves from `planned_emits` to `emits` in the change that ships its
code. The two lists are disjoint.

---

---

## Part D — `catalog_items`

Client-agnostic. One kind of item: a thing that needs work.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | Slug, e.g. `serilog-file-sink` |
| `name` | `TEXT` NOT NULL | |
| `description` | `TEXT` | For catalog authors and reviewers; never generated into a repository |
| `engine_guidance` | `TEXT` | For a conversion engine: what the change is and why it matters on the target (36-COPILOT-ENHANCED-CONVERSION Part K). Null: none written yet |
| `scope` | `TEXT` NOT NULL | CHECK IN (`application`, `occurrence`) |
| `category` | `TEXT` NOT NULL | `hosting`, `logging`, `configuration`, `security`, `data-access`, `integration`, `packaging`, `dependencies`, `framework` |
| `detection` | `JSONB` NOT NULL | Part D |
| `excluded_roles` | `JSONB` NOT NULL DEFAULT `'[]'` | Project roles this item never applies to |
| `state` | `TEXT` NOT NULL DEFAULT `'not_ready'` | CHECK IN (`ready`, `not_ready`). **Computed, never set directly** |
| `state_reason` | `JSONB` | Part B |
| `version` | `INTEGER` NOT NULL DEFAULT 1 | Bumped on detection change |
| `owner_team` | `TEXT` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

### Project role is computed, not catalogued

Six role patterns previously lived in the catalog. They are removed. Role is derived
deterministically in `item-detection` from data already collected:

| Role | Derivation |
|---|---|
| `TEST` | Test framework packages (`solution-discovery`) or testing-indicator signals (`application-fingerprinting`) |
| `DEPLOYMENT` | Out-of-scope structural type from `solution-discovery` — `.dcproj`, `.sfproj`, `.wixproj` |
| `DATABASE` | `structural_type: sql_database_project` |
| `APPLICATION` | Has entry points (`entry-point-inventory`), or `output_type` Exe/WinExe, or a web SDK |
| `LIBRARY` | `output_type: Library` with no entry points |
| `UNKNOWN` | None of the above |

Deterministic, needs no authoring surface, and removes six catalog entries plus the
role-rule concept. Document the logic in the `item-detection` implementation. If it ever needs
to be editable, promote it back to the catalog then.

Application *type* — API, worker, UI — comes from `entry-point-inventory`,
not from catalog items. Nothing in the catalog describes what an application is; the
catalog only describes what needs doing.

---

---

## Part E — Detection with occurrence projection

Two parts. `match` decides whether the item applies. `occurrence_source` decides
**where**.

### Occurrence scope

```json
{
  "match": {
    "all": [
      { "id": "has-file-sink", "signal": { "name": "SERILOG_FILE_SINK_CONFIG" } }
    ]
  },
  "occurrence_source": {
    "signal": "SERILOG_FILE_SINK_CONFIG",
    "group_by": "source_path"
  }
}
```

`occurrence_source` names which signal's evidence defines the locations. Each distinct
`source_path` in that signal's evidence becomes one occurrence row, carrying the line
evidence with it.

This is the bridge between what `application-fingerprinting` already records and what conversion needs.
**Nothing new is extracted** — `application-fingerprinting`'s evidence already has file paths and lines.
What was missing is the catalog declaring which signal to project.

`group_by` accepts `source_path` (default) or `source_path_and_value` where distinct
values at the same path are separate occurrences.

`also` (optional) names further located signals, for an item matched by `any` of several
signals that each carry their own locations: `package-replacement-required` matches
`PACKAGE_NO_COMPATIBLE_VERSION` or `PACKAGE_DEPRECATED`, and either can be the only one
present for a package. Each is projected the same way, in order — `signal` first, then
`also` — and a group that shares a path **and a line** with an occurrence already projected
joins that occurrence instead of making a second one, so a PackageReference line flagged
by both signals is one occurrence. Every `also` signal is validated like `signal`: it must
appear in a positive match group and must not have `evidence_kind: NONE`.

An occurrence-scope item **must** declare `occurrence_source`, and the named signal
must appear in `match.all`, `match.any` or `match.atLeast`. A signal named only in
`match.none` does not count: an exclusion holds precisely where the signal is absent,
so it has no locations to project. Validate both on write. A registered signal with
`evidence_kind: NONE` is also rejected as an `occurrence_source`, since its evidence
carries no path.

### Application scope

No projection. The project is the unit.

```json
{
  "match": {
    "any": [
      { "id": "uses-ws", "signal": { "name": "USE_WINDOWS_SERVICE_INVOCATION" } },
      { "id": "ws-package", "signal": { "name": "MICROSOFT_EXTENSIONS_HOSTING_WINDOWSSERVICES_PACKAGE" } }
    ]
  }
}
```

An application-scope item declaring `occurrence_source` is rejected.

### Overlapping items

There is no election, so nothing stops two items matching the same project. Usually
that is correct: a project can need both `serilog-file-sink` and `datetime-now-usage`.
It is wrong when two items are alternative descriptions of the same thing, and would
put two conflicting resolutions on one project's work list.

For those, declare **precedence with `none`**: the less specific item carries a `none`
condition over **every positive signal** of each more specific item. Only the general
item can do the excluding, because the specific item's signals are a superset (a worker
also has a `Main` method). `conflicts_with` is not coming back. This is ordinary
detection, reviewable in the rule itself.

The hosting chain is the first instance:

| Item | Excludes the positive signals of |
|---|---|
| `windows-service-hosting` | — |
| `modern-worker-service` | `windows-service-hosting` (and web hosts, which are applications, not workers) |
| `console-batch-job` | `windows-service-hosting`, `modern-worker-service` |

A test asserts the chain, so adding a positive signal to a more specific item without
extending the exclusions fails the build.

### Conversion ordering constraints

The other kind of overlap: two items that genuinely both apply, often **on the same
line**, where converting them in the wrong order produces the wrong result. Detection is
correct to report both; the order belongs to conversion. No conversion approaches exist
yet, so the constraints are recorded here and in **both** items' descriptions, so an
approach author meets them from either side. Each becomes a `depends_on` entry (Part J)
on the later item's approaches when they are written.

| First | Then | Why this order | What goes wrong reversed |
|---|---|---|---|
| `windows-auth-connection-string` | `sensitive-config-key` | Fix authentication while the connection string is still in the config file, then move it to an OCP4 Secret | The auth fix has to edit a Secret, not a config file: different `allowed_paths` and a different approach for the same finding |
| `serilog-file-sink` | `hardcoded-windows-path` | Removing the file sink removes its path with it | A path about to be deleted is externalised first, and the work list carries a spurious occurrence |
| `wcf-service-host` → ASP.NET Core web host: its configuration migration | `hardcoded-windows-path`, `unqualified-hostname`, and any item fixing a value held in a Web Deploy SetParam file | The host's move to ASP.NET Core moves each environment's values out of `SetParam.xml` into `appsettings.{Environment}.json` and deletes the SetParam files (`33-IMPACT-ANALYSIS.md`, `deploy_parameter_files`). The fixes then apply where the values now live | A fix edits a SetParam file the host conversion is about to delete: the edit is lost, or carried across by hand. `impact-analysis` reports the pair as a `delete_with_change` conflict on each SetParam file, and wherever it recurs across the estate, as one catalog rule conflict: the rule pair is the catalog's, not the application's |
| `package-upgrade-safe` | `package-upgrade-breaking` — **one unit** for the same package | Bump the version everywhere the package is referenced, then fix the call sites, in one change (`30-DEPENDENCY-ASSESSMENT.md` Part D2). One package can be safe in one project and breaking in another | Fixing call sites first writes against an API the project does not reference yet; bumping only the safe projects splits the solution across two versions of one library, and bumping alone leaves the build broken in between |

Same-line pairs that are *not* ordered: an XML connection string also fires
`sensitive-config-key` through its `connectionString` attribute. That is the first row
above, not a separate constraint.

### Repository-level signals are visible to every project

`application-fingerprinting` emits some signals at repository level, with a null `project_id`: deployment files
outside every fingerprinted project directory, such as a root `k8s/` folder, a
`charts/` folder or a root `Dockerfile` (`21-APPLICATION-FINGERPRINTING.md` Part D,
"Extractor batch 2"). **When `item-detection` evaluates an item against a project, the
repository's repository-level signals are part of that project's signal set**, for
every condition in `match`: `all`, `any`, `atLeast` and `none`.

This matters most for `none`. Without it, every project in a repository with a root
`k8s/` folder reads as missing manifests, and every absence item (`missing-dockerfile`,
`missing-ocp4-manifests`) floods the work list with false findings. The rule is
deliberately coarse: a repository-level manifest counts for every project in that
repository, since `application-fingerprinting` cannot tell which project a root-level file deploys.

A repository-level signal never supplies an occurrence location. `occurrence_source`
projects only the project's own evidence, so a repository-level file is never
attributed to a project's work list as a place to edit.

### Grammar

Unchanged from the existing catalog: `all`, `any`, `atLeast`, `none`, `metadata`,
with signal conditions supporting `minimumOccurrences`, `value` predicates and
`minimumExtractionConfidence`. Rule ids remain required.

**Dropped:** `supporting` groups and weights — there is no score to contribute to.
A condition either holds or it does not. For the same reason a `none` condition has no
`disqualify` or `penalty` flag: it simply excludes.

**Metadata conditions are first-class.** `match.metadata` alone makes a detection
satisfiable (Part C). An item may combine signals and metadata freely.

A detection may reference signals that are not registered yet. The item is accepted,
computed `not_ready` with each such signal blocking as `signal_not_registered`, and is
never evaluated until the signal exists and is ready. The write returns a warning rather
than an error.

---

---

## Part F — Resolutions and decisions

### `item_resolutions`

The menu. Client-agnostic, grows across engagements.

`id` PK · `item_id` FK · `name` · `description` · `target_description` ·
`consumer_impact` (`none`/`low`/`medium`/`high`) · `effort` (`low`/`medium`/`high`) ·
`is_default` BOOL · `linux_compatible` BOOL · `container_ready` BOOL ·
`notes` · `created_at`/`updated_at`

`impact_rules` JSONB (default `[]`): what converting an item this way touches, evaluated by
`impact-analysis` (`33-IMPACT-ANALYSIS.md` Part D). Authored as `impact:` in
`catalog_items.yaml`, seeded through the never-overwrite path and exported; empty means the
default rule (the work item's own evidence, `update`). Optional in the baseline: an empty
list is left out of the content hash and the export.

`engine_guidance` TEXT (null when none is written): what to do, in steps, for a conversion
engine (36-COPILOT-ENHANCED-CONVERSION Part K). `description`, `target_description` and `notes`
are for catalog authors. Factory defaults in `backend/app/seed/data/engine_guidance.yaml`, for
the item and its resolutions together; seeded through the never-overwrite path and exported,
optional in the baseline like `impact_rules`. Editable through the API; a write that omits it
leaves it unchanged.

Unique on `(item_id, name)`. **Exactly one** `is_default` per active item with any live,
active resolution, guaranteed by the database, not just by the API: at most one by
`uq_item_resolutions_one_default` (over live resolutions), at least one by the deferred
constraint trigger `trg_item_resolutions_one_default`, checked at commit, which also
requires the default to be active. The API makes an item's first resolution its default,
restores a resolution as the default when the item has none, and refuses (409
`DEFAULT_REQUIRED`) to unset, deprecate or delete the default while other resolutions
remain. `python -m app.items.catalog_seed --check-defaults` lists any violation; the seed
and the catalog import check before committing. The default is the presumptive choice for every engagement, so it moves in one
transaction: `POST /api/catalog/items/{id}/resolutions/{rid}/make-default` unsets
the old default and sets the new one together, or changes nothing. A deprecated
resolution cannot become the default.

### `engagement_decisions`

One chosen resolution per item per engagement. **Captured upfront**, before repo
ingestion — this is what replaces v1's target state governance steps.

`id` PK · `engagement_id` FK · `item_id` FK · `resolution_id` FK (nullable until approval) ·
`candidates_considered` · `rationale` · `forcing_perspective` · `forcing_rationale` ·
`evaluation_notes` · `approver_name` · `approver_role` · `decision_date` ·
`status` (`pending`/`in_review`/`approved`/`superseded`) · `created_at`/`updated_at`

Partial unique on `(engagement_id, item_id) WHERE status <> 'superseded'`.

Updates are partial. A field **omitted** from the body keeps its value; a field sent as
an explicit **`null`** is cleared. That lets a decision moved from a higher-impact
resolution back to the default shed its forcing perspective and rationale. Otherwise
it would keep a justification it no longer needs and be counted under that
perspective. `status` cannot be null. The result is validated as a whole, so clearing
something an approval needs is rejected.

`forcing_perspective` and `forcing_rationale` are a pair, as established in
`25-STANDARDS-AND-VIEWPOINTS.md` A1. `candidates_considered` records which resolutions
were presented at decision time. The menu grows across engagements, so that history is
kept even though validation judges against the full menu. *Both, and `in_review`, were
restored in review after an earlier draft of this Part omitted them.*

Validation retained from the old decision records, applied on approval: a selected
resolution belonging to the item, a `rationale`, an approver and a date. Selecting a
resolution that is not the lowest `consumer_impact` among the item's live resolutions
also requires both `forcing_perspective` and `forcing_rationale`.

Also retained: warn when the selected resolution has `linux_compatible: false` while
the engagement targets Linux.

---

---

## Part G — `item_occurrences`

The work list's raw rows. Produced by `item-detection`, replaced per repository on rescan.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `repository_id` | `UUID` NOT NULL FK | |
| `project_id` | `UUID` NOT NULL FK | |
| `item_id` | `TEXT` NOT NULL FK | |
| `scope` | `TEXT` NOT NULL | Denormalised from the item |
| `file_path` | `TEXT` | **Null for application scope** |
| `evidence` | `JSONB` | Line spans and values, projected from the signal |
| `signal_registry_version` | `TEXT` NOT NULL | The version the fingerprint was produced under |
| `detection_state` | `TEXT` NOT NULL | CHECK IN (`found`, `checked_absent`, `not_checked`) |
| `step_execution_id` | `UUID` | |
| `detected_at` | `TIMESTAMPTZ` | |

Unique on `(project_id, item_id, file_path)` — treat null `file_path` as application
scope via a partial index.

### `detection_state` — the honesty field

| State | Meaning |
|---|---|
| `found` | Item detected here |
| `checked_absent` | Item evaluated, not present. Genuinely clean |
| `not_checked` | The fingerprint predates a signal this item needs. **Unknown** |

`not_checked` arises when a repository was scanned under a signal registry version
older than the one introducing a signal the item references. Without it, adding an
extractor silently produces wrong results for every repository scanned beforehand —
and across 600 repositories scanned over months, that is guaranteed to happen.

Requires `signal_introduced_in_version` on each registry entry, compared against the
fingerprint's `signal_registry_version`. A `not_checked` result drives a rescan flag
on the dashboard.

Occurrences from a signal whose extractor is later removed **remain valid** — the
`signal_registry_version` on the row records what was true when detected. Readiness
state does not retroactively invalidate detections.

### As implemented (`item-detection`, `backend/app/steps/item_detection.py`)

- **One recorded answer per item per project.** Every evaluated pair writes at least one
  row: `checked_absent` and `not_checked` are a single project-level row with no
  `file_path`.
- **Found but unlocated.** An occurrence-scope item can hold on a signal that locates
  nothing (`system-drawing-common` matched on the package alone). It writes one `found`
  row with no `file_path`. The CHECK is "`file_path` only on a found occurrence-scope
  row", not "iff".
- **`value` column.** For `group_by: source_path_and_value` (one row per connection
  string, one per secret key) the located unique index is `(project_id, item_id,
  file_path, value)`, NULLS NOT DISTINCT.
- **Only rows the condition accepts are projected.** A Serilog sink whose path is not a
  Windows path is not an occurrence of an item whose condition requires one.
- **Certainty (item-occurrences 1.1.0).** A signal's evidence entry may carry
  `certainty: confirmed | ambiguous`. Today only `dependency-assessment`'s `PACKAGE_UPGRADE_BREAKING`
  call sites do, where an unchanged overload could equally take the call. An occurrence
  whose every evidence entry is ambiguous is `item_occurrences.certainty = possible`;
  everything else, including evidence that says nothing about certainty, is
  `confirmed`. Possible occurrences are listed apart in the work list and left out of work
  totals by default: the dashboard's `occurrences_found` (`include_possible=true` counts
  them), the work list's found and occurrence counts, and the repository page's Items found
  tile. An item found in a project only through possible occurrences
  (`summary.possible_only_found`) is not counted as found work either.
  There is no effort-hours total yet; these counts are the work totals.
- **`not_checked` means the platform does not know**, and is never reported as absence:
  - the fingerprint's registry version predates a referenced signal
  - `application-fingerprinting` failed on the project
  - `application-fingerprinting` never reached the project
  - a metadata field one of the item's conditions reads (`frameworkFamily`,
    `frameworkVersion`, `outputType`, `structuralType`, `projectSdk`, `projectFormat`, ...)
    is null for the project. This applies to exclusions too: a `notEquals` on an unknown
    value would otherwise pass and claim knowledge the scan lacks. The reason names the
    field ("project metadata unknown: frameworkFamily").

  Null therefore has to mean genuinely unknown. `solution-discovery` records what MSBuild itself
  defines instead of leaving it null: the framework from `Directory.*.props`, the
  declared SDK (`none` for a legacy MSBuild project), and the output type's SDK default
  when the project declares none (19-SOLUTION-DISCOVERY.md Part F).
- **Deliberately skipped projects are not `not_checked`.** A project `application-fingerprinting` skips as out
  of scope (`.dcproj`, `.sfproj`, Node.js) will never be fingerprinted. Signal-based
  items do not apply to it and write no row; items detected purely by `solution-discovery` metadata are
  still evaluated.
- **Role exclusion writes no row.** An item whose `excluded_roles` contains the project's
  role (Part D, `app/items/roles.py`) does not apply to it.
- **Not-ready items write nothing** (Part C).
- **The artifact** is `item-occurrences@1.0.0`: sorted keys and collections, no
  timestamps. It carries each project's computed role and reason, and the catalog item
  versions evaluated. Byte-identical across runs on unchanged input.

---

---

## Part H — Coverage views

Two lists, both falling out of the readiness relationship.

**Item coverage** — `not_ready` items with their blocking signals, grouped by
expected extractor. This is the extractor backlog, ordered by how many items each
unblocks.

**Signal coverage** — `ready` signals referenced by no item. Either the extractor is
doing unnecessary work, or an item is missing.

```
GET /api/catalog/item-coverage
GET /api/catalog/signal-coverage
GET /api/catalog/extractor-backlog
GET /api/catalog/signal-index            every signal, and the items referencing it
GET /api/catalog/items/{id}/signals      the reverse: one item's signals
```

**The signal index** is built server-side from stored detections, so no client
re-parses rules. Each reference says how the item uses the signal:

- `match` — in `all`, `any` or `atLeast`
- `none` — in an exclusion
- `occurrence_source` — locates occurrences

A signal referenced only in `none` is flagged `exclusion_only`. It does exclusion work,
not detection, which matters when judging whether its extractor earns its keep.

### LLM-assisted signal suggestion

When authoring an item, an optional assist proposes which existing signals might
express it, or concludes a new extractor is needed. Given 91 signal names, this saves
an author reading the registry.

**Advisory only.** It proposes; a human commits. It must never write a detection
rule — an item silently bound to a wrong-but-plausible signal would look ready and
detect the wrong thing, which is worse than one honestly pending. Same discipline as
cluster narration.

### Deliberately not catalogued

Signal coverage lists ready signals that no item references. Most are descriptive rather
than work — test attributes, folders, HTTP attributes, ASP.NET Core namespaces — and feed
`item-detection`'s role derivation instead of items. The groups below *are* migration-relevant and
were reviewed and **left out on purpose** after `application-fingerprinting` batch 2. Revisit when the
condition in the last column changes.

| Signals | Why no item | Revisit when |
|---|---|---|
| Redis — `STACKEXCHANGE_REDIS_PACKAGE`, `REDIS_CONNECTION_CONFIG` | The client runs on Linux unchanged. The real work — endpoint, TLS, password as a Secret — is configuration, covered by `sensitive-config-key` and the outbound inventory (`outbound-invocation-inventory`) | A Redis-specific conversion appears (e.g. a Windows-only cache provider) |
| Kafka — `CONFLUENT_KAFKA_PACKAGE`, `KAFKA_BOOTSTRAP_CONFIG` | Confluent.Kafka ships Linux native libraries and runs unchanged. The one real risk, **SASL/GSSAPI (Kerberos) authentication, cannot be assessed from these signals: it needs a new config signal** for the `sasl.mechanism` / `SaslMechanism` setting before an item can detect it | That signal is registered |
| Vault — `VAULTSHARP_PACKAGE`, `VAULT_CONFIG` | Works on Linux. The work is a platform choice (Kubernetes auth method, or Vault Agent injection instead of the SDK) the client makes once, not a per-project finding | The engagement's secret-delivery pattern is decided |
| Entity Framework 6 — `ENTITYFRAMEWORK_PACKAGE`, `SYSTEM_DATA_ENTITY_NAMESPACE` | EF6 6.3+ runs on .NET 8/10. Porting to EF Core is an optional decision, not a blocker | A client wants EF Core as a target state |
| HTTP handlers and modules — `IHTTP_HANDLER_BASE_CLASS`, `IHTTP_MODULE_BASE_CLASS` | They become middleware, but only once the framework item (`aspnet-webforms`, `fx-aspnet-mvc`) has moved the application to ASP.NET Core; on its own the finding has no conversion | Conversion approaches for the framework items exist, to sequence after |
| Azure Functions — `FUNCTION_NAME_ATTRIBUTE`, `FUNCTIONS_FOLDER` | Only relevant to an estate that has them; none of the current engagements do | An engagement has Azure Functions |
| Process launch — `PROCESS_START_USAGE` | Not inherently broken on Linux; whether it is depends on what is launched (`cmd.exe`, `powershell`), which `application-fingerprinting` deliberately does not record | Someone wants a human-review item for it |

---

---

## Part I — Conversion: five decisions taken

**B1. Conversions do not write to platform tables.** Unlike lifecycle steps, a
conversion receives its context, edits source files, and reports. It gets no
`database_url`. The platform records the outcome. This means an accelerator written
by anyone cannot corrupt platform state, and it is the difference between a
contributed step and a contributed *code change*.

**B2. One git commit per conversion execution (confirmed).** Message derived from the approach.
Rollback is `git revert`, the PR reads as a sequence of named remediations, and
traceability is free. No bespoke rollback machinery.

**B3. Batching is declared, not assumed.** Sixteen `appsettings` files with a Serilog
sink is one coherent change; three `Encoding.Default` occurrences may be independent.
An LLM-based approach may need per-file for context reasons. The approach declares it.

**B4. Dry run is mandatory.** Every approach must support producing its diff without
applying it. This drives estimation, Tier 2 plan approval, and safe rehearsal.

**B5. Three check levels, not one.** Pre-checks ask *should this run*. Post-checks ask
*did it do what it claimed*. Verification asks *is the project still sound*. Collapsing
them loses the distinction between "not applicable", "did the wrong thing" and "broke
the build".

---

---

## Part J — `conversion_approaches`

The table the delivery team populates.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | Slug, e.g. `remove-serilog-file-sink` |
| `version` | `TEXT` NOT NULL | Semver. Recorded on every execution |
| `name` / `description` | `TEXT` | |
| `item_id` | `TEXT` NOT NULL FK → `catalog_items.id` | |
| `resolution_id` | `TEXT` NOT NULL FK → `item_resolutions.id` | The binding: item + chosen resolution |
| `scope` | `TEXT` NOT NULL | CHECK IN (`application`, `occurrence`). Must match the item's scope |
| `invocation` | `JSONB` NOT NULL | See Part D |
| `batching` | `TEXT` NOT NULL DEFAULT `'all'` | CHECK IN (`all`, `per_file`, `per_occurrence`). Ignored for application scope |
| `max_batch_size` | `INTEGER` | Optional cap when `batching` is `all` |
| `pre_checks` | `JSONB` NOT NULL DEFAULT `'[]'` | |
| `post_checks` | `JSONB` NOT NULL DEFAULT `'[]'` | |
| `verification` | `JSONB` NOT NULL DEFAULT `'[]'` | |
| `depends_on` | `JSONB` NOT NULL DEFAULT `'[]'` | Approach ids that must complete first within the same project |
| `order_hint` | `INTEGER` NOT NULL DEFAULT 100 | Tiebreak within a scope |
| `allowed_paths` | `JSONB` | Glob allowlist. A write outside it fails the execution |
| `requires_human_review` | `BOOLEAN` NOT NULL DEFAULT false | Forces review regardless of tier |
| `review_reason` | `TEXT` | Required when the above is true |
| `idempotent` | `BOOLEAN` NOT NULL DEFAULT true | False means never auto-retry |
| `estimated_minutes_per_occurrence` | `INTEGER` | Feeds effort rollup |
| `status` | `TEXT` NOT NULL DEFAULT `'draft'` | CHECK IN (`draft`, `active`, `deprecated`) |
| `owner_team` | `TEXT` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Unique on `(item_id, resolution_id)` where `status = 'active'` — one active approach
per decision. Changing how something is converted is a new version, not a second row.

`allowed_paths` is the containment guard. An approach declaring
`["**/appsettings*.json"]` that writes a `.cs` file fails. Cheap, and it is what makes
a contributed accelerator safe to run unattended across 600 applications.

---

---

## Part K — Invocation

Mirrors the step adapter contract, so the existing adapter layer is reused.

```json
{
  "type": "python",
  "config": { "entrypoint": "conversions.serilog:remove_file_sink" }
}
```

| Type | Config | Use |
|---|---|---|
| `python` | `entrypoint` | In-process. Deterministic edits |
| `process` | `command`, `cwd`, `timeout_seconds` | Any language. The general contributor path |
| `skill` | `skill_name`, `prompt_template`, `allowed_tools` | Claude Code with a scoped skill |
| `copilot` | `scenario`, `playbook_ref` | Copilot modernization |
| `http` | `url`, `timeout_seconds` | A service |
| `human` | `instructions`, `checklist` | No automation exists; creates a work item |
| `noop` | — | Decision is "no action required" |

`human` is a first-class type. Some resolutions have no automation and saying so
explicitly is better than leaving them undetected.

---

---

## Part L — `ConversionContext`

What the platform passes in. **Stable contract — version it if it changes.**

```json
{
  "envelope_version": "1.0",
  "conversion_execution_id": "…",
  "conversion_approach_id": "remove-serilog-file-sink",
  "conversion_approach_version": "1.2.0",
  "scope": "occurrence",
  "dry_run": false,

  "repository": {
    "id": "…", "slug": "orders-api",
    "local_path": "D:\\repos\\orders-api",
    "branch": "modernization/ocp4"
  },

  "project": {
    "id": "…", "name": "OrdersApi",
    "relative_path": "src/OrdersApi/OrdersApi.csproj",
    "framework_family": "net", "framework_version": "10.0",
    "output_type": "Exe", "project_format": "sdk_style"
  },

  "item": {
    "id": "serilog-file-sink",
    "name": "Serilog file sink writing to a Windows path",
    "scope": "occurrence"
  },

  "resolution": {
    "id": "console-json-only",
    "name": "Console sink with CompactJsonFormatter only",
    "parameters": { "formatter": "CompactJsonFormatter", "retain_console_sink": true }
  },

  "occurrences": [
    {
      "occurrence_id": "…",
      "file_path": "src/OrdersApi/appsettings.json",
      "evidence": [ { "line_start": 42, "line_end": 58, "signal_name": "SERILOG_FILE_SINK_CONFIG", "value": "G:\\Logs\\OrdersApi\\" } ]
    }
  ],

  "engagement_parameters": {
    "target_platform": "ocp4",
    "target_framework": "net10.0",
    "log_destination": "stdout-efk",
    "naming_conventions": { "configmap_prefix": "app-" }
  },

  "working_dir": "…", "output_dir": "…",
  "allowed_paths": ["**/appsettings*.json"],
  "log_level": "INFO"
}
```

`resolution.parameters` is how one approach serves several engagements without
branching — the client's choices arrive as data.

For `application` scope, `occurrences` is empty and the whole project is in play.

---

---

## Part M — `ConversionResult`

```json
{
  "envelope_version": "1.0",
  "status": "SUCCESS",
  "message": "Removed file sink from 6 appsettings files",

  "occurrences_resolved": ["…", "…"],
  "occurrences_failed": [ { "occurrence_id": "…", "reason": "sink not found — already removed" } ],

  "files_modified": ["src/OrdersApi/appsettings.json"],
  "files_created": [], "files_deleted": [],

  "pre_check_results":    [ { "check": "sink-present", "passed": true } ],
  "post_check_results":   [ { "check": "no-windows-path", "passed": true } ],
  "verification_results": [ { "check": "build", "passed": true, "duration_ms": 18400 } ],

  "metrics": { "occurrences_resolved": 6, "occurrences_failed": 0, "files_touched": 6 },
  "diagnostics": [ { "level": "warning", "code": "…", "message": "…", "ref": "…" } ],

  "requires_human_review": false,
  "review_reason": null,
  "diff_summary": { "lines_added": 0, "lines_removed": 94 }
}
```

Statuses: `SUCCESS` · `PARTIAL` (some occurrences resolved) · `FAILED` ·
`NOT_APPLICABLE` (pre-checks say nothing to do — not a failure) · `SKIPPED`.

On `dry_run: true`, the same shape with no files written and the diff in
`output_dir`.

---

---

## Part N — Checks

```json
{
  "pre_checks": [
    { "id": "sink-present", "type": "file_contains", "path": "{occurrence.file_path}", "pattern": "\"Name\"\\s*:\\s*\"File\"" }
  ],
  "post_checks": [
    { "id": "no-windows-path", "type": "file_not_matches", "path": "{occurrence.file_path}", "pattern": "[A-Z]:\\\\\\\\" },
    { "id": "valid-json",      "type": "json_parses",      "path": "{occurrence.file_path}" }
  ],
  "verification": [
    { "id": "build", "type": "shell", "command": "dotnet build {project.relative_path} -c Release" }
  ]
}
```

Check types: `file_exists`, `file_contains`, `file_not_matches`, `json_parses`,
`xml_parses`, `shell`, `signal_absent` (re-run the `application-fingerprinting` extractor and assert the
signal is gone — the strongest post-check available).

**A failed pre-check yields `NOT_APPLICABLE`, not failure.** A failed post-check is a
failure and triggers rollback. Verification failure is a failure but rollback is
configurable, since a pre-existing broken build should not be attributed to the
conversion.

---

---

## Part O — Worked examples

Both are patterns typical of legacy .NET estates; the repositories and counts are invented for the examples. The test that decides scope:

> **Can this occur more than once in a single project?** Six Serilog file sinks —
> yes, occurrence. One host builder — no, application.

Application scope is not "bigger". It is "at most once per project, and it is a choice
about the project".

### J1 — Occurrence scope: Serilog file sink

`orders-api` — a Serilog file sink writing to a Windows path in each of its six `appsettings` files.

**Catalog item** (client-agnostic, defined once):

```json
{
  "id": "serilog-file-sink",
  "name": "Serilog file sink writing to a Windows path",
  "scope": "occurrence",
  "category": "logging",
  "detection": {
    "all": [ { "signal": { "name": "SERILOG_FILE_SINK_CONFIG" } } ]
  }
}
```

**Resolutions:**

| id | Description | Consumer impact | Default |
|---|---|---|---|
| `console-json-only` | Remove file sink; keep console with CompactJsonFormatter for EFK | low | yes |
| `otlp-exporter` | Replace with an OpenTelemetry exporter | medium | |

**Engagement decision:** the client selects `console-json-only`, with rationale,
approver and date.

**Conversion approach:**

```json
{
  "id": "remove-serilog-file-sink",
  "version": "1.0.0",
  "item_id": "serilog-file-sink",
  "resolution_id": "console-json-only",
  "scope": "occurrence",

  "invocation": {
    "type": "python",
    "config": { "entrypoint": "conversions.serilog:remove_file_sink" }
  },

  "batching": "all",
  "allowed_paths": ["**/appsettings*.json", "**/appsettings.*.json"],

  "pre_checks": [
    { "id": "sink-present", "type": "file_contains",
      "path": "{occurrence.file_path}", "pattern": "\"Name\"\\s*:\\s*\"File\"" }
  ],
  "post_checks": [
    { "id": "valid-json",   "type": "json_parses",      "path": "{occurrence.file_path}" },
    { "id": "no-win-path",  "type": "file_not_matches", "path": "{occurrence.file_path}",
      "pattern": "[A-Za-z]:\\\\\\\\" },
    { "id": "console-kept", "type": "file_contains",    "path": "{occurrence.file_path}",
      "pattern": "\"Name\"\\s*:\\s*\"Console\"" }
  ],
  "verification": [
    { "id": "build", "type": "shell",
      "command": "dotnet build {project.relative_path} -c Release" }
  ],

  "estimated_minutes_per_occurrence": 3,
  "status": "active"
}
```

`batching: all` because six config files are one coherent change. Six separate
edits and six builds would be slower and no safer.

**ConversionContext in** (abbreviated to two of six occurrences):

```json
{
  "envelope_version": "1.0",
  "conversion_execution_id": "ce-8f2c",
  "conversion_approach_id": "remove-serilog-file-sink",
  "conversion_approach_version": "1.0.0",
  "scope": "occurrence",
  "dry_run": false,

  "repository": { "id": "r-001", "slug": "orders-api",
                  "local_path": "D:\\repos\\orders-api",
                  "branch": "modernization/ocp4" },

  "project": { "id": "p-014", "name": "OrdersApi",
               "relative_path": "src/OrdersApi/OrdersApi.csproj",
               "framework_family": "net", "framework_version": "10.0",
               "output_type": "Exe", "project_format": "sdk_style" },

  "item": { "id": "serilog-file-sink", "scope": "occurrence" },

  "resolution": { "id": "console-json-only",
                  "parameters": { "formatter": "CompactJsonFormatter",
                                  "retain_console_sink": true } },

  "occurrences": [
    { "occurrence_id": "o-001",
      "file_path": "src/OrdersApi/appsettings.json",
      "evidence": [ { "line_start": 42, "line_end": 58,
                      "signal_name": "SERILOG_FILE_SINK_CONFIG",
                      "value": "G:\\Logs\\OrdersApi\\" } ] },
    { "occurrence_id": "o-002",
      "file_path": "src/OrdersApi/appsettings.DEV.json",
      "evidence": [ { "line_start": 39, "line_end": 55,
                      "signal_name": "SERILOG_FILE_SINK_CONFIG",
                      "value": "C:\\logs\\OrdersApi\\" } ] }
  ],

  "engagement_parameters": { "target_platform": "ocp4",
                             "log_destination": "stdout-efk" },

  "working_dir": "runs/.../remove-serilog-file-sink",
  "output_dir": "runs/.../remove-serilog-file-sink/out",
  "allowed_paths": ["**/appsettings*.json", "**/appsettings.*.json"],
  "log_level": "INFO"
}
```

**ConversionResult out:**

```json
{
  "envelope_version": "1.0",
  "status": "SUCCESS",
  "message": "Removed file sink from 16 appsettings files",

  "occurrences_resolved": ["o-001", "o-002"],
  "occurrences_failed": [],

  "files_modified": ["src/OrdersApi/appsettings.json",
                     "src/OrdersApi/appsettings.DEV.json"],
  "files_created": [], "files_deleted": [],

  "pre_check_results":    [ { "check": "sink-present",  "passed": true } ],
  "post_check_results":   [ { "check": "valid-json",    "passed": true },
                            { "check": "no-win-path",   "passed": true },
                            { "check": "console-kept",  "passed": true } ],
  "verification_results": [ { "check": "build", "passed": true, "duration_ms": 18400 } ],

  "metrics": { "occurrences_resolved": 16, "occurrences_failed": 0, "files_touched": 16 },
  "diagnostics": [],
  "requires_human_review": false,
  "diff_summary": { "lines_added": 0, "lines_removed": 94 }
}
```

### J2 — Application scope: Windows Service hosting

`batch-worker` — `UseWindowsService()` in `Program.cs`, flagged BLOCKER.

**Catalog item:**

```json
{
  "id": "windows-service-hosting",
  "name": "Application hosts as a Windows Service",
  "scope": "application",
  "category": "hosting",
  "detection": {
    "any": [
      { "signal": { "name": "USE_WINDOWS_SERVICE_INVOCATION" } },
      { "signal": { "name": "MICROSOFT_EXTENSIONS_HOSTING_WINDOWSSERVICES_PACKAGE" } }
    ]
  }
}
```

**Resolutions:**

| id | Description | Consumer impact | Default |
|---|---|---|---|
| `generic-host-deployment` | Generic host, deployed as an OCP4 Deployment | low | yes |
| `generic-host-cronjob` | Generic host, scheduled as an OCP4 CronJob | medium | |
| `remain-windows-hosted` | Out of scope; stays on Windows | none | |

The client selects `generic-host-deployment` — the assessment records
*"Deployment replicas=1, NOT Job/CronJob"*, because it is a continuous queue processor.

**Conversion approach:**

```json
{
  "id": "windows-service-to-generic-host",
  "version": "1.0.0",
  "item_id": "windows-service-hosting",
  "resolution_id": "generic-host-deployment",
  "scope": "application",

  "invocation": {
    "type": "process",
    "config": { "command": ["conversions/dotnet/publish/HostingConverter.exe"],
                "timeout_seconds": 600 }
  },

  "allowed_paths": ["**/Program.cs", "**/*.csproj"],
  "order_hint": 10,

  "pre_checks": [
    { "id": "uses-windows-service", "type": "file_contains",
      "path": "{project.dir}/Program.cs", "pattern": "UseWindowsService\\(" }
  ],
  "post_checks": [
    { "id": "no-windows-service",  "type": "file_not_matches",
      "path": "{project.dir}/Program.cs", "pattern": "UseWindowsService\\(" },
    { "id": "package-removed",     "type": "file_not_matches",
      "path": "{project.relative_path}",
      "pattern": "Microsoft\\.Extensions\\.Hosting\\.WindowsServices" },
    { "id": "host-builder-intact", "type": "file_contains",
      "path": "{project.dir}/Program.cs",
      "pattern": "CreateApplicationBuilder|CreateDefaultBuilder" }
  ],
  "verification": [
    { "id": "build", "type": "shell",
      "command": "dotnet build {project.relative_path} -c Release" },
    { "id": "test",  "type": "shell",
      "command": "dotnet test {project.relative_path} --no-build" }
  ],

  "estimated_minutes_per_occurrence": 45,
  "status": "active"
}
```

**ConversionContext in** — note `occurrences` is empty; the project is the subject:

```json
{
  "envelope_version": "1.0",
  "conversion_execution_id": "ce-b41a",
  "conversion_approach_id": "windows-service-to-generic-host",
  "conversion_approach_version": "1.0.0",
  "scope": "application",
  "dry_run": false,

  "repository": { "id": "r-007", "slug": "batch-worker",
                  "local_path": "D:\\repos\\batch-worker",
                  "branch": "modernization/ocp4" },

  "project": { "id": "p-102", "name": "WorkflowService",
               "relative_path": "src/WorkflowService/WorkflowService.csproj",
               "framework_family": "net", "framework_version": "10.0",
               "output_type": "Exe", "project_format": "sdk_style" },

  "item": { "id": "windows-service-hosting", "scope": "application" },

  "resolution": { "id": "generic-host-deployment",
                  "parameters": { "replicas": 1, "restart_policy": "Always" } },

  "occurrences": [],

  "engagement_parameters": { "target_platform": "ocp4",
                             "target_framework": "net10.0" },

  "working_dir": "runs/.../windows-service-to-generic-host",
  "output_dir": "runs/.../windows-service-to-generic-host/out",
  "allowed_paths": ["**/Program.cs", "**/*.csproj"],
  "log_level": "INFO"
}
```

**ConversionResult out:**

```json
{
  "envelope_version": "1.0",
  "status": "SUCCESS",
  "message": "Removed Windows Service hosting; generic host retained",

  "occurrences_resolved": [],
  "occurrences_failed": [],

  "files_modified": ["src/WorkflowService/Program.cs",
                     "src/WorkflowService/WorkflowService.csproj"],
  "files_created": [], "files_deleted": [],

  "pre_check_results":    [ { "check": "uses-windows-service", "passed": true } ],
  "post_check_results":   [ { "check": "no-windows-service",   "passed": true },
                            { "check": "package-removed",      "passed": true },
                            { "check": "host-builder-intact",  "passed": true } ],
  "verification_results": [ { "check": "build", "passed": true, "duration_ms": 22100 },
                            { "check": "test",  "passed": true, "detail": "203 passed" } ],

  "metrics": { "files_touched": 2 },
  "diagnostics": [],
  "requires_human_review": false,
  "diff_summary": { "lines_added": 3, "lines_removed": 7 }
}
```

### J3 — The differences that matter

| | Occurrence scope | Application scope |
|---|---|---|
| `occurrences[]` | Populated; drives the work | Empty; the project is the subject |
| Path templates | `{occurrence.file_path}` | `{project.dir}`, `{project.relative_path}` |
| `batching` | Meaningful | Ignored |
| Effort | Per occurrence x count | Per project |
| Runs in | Step B | Step A, first |

**Why ordering matters, concretely.** `windows-service-to-generic-host` rewrites
`Program.cs`. A later occurrence-scope conversion adding health endpoints also touches
`Program.cs`. Run in the other order, the health-endpoint edit would land on a file
about to be restructured. This is why application scope runs first, and why
`depends_on` and `order_hint` exist within a scope.

---

---

## Part P — Tables

| Table | Holds |
|---|---|
| `catalog_items` | id, name, description, scope, detection rule, category, status. Client-agnostic |
| `item_resolutions` | id, item_id, name, description, target description, consumer impact, effort, default flag |
| `engagement_decisions` | engagement_id, item_id, chosen resolution, rationale, forcing perspective, approver, date, status |
| `item_occurrences` | occurrence_id, repository_id, project_id, item_id, file_path, evidence, detected_at, status |
| `conversion_approaches` | Part C |
| `conversion_executions` | execution_id, work_item, approach id + version, status, result payload, commit sha, timings |

**The work list** is a view: occurrences joined to decisions joined to approaches.
`repo · project · item · resolution · approach · files[] · status`. Count it for an
estimate, group it for a dashboard, iterate it to convert.

An occurrence with no decision is flagged, never guessed — surfaced on the UI as
"decision required" exactly as you described.

---

---

## Part Q — Migration

Existing catalog: 21 patterns, target state options, decision records, engagement
overlays, and `pattern-classification`'s classification tables.

| Existing | Becomes |
|---|---|
| `patterns` (work patterns) | `catalog_items` — keep id, name, description, detection `match`; add `scope` and `occurrence_source`; drop the election columns |
| `patterns` (6 role patterns) | **Not migrated.** Role is computed per Part D; the pattern rows stay until cut-over |
| `patterns` (5 modern + 2 desktop) | **Review case by case.** Most describe what an application *is*, which the catalog no longer models. Retain only where they identify real work |
| `target_state_options` | `item_resolutions` |
| `decision_records` | `engagement_decisions` |
| `engagement_patterns` overlay | `engagement_item_scope` — same purpose, renamed |
| `project_classifications`, `classification_matches` | **Dropped.** Replaced by `item_occurrences` |
| `catalog_coverage_reports` | Replaced by the Part G views |

**Run both models side by side** rather than cutting over. Build the new tables, have
`item-detection` populate occurrences, and verify against the two sample repositories before
dropping the classification tables. The old data is the only reference for whether the
new detection produces sensible results.

Each surviving item needs `scope` and, for occurrence scope, `occurrence_source`
assigned by hand. That is a judgement call per item — apply the Part O scope test:
*can this occur more than once in a single project?*

### As migrated

Run by `backend/app/items/pattern_migration.py` (also part of `python -m app.seed`).
It is idempotent and reversible: `--revert` removes exactly the rows it wrote, and
refuses once occurrences, resolutions or decisions have been built on top of them. It
never writes to the pattern tables.

| Patterns | Outcome |
|---|---|
| 8 work patterns | Items, all **application** scope, no `occurrence_source`. Detection is the old rules verbatim minus `supporting`, `schema`, `matchWarnings` and the `none` flags. `excluded_roles` is left empty so detection matches the old model in the side-by-side comparison |
| `winforms-desktop`, `wpf-desktop` | Items, application scope, category `hosting`: a desktop UI cannot land on OpenShift. WinForms keeps its detection (WinExe with XAML absent); the positive signals it lacks are recorded in its description as an enhancement |
| 5 already-modern patterns | Not migrated — they describe what an application is. **Knock-on:** client-a's parked `aspnetcore-minimal-api` decision (forcing perspective `REGULATION`) has no item to attach to and stays in `decision_records` |
| 6 role patterns | Not migrated — role is computed (Part D) |

Resolutions keep their target state option ids (`is_recommended` → `is_default`).
Decisions keep their ids. `parked` becomes `pending`; `in_review`, `approved` and
`superseded` are unchanged. Forcing pairs and `candidates_considered` carry over
intact.

**All migrated items are application scope.** The occurrence path is exercised by the
five authored items in `backend/app/seed/data/catalog_items.yaml`.

---

---

## Part R — What this replaces

| Existing | Fate |
|---|---|
| `repository-ingest`, `solution-discovery` | Unchanged |
| `application-fingerprinting` | **Unchanged and now central.** Signals and evidence are the detection engine; evidence supplies occurrence file paths |
| `pattern-classification` | **Rewritten, much smaller.** Detection rules survive. Primary election, conflicts, ambiguity, the eight statuses, scoring resolution all removed |
| `pattern-discovery-clustering`, `pattern-validation` | Demoted to a safety net: signals matching no catalog item, reported for review |
| Three-layer catalog | Replaced by items + resolutions + decisions |
| Track A's v1 transformation steps (engine assessment through logging & health) | **Collapse** into the two conversion steps |
| Engine, adapters, gates, policy, observability, admin | Unchanged |

Net effect deletes more code than it adds. The classification engine loses the half
that produced most of the recent defects.

---

---

---

## Part S — Settled decisions

Confirmed and not open for re-litigation without a reason:

| Decision | Status |
|---|---|
| `allowed_paths` as a hard containment guard | **Adopted.** A write outside the declared globs fails the execution |
| One git commit per conversion execution | **Adopted.** Message derived from the approach. Rollback is `git revert` |
| `human` invocation type | **Not adopted.** An item with no automation has no active approach row; its occurrences sit in the work list with status `awaiting_approach`. Honest, and the work list already shows what is unconverted |
| `signal_absent` post-check | **Deferred.** Available as a check type but not mandated |
| Approach version recorded per execution | **Deferred.** Recorded, but no re-run policy defined yet |

---

## Part T — Architecture items on `entry-point-inventory`'s signals

An architecture item describes something a whole application does, such as exposing a
WCF service, serving WebForms pages, or being an MVC site. Its pieces are often spread
over several projects, so a rule that needs every signal in one project never fires.
Architecture items therefore detect on `entry-point-inventory`'s architecture signals (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES Part B6),
which are emitted on the project that does the thing.

**Item attribute.** An application-scope item may record one fact about what it
detected, without matching on it:

```yaml
detection:
  attribute: { signal: WCF_SERVICE_HOSTING, label: hosting }
```

The occurrence value is `hosting: <value>; <value>`, using the signal's distinct values
in sorted order. The attribute signal is a referenced signal for readiness. An attribute
on any other scope is rejected (`ATTRIBUTE_NOT_ALLOWED`).

**Items.** These are applied by `app/items/architecture_items.py`
(`python -m app.items.architecture_items [--dry-run]`, idempotent), and called by the
seed after the authored items.

| Item | Change |
|---|---|
| `wcf-service` (new) | Replaces `wcf-iis-servicemodel`. Detects on any `EXPOSES_WCF_SERVICE`, with the hosting as an attribute, so IIS, self-hosted and both are one item. Resolutions: CoreWCF on .NET 10 (default, impact none), REST rewrite, gRPC rewrite, Remain Windows-hosted (`linux_compatible: false`, `container_ready: false`, like every other Linux-blocker item) |
| `wcf-service-host` (new) | Detects on any `HOSTS_WCF_SERVICE`: the process that hosts the service. Resolutions: ASP.NET Core web host (default), retire the host, remain Windows-hosted |
| `wcf-iis-servicemodel` | Soft-deleted (`deleted_by` "architecture-items: replaced by wcf-service"). Uses insert-new, repoint and soft-delete: every decision is repointed to `wcf-service` with its id kept, and its resolution mapped (`corewcf-net10` → CoreWCF, `rest-net10` → REST, `grpc-net10` → gRPC). An evaluation note records the move. Scope rows are copied |
| `console-batch-job` | Excluded on `HOSTS_WCF_SERVICE` and on every `EXPOSES_*`. A service host is not a batch job |
| `aspnet-webforms` | Detects on `EXPOSES_WEBFORMS_UI`. The `.aspx` pages and their code-behind may sit in different projects from the site's configuration |
| `fx-aspnet-mvc` | Detects on `EXPOSES_HTTP_API`. The controllers may be in a library separate from the web project |
| `asmx-service` | Detects on `EXPOSES_ASMX_SERVICE` |
| `aspnetcore-rest-api-legacy` | Unchanged. Its signals (the ASP.NET Core package and the legacy API constructs) sit on the same project by construction |
| `wcf-nettcp-client` | New resolution `migrate-to-service-protocol`: an internal client whose service is being re-platformed moves to whatever the service will expose |

On the WCF sample:
- `wcf-service` is found on `Catalog.Services`.
- `wcf-service-host` is found on `Catalog.Host`, where `console-batch-job` used to fire.
- `wcf-nettcp-client` and `console-batch-job` are found on `Catalog.TestClient`, which is
  a console client.

---

## Part U — Decision coupling

Architecture decisions drive others, **by resolution, not by item**: CoreWCF and a REST
rewrite of the same `wcf-service` mean different things for its clients. What choosing
each resolution means for each dependent item is master catalog data.

### Derivations are catalog data

`resolution_derivations`, keyed by (leading resolution, dependent item), is authored
beside the resolution in `catalog_items.yaml`:

```yaml
      - id: wcf-service-rest-rewrite
        ...
        derivations:
          - item: wcf-nettcp-client
            action: derive                       # derive | not_derived | subsume | not_subsumed
            resolution: migrate-to-service-protocol   # derive only
            applies_to: internal_clients         # optional; default all
            reason: "The service stops speaking WCF: an internal client moves to its REST API ..."
```

| Action | Meaning |
|---|---|
| `derive` | The dependent's decision is derived as `resolution`. With `applies_to: internal_clients`, only on projects whose integration edges (`dependency-and-context-map`) reach the leader's project |
| `not_derived` | The leading decision does not settle the dependent. It stays awaiting_decision, and the work list shows the reason |
| `subsume` | The dependent, on the leader's own project, is no separate work |
| `not_subsumed` | It stays separate work, and the work list shows the reason |

`app/items/derivations.py` loads the rows, and the seed runs it last (`python -m
app.items.derivations [--dry-run]`). Validation is a hard error:
- the dependent item exists;
- a `derive` names a resolution of the dependent item, and every other action names none;
- **completeness**: every live resolution of a leading item declares a row for every
  dependent any of its resolutions names. A new resolution that forgets the clients fails
  the seed. It cannot silently derive nothing.

The YAML is a factory default (Part V):
- **Seeding.** A row not edited since it was seeded follows the file. When the file drops
  it, it is soft-deleted. An edited row is never overwritten.
- **Revert.** Pattern-migration revert removes rows that name a migrated item only when
  every one is unedited, so the seed can recreate it. Otherwise revert refuses.
- **Where they show.** The catalog shows the rows beside each resolution ("Choosing this
  derives"), and `GET /api/catalog/items/{id}/resolutions` returns them as
  `derivations`.

**wcf-service, as authored:**

| wcf-service | wcf-service-host | wcf-nettcp-client | fx47-class-library |
|---|---|---|---|
| REST rewrite | derive: ASP.NET Core web host | derive: migrate to the service's new protocol (internal clients) | subsume |
| gRPC rewrite | derive: ASP.NET Core web host | derive: migrate to the service's new protocol (internal clients) | subsume |
| CoreWCF | derive: ASP.NET Core web host | not derived: CoreWCF keeps WCF and SOAP, so the client still needs a Linux-compatible binding | subsume |
| Remain Windows-hosted | not derived | not derived | not subsumed |

### Decisions

**Columns on `engagement_decisions`.** Migrations `d82f5c3e19a4` and `e5a1b7c9d302`.

| Column | Meaning |
|---|---|
| `source` | `manual` or `derived` |
| `derived_from_decision_id` | The leading decision |
| `derived_against_resolution_id` | The leading resolution the decision was derived from or overridden against. Replaces `derivation_rule`, which named a rule in code |
| `overrides_derivation` | A manual decision that replaced, or stands in place of, a derived one |
| `needs_review`, `review_note` | Whether the override needs review, and why |

**Derivation (`rederive`).**
- **When it runs:**
  - after any write to a leading decision;
  - after a supersede of a dependent's decision, so that superseding an override takes
    the derived decision again;
  - at the end of each `dependency-and-context-map` run.
- **What it does, for a dependent with no manual decision:**
  - When the row derives, the dependent's decision is created or updated:
    - its status follows the leader's;
    - approver and date are copied once the leader is approved;
    - the forcing pair is carried;
    - the rationale names the leader and the reason.
  - When nothing is derived (`not_derived`, no internal client, no decision on the
    leader), a derived decision is superseded.
- **A manual decision is never changed.** If a derivation applies to it, it is linked to
  the leader as an override.

**Overrides when the leader changes.** An override was made against a leading decision.
When that decision no longer stands, the override is flagged `needs_review`, never kept or
discarded silently. "No longer stands" means another resolution, another decision, or
superseded with nothing in its place.
- **The note** names the old and new leading decisions and what the new one would give,
  for example: "Overridden by hand against the WCF service decision (REST rewrite on
  .NET 10); that decision is now CoreWCF on .NET 10. It would derive ASP.NET Core web
  host. Review the override: …".
- **Clearing the flag:**
  - saving the decision again keeps the override, now against the current leader;
  - superseding it takes the derived decision;
  - the flag clears on its own if the leader returns to what it was.
- **The work list** shows the flag on the row, and the leader's "drives" list shows it too.

**Showing the dependency.**
- **On a decision:** `derived_from` (the leading decision, `derivation_reason`, and for an
  override `would_derive`) and `followers`.
- **On the work list:** `GET /api/repositories/{id}/work-list-decisions` gives per-project
  notes:
  - `subsumed_by`;
  - for a dependent, the leader it `follows`, the `action` and whether it `applies` there;
  - a note with the reason ("Not derived: the wcf-service decision (CoreWCF on .NET 10)
    does not settle this item. CoreWCF keeps WCF and SOAP, …").

**Client-scoped.** Derivation writes `engagement_decisions` only (rule 9). Derivations are
master catalog data and are read, never written, by engagement operations.

---

## Part V — The database is authoritative for the catalog

The item catalog is edited in the UI. These are **factory defaults**, not a second
source of truth:
- `catalog_items.yaml` (authored items, resolutions and derivations);
- the pattern tables the migration reads;
- the amendments in code (pattern migration and architecture items).

A reseed must never overwrite a catalog edit (CLAUDE.md rule 10).

**Baselines.** `catalog_items`, `item_resolutions` and `resolution_derivations` each carry
`seeded_hash` (migration `a3d9e6f20b17`). It is a SHA-256 of the content the seed last
wrote:
- the authored fields, plus whether the row is soft-deleted;
- not readiness, `version` or timestamps, which are computed.

A row is **edited** when its current content no longer hashes to `seeded_hash`. Every seed
write goes through `app/items/baseline.py` `seed_row`:

| Row | Factory default | Outcome |
|---|---|---|
| missing | — | inserted, baseline recorded |
| equals the default | — | unchanged (baseline recorded if it had none: *adopted*) |
| unedited | changed | updated to the default, baseline re-recorded |
| edited | unchanged since seeding | left as is: the edit stands |
| edited | changed too | left as is, reported as a **conflict** naming the row and both versions, field by field |
| no baseline | differs | left as is, reported as a conflict (which side changed is unknowable) |

**Rules.**
- A UI soft delete is an edit, so a reseed never restores the row.
- A UI edit that returns a row to its default makes it unedited again.
- An amendment for an **authored** item goes into `catalog_items.yaml`. `AMENDMENTS` in
  code holds only migrated items' amendments, which are part of those items' defaults.
  For example, asmx-service's `exposes-asmx-service` rule moved into the file.

**Entry points.**
- `python -m app.seed` runs the full seed, including decisions.
- `python -m app.items.catalog_seed [--dry-run]` runs the catalog only and never reads or
  writes engagement data.

Both print every conflict. The seed never resolves a conflict: a person edits the row in
the UI, or changes the file to match.

**Existing rows.** The migration does no backfill: which rows were edited cannot be
proved from the data. The first seed adopts every row equal to its default and reports
the rest. On the local database, all 129 rows (items, resolutions, derivations) equalled
their defaults and were adopted, with 0 conflicts.

**Revert refuses rather than destroys.** Pattern-migration revert removes migrated items,
their resolutions, and derivations naming them. It removes them only when every such row
is unedited, because then it is exactly its default and the seed recreates it. Otherwise
revert refuses (`REVERT_BLOCKED`), naming each blocking row:
- "item_resolutions windows-service-remain-windows-hosted has been edited since it was
  seeded";
- "... has no seed baseline to prove it unedited".

**Reviewability.** Git holds the item catalog through its export (Part W),
`catalog/items/<item-id>.yaml`. It is read in review; it is never edited to change the
catalog.

---

## Part W — Item catalog export

The catalog's version history and code review, now that the database is authoritative
(Part V). Code: `app/items/catalog_export.py`. Tests: `tests/test_catalog_export.py`.

**Files.** There is one file per item, `catalog/items/<item-id>.yaml`, holding:
- the item;
- its resolutions;
- each resolution's derivations.

Per-item files give small git diffs and rare merge conflicts. Nested rows omit what
nesting already says (`item_id`, `resolution_id`).

**Deterministic.**
- Keys are sorted at every level.
- Resolutions are sorted by id, derivations by dependent item, items by id.
- Detection is exported exactly as stored.
- Multi-line text is a YAML literal block, with no line folding and no aliases.
- Files are written with LF line endings. `.gitattributes` pins `catalog/items/*.yaml` to
  `eol=lf`, so a Windows checkout stays byte-identical to a re-export.

An unchanged catalog re-exports byte-identically; the command then reports "0 written".

**Content only.** Each row's content is exactly its baseline content
(`baseline.CONTENT_FIELDS`). Left out:
- `seeded_hash`;
- computed columns (readiness `state`, `version`);
- timestamps;
- engagement data: decisions and scope are client data, not catalog content.

Soft-deleted rows are included with `deleted: true`, because a deletion is a reviewable
change.

**Entry points.**
- `python -m app.items.catalog_export export [--out DIR]` writes into `catalog/items/`. The
  command owns the directory: a file for an item that no longer exists is removed.
- `GET /api/catalog/export/items` returns the same files as `catalog-items.zip`, with fixed
  timestamps, so the same catalog gives the same bytes.
- The master catalog view has an "Export catalog (YAML per item)" link. It is read-only and
  hidden in a client catalog view.

**Staleness.** `catalog/` reflects the catalog only as of the last export, and the team
edits in the UI. To stop git silently drifting while it looks like the record:
- **Recording.** Each export into the repository's `catalog/items/` records a
  `catalog_exports` row (migration `b4e8c1a73d50`): the time, a hash of the whole catalog,
  and a hash and deleted flag per item. An export to any other directory is not recorded.
- **Status.** `GET /api/catalog/export/items/status` compares the database's items with
  the content of the export files in `catalog/items/`: each file parsed, against what the
  item's file would hold. Timestamps and the export record play no part, so an item that
  matches its file never counts as changed, however it came to match: an export, an update
  that shipped the files, or a seed that corrected the database to the shipped wording. It
  lists each changed item as one of:
  - `added`: no file for it;
  - `deleted`: soft-deleted while its file is not, or a file whose item is not in the
    database at all;
  - `edited`: its file would differ, including a change to one of its resolutions or
    derivations, or a restore.

  The record still gives the time of the last export.
- **Installations.** A platform folder with a `PLATFORM_SOURCE.json` is an installation in
  a client's repository, not our development repository. Its files change only through
  updates, and a commit there would make the next update refuse. So on an installation:
  - the status says `installation: true`, and the items that differ are local edits;
  - nothing is ever exported into the platform folder: the export command refuses, and
    the view never offers to export and commit;
  - the local edits are exported outside it, to send upstream: "Download the edited items"
    (`GET /api/catalog/export/items?changed_only=true`), or
    `python -m app.items.catalog_export export --changed`, which writes to
    `RUNS_DIR\catalog-edits` unless `--out` names another folder outside the platform.
- **Master catalog view.** Beside the export link it shows "Export is current", or "N items
  differ from the exported files" with the items, their change type, and the command to
  run and commit. On an installation: "Matches the platform's catalog files", or "N items
  edited on this installation" with the items, the download and the command to export them
  outside the platform folder.
- **Dashboard.** The dashboard summary carries the same count (`catalog_export`) on a
  "Catalog export" card. It is master-catalog data, the same for every engagement.
- **Cost.** Computing status renders every item from three bulk queries, about 0.2 s on
  the local catalog. It is cached (`cached_status`) against `catalog_change_counter`, a
  one-row counter (migration `d3b8e5f07a29`).
  - **What bumps it.** A statement-level trigger on `catalog_items`, `item_resolutions`,
    `resolution_derivations` and `catalog_exports` bumps the counter on every write, from
    any process: the API, the seed or the export command. It catches ORM writes, bulk
    updates and raw SQL alike. The export files' listing (name, size, modification time)
    is part of the cache key too, so files an update brings recompute it; it decides only
    when to recompute, never what counts as changed.
  - **Why a counter, not a sequence.** The bump is inside the writer's transaction, so the
    new version becomes visible together with the rows. Reading it before computing means
    a stale status is never cached under a current version. A sequence (`c7f2a9d41e86`,
    replaced) advanced before commit and could do exactly that.
  - **Effect.** A dashboard poll reads one number and returns the cached status, in about
    10 ms. The cache is per server process.
- **Nothing exports automatically.** Writing into the repository from a web request would
  couple the running server to the working tree, so a person runs the export and commits.
- **The zip download is not recorded.** It does not put files in the repository.

**One-way.** The export is not a second place to edit.
`python -m app.items.catalog_export import [--from DIR] [--dry-run]` exists to bootstrap a
new environment:
- **Onto an empty catalog** it inserts every row.
- **Onto a non-empty catalog** it goes through `baseline.seed_row` like any seed:
  - missing rows are inserted;
  - rows not edited since they were seeded are updated;
  - an edited row is never overwritten, and a conflict is reported.

Detection is validated against the signal registry exactly as the API does, so seed the
registry first.

**Standing up a new environment.** The canonical bootstrap takes platform configuration
from the seed's files and catalog content from this export. The procedure is
`01-ENVIRONMENT-SETUP.md` section 9. `python -m app.seed` chooses the catalog source
(`app/seed/catalog_source.py`):

| Catalog in the database | Export in the repository | Source |
|---|---|---|
| empty | present | the export, imported |
| not empty | present | the database's own, untouched: it is authoritative, and a stale export would roll back newer rows. Merge explicitly with `catalog_export import` |
| either | absent | the factory defaults (`catalog_items.yaml`, the pattern migration, amendments) |

The engagement data tied to the catalog comes along in every case and writes no catalog
rows: legacy decision records and overlays migrated onto items, and decisions repointed
off replaced items.

A changed factory default therefore no longer reaches an existing machine on reseed once
an export exists. Apply it with `python -m app.items.catalog_seed`, which is protected by
the baseline. Then export and commit.

A soft-deleted row is exported with its `deleted_by`, and import restores it: why a row
was deleted is part of the reviewable record.

`python -m app.seed.reproduce --prove-export-bootstrap` proves the path:
1. it bootstraps environment A and edits an item in A through the UI's handler;
2. it exports A and bootstraps B from that export alone;
3. it requires B to carry the edit, not the factory description, and to export
   byte-identically to A.

**Round trip.** `python -m app.items.catalog_export roundtrip`:
1. exports the configured database;
2. creates a fresh database, migrates it to head and seeds only the signal registry;
3. imports the export into it, then exports again;
4. compares the two exports byte for byte;
5. drops the database.

On the local catalog: 35 files, 85,311 bytes, 130 rows inserted (bootstrap), byte-identical.

---

## Acceptance criteria

### Catalog

- [ ] Signals carry `state`, `state_reason`, `signal_introduced_in_version`
- [ ] Extractors declare emittable signals; a registered signal no extractor claims is
      a hard error
- [ ] Item readiness computes from signal readiness and recomputes on signal change
- [ ] A `not_ready` item is excluded from detection and visible as pending
- [ ] An item promotes automatically when its last blocking signal becomes ready, with
      no edit to the item
- [ ] An occurrence-scope item without `occurrence_source` is rejected on write
- [ ] An application-scope item with `occurrence_source` is rejected on write
- [ ] `occurrence_source` must name a signal that appears in `match`
- [ ] Project role is computed, not catalogued; the six role patterns are gone
- [ ] Occurrence projection produces one row per distinct `source_path`, carrying
      line evidence
- [ ] Application-scope items produce one occurrence with null `file_path`
- [ ] A fingerprint predating a referenced signal's introduction yields `not_checked`,
      never `checked_absent`, and flags a rescan
- [ ] Occurrences survive their signal's extractor being removed
- [ ] Item coverage groups blocking signals by expected extractor
- [ ] Signal coverage lists ready signals no item references
- [ ] Signal suggestion is advisory and never writes a rule
- [ ] Existing decision records migrate with their forcing perspectives intact

### Conversion

- [ ] An approach writing outside its `allowed_paths` fails the execution
- [ ] Each conversion execution produces one git commit, message from the approach
- [ ] `dry_run` produces the diff without applying it
- [ ] A failed pre-check yields `NOT_APPLICABLE`, not failure
- [ ] A failed post-check triggers rollback of that execution
- [ ] `batching` is honoured: `all`, `per_file` and `per_occurrence` each behave as declared
- [ ] Application-scope conversions run before occurrence-scope for the same project
- [ ] `depends_on` and `order_hint` sequence approaches within a scope
- [ ] An item with no active approach leaves its occurrences `awaiting_approach`
- [ ] An occurrence with no engagement decision is flagged `awaiting_decision`, never guessed
- [ ] Approach version is recorded on every execution
- [ ] Occurrence-scope context carries populated `occurrences[]`; application-scope carries none
