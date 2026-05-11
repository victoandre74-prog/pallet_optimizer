"""
Stacking-rule validation.

Rules (from the specification):
    Priority 1 boxes may be placed on:
        - the pallet floor (z == 0)
        - another Priority 1 box
        - any box surface marked as stackable

    Priority 2 boxes may be placed on:
        - a Priority 1 box   } only when the lower box surface
        - a Priority 2 box   } is marked as stackable

In both cases "placed on" means the bottom face of the new box
exactly touches the top face of the supporting box.

Tolerance:
    A small floating-point tolerance (FLOAT_TOL) is used when comparing
    z coordinates to avoid issues with floating-point rounding.
"""

from typing import List

from models.placed_box import PlacedBox
from utils.geometry import xy_overlap

# Floating-point tolerance for z-level comparisons (cm)
FLOAT_TOL = 1e-6


def _is_directly_below(candidate_z: float, pb: PlacedBox) -> bool:
    """
    Returns True if the top of pb is (approximately) at the given z level,
    meaning pb could act as a direct support for a box placed at candidate_z.
    """
    return abs(pb.z_max - candidate_z) <= FLOAT_TOL


def _xy_overlaps_with(
    x: float, y: float, length: float, width: float, pb: PlacedBox
) -> bool:
    """Returns True when the candidate footprint overlaps with pb in XY."""
    return xy_overlap(
        x, y, x + length, y + width,
        pb.x, pb.y, pb.x_max, pb.y_max
    )


def get_supporting_boxes(
    x: float, y: float, z: float,
    length: float, width: float,
    placed_boxes: List[PlacedBox]
) -> List[PlacedBox]:
    """
    Returns all already-placed boxes whose top face is at z and whose
    XY footprint overlaps with the candidate box footprint.

    These are the boxes that would directly support the new box.
    """
    return [
        pb for pb in placed_boxes
        if _is_directly_below(z, pb) and
           _xy_overlaps_with(x, y, length, width, pb)
    ]


def can_place_on_floor(priority: int) -> bool:
    """
    Any box (priority 1 or 2) may be placed directly on the pallet floor (z == 0).
    """
    return True  # No restriction for floor placement


def check_stacking_rules(
    x: float, y: float, z: float,
    length: float, width: float,
    priority: int,
    placed_boxes: List[PlacedBox]
) -> bool:
    """
    Validates stacking rules for a box about to be placed at (x, y, z).

    Returns True if the placement is allowed, False otherwise.

    Logic:
        If z == 0: always allowed (floor placement).

        If z > 0: the box must rest on at least one supporting box.
            For Priority 1: support must be from P1 boxes OR stackable surfaces.
            For Priority 2: support must be from P1/P2 boxes that are stackable.

    Note:
        This function only checks the RULE, not the support RATIO
        (minimum coverage area). That is handled by stability_check.py.
    """
    # Floor placement: always valid
    if z <= FLOAT_TOL:
        return True

    # Find supporting boxes (top face at z, overlapping in XY)
    supports = get_supporting_boxes(x, y, z, length, width, placed_boxes)

    # There must be at least one supporting box
    if not supports:
        return False

    if priority == 1:
        # Priority 1 may rest on:
        #   (a) another Priority 1 box (regardless of stackable flag)
        #   (b) any box whose surface is marked stackable
        # ALL supports in the footprint must satisfy one of these conditions —
        # a single non-stackable P2 support is enough to reject the placement.
        for sup in supports:
            if sup.priority == 1:
                continue            # (a) P1 on P1: always OK
            if sup.stackable:
                continue            # (b) stackable surface: OK
            return False            # non-stackable P2 surface: reject

        return True

    elif priority == 2:
        # Priority 2 may rest on P1 or P2, but EVERY supporting surface
        # must be stackable — a single non-stackable support rejects the placement.
        for sup in supports:
            if not sup.stackable:
                return False

        return True

    # Unknown priority — reject to be safe
    return False
