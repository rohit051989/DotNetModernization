"""Process-adapter fixture: writes an artifact to output_dir and reports its
checksum. Set CHECKSUM_MODE=wrong in the adapter's env config to report a
deliberately incorrect checksum, exercising the base adapter's verification."""

import hashlib
import json
import os
import sys
from pathlib import Path


def main() -> None:
    context = json.load(sys.stdin)
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "artifact.json"
    content = b'{"hello": "world"}'
    artifact_path.write_bytes(content)

    checksum = "sha256:" + hashlib.sha256(content).hexdigest()
    if os.environ.get("CHECKSUM_MODE") == "wrong":
        checksum = "sha256:" + "0" * 64

    result = {
        "envelope_version": "1.0",
        "exit_status": "COMPLETED",
        "outputs": [
            {
                "artifact_type": "test-artifact",
                "artifact_version": "1.0.0",
                "uri": artifact_path.as_uri(),
                "checksum": checksum,
            }
        ],
    }
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
