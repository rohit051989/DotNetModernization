import argparse

from app.seed.seed_data import (
    print_steps_summary,
    print_summary,
    seed,
    seed_lifecycle_steps,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the pattern catalog and lifecycle steps")
    parser.add_argument(
        "--reset", action="store_true", help="Truncate all four catalog tables before seeding"
    )
    args = parser.parse_args()

    result = seed(reset=args.reset)
    print_summary(result)

    steps_result = seed_lifecycle_steps()
    print_steps_summary(steps_result)


if __name__ == "__main__":
    main()
