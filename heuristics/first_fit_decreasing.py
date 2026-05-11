"""
First Fit Decreasing (FFD) heuristic for 3-D palletization.

Algorithm:
    For each box (sorted large-to-small):
        1. Try each existing pallet in order.
        2. Place the box on the FIRST pallet that accepts it (true First Fit).
           Within that pallet, the best position is chosen by the placement
           engine (lowest z, leftmost x, most-back y).
        3. If no existing pallet accepts the box, open a new pallet.

The function is deliberately kept generic so it can be called:
    - In Phase 1 with a single-client box list (mono-client mode)
    - In Phase 2 with a mixed box list (repack mode)
"""

from typing import List, Optional, Tuple

from models.box import Box
from models.pallet import Pallet
from config.parameters import OptimizationParameters
from core.placement_engine import find_best_placement, make_placed_box


def _make_new_pallet(pallet_id: int, params: OptimizationParameters) -> Pallet:
    """Creates a fresh empty pallet with standard dimensions."""
    return Pallet(
        id=pallet_id,
        length=params.pallet_length,
        width=params.pallet_width,
        max_height=params.pallet_max_height,
        max_weight=params.pallet_max_weight,
    )


def pack_boxes_ffd(
    boxes: List[Box],
    params: OptimizationParameters,
    initial_pallets: Optional[List[Pallet]] = None,
    next_pallet_id: int = 1,
    allow_multi_client: bool = True,
) -> List[Pallet]:
    """
    Packs a pre-sorted list of boxes onto pallets using First Fit Decreasing.

    Args:
        boxes:              Pre-sorted list of boxes to pack.
        params:             Optimization parameters.
        initial_pallets:    Optionally start from existing pallets (for Phase 2).
        next_pallet_id:     ID to assign to the first newly created pallet.
        allow_multi_client: When False, a box may only be placed on a pallet
                            that is empty or already contains boxes from the
                            same client, preventing new mixed-client pallets.

    Returns:
        List of pallets (including any from initial_pallets) after packing.
        Boxes that could not be placed are silently skipped (should not happen
        with well-configured parameters, but added as a safeguard).
    """
    # Start from any existing pallets (Phase 2 repack uses this)
    pallets: List[Pallet] = list(initial_pallets) if initial_pallets else []
    pallet_counter = next_pallet_id

    unplaced: List[Box] = []   # track any box that truly cannot be placed

    for box in boxes:
        placed = False

        # ── Step 1: try each existing pallet ──────────────────────────────────
        best_pallet: Optional[Pallet] = None
        best_result: Optional[Tuple]  = None

        for pallet in pallets:
            # Skip pallets that would create a new mixed-client situation
            if not allow_multi_client and pallet.boxes:
                if any(pb.client_id != box.client_id for pb in pallet.boxes):
                    continue

            result = find_best_placement(box, pallet, params)
            if result is None:
                continue    # no valid position on this pallet

            # First Fit: use the first pallet that accepts the box
            best_result = result
            best_pallet = pallet
            break

        if best_pallet is not None:
            # Place the box on the best pallet found
            x, y, z, orientation = best_result
            placed_box = make_placed_box(box, x, y, z, orientation)
            placed_box.sequence = len(best_pallet.boxes) + 1
            best_pallet.boxes.append(placed_box)
            placed = True

        # ── Step 2: open a new pallet if no existing one works ─────────────────
        if not placed:
            new_pallet = _make_new_pallet(pallet_counter, params)
            pallet_counter += 1

            result = find_best_placement(box, new_pallet, params)
            if result is not None:
                x, y, z, orientation = result
                placed_box = make_placed_box(box, x, y, z, orientation)
                placed_box.sequence = 1
                new_pallet.boxes.append(placed_box)
                pallets.append(new_pallet)
            else:
                # Box physically cannot fit on any pallet (too large / too heavy)
                unplaced.append(box)
                print(
                    f"[FFD] WARNING: Box {box.id!r} could not be placed "
                    f"(dims {box.length}×{box.width}×{box.height}, "
                    f"weight {box.weight}kg). Skipping."
                )

    return pallets
