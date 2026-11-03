"""Whether this machine can build and test a repository's baseline on the repository's own frameworks, before any
conversion (36-COPILOT-ENHANCED-CONVERSION.md Part P).

- machine: what this machine has, read from folders, executable headers and the registry, never by running anything.
- needs: what a repository's projects need, and the check of one against the other, in plain words.
- service: a repository's projects from the database, the check recorded after discovery, and read back.

`machine` and `needs` are standard library only: scripts/preflight.py's report goes through this package's command
line (python -m app.toolchain report).
"""
