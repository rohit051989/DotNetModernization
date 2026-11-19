# 39 — Artifactory (an engagement's Artifactory repositories)

The **Artifactory** tab, beside Workflow inside an engagement, lists the Artifactory repositories the engagement's scans ask, in
addition to the sources each repository's `NuGet.config` declares. It serves `dependency-assessment` and
`dependency-hierarchy`.

## What is shared and what is not

| What | Where | Shared |
|---|---|---|
| Artifactory name and URL | table `engagement_feeds` | yes, every developer on the database |
| Username and password | the scanning machine's environment | no, never in the database, an API response, a log, an artifact or the lookup cache |

This keeps the rule of `38-PACKAGE-ACCESS.md` and `30-DEPENDENCY-ASSESSMENT.md` Part B4: the platform never receives,
stores, logs or transmits an artifactory credential. The tab has no password field.

## Which login an artifactory gets

For each artifactory, in order (`Fingerprinting.Dependencies/EngagementFeeds.cs`, `FeedResolver.Resolve`):

1. **`NuGet.config`.** A source it declares with the same URL, and its `packageSourceCredentials`, are used as they are.
2. **`NuGetPackageSourceCredentials_<artifactory name>`** in the environment, NuGet's own format `Username=...;Password=...`.
3. **`ARTIFACTORY_USERNAME` and `ARTIFACTORY_PASSWORD`**: one login for every engagement artifactory that has neither of the above, so a
   new artifactory never asks again. Set them in the operating system's environment, or in `backend/.env` (gitignored), which
   the backend exports to the step programs.

With none of them the artifactory is asked anonymously; a 401 or 403 then shows as `feed_auth` (`38-PACKAGE-ACCESS.md`). An artifactory
that `NuGet.config` already declares with a login keeps that login.

## Rules

- An artifactory URL is an absolute `http` or `https` URL without a login in it (422 `EMBEDDED_CREDENTIALS`).
- **Duplicates are refused** (409 `DUPLICATE_ARTIFACTORY_URL`) once the URL is normalised: scheme and host in lower case,
  no user information, query, fragment or trailing slash (the same form the scan stores,
  `FeedResolver.NormaliseUrl`). A name is unique in the engagement too (409 `DUPLICATE_ARTIFACTORY_NAME`).
- Removing an artifactory is a soft delete (`deleted_at`, `deleted_by`); its URL can then be added again.
- Anyone signed in may add or remove an artifactory (`app.auth.policy`).
- The engine passes the list to the two steps in `step_context.artifactories` (names and URLs). A new or removed artifactory
  applies to the next scan of a repository; **rescan** to use it.

## API

`GET|POST /api/engagements/{id}/artifactories`, `DELETE /api/engagements/{id}/artifactories/{artifactory_id}`,
`GET /api/engagements/{id}/artifactory/credentials-status` (`{"machine_login": true|false}`, never a value).
