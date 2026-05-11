"""
Collision detection for 3-D box placement.

Provides functions to check whether a candidate box position conflicts
with already-placed boxes or violates pallet boundary constraints.
"""

from typing import List

from models.placed_box import PlacedBox
from models.pallet import Pallet
from utils.geometry import boxes_intersect_3d


def is_within_pallet(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    pallet: Pallet
) -> bool:
    """
    Returns True when the box fits entirely within the pallet boundaries.

    Checks:
        x ≥ 0  and  x + length  ≤ pallet.length
        y ≥ 0  and  y + width   ≤ pallet.width
        z ≥ 0  and  z + height  ≤ pallet.max_height
    """
    return (
        x >= 0 and x + length  <= pallet.length   and
        y >= 0 and y + width   <= pallet.width     and
        z >= 0 and z + height  <= pallet.max_height
    )


def collides_with_any(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox]
) -> bool:
    """
    Returns True when the candidate box overlaps with ANY already-placed box.

    Uses strict 3-D AABB intersection (touching faces are NOT considered colliding).
    """
    for pb in placed_boxes:
        if boxes_intersect_3d(
            x, y, z, length, width, height,
            pb.x, pb.y, pb.z, pb.length, pb.width, pb.height
        ):
            return True
    return False


def is_placement_geometrically_valid(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    pallet: Pallet
) -> bool:
    """
    Combined check: within pallet boundaries AND no collision with existing boxes.

    This is the fast gate before the more expensive physics/stacking checks.
    """
    if not is_within_pallet(x, y, z, length, width, height, pallet):
        return False
    if collides_with_any(x, y, z, length, width, height, pallet.boxes):
        return False
    return True
