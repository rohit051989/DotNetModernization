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
      PatternList.tsx          master catalog list
      PatternDetail.tsx        master catalog detail
      PatternForm.tsx
      TargetStateForm.tsx
      ClientPatternList.tsx    client catalog list (one engagement's view)
      ClientPatternDetail.tsx  client catalog detail: read-only definition,
                               defer/delete, decision panel
      DecisionPanel.tsx
      DecisionForm.tsx
  App.tsx
  main.tsx
```

## App shell

Header: product name **Modernization Platform**, a small environment pill showing
API health (green `connected` / red `unreachable`, polled every 30s), and a
**view switcher** on the right, populated from `GET /api/engagements`: **Master
Catalog** as a fixed first entry, then one entry per engagement. This replaces
what was a plain engagement dropdown — it now selects between two fundamentally
different editing surfaces, not just a filter, so it must read as a mode switch,
not a filter control.

The current scope must be unmistakable at all times — a distinct label, colour
accent, or both, changing with the switcher, so nobody edits the master catalog
believing they're in a client's engagement, or vice versa. This is a safety
property, not decoration: master edits are global; client edits are scoped to
one engagement. Get this wrong and the two-view separation this document exists
to describe stops meaning anything.

`// TODO: gate the Master Catalog entry behind an admin check once auth exists`
— non-admins should not see it at all. See "Future: access control" below.

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

## Catalog tab — list/detail layout

Two-column layout. Left column fixed ~380px, right column fills. Both the master
and client views share this shape; what differs is the content and which actions
are editable. Which view is showing is entirely driven by the header's view
switcher — the Catalog tab itself doesn't have its own mode toggle.

## Master catalog view

Selected via "Master Catalog" in the view switcher. This is the reusable IP:
pattern definition, detection rules, target state options and the
recommendation. Fully editable. No decision content appears here at all — a
decision belongs to an engagement, and the master view has no engagement
context.

### Left — pattern list

- Search box filtering on name, summary and legacy stack (calls `?q=`)
- Filter chips: category (`web-api`, `web-ui`, `service`, `batch`, `library`,
  `data-etl`) and status (default: hide `deprecated`)
- **+ New Pattern** button at the top
- Each row shows: name, legacy stack (small, muted), a count badge of target state
  options, and a status dot if not `active`
- Selected row visibly highlighted
- Empty state when filters match nothing, with a clear-filters action

Soft-deleted patterns are never fetched (the API excludes them by default) and so
never appear here under any filter combination, including the status filter — the
status filter only ever toggles between lifecycle states of records that still
exist. Deletion is not a fourth status; do not add a "deleted" option to the status
filter chips.

### Right — pattern detail

Header block: pattern name, `id` in monospace, category and status badges,
**Edit**, **Deprecate** and **Delete** buttons.

`// TODO: gate Edit/Deprecate/Delete behind an admin check once auth exists` —
see "Future: access control" below.

Then three stacked sections, all editable:

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
- **RECOMMENDED badge** when `is_recommended` is true — the master catalog's own
  recommendation, distinct from and independent of any engagement's decision.
  Give it a visually distinct treatment from the impact/effort badges (it's an
  editorial marker, not a status), and keep it separate from the "Presumptive
  choice" label below — a pattern can have a presumptive choice (lowest impact)
  that differs from its recommended option, and both facts should be visible at
  once when that happens
- **impact badge** — `none` green, `low` teal, `medium` amber, `high` red
- **effort badge** — neutral grey, `low`/`medium`/`high`
- `LIFT & SHIFT` pill when `is_lift_and_shift` is true
- `linux_compatible` and `container_ready` as small check/cross indicators
- engine coverage: a labelled badge from `engine_support.coverage`
  (`strong` / `partial` / `none`), with gaps listed beneath when present
- expandable playbook markdown
- Edit button, which includes an `is_recommended` toggle (see `TargetStateForm`)

The first card carries a subtle **"Presumptive choice"** label. This is a
deliberate demo point: the lowest-impact option is the default under the
lift-and-shift posture, and the UI should make that visible rather than leaving it
to policy documents.

**+ Add target state option** button below the cards.

Deprecating or deleting a pattern here can be refused by the server with a 409 if
any engagement holds a non-superseded decision record for it (see
`03-BACKEND-SPEC.md`'s master delete guard). Surface that message clearly — it's
telling the user which engagement(s) are relying on this pattern, which is exactly
the information they need to act on. Don't just show a generic "action failed"
toast for this case.

## Client catalog view

Selected via an engagement's name in the view switcher. Read-only for pattern
definition, detection rules and target state options; editable for this
engagement's posture toward the pattern (active/deferred, present/deleted) and
its decision.

### Left — pattern list

Same search and category filters as the master view. No **+ New Pattern**
button — patterns are created only in the master catalog. Status filtering is
replaced by a **deferred** filter: a "Show deferred" toggle (default on — see
`03-BACKEND-SPEC.md`'s `include_deferred`, which defaults to `true`), since
hiding a whole category of work by default risks losing track of it. Deferred
rows render visually muted with a **DEFERRED** badge, distinguishing them from
active ones without hiding them.

Client-deleted patterns behave exactly like soft-deleted patterns in the master
view: never fetched, never shown, not a filter option.

### Right — pattern detail

Header block: pattern name, `id` in monospace, category badge, a **DEFERRED**
badge when this engagement has deferred it. Actions: **Defer** / **Reactivate**
(whichever applies) and **Delete**. No Edit button anywhere in the client view —
there is nothing here to edit except this engagement's own overlay and decision.

`// TODO: gate Delete behind an admin check once auth exists` — see "Future:
access control" below. Defer/Reactivate are not gated even in the future design;
they're a normal engagement-team action, not an administrative one.

Then the same three stacked sections as the master view — **Definition**,
**Detection rules**, **Target state options** — rendered identically but
entirely read-only: no Edit buttons, no raw-JSON edit affordance (the "view raw
JSON" toggle is still fine; it's read-only either way), no `+ Add target state
option` button. Put a visible, unmissable note at the top of this block: **"Managed
in the master catalog."** The RECOMMENDED badge and Presumptive choice label
both still show here — they're informational in both views.

### Decision panel

Below the target state options, a bordered panel titled
**Decision — {engagement name}**. This panel exists **only** in the client
view — the master view has no engagement context to hang a decision off, so it
must not appear there at all.

If a decision record exists for this pattern and engagement:
- status badge (`parked` grey, `in_review` amber, `approved` green,
  `superseded` muted), alongside a `forcing_perspective` badge if one is set
  (`25-STANDARDS-AND-VIEWPOINTS.md` Part A1)
- selected target state, rationale, forcing rationale if present, approver, date
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

PatternForm and TargetStateForm only ever appear in the master catalog view —
there is nothing to create or edit in the client view.

### TargetStateForm

Fields: `id` (slug, create only), `name`, `summary`, `target_stack`,
`consumer_impact` (select), `effort` (select), `linux_compatible` (toggle),
`container_ready` (toggle), `is_lift_and_shift` (toggle), `is_recommended`
(toggle), `prerequisites`, `known_limitations`, `playbook_md` (large textarea,
monospace).

Enabling `is_recommended` on one option and saving should be reflected as the
only recommended option for that pattern afterward — the server clears it on
every sibling option in the same request (`03-BACKEND-SPEC.md`). Refetch the
pattern's target state options after save so the UI reflects this rather than
trying to predict it client-side.

`engine_support`: engine name (text), coverage (select), scenarios (tag input),
skills (tag input), gaps (tag input), custom skills required (tag input).

### DecisionForm

Fields: pattern (read-only, from context), engagement (read-only, from selector),
`candidates_considered` (multi-select of that pattern's target state options,
defaulting to all active ones), `selected_target_state_id` (select, constrained to
the candidates chosen), `evaluation_notes`, `rationale`, a `forcing_perspective`
select (the seven values in `25-STANDARDS-AND-VIEWPOINTS.md` Part A1) positioned
above `forcing_rationale`, `approver_name`, `approver_role`, `decision_date`
(date), `status` (select).

**Client-side mirror of the server rule:** when the selected option is not the
lowest `consumer_impact` among the candidates, show an inline warning above the
`forcing_perspective` select and mark both it and `forcing_rationale` required:

> CoreWCF on .NET 10 has lower consumer impact (none) than your selection
> (high). Record the perspective and rationale that justify the higher-impact
> option.

Do not block submission client-side only — the server enforces it too. The client
warning exists to make the governance rule visible during the demo.

DecisionForm only ever appears in the client catalog view, opened from the
Decision panel.

## Behaviour and states

- **Loading** — skeleton rows in the list, spinner in the detail pane. No layout jump.
- **Errors** — toast with the server's message. Surface 422 field errors inline on
  the offending field, not only in the toast.
- **Optimistic updates** — not required. Refetch after mutation is fine at this scale.
- **Unsaved changes** — confirm before closing a dirty drawer.
- **Deprecate** — always via `ConfirmDialog`, wording: "Deprecate this pattern? It
  stays in the catalog and existing decision records remain valid, but it will be
  hidden from the default list."
- **Delete** — always via `ConfirmDialog`, wording: "Delete this pattern? It will
  be removed from the catalog and can only be restored by an administrator."
  Distinct from Deprecate: this calls the soft-delete endpoint (`DELETE`), not
  `POST .../deprecate`, and the record disappears from the UI entirely rather than
  moving behind the status filter.

  Delete is intended to become a role-gated action once authentication and roles
  exist — non-admins should not see or be able to trigger it. No such check exists
  yet anywhere in this build (see `CLAUDE.md`'s out-of-scope list), so the button
  is currently reachable by anyone. Leave a clear `// TODO: gate behind admin role
  once auth exists` marker directly on the Delete button/handler in the component,
  so the gap is visible in the code and not just in this document. This applies to
  the master view's Delete; the client view's Delete is scoped to one engagement
  and is not planned to be admin-gated (see "Future: access control").
- **Client-scoped Delete** — always via `ConfirmDialog`, wording: "Delete this
  pattern from {engagement name}'s catalog? It will be removed from this
  engagement's view and can only be restored by an administrator. The master
  catalog and other engagements are unaffected." The trailing sentence matters:
  it's the one place in the UI that explicitly reassures the user this action's
  blast radius is one engagement, which is the entire point of the master/client
  split.
- **Defer / Reactivate** — no `ConfirmDialog`. Both are low-stakes and instantly
  reversible (deferring never touches the decision record, and reactivating just
  flips it back), unlike Deprecate or either Delete, so a confirmation step would
  only add friction without protecting against anything real.

## Long lists (release 6)

Every list the UI shows from data — projects, entry points, invocations, SOAP calls and their environment rows,
backend calls, lifecycle hooks, work items, packages, conversions, executions, estate rows, catalog items, policies,
and so on — goes through one component, `frontend/src/components/LimitedList.tsx`:

- it shows the first 20 items. Below them, when 20 or fewer remain, "+N more" reveals them all; when more remain,
  "Show 20 more · N remaining" with "Show all" beside it. Once more are shown, "Show less" returns to 20;
- a list of more than 20 items gets a filter box matching on the names the list shows (a project's path, a
  package's id, an item's name), so one among hundreds is found without paging. A list that already has a search of
  its own keeps it, and gets no second box;
- a grouped summary line ("164 projects with no request entry points") counts as one item of its list; a list
  nested inside an item is limited on its own;
- rows of a table body that cannot be wrapped (rows sharing cells through `rowSpan`) use the same limit through
  `useLimitedList`, its controls in a row of their own.

Not limited: fixed lists that are not data — table headers, `<option>`s, tabs, form fields, chips summarising
counts, the fixed fields of one record, and a diagram laid out from every item.

Inside a long list of panels (a project's entry points, an application's backend calls), a panel starts open only
when the list has three or fewer; its header line gives its counts.

Sections fold through one component, `frontend/src/components/CollapsibleSection.tsx`, and a SectionGroup gives a
group of them jump links and Expand all / Collapse all (`29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` Part D).

Both are covered by component tests (Vitest with Testing Library, jsdom), beside the components as `*.test.tsx`:

```powershell
cd C:\MP\code\frontend; npm test
```

## Future: access control

Not implemented. Recorded here so the intent is visible before auth exists, and
so the TODO markers scattered through this document and the code have something
to point at.

- **Admin users** see the Master Catalog entry in the view switcher and every
  engagement; they can perform every master-scoped mutation (create, edit,
  deprecate, delete, restore patterns and target state options).
- **Non-admin users** never see the Master Catalog entry at all — not disabled,
  not greyed out, simply absent from the switcher. They see only their own
  engagement's client catalog view (however "their own" ends up being determined
  — out of scope to decide here). They can defer/reactivate, delete/restore, and
  record decisions within that engagement; they have no path to any master-scoped
  action.
- Every `// TODO: gate ... once auth exists` marker left in this document and in
  the component code (the view switcher's Master Catalog entry, and each
  master-scoped mutation: pattern/target-state Edit, Deprecate, Delete) is where
  that check belongs. Do not implement the check now — there is no auth system to
  check against (see `CLAUDE.md`'s out-of-scope list) — but do not remove or
  "simplify away" these markers either; they are the map for when auth lands.

## Visual direction

Restrained and professional — this will be shown to a client. Neutral background,
one accent colour, generous whitespace, clear typographic hierarchy. Semantic
colour is reserved for impact/effort/status badges so those read instantly.

Avoid: gradients, drop shadows on everything, emoji in UI copy, cartoon
illustrations, animated transitions longer than 150ms.

Target a 1440px desktop viewport. Responsive below that is nice but not required.

## Acceptance checks

- [ ] View switcher lists Master Catalog plus every engagement, and the current
      scope is visually unmistakable
- [ ] Master pattern list loads, searches and filters against the live API
- [ ] Selecting a pattern in the master view shows its detail and target state
      options, impact-sorted, all editable
- [ ] Create and edit work for both patterns and target state options in the
      master view; `is_recommended` shows a RECOMMENDED badge and setting it on
      one option clears it on the others for that pattern
- [ ] Detection rules render readably and round-trip through the structured editor
      without data loss
- [ ] Switching to an engagement shows the client catalog view: definition,
      detection rules and target state options read-only with the "Managed in
      the master catalog" note, no Edit buttons anywhere in those sections
- [ ] Deferring a pattern in the client view shows it muted with a DEFERRED badge
      and it remains reachable via the deferred filter; Reactivate clears it
- [ ] Client-scoped Delete removes the pattern from that engagement's list only —
      the master catalog and other engagements are unaffected
- [ ] Decision panel appears only in the client view, reflects the selected
      engagement, and shows parked patterns
- [ ] The forcing-factor warning appears when a higher-impact option is selected
- [ ] Deprecating or deleting a master pattern that a decision record still
      references surfaces the server's 409 clearly, naming what blocks it
- [ ] Deprecating a pattern removes it from the master default list but keeps it
      reachable via the status filter
- [ ] Disabled tabs are visibly inert and non-clickable
