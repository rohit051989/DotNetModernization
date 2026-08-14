"""Process-adapter fixture: exits 0 but writes unparseable stdout — exercises
the 'exit code 0 with unparseable stdout' rule from 11-STEP-CONTRACT.md."""

import sys


def main() -> None:
    sys.stdin.read()
    sys.stdout.write("this is not json")


if __name__ == "__main__":
    main()
