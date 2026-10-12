"""Conversion recipes from recipes.yaml into conversion_recipes and
conversion_recipe_steps — 34-CONVERSION-ARCHITECTURE.md C1. Idempotent: a
recipe is upserted by id, its steps replaced. The file is the record."""

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app import models

RECIPES_FILE = Path(__file__).with_name("recipes.yaml")


def load() -> list[dict]:
    return yaml.safe_load(RECIPES_FILE.read_text(encoding="utf-8"))["recipes"]


_RECIPE_FIELDS = ("version", "item_id", "resolution_id", "supported_layouts", "status", "owner_team", "blockers")
_STEP_FIELDS = ("phase", "approach_id", "approach_version", "automation_class", "targets", "depends_on", "optional_when")


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _from_file(data: dict) -> tuple[dict, dict[str, dict]]:
    recipe = {f: data.get(f, [] if f == "blockers" else None) for f in _RECIPE_FIELDS}
    steps = {s["step_id"]: {f: s.get(f, [] if f == "depends_on" else None) for f in _STEP_FIELDS} for s in data["steps"]}
    return recipe, steps


def _from_row(db: Session, row: models.ConversionRecipe) -> tuple[dict, dict[str, dict]]:
    recipe = {f: getattr(row, f) for f in _RECIPE_FIELDS}
    steps = {s.step_id: {f: getattr(s, f) for f in _STEP_FIELDS}
             for s in db.query(models.ConversionRecipeStep).filter_by(recipe_id=row.id)}
    return recipe, steps


def sync(db: Session) -> dict[str, list[str]]:
    """recipes.yaml into the database, by the platform seed's rules (CLAUDE.md
    rule 10, app/seed/platform.py): a missing recipe is inserted, a newer file
    version upgrades it, an identical one is left alone, and a newer row or the
    same version with different content is left as it is and reported. A step
    is never deleted: a recipe that drops a step is refused, since recipe steps
    are catalog and nothing in the catalog is hard-deleted (rule 7). Flushes;
    the caller commits."""
    report: dict[str, list[str]] = {"inserted": [], "upgraded": [], "unchanged": [], "repository_behind": [], "conflicts": []}
    for data in load():
        wanted, wanted_steps = _from_file(data)
        row = db.get(models.ConversionRecipe, data["id"])
        is_new = row is None
        if not is_new:
            have, have_steps = _from_row(db, row)
            if (have, have_steps) == (wanted, wanted_steps):
                report["unchanged"].append(row.id)
                continue
            if _semver(row.version) > _semver(wanted["version"]):
                report["repository_behind"].append(f"{row.id}: {row.version} here, {wanted['version']} in recipes.yaml")
                continue
            if row.version == wanted["version"]:
                report["conflicts"].append(f"{row.id} {row.version}: content differs from recipes.yaml at the same version")
                continue
            dropped = sorted(set(have_steps) - set(wanted_steps))
            if dropped:
                report["conflicts"].append(f"{row.id}: recipes.yaml {wanted['version']} drops step(s) {', '.join(dropped)}; "
                                           f"a step is never deleted, so the recipe needs a new id")
                continue
        else:
            row = models.ConversionRecipe(id=data["id"])
        for field, value in wanted.items():
            setattr(row, field, value)
        db.add(row)
        db.flush()
        for step_id, fields in wanted_steps.items():
            step_row = db.get(models.ConversionRecipeStep, (row.id, step_id))
            if step_row is None:
                step_row = models.ConversionRecipeStep(recipe_id=row.id, step_id=step_id)
            for field, value in fields.items():
                setattr(step_row, field, value)
            db.add(step_row)
        report["inserted" if is_new else "upgraded"].append(row.id)
    db.flush()
    return report


def step(db: Session, recipe_id: str, step_id: str = "F01") -> models.ConversionRecipeStep:
    return db.get(models.ConversionRecipeStep, (recipe_id, step_id))
