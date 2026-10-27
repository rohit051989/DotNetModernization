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

Everyone signed in sees the Master Catalog entry; only admins change the master catalog. See "Sign-in and roles"
below.

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

Edit, Deprecate and Delete are admins' (hidden from developers): see "Sign-in and roles" below.

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

Defer, Reactivate and Delete are admins' (developers see them read-only): a developer registers repositories and acts
on the ones they own, and the client catalog is engagement-wide. See "Sign-in and roles" below.

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

  Delete is an admin's: hidden from developers, and refused by the backend for anyone else
  (see "Sign-in and roles").
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
- a grouped summary line ("N projects with no request entry points") counts as one item of its list; a list
  nested inside an item is limited on its own;
- rows of a table body that cannot be wrapped (rows sharing cells through `rowSpan`) use the same limit through
  `useLimitedList`, its controls in a row of their own.

Not limited: fixed lists that are not data — table headers, `<option>`s, tabs, form fields, chips summarising
counts, the fixed fields of one record, and a diagram laid out from every item.

**A list that grows with a repository is paged by the server** (`frontend/src/components/PagedList.tsx`, backend
`app.results.paging`): the repository page's entry points, invocations, backend calls, SOAP calls, packages and their
projects, the work list and each row's occurrences, solutions, projects, artifacts and warnings, impact files, work
items and conflicts, tests, test classes, coverage per project and per file, and the estate's register, unresolved
endpoints, integration applications and their calls, packages, dependency lists and SOAP backends. It looks and works
as above — 20, "+N more", "Show 20 more · N remaining", "Show all", "Show less", the filter box past 20 — but each
control asks the server for what it shows, and the filter box's text is matched by the database (a moment after
typing stops). A row's nested list that came with the row (a work-list row's first 20 occurrences) asks for nothing
until more is wanted. What a view computed over a whole list before — its groups, counts and order, the work list's
totals, the tests' note numbers, the register's conversation counts — the server computes and sends with the view's
summary. A grouped line ("N projects with no request entry points") follows its list, opening its own paged list. An
execution's artifact viewer, which has the whole artifact in hand, pages the same panels in memory (`localPages`).

Inside a long list of panels (a project's entry points, an application's backend calls), a panel starts open only
when the list has three or fewer; its header line gives its counts.

Sections fold through one component, `frontend/src/components/CollapsibleSection.tsx`, and a SectionGroup gives a
group of them jump links and Expand all / Collapse all (`29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` Part D).

Both are covered by component tests (Vitest with Testing Library, jsdom), beside the components as `*.test.tsx`:

```powershell
cd C:\MP\code\frontend; npm test
```

## File links

Every link to a file in a repository (a handler, a call site, a package reference, a test) goes through one
component, `frontend/src/pages/repositories/SourceLink.tsx`. Clicking it does what the person chose; ▾ beside it
opens a menu with every other way.

Each person chooses an editor for file links: **VS Code**, one of the **Visual Studio** installations, or **Copy
only**. The choice is remembered in the browser (`localStorage`, key `file-links:editor`: `vscode`,
`visual_studio:<installation>` or `copy`), changed from the menu beside any file link, and every link on the page
follows it. Only editors found on the machine the platform runs on are offered (`GET /api/editors`), VS Code first,
then each Visual Studio installation by its full name, newest first ("Visual Studio Enterprise 2026", "Visual
Studio Enterprise 2022"). Copying is always offered. Until a person chooses, links use the first editor found, else
copy. A remembered Visual Studio that is no longer installed, or the plain `visual_studio` remembered before
installations were told apart, becomes the newest Visual Studio; any other remembered editor that is gone falls back
to the first.

**Which Visual Studio** (`app/editors.py`). VS Code is offered when `code` is on PATH. Visual Studio: every
installation `vswhere -all -prerelease -products *` lists that is an edition — product id
`Microsoft.VisualStudio.Product.Community`, `.Professional` or `.Enterprise` — that vswhere also lists with
`-requires Microsoft.VisualStudio.Component.CoreEditor`, whose program (`productPath`) is `devenv.exe`, from version
17 (2022) on with no upper bound, complete and launchable. Everything else is refused, whatever its shell: SQL Server
Management Studio 22 is built on the Visual Studio 2026 shell, installed through the Visual Studio Installer, and
listed by vswhere, and on one machine used to be launched in place of Visual Studio 2026. Two settings, both
optional: `VISUAL_STUDIO_PATH` names one `devenv.exe` in place of detection (its name and version from vswhere when
it lists it, else the file's version), and `VISUAL_STUDIO=off` offers none. `python -m app.editors` prints what
detection finds — each installation with its name, version, program, and accepted or why not — and opens nothing
(`VDI-SETUP.md` "Checking which Visual Studio is used").

- **VS Code** opens through its `vscode://file/<path>:<line>` link, at the file and line. The browser opens it.
- **Visual Studio** cannot be opened by a browser, so the backend opens it (`POST /api/editors/visual-studio/open`,
  with the chosen `installation`; the newest when omitted): it runs on the same machine, in the person's session
  (CLAUDE.md "Operating model"). It hands the file to a running instance of that installation, through the
  installation's own versioned automation object (DTE), and moves the caret to the line. The instance is found in the
  running object table under its versioned name (`!VisualStudio.DTE.18.0:<process id>` for 2026, `.17.0` for 2022)
  and used only when its program is that installation's `devenv.exe`. A version-independent registration, which
  another product such as SSMS may own, is never read. With none running, it starts that `devenv.exe /Edit` and
  moves to the line once it is ready, up to 90 seconds. A
  toast gives the answer. When the line could not be set (an instance that never became ready, or one running as
  administrator, which a backend that is not cannot reach), the file is still open, and the toast says plainly that
  it is not at the line: "It could not be moved to line N: go there with Ctrl+G."
- **Copy path and line** puts `D:\repos\shop\src\Web\X.cs:42` on the clipboard, in the repository path's own
  style, whatever editor is chosen.

The backend opens only a file inside a registered repository (not soft-deleted), a conversion worktree or
`RUNS_DIR`, after following links and junctions; any other path, or a folder, is refused with 403
`PATH_NOT_ALLOWED`, and no editor is touched. Nothing on the machine changes: no registry keys, protocol handlers or
settings.

Tests: `frontend/src/pages/repositories/SourceLink.test.tsx` and `backend/tests/test_editors.py`.

## Repository page: tabs in groups (release 7)

The repository page shows one tab at a time, in the same browser tab (`frontend/src/pages/repositories/`:
`RepositoryDetailPage.tsx`, `repositoryTabs.ts`). Before release 7 every section was on one long page and the bar
only jumped down to it.

- **Two rows.** The first holds the groups; the second, the selected group's tabs. Overview is on its own, with no
  second row.

  | Group | Tabs (address) |
  |---|---|
  | Overview | Overview (`overview`) |
  | Discovery | Surface (`surface`), Projects & fingerprint (`projects`), Dependencies (`dependencies`), Dependency graph (`dependency-graph`), Impact (`impact`), Tests (`tests`) |
  | Modernization | Work list (`work-list`), Conversion (`conversion`) |
  | Activity | Executions (`executions`), Details (`details`) |

  Choosing a group opens the tab last shown in it, else its first.
- **Only the selected tab is shown.** Every other tab's content is hidden, and loaded only when its tab is first
  opened; after that it is kept, hidden, so coming back to it does not load it again.
- **Each tab has its own address**, `/repositories/<id>/<tab>`. A refresh stays on the tab, Back and Forward move
  between tabs, and a link can open a repository on a tab. `/repositories/<id>` opens the repository's last tab (else
  Overview) and the address becomes that tab's. Old links to a section (`#repo-worklist`, `#repo-hierarchy`, …, and a
  Surface section's own anchors) open the matching tab.
- **A slim header**: the name, the status chips and the actions (Verify path, Rescan, Edit, Delete) stay at the top
  of every tab, with the two rows. A tab's own sticky bar (Surface's section bar) sits just below it (`--repo-header`).
- **Overview is the summary**: the cards (size, files, main language, projects, request entry points, Linux
  incompatible, version drift, items found, last scanned), then the key figure from each tab, each a link into it —
  work items, request entry points, dependencies needing change (any outcome but current or unknown), SOAP calls
  needing change (the SOAP panel's rule), the conversion's state, the latest execution (`useRepositorySummary.ts`).
- **Tab labels carry counts** where they help: "Surface · 54" (request entry points), "Projects & fingerprint · 11",
  "Dependencies · 66" (needing change), "Work list · 28", "Conversion · ready", "Executions · 9".
- **Remembered**: each repository's last tab in this browser (`localStorage`, `repo-tab:<id>`), and each tab's scroll
  position for the session (`sessionStorage`), restored when the tab is shown again.
- **Kept inside the tabs**: the collapsible sections, the 20-item lists, the filters, and the Surface section bar.

Other pages: none has the long-page pattern. Estate already shows one view at a time (its views have no address of
their own); Catalog, Dashboard, Workflow and Workflow Administration are lists or single views.

Tests: `frontend/src/pages/repositories/RepositoryDetailPage.test.tsx` covers the groups, switching tabs, loading on
first open, the addresses, Back and Forward, the old section links, the remembered tab and scroll position, and
Overview's links.

## Results on another machine

A repository's results are read from the database (backend `app.results`), so every tab shows the same on every
machine, whoever scanned it. On another machine, the repository page says "Scanned on Ann's machine (DEVBOX-07): its
results are read from the database ..." under its header.

File locations are relative to the repository, and every file link on a repository's page and its executions' pages
opens from the **viewer's own clone** on this machine (`RepositoryFiles` in `SourceLink.tsx`, from the repository's
`my_clone_path`; the owner's is the folder it was registered from). A line under the header says which folder ("File
links open from your clone: ...", with **Change**). With none recorded it says so, and each file link, clicked, offers
**Record your clone…** or **Copy the relative path**. Recording shows the repository's `clone_command` to make one,
with **Copy**, and a field for the folder (the command's own target by default); the backend refuses a folder that is
not the top of a clone of the same repository, and the dialog shows its message. **Forget my clone here** removes the
record. An evidence file of a conversion, and an artifact no view reads (a SARIF export, a log), are only on the
owner's machine, and say so instead of linking. The Conversion tab shows the
conversions as their owner's machine last published them, with when. A repository scanned before results were shared
says so under its header, with the command its owner runs to copy them.

## Dependency graph (repository page)

The repository page's **Dependency graph** tab (until release 7, the "Structure" section) shows the repository's
dependency graph, as a node-link graph (React Flow, laid out top to bottom by dagre) or an indented tree. The section
that was "Structure & fingerprint" is now **Projects & fingerprint**. Its behaviour, API and libraries are specified in `37-DEPENDENCY-HIERARCHY.md` Part E. In
short:
- it opens on the roots; + and − expand and collapse, and nothing expands on a double click;
- children load when a node is expanded, 20 at a time ("+N more");
- a shared node is drawn once, and says "referenced by N";
- search reveals a node with its path from a root; transitive packages are off by default; filters show internal,
  external or projects only;
- clicking a node opens its details, with the editor link (see "File links").

Tests: `frontend/src/pages/repositories/structure/*.test.tsx`.

## Sign-in and roles

Several developers each run their own platform against one database (docs/VDI-SETUP.md, "Users and sign-in"). The
backend enforces every rule below for every call (`app.auth.policy`); the UI follows it, so nobody is offered an action
the backend would refuse.

- **Sign-in.** Until there is a session, the app shows the sign-in page (`SignInPage.tsx`): the machine and the
  Windows account the sign-in is checked against, the sign-in name and password, and the backend's own plain message
  when it is refused. A password set by an admin asks for a new one there. Before any admin exists, the page says how
  the first one is created. Any call answered 401 `SIGNED_OUT` (a session that ended or expired) returns to it. The
  header shows the person, their role, **Sign out**, and **N online** (who is signed in, on which machine).
- **Asking for access.** Once an admin exists, someone not registered sees **Request access** under the sign-in form
  (`GET /api/auth/machine` says `registration: none`): their full name and a chosen password, twice. A registered user
  on a machine their registration does not name (`other_machines`) sees **Ask to add this machine**: their password
  only. The Windows account and machine are never typed. The page then shows how the request stands
  (`GET /api/auth/access-request`): pending, with the sign-in name it will have; rejected, with the reason, and they
  may ask again; or approved, with the sign-in name filled in.
- **Deciding requests.** For admins, the header shows **N access requests** while any are pending
  (`pending_access_requests` from `/api/auth/me`, polled each minute and refreshed as soon as one is decided); it
  opens the **Users** tab, whose **Access requests** section lists the pending ones with **Approve** and **Reject**
  (an optional reason), and the decided ones beneath. Approving makes a developer. **Make admin** in the role column
  is the only way to make an admin (after a confirmation); **Register a user** has no role choice.
- **Managing users.** In the Users tab, each user's machines are listed one per line, with **×** to remove one (not
  their only one) and **change** to edit the list. **Disable** asks first, listing the repositories they own (which
  stay theirs), and ends their sessions at once; a disabled user shows "(disabled)" and **Enable**. **Delete** asks
  first; while they own a repository the backend refuses, and the toast names each one to reassign. Both are disabled,
  titled why, on your own row and on the last admin's.
- **The platform updated.** Once the admin has updated the database while this backend runs, a banner under the
  header ("The platform has been updated", from `/api/health`'s `platform_update`, or at once from any change refused
  409 `PLATFORM_UPDATED`) says to pull the update and restart; until then every change is refused.
- **Everyone signed in sees everything**: the master catalog and every engagement, repository and result.
- **Admins** change everything. The **Users** tab and **Workflow Administration** show to admins only.
- **Developers** register repositories and act on the ones they own. The master catalog's edit controls are hidden
  from them, with "Read-only: only an admin changes the master catalog." **+ New engagement**, **Delete
  engagement…** and **Run estate consolidation** are disabled for them, titled "Only an admin can do this."
- **A repository's owner** shows on its page ("Owner: Alice", or "No owner: admins only"); an admin assigns or changes
  it there. For anyone who may not act on it (not its owner, or not on the machine it was registered on), **Rescan**,
  **Verify path**, **Edit**, **Delete** and the conversion buttons are disabled, each titled with the backend's reason
  (`cannot_act_reason`), and a line under the header says "Read-only for you: ...".
- **A stale copy.** Edits of shared records send the version of the copy shown in `If-Match`: catalog items
  (`edit_version`) and their resolutions, item decisions, and an engagement's estate settings. A 409 `STALE_COPY`
  shows the backend's message: who changed it first, and that nothing was overwritten.
- **The frontend reaches the backend through its own dev server** (`vite.config.ts` proxies `/api` to the backend in
  `frontend\.env`), so the session cookie is the page's own.

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
