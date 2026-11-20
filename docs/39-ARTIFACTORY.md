# 39 — Artifactory (an engagement's Artifactory repositories)

The **Artifactory** tab, beside Workflow inside an engagement, lists the Artifactory repositories the engagement's scans ask, in
addition to the sources each repository's `NuGet.config` declares. It serves `dependency-assessment` and
`dependency-hierarchy`.

## What is shared and what is not

| What | Where | Shared |
|---|---|---|
| Artifactory name and URL | table `engagement_feeds` | yes, every developer on the database |
| Token, username and password | the scanning machine's environment | no, never in the database, an API response, a log, an artifact or the lookup cache |

This keeps the rule of `38-PACKAGE-ACCESS.md` and `30-DEPENDENCY-ASSESSMENT.md` Part B4: the platform never receives,
stores, logs or transmits an artifactory credential. The tab has no password field.

## Which login an artifactory gets

For each artifactory, in order (`Fingerprinting.Dependencies/EngagementFeeds.cs`, `FeedResolver.Resolve`):

1. **`NuGet.config`.** A source it declares with the same URL, and its `packageSourceCredentials`, are used as they are.
2. **`NuGetPackageSourceCredentials_<artifactory name>`** in the environment, NuGet's own format `Username=...;Password=...`.
3. **The machine login**: `ARTIFACTORY_TOKEN`, or `ARTIFACTORY_USERNAME` and `ARTIFACTORY_PASSWORD`: one login for every engagement
   artifactory that has neither of the above, so a new artifactory never asks again. Set them in the operating system's
   environment, or in `backend/.env` (gitignored), which the backend exports to the step programs.

With none of them the artifactory is asked anonymously; a 401 or 403 then shows as `feed_auth` (`38-PACKAGE-ACCESS.md`). An artifactory
that `NuGet.config` already declares with a login keeps that login.

### A token, or a username and password

One place decides how the machine login authenticates a call: `Fingerprinting.Dependencies/ArtifactoryLogin.cs`. Every call
the dependency steps make to an engagement artifactory goes through it, and so does preflight's connection check, which
runs the same code (`DependencyAssessment.Cli.exe --check-artifactory <url>...`). The backend only passes the three settings
on to the step programs (`app.config.apply_credentials`) and names the configured method (`app.config.artifactory_method`).

| Set | What is sent |
|---|---|
| `ARTIFACTORY_TOKEN` | `Authorization: Bearer <token>`, to the artifactory's own host only. With a username and password as well, the token wins. |
| The token is rejected (401 or 403), with a username and password | One warning in the step's log, naming the artifactory; then the username and password for the rest of that run. The token is not tried again in that run. |
| The token is rejected, without a username and password | The lookup fails with `feed_auth` and says so: "artifactory '<name>' rejected ARTIFACTORY_TOKEN (401): set a valid token, or ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD to fall back to". |
| Only `ARTIFACTORY_USERNAME` and `ARTIFACTORY_PASSWORD`, or nothing | Exactly as before the token existed: NuGet's own credential, or anonymous. |

An empty value counts as not set. A network error, a timeout or any other failure never switches to the username and
password: it is reported as it always was.

The token is a secret like the password: never logged, never in a URL, a result, the database, an error message or a
generated file. A log, preflight and the Artifactory tab may name the method, never a value: `token`, `username and
password`, `token rejected, used username and password`, `token rejected` or `none`. The token is not used by the scratch
`dotnet restore` of `include_transitive` either, which, as before, uses only what `NuGet.config` and NuGet's own
`NuGetPackageSourceCredentials_<name>` variables carry.

## Rules

- An artifactory URL is an absolute `http` or `https` URL without a login in it (422 `EMBEDDED_CREDENTIALS`).
- **It is a NuGet feed, not the Artifactory web page.** A URL whose path has `/ui/` in it (the JFrog page a person
  browses to, such as `https://host.client-a.example/ui/packages`) is refused (422 `NOT_A_NUGET_FEED`): a scan asking it
  gets HTML, or 401 or 403, never packages. The message gives the shape to use,
  `https://host/artifactory/api/nuget/v3/<repository-key>/index.json` (the repository's Set Me Up page shows it; the
  trailing `/` form NuGet.config files often use works too). Any other URL that neither ends in `index.json` nor has
  `/api/nuget/` in it is taken, with a warning, since a server may serve a feed elsewhere. Every listed artifactory
  carries the same warning (`warning`), so one saved before this check is named on the tab and left working; an admin
  corrects it with Edit.
- **An admin may change a saved artifactory's URL or name** (`PUT`, below): the same checks as adding one, and a version
  check (`If-Match`, `app.auth.versions`; a stale copy is refused, 409 `STALE_COPY`, naming who changed it first). The
  change is recorded in the activity log. It applies to the next scan: rescan to use it.
- **Test connection** asks the URL's service index from the person's own backend, with that machine's login, through
  the dependency step's own code (`DependencyAssessment.Cli.exe --check-artifactory`, as preflight does), so it
  authenticates exactly as a scan does. It answers `answered`, `rejected ARTIFACTORY_TOKEN (401)`, `refused the login
  (403)`, `answered 404`, `no answer within 30 seconds` or `could not be reached: ...`, with the login used and the
  machine, never a value. It works on a saved artifactory or on a URL before it is added, changes nothing, and is open to
  everyone signed in.
- **Duplicates are refused** (409 `DUPLICATE_ARTIFACTORY_URL`) once the URL is normalised: scheme and host in lower case,
  no user information, query, fragment or trailing slash (the same form the scan stores,
  `FeedResolver.NormaliseUrl`). A name is unique in the engagement too (409 `DUPLICATE_ARTIFACTORY_NAME`).
- Removing an artifactory is a soft delete (`deleted_at`, `deleted_by`); its URL can then be added again.
- Anyone signed in may add or remove an artifactory (`app.auth.policy`).
- The engine passes the list to the two steps in `step_context.artifactories` (names and URLs). A new or removed artifactory
  applies to the next scan of a repository; **rescan** to use it.
- A scan records an artifactory that no `NuGet.config` declares in each project's `feeds` with `declaredIn: "engagement"`
  (dependency-assessment artifact 1.8.0; `30-DEPENDENCY-ASSESSMENT.md`). The Dependencies view's "Artifactories:" line
  lists it, and its tooltip says it comes from the engagement's Artifactory tab. Before 1.8.0 such a scan failed at
  dependency-assessment, because artifact 1.7.0 did not allow that value.

## API

`GET|POST /api/engagements/{id}/artifactories`, `DELETE /api/engagements/{id}/artifactories/{artifactory_id}`,
`PUT /api/engagements/{id}/artifactories/{artifactory_id}` (admins; `{"url", "name"?}` with `If-Match: <version>`),
`POST /api/engagements/{id}/artifactory/test-connection` (`{"url"}` -> `{"ok", "url", "answer", "login", "machine",
"warning"}`, anyone signed in),
`GET /api/engagements/{id}/artifactory/credentials-status` (`{"machine_login": true|false, "method": "token"|"username and password"|"none"}`,
never a value).
