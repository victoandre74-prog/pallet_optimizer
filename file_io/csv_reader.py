"""
CSV reader for box input data.

Expected CSV columns (semicolon-delimited):
    id                  — unique box identifier (string)
    priority            — 1 or 2
    length              — cm (float, > 0)
    width               — cm (float, > 0)
    height              — cm (float, > 0)
    weight              — kg (float, > 0)
    client_id           — integer
    allowed_orientations — comma-separated orientation names, or "all"
                           Example: "LWH,WLH,HLW"  or  "all"
    stackable           — "true" / "false"
                           Applies uniformly to all allowed orientations.

Call validate_csv(filepath) before read_boxes_from_csv() to get a full
list of errors without crashing.
"""

import csv
from pathlib import Path
from typing import List, Tuple

from models.box import Box
from models.orientation import Orientation, ALL_ORIENTATIONS

REQUIRED_COLUMNS = {
    "id", "priority", "length", "width", "height",
    "weight", "client_id", "allowed_orientations", "stackable",
}
VALID_ORIENTATIONS = {o.name for o in ALL_ORIENTATIONS}


# ── Internal parsers ───────────────────────────────────────────────────────────

def _parse_orientations(value: str) -> List[Orientation]:
    value = value.strip()
    if value.lower() == "all":
        return list(ALL_ORIENTATIONS)
    orientations = []
    for name in value.split(","):
        name = name.strip().upper()
        try:
            orientations.append(Orientation[name])
        except KeyError:
            raise ValueError(
                f"Unknown orientation: {name!r}. "
                f"Valid values: {sorted(VALID_ORIENTATIONS)}"
            )
    return orientations


def _parse_stackable(value: str, orientations: List[Orientation]) -> dict:
    flag = value.strip().lower() in ("true", "1", "yes")
    return {o: flag for o in orientations}


# ── CSV validation ─────────────────────────────────────────────────────────────

def validate_csv(filepath: str, pallet_max_height: float = None) -> List[str]:
    """
    Validates the structure and content of a box input CSV.

    Checks performed:
      - File exists and is readable
      - Delimiter is semicolon (detects comma-delimited files)
      - All required columns are present
      - No duplicate box ids
      - priority is 1 or 2
      - length, width, height, weight are positive floats
      - client_id is an integer
      - allowed_orientations contains only valid orientation names (or "all")
      - stackable is a recognised boolean string
      - (if pallet_max_height given) no dimension of a box exceeds pallet_max_height

    Returns a list of error strings (empty list = file is valid).
    Does NOT raise exceptions.
    """
    errors: List[str] = []
    path = Path(filepath)

    if not path.exists():
        return [f"File not found: {filepath}"]

    # ── Read raw content ───────────────────────────────────────────────────────
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        return [f"Cannot read file: {e}"]

    if not raw.strip():
        return ["File is empty."]

    # ── Delimiter sniff ────────────────────────────────────────────────────────
    first_line = raw.splitlines()[0]
    if ";" not in first_line and "," in first_line:
        errors.append(
            "Wrong delimiter: file appears to use comma (,) instead of semicolon (;). "
            "Please save the CSV with semicolons as column separators."
        )
        # Can't continue column checks reliably — return early
        return errors

    # ── Column presence ────────────────────────────────────────────────────────
    reader = csv.DictReader(raw.splitlines(), delimiter=";")
    if reader.fieldnames is None:
        return ["Could not read header row."]

    actual_cols = {c.strip().lower() for c in reader.fieldnames if c}
    missing = REQUIRED_COLUMNS - actual_cols
    if missing:
        errors.append(f"Missing columns: {sorted(missing)}")
        # Can't validate rows without the columns — return early
        return errors

    # ── Row-level validation ───────────────────────────────────────────────────
    seen_ids: set = set()

    for row_num, row in enumerate(reader, start=2):
        row = {k.strip(): v.strip() if v else "" for k, v in row.items() if k}
        prefix = f"Row {row_num}"

        # id
        box_id = row.get("id", "").strip()
        if not box_id:
            errors.append(f"{prefix}: 'id' is empty.")
        elif box_id in seen_ids:
            errors.append(f"{prefix}: duplicate id {box_id!r}.")
        else:
            seen_ids.add(box_id)

        # priority
        try:
            p = int(row.get("priority", ""))
            if p not in (1, 2):
                errors.append(f"{prefix} (id={box_id!r}): 'priority' must be 1 or 2, got {p}.")
        except ValueError:
            errors.append(f"{prefix} (id={box_id!r}): 'priority' is not an integer ({row.get('priority')!r}).")

        # positive floats + dimension vs pallet_max_height
        dims: dict = {}
        for field in ("length", "width", "height", "weight"):
            try:
                v = float(row.get(field, ""))
                if v <= 0:
                    errors.append(f"{prefix} (id={box_id!r}): '{field}' must be > 0, got {v}.")
                else:
                    dims[field] = v
            except ValueError:
                errors.append(f"{prefix} (id={box_id!r}): '{field}' is not a number ({row.get(field)!r}).")

        if pallet_max_height is not None and dims:
            for field in ("length", "width", "height"):
                v = dims.get(field)
                if v is not None and v > pallet_max_height:
                    errors.append(
                        f"{prefix} (id={box_id!r}): '{field}' ({v} cm) exceeds "
                        f"pallet_max_height ({pallet_max_height} cm)."
                    )

        # client_id
        try:
            int(row.get("client_id", ""))
        except ValueError:
            errors.append(f"{prefix} (id={box_id!r}): 'client_id' is not an integer ({row.get('client_id')!r}).")

        # allowed_orientations
        ao = row.get("allowed_orientations", "").strip()
        if ao.lower() != "all":
            for name in ao.split(","):
                name = name.strip().upper()
                if name not in VALID_ORIENTATIONS:
                    errors.append(
                        f"{prefix} (id={box_id!r}): unknown orientation {name!r}. "
                        f"Valid values: {sorted(VALID_ORIENTATIONS)} or 'all'."
                    )

        # stackable
        st = row.get("stackable", "").strip().lower()
        if st not in ("true", "false", "1", "0", "yes", "no"):
            errors.append(
                f"{prefix} (id={box_id!r}): 'stackable' must be true/false, got {st!r}."
            )

    return errors


# ── Box loader ─────────────────────────────────────────────────────────────────

def read_boxes_from_csv(filepath: str) -> List[Box]:
    """
    Reads a list of Box objects from a CSV file.

    Assumes the file has already been validated with validate_csv().
    Raises FileNotFoundError or ValueError on unexpected issues.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")

    boxes: List[Box] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row_num, row in enumerate(reader, start=2):
            try:
                allowed   = _parse_orientations(row["allowed_orientations"])
                stackable = _parse_stackable(row["stackable"], allowed)

                box = Box(
                    id=row["id"].strip(),
                    priority=int(row["priority"]),
                    length=float(row["length"]),
                    width=float(row["width"]),
                    height=float(row["height"]),
                    weight=float(row["weight"]),
                    client_id=int(row["client_id"]),
                    allowed_orientations=allowed,
                    stackable=stackable,
                    designation=row.get("designation", "").strip(),
                    location=row.get("location", "").strip(),
                )
                boxes.append(box)

            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"Error in row {row_num} of {filepath}: {exc}\n"
                    f"Row content: {dict(row)}"
                ) from exc

    print(f"[CSV Reader] Loaded {len(boxes)} boxes from {filepath}")
    return boxes
