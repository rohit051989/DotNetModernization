import argparse

from app.seed.seed_data import print_summary, seed


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the pattern catalog")
    parser.add_argument(
        "--reset", action="store_true", help="Truncate all four tables before seeding"
    )
    args = parser.parse_args()

    result = seed(reset=args.reset)
    print_summary(result)


if __name__ == "__main__":
    main()
