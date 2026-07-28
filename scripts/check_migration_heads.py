#!/usr/bin/env python3
"""Validate that Alembic migrations form one linear head.

This is intentionally stdlib-only so CI can catch accidental branch heads before
Flask-Migrate is even imported.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _literal_assignment(module: ast.Module, name: str):
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise ValueError(f"Missing {name!r} assignment")


def _down_revisions(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (tuple, list)):
        return [item for item in value if item]
    raise ValueError(f"Unsupported down_revision value: {value!r}")


def main() -> int:
    revisions = {}
    referenced = set()
    errors = []

    files = sorted(MIGRATIONS_DIR.glob("*.py"))
    if not files:
        print(f"No migration files found in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    for path in files:
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = _literal_assignment(module, "revision")
            down_revision = _literal_assignment(module, "down_revision")
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        if revision in revisions:
            errors.append(f"{path.name}: duplicate revision {revision!r}")
        revisions[revision] = path.name
        referenced.update(_down_revisions(down_revision))

    missing = sorted(referenced - set(revisions))
    for revision in missing:
        errors.append(f"missing migration file for down_revision {revision!r}")

    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        errors.append(f"expected exactly one migration head, found {heads}")

    if errors:
        print("Migration graph check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Migration graph OK. Head: {heads[0]} ({revisions[heads[0]]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
