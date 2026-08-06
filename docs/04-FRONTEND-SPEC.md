# 04 — Frontend Spec

React 18 + Vite + TypeScript + Tailwind. No component library, no state manager.
Local `useState`/`useReducer` and a thin fetch wrapper are sufficient.

## Layout

```
frontend/src/
  api/
    client.ts        fetch wrapper, base URL from VITE_API_BASE_URL, error normalisation
    catalog.ts       typed calls: patterns, target states, engagements, decisions
  types/
    catalog.ts       TypeScript interfaces mirroring the API response models
  components/
    AppShell.tsx     header, tab bar, content slot
    TabBar.tsx       active + disabled placeholder tabs
    DataTable.tsx    simple sortable table
    Drawer.tsx       right-side slide-over used for all create/edit forms
    Badge.tsx        impact / effort / status pills
    EmptyState.tsx
    ConfirmDialog.tsx
    Toast.tsx
  pages/
    CatalogPage.tsx          the only implemented tab
    catalog/
      PatternList.tsx
      PatternDetail.tsx
      PatternForm.tsx
      TargetStateForm.tsx
      DecisionPanel.tsx
  App.tsx
  main.tsx
```

## App shell

Header: product name **Modernization Platform**, a small environment pill showing
API health (green `connected` / red `unreachable`, polled every 30s), and an
engagement selector dropdown on the right populated from `GET /api/engagements`.

Tab bar:

| Tab | State |
|---|---|
| Catalog | **active — the only one implemented** |
| Repositories | disabled, tooltip "Coming in platform build" |
| Applications | disabled, same tooltip |
| Dependencies | disabled, same tooltip |
| Waves | disabled, same tooltip |
| Dashboard | disabled, same tooltip |

Disabled tabs must look deliberately inactive — muted text, `cursor-not-allowed`,
no hover state. They exist to show the growth path in a demo, not to tease broken
features.

## Catalog tab — master/detail

Two-column layout. Left column fixed ~380px, right column fills.

### Left — pattern list

- Search box filtering on name, summary and legacy stack (calls `?q=`)
- Filter chips: category (`web-api`, `web-ui`, `service`, `batch`, `library`,
  `data-etl`) and status (default: hide `deprecated`)
- **+ New Pattern** button at the top
- Each row shows: name, legacy stack (small, muted), a count badge of target state
  options, and a status dot if not `active`
- Selected row visibly highlighted
- Empty state when filters match nothing, with a clear-filters action

### Right — pattern detail

Header block: pattern name, `id` in monospace, category and status badges,
**Edit** and **Deprecate** buttons.

Then three stacked sections:

**1. Definition**
`summary`, `description` (render markdown), `legacy_stack`, `typical_indicators`,
`known_risks`, `version`.

**2. Detection rules**
Render `detection_rules` JSON in a readable form — not a raw JSON dump. Group by
key with labelled lists: target frameworks, required namespaces, forbidden
namespaces, required packages, file globs, config markers. Show `notes` as prose
underneath. Include a "view raw JSON" toggle for the technical audience.

**3. Target state options**
A card per option, ordered lowest consumer impact first (the API already sorts
this way — do not re-sort).

Each card shows:
- name and `target_stack`
- **impact badge** — `none` green, `low` teal, `medium` amber, `high` red
- **effort badge** — neutral grey, `low`/`medium`/`high`
- `LIFT & SHIFT` pill when `is_lift_and_shift` is true
- `linux_compatible` and `container_ready` as small check/cross indicators
- engine coverage: a labelled badge from `engine_support.coverage`
  (`strong` / `partial` / `none`), with gaps listed beneath when present
- expandable playbook markdown
- Edit button

The first card carries a subtle **"Presumptive choice"** label. This is a
deliberate demo point: the lowest-impact option is the default under the
lift-and-shift posture, and the UI should make that visible rather than leaving it
to policy documents.

**+ Add target state option** button below the cards.

### Decision panel

Below the target state options, a bordered panel titled
**Decision — {engagement name}**, driven by the header's engagement selector.

If a decision record exists for this pattern and engagement:
- status badge (`parked` grey, `in_review` amber, `approved` green,
  `superseded` muted)
- selected target state, rationale, forcing factor if present, approver, date
- Edit and Supersede buttons

If none exists: an empty state with **Record a decision**.

## Forms — all in a right-side Drawer

Never navigate away for a create or edit. The drawer keeps the list context visible.

### PatternForm

Fields: `id` (slug, editable only on create, live-validated against
`^[a-z0-9]+(-[a-z0-9]+)*$` with an inline hint), `name`, `summary`,
`description` (textarea), `legacy_stack`, `category` (select), `typical_indicators`,
`known_risks`, `status` (select).

`detection_rules`: a **structured** editor, not a JSON textarea. One repeatable
tag-input row per array key (target frameworks, required namespaces, forbidden
namespaces, required packages, file globs, forbidden file globs, config markers),
plus a `notes` textarea and a `confidence_weight` number input. Offer a raw-JSON
escape hatch behind a toggle for power users, validated on blur.

### TargetStateForm

Fields: `id` (slug, create only), `name`, `summary`, `target_stack`,
`consumer_impact` (select), `effort` (select), `linux_compatible` (toggle),
`container_ready` (toggle), `is_lift_and_shift` (toggle), `prerequisites`,
`known_limitations`, `playbook_md` (large textarea, monospace).

`engine_support`: engine name (text), coverage (select), scenarios (tag input),
skills (tag input), gaps (tag input), custom skills required (tag input).

### DecisionForm

Fields: pattern (read-only, from context), engagement (read-only, from selector),
`candidates_considered` (multi-select of that pattern's target state options,
defaulting to all active ones), `selected_target_state_id` (select, constrained to
the candidates chosen), `evaluation_notes`, `rationale`, `forcing_factor`,
`approver_name`, `approver_role`, `decision_date` (date), `status` (select).

**Client-side mirror of the server rule:** when the selected option is not the
lowest `consumer_impact` among the candidates, show an inline warning above the
`forcing_factor` field and mark it required:

> CoreWCF on .NET 10 has lower consumer impact (none) than your selection
> (high). Record the forcing factor that justifies the higher-impact option.

Do not block submission client-side only — the server enforces it too. The client
warning exists to make the governance rule visible during the demo.

## Behaviour and states

- **Loading** — skeleton rows in the list, spinner in the detail pane. No layout jump.
- **Errors** — toast with the server's message. Surface 422 field errors inline on
  the offending field, not only in the toast.
- **Optimistic updates** — not required. Refetch after mutation is fine at this scale.
- **Unsaved changes** — confirm before closing a dirty drawer.
- **Deprecate** — always via `ConfirmDialog`, wording: "Deprecate this pattern? It
  stays in the catalog and existing decision records remain valid, but it will be
  hidden from the default list."

## Visual direction

Restrained and professional — this will be shown to a client. Neutral background,
one accent colour, generous whitespace, clear typographic hierarchy. Semantic
colour is reserved for impact/effort/status badges so those read instantly.

Avoid: gradients, drop shadows on everything, emoji in UI copy, cartoon
illustrations, animated transitions longer than 150ms.

Target a 1440px desktop viewport. Responsive below that is nice but not required.

## Acceptance checks

- [ ] Pattern list loads, searches and filters against the live API
- [ ] Selecting a pattern shows its detail and target state options, impact-sorted
- [ ] Create and edit work for both patterns and target state options
- [ ] Detection rules render readably and round-trip through the structured editor
      without data loss
- [ ] Decision panel reflects the selected engagement and shows parked patterns
- [ ] The forcing-factor warning appears when a higher-impact option is selected
- [ ] Deprecating a pattern removes it from the default list but keeps it reachable
      via the status filter
- [ ] Disabled tabs are visibly inert and non-clickable
