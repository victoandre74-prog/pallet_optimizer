"""
Stability and support checks for placed boxes.

Two separate checks are performed:

1. Support ratio check
   A box floating above the floor must have at least `min_support_ratio`
   (e.g. 70%) of its base area resting on boxes below it.

2. Stack stability check
   Boxes whose XY projections overlap form a "stack".
   The stack must satisfy:
       stack_height / min(stack_base_x, stack_base_y) < stability_ratio
   This prevents dangerously tall, thin towers.
"""

from typing import List

from models.placed_box import PlacedBox
from utils.geometry import xy_intersection_area, xy_overlap

FLOAT_TOL = 1e-6


# ── Support ratio ──────────────────────────────────────────────────────────────

def compute_support_area(
    x: float, y: float, z: float,
    length: float, width: float,
    placed_boxes: List[PlacedBox]
) -> float:
    """
    Computes the total area of the new box base that is directly supported
    by existing boxes whose top face sits at z.

    Returns the total overlapping XY area with supporting boxes.
    """
    total_support = 0.0
    for pb in placed_boxes:
        # Only consider boxes whose top is exactly at z (within tolerance)
        if abs(pb.z_max - z) > FLOAT_TOL:
            continue
        # Accumulate the overlapping XY area
        total_support += xy_intersection_area(
            x, y, x + length, y + width,
            pb.x, pb.y, pb.x_max, pb.y_max
        )
    return total_support


def check_support_ratio(
    x: float, y: float, z: float,
    length: float, width: float,
    placed_boxes: List[PlacedBox],
    min_support_ratio: float
) -> bool:
    """
    Returns True when the box placed at (x, y, z) has sufficient support.

    Floor-level boxes (z ≈ 0) always pass — the pallet floor supports them.
    """
    # Boxes on the floor are fully supported
    if z <= FLOAT_TOL:
        return True

    base_area = length * width
    if base_area <= 0:
        return False    # degenerate box

    support_area = compute_support_area(x, y, z, length, width, placed_boxes)
    support_ratio = support_area / base_area

    return support_ratio >= min_support_ratio


# ── Stack stability ────────────────────────────────────────────────────────────

def _get_xy_connected_stack(
    new_box_x: float, new_box_y: float,
    new_box_x_max: float, new_box_y_max: float,
    placed_boxes: List[PlacedBox]
) -> List[PlacedBox]:
    """
    Returns all placed boxes whose XY footprint overlaps with the new box.
    This defines the "stack" containing the new box.
    """
    return [
        pb for pb in placed_boxes
        if xy_overlap(
            new_box_x, new_box_y, new_box_x_max, new_box_y_max,
            pb.x, pb.y, pb.x_max, pb.y_max
        )
    ]


def check_stack_stability(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox],
    stability_ratio: float
) -> bool:
    """
    Returns True when adding this box to its stack would not make the
    stack too tall relative to its base dimensions.

    Stack is defined as all placed boxes (including the new one) whose
    XY projections overlap with the new box.

    Stability condition:
        stack_height / min(stack_base_x, stack_base_y) < stability_ratio
    """
    # Collect all boxes in the same XY stack (including the new box)
    x_max = x + length
    y_max = y + width
    stack = _get_xy_connected_stack(x, y, x_max, y_max, placed_boxes)

    # Include the new box itself
    all_z_tops = [pb.z_max for pb in stack] + [z + height]
    all_z_bots = [pb.z for pb in stack]     + [z]

    # Stack height spans from the lowest box bottom to the highest box top
    stack_height = max(all_z_tops) - min(all_z_bots)

    # Stack XY bounding box (union of all footprints + new box)
    all_xs = ([pb.x for pb in stack] + [pb.x_max for pb in stack] +
              [x, x_max])
    all_ys = ([pb.y for pb in stack] + [pb.y_max for pb in stack] +
              [y, y_max])

    stack_base_x = max(all_xs) - min(all_xs)
    stack_base_y = max(all_ys) - min(all_ys)

    # Avoid division by zero for degenerate stacks
    min_base = min(stack_base_x, stack_base_y)
    if min_base <= 0:
        return True     # single point — always stable

    return (stack_height / min_base) < stability_ratio
