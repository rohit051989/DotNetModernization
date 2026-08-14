"""Trivial process-adapter fixture: reads a StepContext JSON on stdin, writes
a valid StepResult JSON to stdout. Represents a well-behaved, non-Python step
that only depends on stdin/stdout, per 11-STEP-CONTRACT.md's process adapter."""

import json
import sys


def main() -> None:
    context = json.load(sys.stdin)
    result = {
        "envelope_version": "1.0",
        "exit_status": "COMPLETED",
        "exit_message": f"echoed step {context.get('step_name')}",
        "outputs": [],
    }
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
