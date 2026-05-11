"""
Placement engine — finds valid positions for a box on a pallet.

Algorithm: Extreme-Point (EP) heuristic
────────────────────────────────────────
The extreme-point heuristic maintains a set of candidate positions
(x, y) derived from the corners of already-placed boxes.  For each
candidate, the actual placement z is found by "projecting" the box
downward until it rests on a support surface.

Extreme points are generated after each placement:
    Right face: (x + length, y)
    Front face: (x, y + width)
    Top:        handled implicitly by projecting z to the top of the
                tallest supporting box

This gives bottom-left-back behaviour: we score positions by
(z, x, y) ascending, so the lowest, leftmost, most-back position wins.
"""

from typing import List, Optional, Tuple

from models.box import Box
from models.placed_box import PlacedBox
from models.pallet import Pallet
from models.orientation import Orientation, get_oriented_dimensions
from config.parameters import OptimizationParameters
from core.collision_detection import is_placement_geometrically_valid
from core.stacking_rules import check_stacking_rules
from core.stability_check import check_support_ratio, check_stack_stability
from utils.geometry import xy_overlap, boxes_intersect_3d

# Floating-point tolerance
FLOAT_TOL = 1e-6


# ── Residual-area scoring ──────────────────────────────────────────────────────

def _compute_residual_area(
    cx: float, cy: float,
    length: float, width: float,
    pallet: Pallet,
) -> float:
    """
    Estimates the largest free rectangular zone remaining after placing a box
    with footprint (length × width) at (cx, cy).

    Uses the two new extreme points that this placement would generate as
    cheap proxies for the residual free space:
        right EP : (cx + length, cy)
        front EP : (cx, cy + width)

    For each EP, the free area is approximated as:
        (pallet.length - ep_x) * (pallet.width - ep_y)

    A larger value means less fragmentation — the placement leaves a bigger
    contiguous zone available for subsequent boxes.
    """
    best = 0.0
    for (ex, ey) in ((cx + length, cy), (cx, cy + width)):
        free_x = pallet.length - ex
        free_y = pallet.width - ey
        if free_x > 0 and free_y > 0:
            best = max(best, free_x * free_y)
    return best


# ── Extreme-point management ───────────────────────────────────────────────────

def generate_extreme_points(pallet: Pallet) -> List[Tuple[float, float]]:
    """
    Returns a deduplicated list of (x, y) candidate positions.

    Candidates are:
        (0, 0)                          — pallet origin
        (pb.x + pb.length, pb.y)       — right edge of each placed box
        (pb.x, pb.y + pb.width)        — front edge of each placed box
    """
    points = {(0.0, 0.0)}
    for pb in pallet.boxes:
        points.add((pb.x + pb.length, pb.y))
        points.add((pb.x, pb.y + pb.width))
    return list(points)


def find_support_z(
    cx: float, cy: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox]
) -> float:
    """
    Finds the lowest z at which a box (cx, cy, length, width, height) can
    rest without a 3-D collision with any placed box.

    Candidate resting surfaces: the pallet floor (z=0) and the top face
    of every already-placed box whose XY footprint overlaps the candidate.
    Candidates are tested lowest-first; the lowest valid z is returned.

    Going lowest-first preserves open space under overhanging boxes: a
    candidate may rest on the floor even if a higher placed box partially
    overhangs the same XY area, as long as the candidate height does not
    reach that overhanging box.
    """
    cx_max = cx + length
    cy_max = cy + width

    # Collect candidate resting z values from XY-overlapping boxes + floor
    candidate_zs = {0.0}
    for pb in placed_boxes:
        if xy_overlap(cx, cy, cx_max, cy_max, pb.x, pb.y, pb.x_max, pb.y_max):
            candidate_zs.add(pb.z_max)

    # Test surfaces lowest-first; return the first (lowest) without collision
    for z in sorted(candidate_zs):
        for pb in placed_boxes:
            if boxes_intersect_3d(
                cx, cy, z, length, width, height,
                pb.x, pb.y, pb.z, pb.length, pb.width, pb.height
            ):
                break
        else:
            return z  # no collision at this level

    return 0.0  # fallback (should not be reached for valid inputs)


# ── Constraint validation ──────────────────────────────────────────────────────

def is_valid_placement(
    box: Box,
    x: float, y: float, z: float,
    orientation: Orientation,
    length: float, width: float, height: float,
    pallet: Pallet,
    params: OptimizationParameters
) -> bool:
    """
    Full constraint check for placing `box` at (x, y, z) with the given
    oriented dimensions.

    Checks (in order of increasing cost):
        1. Pallet bounds + no collision      (collision_detection)
        2. Weight budget
        3. Ergonomic height limit (priority 2)
        4. Stacking rules (priority-based)
        5. Support ratio
        6. Stack stability (priority-1 only)
    """
    placed = pallet.boxes

    # 1. Geometry: bounds + collision
    if not is_placement_geometrically_valid(x, y, z, length, width, height, pallet):
        return False

    # 2. Weight
    if pallet.total_weight + box.weight > pallet.max_weight:
        return False

    # 3. Ergonomic height limit for priority-2 boxes (manually deposited)
    if box.priority == 2 and z > params.priority2_max_deposit_height:
        return False

    # 4. Stacking rules
    # TODO: pass per-orientation stackability to check_stacking_rules when
    #       the input format supports orientation-specific stackable flags.
    if not check_stacking_rules(x, y, z, length, width, box.priority, placed):
        return False

    # 5. Support ratio (only if box is above the floor)
    if z > FLOAT_TOL:
        if not check_support_ratio(
            x, y, z, length, width, placed, params.min_support_ratio
        ):
            return False

    # 6. Stack stability (priority-1 boxes only — priority-2 are placed by hand)
    if box.priority == 1:
        if not check_stack_stability(
            x, y, z, length, width, height, placed, params.stability_ratio
        ):
            return False

    return True


# ── Main placement finder ──────────────────────────────────────────────────────

def find_best_placement(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters
) -> Optional[Tuple[float, float, float, Orientation]]:
    """
    Finds the best valid placement for `box` on `pallet`.

    Returns (x, y, z, orientation) of the best position, or None if
    the box cannot be placed on this pallet at all.

    Selection criterion (bottom-left-back):
        Minimize (z, x, y) — lowest, then leftmost, then most-back.
    """
    best: Optional[Tuple] = None
    best_score: Optional[Tuple] = None

    # Extreme-point candidates in XY
    ep_candidates = generate_extreme_points(pallet)

    for orientation in box.allowed_orientations:
        length, width, height = get_oriented_dimensions(
            box.length, box.width, box.height, orientation
        )

        for (cx, cy) in ep_candidates:
            # Project downward to find the actual resting z
            z = find_support_z(cx, cy, length, width, height, pallet.boxes)

            # Validate all constraints
            if is_valid_placement(
                box, cx, cy, z, orientation,
                length, width, height, pallet, params
            ):
                # Score: minimise z first, then x, then y;
                # break ties by preferring a lower top-face (z + height) to
                # preserve vertical room — but only when the box is stackable
                # in this orientation (if nothing can go on top, height above
                # is wasted regardless, so the criterion is neutralised);
                # finally maximise the residual free area to reduce XY
                # fragmentation.
                stackable    = box.is_stackable_in(orientation)
                height_score = (z + height) if stackable else 0.0
                residual     = _compute_residual_area(cx, cy, length, width, pallet)
                score = (z, cx, cy, height_score, -residual)
                if best_score is None or score < best_score:
                    best_score = score
                    best = (cx, cy, z, orientation)

    return best


def make_placed_box(
    box: Box,
    x: float, y: float, z: float,
    orientation: Orientation
) -> PlacedBox:
    """
    Constructs a PlacedBox from a Box and its confirmed placement.
    Pre-computes all oriented dimensions for fast later access.
    """
    length, width, height = get_oriented_dimensions(
        box.length, box.width, box.height, orientation
    )
    return PlacedBox(
        box_id=box.id,
        x=x, y=y, z=z,
        orientation=orientation,
        length=length,
        width=width,
        height=height,
        priority=box.priority,
        weight=box.weight,
        client_id=box.client_id,
        stackable=box.is_stackable_in(orientation),
        designation=box.designation,
        location=box.location,
    )
