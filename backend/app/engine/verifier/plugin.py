"""The vendored code-modernization scripts (third_party/code-modernization, 36-COPILOT-ENHANCED-CONVERSION
Part C), imported in place and unmodified. Standard library only; none makes a network call."""
import sys

from app.config import settings
from pathlib import Path

SCRIPTS = Path(settings.platform_root) / "third_party" / "code-modernization" / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import baseline_diff  # noqa: E402
import compare  # noqa: E402
import proof_pack  # noqa: E402
import uplift_checks  # noqa: E402

__all__ = ["baseline_diff", "compare", "proof_pack", "uplift_checks", "SCRIPTS"]
