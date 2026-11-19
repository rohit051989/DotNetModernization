# 38 — Package access: why a package is unknown, and what to do

Status: **implemented** (dependency-assessment 1.8.0, artifact 1.7.0). The step's own version was already 1.7.1, so the
artifact takes 1.7.0 and the step 1.8.0; wherever this spec says "step 1.7.0" it means this change.
Extends `30-DEPENDENCY-ASSESSMENT.md` (Parts B2, B4, B7) and the Dependencies tab (`04-FRONTEND-SPEC.md`).
The UI says *artifactory* (a package source); the cause codes and field names keep their `feed_*` / `*Feeds` spelling.

## Why

dependency-assessment answers a package from the artifactories the repository's `NuGet.config` resolves (Part B2). A package
it cannot answer is `unknown`. Today the UI shows an "unknown" chip and a free-text reason. A developer cannot tell
whether they must log in to an artifactory, connect to a network, add a missing artifactory, or fix a version — and has no way to act
from the page.

The most common cause in a client estate is a package that lives on an internal artifactory the scanning machine cannot use:
the artifactory needs a login the developer has not made, or no `NuGet.config` the scan can see names it.

## Goal and non-goals

Goal: for one repository, say why each unknown package is unknown (its **cause**), and tell the developer what that cause needs, so the
owner can fix it and rescan.

Non-goals (decided):

- **The platform never receives, stores, logs or transmits an artifactory credential** (Part B4, rule 3). Authentication stays
  the developer's, on their own machine, through NuGet's own mechanisms. No credential field, no registry-with-secrets
  table, no encrypted vault.
- No artifactory registry table *for this step*: artifactories come from `NuGet.config` as resolved today (Part B2). An engagement can
  also list artifactories of its own in the Artifactory tab, which hold a name and a URL and never a credential
  (`39-ARTIFACTORY.md`); the login for them comes from the scanning machine's environment.
- Vendored DLLs referenced by `HintPath` are not assessed by the step today and are not a cause here.
- The platform does not run `dotnet nuget add source` for the user, and changes no NuGet, certificate or machine
  configuration (rule 14). It shows a command; the developer runs it.

## Decisions

1. **Cause detection is structured, in the step (Option A).** dependency-assessment records why each unknown package is
   unknown, as a code, not text to be parsed. Schema version bump, additive.
2. **No tab of its own**: the cause shows on the Dependencies tab, on the unknown package's row. Not an
   engagement-wide view.
3. **Rescan is the repository header's**, with its existing gating. Nothing new launches jobs.

## Part A — Causes

A package's `unknownCause` is one of:

| Code | Meaning | Where decided (`DependencyPipeline`) |
|---|---|---|
| `feed_auth` | An authority artifactory answered 401 or 403 | the artifactory loop (`errors.Count > 0` path) |
| `feed_unreachable` | An authority artifactory could not be reached: DNS, timeout, TLS, connection refused, any other protocol error | same |
| `not_on_feed` | Every authority artifactory answered, none holds the package | the `ordered.Count == 0` path |
| `version_unresolved` | The `PackageReference` version could not be read (a property or central-package-version that does not resolve) | the `declaration.Version is null` path |

When more than one authority artifactory failed for one package, the package's cause is the most actionable: `feed_auth`,
then `feed_unreachable`. `not_on_feed` and `version_unresolved` occur only when no artifactory failed / no lookup was made.

Unknown outcomes the step produces for other reasons (a lookup answered offline from a frozen snapshot, `lookup_offline`)
get no `unknownCause` and show as "Not answered (offline lookup)", with no action.

### Failed artifactories (`failedFeeds`)

For `feed_auth` and `feed_unreachable` the package also records `failedFeeds`: a list of
`{ name, url, failure, httpStatus }`, where `url` is the **normalised** artifactory URL (`FeedResolver.NormaliseUrl`:
scheme, host, port, path; no userinfo, query or fragment — Part B4), `failure` is `auth` or `unreachable`, and
`httpStatus` is the HTTP status when there was one. For `not_on_feed` it records the artifactories that were asked
(`consultedFeeds`, same shape without `failure`), so the row can say which artifactories were tried.

## Part B — Step change (dependency-assessment 1.8.0, artifact 1.7.0)

- `LookupResult` carries a failure kind and status alongside `Error`: `Failure` (`None`, `Auth`, `Unreachable`) and
  `HttpStatus`. `PackageLookup.GetAsync` sets `Auth` when the `FatalProtocolException` / `HttpRequestException` chain
  carries status 401 or 403, `Unreachable` for every other caught exception. The `Error` text and its URL
  normalisation (`Describe`) are unchanged.
- `PackageAssessment` gains optional `unknownCause`, `failedFeeds`, `consultedFeeds` (set only when outcome is
  `unknown`). Nothing existing changes; `outcome_reason` text stays as it is.
- Schema `dependency-assessment-1.7.0.schema.json` (generated as the earlier ones are, `make_dependency_schema.py`),
  step version bumped, `steps/step-003-fingerprinting/registration/dependency-assessment.json` updated in the same
  change (rule 11). Fields are optional, so a 1.6.0 consumer is unaffected.
- **No credential, token, userinfo or query string is ever written** into these fields (Part B4). A test asserts it
  with an artifactory URL carrying userinfo and a token query.
- Failed lookups are not cached (`cache.Put` runs only on success), so a rescan after the developer logs in re-asks the
  artifactory. A `not_on_feed` answer is cached for the lookup TTL (24 hours) like any answer; adding the missing artifactory to a
  `NuGet.config` changes the artifactory key, so it is asked fresh. A package published to an *already consulted* artifactory after
  a `not_on_feed` answer shows up after the TTL. The row says so for this cause, and says that a package from a private
  artifactory the engagement does not list yet needs that artifactory added in the Artifactory tab (a link to it), then a rescan
  (`39-ARTIFACTORY.md`). `feed_auth` shows the same link.

## Part C — Where it is shown

There is no separate tab. A first version of this change added a "Package access" tab; it duplicated what the
Dependencies tab already shows for an `unknown` package, so it was dropped and its useful parts moved into
**Dependencies** (`04-FRONTEND-SPEC.md`, "Dependencies (repository page)").

- Each `unknown` package row's Reason cell shows the cause title, what it needs, and the artifactories involved (failed artifactories
  with `login needed` or `unreachable` and the HTTP status, or the artifactories consulted for `not_on_feed`).
- A result from before 1.7.0 has no cause: the row says "Cause not recorded: rescan to classify". **The backend and UI
  never parse the reason text to guess a cause.**
- The cause is read from the package's own assessment (`worst.pkg`), so no endpoint of its own is needed.
- Rescan is the repository header's Rescan, with its existing gating.
- The `feed_auth` guidance names the alternatives that store no password: a credential provider, or the
  `NuGetPackageSourceCredentials_<name>` environment variable (`docs/VDI-SETUP.md`, "From a client repository's
  nuget.config"). The page never takes or shows a credential.

## Part D — Tests

- C# (offline, `Fingerprinting.Dependencies.Tests`): a local-folder artifactory for `not_on_feed`; an artifactory that throws a
  protocol error with 401, with 403, and with a network failure, asserting `feed_auth` / `feed_unreachable` and the
  priority when both occur; `version_unresolved`; no credential or userinfo in any new field.
- Frontend: `StoredResultViews.test.tsx` shows the cause and the failed artifactory on an unknown package.
- `python -m app.seed.reproduce` reports 0 differences (rule 11).

## Part E — Upgrade (rule 15)

- No database migration: results are stored as the artifact's content, and the view reads the new optional fields.
- The step version bump and registration file travel together; the admin updates first, then every developer pulls and
  restarts (one platform version).
- Existing results stay readable; their unknown packages show "Cause not recorded" until the repository is rescanned
  (`docs/VDI-SETUP.md`, "Upgrade notes").

## Acceptance

- [ ] A package unknown because an artifactory returned 401 or 403 shows cause `feed_auth` with the artifactory's normalised URL and
      the login guidance on the Dependencies tab; no credential appears anywhere in the artifact, the database or the
      page.
- [ ] A package on no consulted artifactory shows `not_on_feed` with the artifactories consulted.
- [ ] An unreachable artifactory shows `feed_unreachable`; auth wins when both occur for one package.
- [ ] A result from before 1.7.0 shows "Cause not recorded: rescan to classify", and nothing is guessed from text.
- [ ] All suites pass: backend, frontend, C#; `seed.reproduce` reports 0 differences.
