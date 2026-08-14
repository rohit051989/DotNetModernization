"""Process-adapter fixture: reads stdin (to behave like a real step), writes
to stderr, and exits non-zero."""

import sys


def main() -> None:
    sys.stdin.read()
    sys.stderr.write("boom: something went wrong\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
