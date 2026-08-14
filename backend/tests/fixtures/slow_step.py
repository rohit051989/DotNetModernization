"""Process-adapter fixture: sleeps longer than any reasonable test timeout,
to exercise the adapter's timeout handling."""

import sys
import time


def main() -> None:
    sys.stdin.read()
    time.sleep(30)


if __name__ == "__main__":
    main()
