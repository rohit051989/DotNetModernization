"""In-process steps, invoked via the `python` adapter.

Steps that read and write platform tables and do no analysis live here —
a separate process buys nothing and costs a serialisation boundary. Steps
2, 4 and 5 are the opposite case and live under `steps/` at the repo root
with their own virtualenvs.
"""
