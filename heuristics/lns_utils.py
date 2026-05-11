"""
Shared utilities for LNS passes (mono and multi-client).
"""

from typing import List

from models.box import Box
from models.placed_box import PlacedBox
from models.pallet import Pallet


# ── Pool helpers ───────────────────────────────────────────────────────────────

def make_pool_box(pb: PlacedBox, box_lookup: dict) -> Box:
    """
    Reconstructs a Box from a PlacedBox, restoring all allowed orientations.

    The original Box (from box_lookup) is used to get the canonical
    (unoriented) dimensions and the full allowed-orientations list so that
    the placement engine can pick the best valid orientation during repair.
    Randomisation is achieved by shuffling the pool order, not by restricting
    orientations — restricting orientations risks making a box impossible to
    place if its only forced orientation exceeds the pallet bounds.

    If the original is not found (should not happen in normal use), the
    placed dimensions are used as canonical dims with all orientations.
    """
    from models.orientation import ALL_ORIENTATIONS

    original = box_lookup.get(pb.box_id)
    if original is not None:
        return Box(
            id=original.id,
            priority=original.priority,
            length=original.length,
            width=original.width,
            height=original.height,
            weight=original.weight,
            client_id=original.client_id,
            allowed_orientations=list(original.allowed_orientations),
            stackable=dict(original.stackable),
        )
    else:
        return Box(
            id=pb.box_id,
            priority=pb.priority,
            length=pb.length,
            width=pb.width,
            height=pb.height,
            weight=pb.weight,
            client_id=pb.client_id,
            allowed_orientations=list(ALL_ORIENTATIONS),
            stackable={o: pb.stackable for o in ALL_ORIENTATIONS},
        )


def get_next_pallet_id(pallets: List[Pallet]) -> int:
    """Returns the next available pallet ID (max existing + 1)."""
    if not pallets:
        return 1
    return max(p.id for p in pallets) + 1
