import argparse

from app.seed.seed_data import (
    print_catalog_items_summary,
    print_pattern_migration_summary,
    print_signal_registry_summary,
    print_steps_summary,
    print_summary,
    seed,
    seed_catalog_items,
    seed_lifecycle_steps,
    seed_pattern_migration,
    seed_signal_registry,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the catalog and lifecycle steps (idempotent upsert; never deletes). "
        "To reset client and repository data, run scripts/reset-demo.ps1 — the one reset path."
    )
    # Removed: it truncated with CASCADE, wiping repositories and every step
    # policy, global ones included. Kept only to fail loudly.
    parser.add_argument("--reset", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reset:
        parser.error("--reset was removed. Run scripts\\reset-demo.ps1 to reset client and repository data; "
                     "the catalog is never reset, only reseeded.")

    result = seed()
    print_summary(result)

    steps_result = seed_lifecycle_steps()
    print_steps_summary(steps_result)

    # Order matters: items compute readiness from the signal registry, and
    # the pattern migration reads the pattern tables seeded above.
    print_signal_registry_summary(seed_signal_registry())
    print_pattern_migration_summary(seed_pattern_migration())
    print_catalog_items_summary(seed_catalog_items())


if __name__ == "__main__":
    main()
