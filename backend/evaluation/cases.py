"""Loading the datasets and checking that every case is complete."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

DATASETS = Path(__file__).parent / "datasets"
REQUIRED = ("id", "description", "category", "target", "input", "expected_constraints", "expected")
TARGETS = ("planner", "self_check")


class DatasetError(ValueError):
    pass


def load(path: Path, targets: tuple = TARGETS) -> list[dict]:
    """Read one dataset. Decimal numbers stay exact (they are never turned into floating point)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, ValueError) as e:
        raise DatasetError(f"{path.name}: cannot be read ({e})") from None
    if data.get("synthetic") is not True or "SYNTHETIC" not in str(data.get("label", "")):
        raise DatasetError(f"{path.name}: must be labelled as synthetic test data")
    cases, seen = data.get("cases") or [], set()
    for number, case in enumerate(cases, 1):
        missing = [k for k in REQUIRED if k not in case]
        if missing:
            raise DatasetError(f"{path.name}: case {case.get('id', number)} has no {', '.join(missing)}")
        if case["target"] not in targets:
            raise DatasetError(f"{path.name}: case {case['id']} has an unknown target")
        if case["id"] in seen:
            raise DatasetError(f"{path.name}: the id {case['id']} is used twice")
        seen.add(case["id"])
    if not cases:
        raise DatasetError(f"{path.name}: has no cases")
    return cases
