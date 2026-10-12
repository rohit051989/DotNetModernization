"""No in-place mutation of a JSON column.

Every JSONB column in app/models.py is plain JSONB — no MutableDict or
MutableList — so SQLAlchemy only sees a change when the attribute is
reassigned. `plan.ordering["declarations"].append(...)` after a flush was
silently never saved (the conversion planner, fixed by reassigning). This
test reads every module under app/ and fails on the shapes that mutate a
JSON column in place:

    obj.col[k] = v      obj.col[k][j] = v      obj.col[k] += v      del obj.col[k]
    obj.col.append(v)   obj.col[k].update(v)   obj.col.setdefault(...)   ...

where `col` is the name of any JSONB column. Reassign instead:
`obj.col = {**obj.col, k: v}`. It cannot follow an alias
(`x = obj.col; x.append(v)`), so do not write one either.

It matches by attribute name, so an object that is not a model but has an
attribute named like a JSON column trips it; mark that line with
`# not a JSON column` and say what the object is.
"""

import ast
import unittest
from pathlib import Path

from sqlalchemy.dialects.postgresql import JSONB

from app import models

APP = Path(__file__).resolve().parents[1] / "app"
MUTATORS = {"append", "extend", "insert", "remove", "pop", "popitem", "clear", "update", "setdefault", "sort",
            "reverse", "add", "discard"}


def json_attributes() -> set[str]:
    names = set()
    for mapper in models.Base.registry.mappers:
        for attr in mapper.column_attrs:
            if any(isinstance(c.type, JSONB) for c in attr.columns):
                names.add(attr.key)
    return names


def _json_root(node: ast.AST, names: set[str]) -> str | None:
    """The JSON column a subscript/attribute chain starts from: obj.col, obj.col[k], obj.col[k][j]."""
    while isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute) and node.attr in names and not isinstance(node.value, ast.Constant):
        return node.attr
    return None


OPT_OUT = "# not a JSON column"


def find_mutations(source: str, names: set[str]) -> list[tuple[int, str]]:
    lines = source.splitlines()
    found = []
    for node in ast.walk(ast.parse(source)):
        targets = []
        if isinstance(node, (ast.Assign, ast.Delete)):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Subscript) and (col := _json_root(target.value, names)):
                found.append((node.lineno, f"item assignment into {col}"))
            elif isinstance(node, ast.AugAssign) and (col := _json_root(target, names)):
                found.append((node.lineno, f"augmented assignment to {col}"))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS
                and (col := _json_root(node.func.value, names))):
            found.append((node.lineno, f"{col}.{node.func.attr}(...)"))
    return sorted(f for f in found if OPT_OUT not in lines[f[0] - 1])


class JsonMutationTests(unittest.TestCase):
    def test_the_detector_sees_the_shapes_that_lose_a_change(self):
        names = {"ordering", "evidence"}
        source = (
            "plan.ordering['declarations'].append(x)\n"
            "plan.ordering['a'] = 1\n"
            "plan.ordering['a']['b'] = 1\n"
            "plan.ordering['n'] += 1\n"
            "del unit.evidence[0]\n"
            "unit.evidence.extend(records)\n"
            "plan.ordering.update(x)\n"
        )
        self.assertEqual([line for line, _ in find_mutations(source, names)], [1, 2, 3, 4, 5, 6, 7])

    def test_reassignment_and_reads_are_not_mutation(self):
        names = {"ordering"}
        source = (
            "plan.ordering = {**plan.ordering, 'declarations': placements}\n"
            "x = plan.ordering['solution']\n"
            "y = plan.ordering.get('to')\n"
            "placements.append(plan.ordering)\n"
        )
        self.assertEqual(find_mutations(source, names), [])

    def test_no_json_column_is_mutated_in_place_anywhere_in_app(self):
        names = json_attributes()
        self.assertIn("ordering", names)   # the detector is looking at the real columns
        problems = []
        for path in sorted(APP.rglob("*.py")):
            for line, what in find_mutations(path.read_text(encoding="utf-8"), names):
                problems.append(f"{path.relative_to(APP.parent).as_posix()}:{line}: {what}")
        self.assertEqual(problems, [], "in-place mutation of a JSON column is never saved; reassign the attribute")


if __name__ == "__main__":
    unittest.main()
