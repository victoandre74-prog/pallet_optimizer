"""
Low-level geometry utilities shared across the codebase.

All functions here operate on plain numeric arguments (no model objects)
to keep the utility layer dependency-free and easily testable.
"""


def intervals_overlap(a_min: float, a_max: float,
                      b_min: float, b_max: float) -> bool:
    """
    Returns True when two 1-D intervals (a_min, a_max) and (b_min, b_max)
    overlap (share at least one interior point — touching edges do NOT count).

    Example:
        [0, 5) and [5, 10) → False (adjacent, not overlapping)
        [0, 6) and [5, 10) → True
    """
    return a_min < b_max and a_max > b_min


def xy_overlap(
    x1: float, y1: float, x1_max: float, y1_max: float,
    x2: float, y2: float, x2_max: float, y2_max: float
) -> bool:
    """
    Returns True when two axis-aligned rectangles share interior XY area.

    Each rectangle is specified by its min and max corners.
    """
    return (
        intervals_overlap(x1, x1_max, x2, x2_max) and
        intervals_overlap(y1, y1_max, y2, y2_max)
    )


def xy_intersection_area(
    x1: float, y1: float, x1_max: float, y1_max: float,
    x2: float, y2: float, x2_max: float, y2_max: float
) -> float:
    """
    Returns the shared XY area between two axis-aligned rectangles.
    Returns 0.0 if they do not overlap.
    """
    # Compute overlap along each axis
    overlap_x = max(0.0, min(x1_max, x2_max) - max(x1, x2))
    overlap_y = max(0.0, min(y1_max, y2_max) - max(y1, y2))
    return overlap_x * overlap_y


def boxes_intersect_3d(
    x1: float, y1: float, z1: float,
    l1: float, w1: float, h1: float,
    x2: float, y2: float, z2: float,
    l2: float, w2: float, h2: float
) -> bool:
    """
    Returns True when two axis-aligned 3-D boxes share interior volume.

    Each box is specified by its bottom-left-back corner and dimensions.
    Two boxes that merely share a face or edge are NOT considered intersecting.
    """
    return (
        intervals_overlap(x1, x1 + l1, x2, x2 + l2) and
        intervals_overlap(y1, y1 + w1, y2, y2 + w2) and
        intervals_overlap(z1, z1 + h1, z2, z2 + h2)
    )


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamps value to [lo, hi]."""
    return max(lo, min(hi, value))
