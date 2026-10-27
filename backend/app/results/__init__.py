"""Central results (docs/VDI-SETUP.md, "More than one person"; 04-FRONTEND-SPEC.md "Results on another machine").

Developers run their own platform against one database. A repository's owner scans it on their own machine, where
the run output lands in that machine's RUNS_DIR; everyone else sees the results from the database:

- store: every result artifact a view reads (RESULT_TYPES) is copied into the database when its step registers it,
  once per checksum, as JSONB the server compresses. The newest RESULTS_KEEP of each kind are kept, per repository
  and, for the estate's, per engagement; older ones are pruned. Local run folders are never touched.
- paging: every list that grows with the repository is served by the database a page at a time, with its filter.
- views: those lists over the stored artifacts (fingerprint, dependencies, work list, the estate's).
- conversions: a repository's conversions, runbooks and VERIFICATION.md as its owner's machine last saw them.
- held: what is only on the owner's machine (logs, timing profiles, evidence, the repository's own files) is named as
  such: "on <owner>'s machine (<host>)", never a broken link.
- python -m app.results copy-existing: copies the results of scans made before this existed, from this machine's
  RUNS_DIR. A repository whose owner never runs it shows its results after its next scan.
"""
