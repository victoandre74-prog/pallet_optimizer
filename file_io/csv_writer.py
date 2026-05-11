"""
CSV writer for palletization results.

Writes one row per placed box.  The output file is consumed by the
Dash visualization dashboard (pallet_dashboard.py).

Output columns:
    pallet_id       — integer pallet identifier
    box_id          — original box identifier
    client_id       — client owning this box
    priority        — 1 or 2
    x               — bottom-left-back X position (cm)
    y               — bottom-left-back Y position (cm)
    z               — bottom-left-back Z position (cm)
    orientation     — orientation name (e.g. "LWH")
    length          — placed length along X (cm)
    width           — placed width along Y (cm)
    height          — placed height along Z (cm)
    weight          — box weight (kg)
    pallet_length   — pallet dimension X (cm)  ← for dashboard
    pallet_width    — pallet dimension Y (cm)  ← for dashboard
    pallet_height   — pallet max height Z (cm) ← for dashboard
    multi_client    — yes/no whether the pallet holds boxes from multiple clients
    volumetric_fill_ratio — used volume / total pallet volume (0.0–1.0)
    worst_stability_ratio — worst effective height/min_base across P1 sub-columns
                            (higher = less stable, accounts for lateral P1 bracing)
"""

import csv
from pathlib import Path
from typing import List

from models.pallet import Pallet


# Ordered list of column names
RESULT_COLUMNS = [
    "pallet_id",
    "sequence",
    "box_id",
    "client_id",
    "priority",
    "x", "y", "z",
    "orientation",
    "length", "width", "height",
    "weight",
    "pallet_length",
    "pallet_width",
    "pallet_height",
    "multi_client",
    "volumetric_fill_ratio",
    "worst_stability_ratio",
    "designation",
    "location",
]


def write_results_to_csv(pallets: List[Pallet], filepath: str) -> None:
    """
    Writes the full palletization result to a CSV file.

    Args:
        pallets:  List of packed pallets (output of the optimizer).
        filepath: Destination path for the CSV file.
    """
    path = Path(filepath)
    # Create parent directories if they don't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    row_count = 0

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, delimiter=";")
        writer.writeheader()

        for pallet in pallets:
            for pb in pallet.boxes:
                writer.writerow({
                    "pallet_id":    pallet.id,
                    "sequence":     pb.sequence,
                    "box_id":       pb.box_id,
                    "client_id":    pb.client_id,
                    "priority":     pb.priority,
                    "x":            round(pb.x,      4),
                    "y":            round(pb.y,      4),
                    "z":            round(pb.z,      4),
                    "orientation":  pb.orientation.value,
                    "length":       round(pb.length, 4),
                    "width":        round(pb.width,  4),
                    "height":       round(pb.height, 4),
                    "weight":       round(pb.weight, 4),
                    "pallet_length": pallet.length,
                    "pallet_width":  pallet.width,
                    "pallet_height": pallet.max_height,
                    "multi_client":  "yes" if pallet.is_multi_client else "no",
                    "volumetric_fill_ratio": round(pallet.volumetric_fill_ratio, 4),
                    "worst_stability_ratio": pallet.worst_stability_ratio,
                    "designation": pb.designation,
                    "location":    pb.location,
                })
                row_count += 1

    print(
        f"[CSV Writer] Results written to {filepath} "
        f"({len(pallets)} pallets, {row_count} placed boxes)."
    )
