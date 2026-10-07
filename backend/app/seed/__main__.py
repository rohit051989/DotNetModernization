import argparse

from app.items import baseline
from app.seed.catalog_source import print_report as print_catalog_report
from app.seed.catalog_source import seed_from_export_or_database
from app.seed.platform import print_platform_summary, seed_platform
from app.seed.seed_data import (
    print_conflicts,
    print_catalog_items_summary,
    print_pattern_migration_summary,
    print_signal_registry_summary,
    print_steps_summary,
    print_summary,
    seed,
    seed_architecture_items,
    seed_catalog_items,
    seed_lifecycle_steps,
    seed_pattern_migration,
    seed_resolution_derivations,
    seed_signal_registry,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the catalog and lifecycle steps (idempotent; never deletes; never overwrites a catalog "
        "row edited since it was seeded — conflicts are reported, the database row stands). "
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
    # After the stubs: implemented registrations and job definitions from
    # the repository (app/seed/platform.py). Never downgrades.
    print_platform_summary(seed_platform())

    # Order matters: items compute readiness from the signal registry, and
    # the pattern migration reads the pattern tables seeded above.
    print_signal_registry_summary(seed_signal_registry())

    # The item catalog: from the export when the catalog is empty, left as
    # it is when it is not, factory defaults only when no export exists
    # (app/seed/catalog_source.py).
    catalog = seed_from_export_or_database()
    if catalog is not None:
        print_catalog_report(catalog)
        return
    print("Catalog from the factory defaults (no export in the repository):")
    print_pattern_migration_summary(seed_pattern_migration())
    print_catalog_items_summary(seed_catalog_items())
    # After both: it repoints migrated decisions onto authored items.
    architecture = seed_architecture_items()
    print(f"Architecture items: {baseline.summary(architecture['baseline'])}; "
          f"{len(architecture['repointed_decisions'])} decision(s) repointed")
    print_conflicts(architecture["baseline"])
    # Last: derivations name items from every source above.
    derivations = seed_resolution_derivations()
    print(f"Resolution derivations: {baseline.summary(derivations)}")
    print_conflicts(derivations)


if __name__ == "__main__":
    main()
