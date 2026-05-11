"""
Pallet data model.

A Pallet represents a single shipping pallet together with all the
boxes that have been packed onto it.  It exposes helpers for common
statistics used by both the optimizer and the visualizer.
"""

from dataclasses import dataclass, field
from typing import List, Set

from models.placed_box import PlacedBox

FLOAT_TOL = 1e-6


@dataclass
class Pallet:
    """
    A shipping pallet that holds a collection of PlacedBox objects.

    Attributes:
        id:           Unique integer identifier for this pallet
        length:       Pallet length along X axis (cm)
        width:        Pallet width along Y axis (cm)
        max_height:   Maximum allowed stacking height (cm)
        max_weight:   Maximum allowed total weight (kg)
        boxes:        List of boxes currently placed on this pallet
    """

    id: int
    length: float
    width: float
    max_height: float
    max_weight: float
    boxes: List[PlacedBox] = field(default_factory=list)

    # ── Weight ─────────────────────────────────────────────────────────────────

    @property
    def total_weight(self) -> float:
        """Sum of weights of all placed boxes (kg)."""
        return sum(pb.weight for pb in self.boxes)

    @property
    def remaining_weight(self) -> float:
        """Remaining weight capacity (kg)."""
        return self.max_weight - self.total_weight

    # ── Geometry ───────────────────────────────────────────────────────────────

    @property
    def pallet_volume(self) -> float:
        """Total usable volume of the pallet (cm³)."""
        return self.length * self.width * self.max_height

    @property
    def used_volume(self) -> float:
        """Sum of volumes of all placed boxes (cm³)."""
        return sum(pb.volume for pb in self.boxes)

    @property
    def volumetric_fill_ratio(self) -> float:
        """Fraction of pallet volume occupied by boxes (0.0 – 1.0)."""
        if self.pallet_volume == 0:
            return 0.0
        return self.used_volume / self.pallet_volume

    @property
    def current_height(self) -> float:
        """Height of the tallest box (z + height), or 0 if empty."""
        if not self.boxes:
            return 0.0
        return max(pb.z_max for pb in self.boxes)

    # ── Client information ─────────────────────────────────────────────────────

    @property
    def client_ids(self) -> Set[int]:
        """Set of distinct client IDs present on this pallet."""
        return {pb.client_id for pb in self.boxes}

    @property
    def is_multi_client(self) -> bool:
        """True if boxes from more than one client are present."""
        return len(self.client_ids) > 1

    # ── Priority counts ────────────────────────────────────────────────────────

    @property
    def priority1_count(self) -> int:
        return sum(1 for pb in self.boxes if pb.priority == 1)

    @property
    def priority2_count(self) -> int:
        return sum(1 for pb in self.boxes if pb.priority == 2)

    # ── Stability metric (post-hoc analysis, NOT a placement constraint) ─────

    @property
    def worst_stability_ratio(self) -> float:
        """
        Worst (highest) effective stability ratio across all P1 sub-columns.

        For each P1 box, considers:
          1. Full-stack bounding box (all XY-overlapping P1 boxes).
          2. Sub-column: only boxes equally narrow (or narrower) on the
             min-base axis, starting at-or-above the anchor.  Wider boxes
             below act as stable foundations and are excluded.
          3. Lateral P1/P1 bracing reduces the effective height.

        Higher = less stable.  This is purely informational — it does NOT
        prevent box placement (that is handled by check_stack_stability).
        """
        return _compute_worst_stability_ratio(self.boxes)

    # ── Convenience ────────────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        return len(self.boxes) == 0

    def __repr__(self) -> str:
        return (
            f"Pallet(id={self.id}, boxes={len(self.boxes)}, "
            f"fill={self.volumetric_fill_ratio:.1%}, "
            f"weight={self.total_weight:.1f}kg, "
            f"clients={self.client_ids})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Stability analysis helpers (module-level, used by Pallet.worst_stability_ratio)
# ══════════════════════════════════════════════════════════════════════════════

_MIN_SUPPORT_RATIO = 0.75   # same default as OptimizationParameters


def _support_ratio(upper: PlacedBox, lower: PlacedBox) -> float:
    """Fraction of *upper*'s base area resting on *lower*'s top face."""
    if abs(upper.z - lower.z_max) > FLOAT_TOL:
        return 0.0
    x_ov = max(0.0, min(upper.x_max, lower.x_max) - max(upper.x, lower.x))
    y_ov = max(0.0, min(upper.y_max, lower.y_max) - max(upper.y, lower.y))
    base = upper.length * upper.width
    if base <= 0:
        return 0.0
    return (x_ov * y_ov) / base


def _build_support_stacks(p1_boxes: List[PlacedBox]) -> List[List[PlacedBox]]:
    """
    Groups P1 boxes into support-connected stacks.

    Two boxes are stack-connected when one directly rests on the other
    with support area ≥ _MIN_SUPPORT_RATIO of the upper box's base.
    Transitive closure gives connected components = physical stacks.
    """
    n = len(p1_boxes)
    adj: List[Set[int]] = [set() for _ in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            a, b = p1_boxes[i], p1_boxes[j]
            if (_support_ratio(b, a) >= _MIN_SUPPORT_RATIO
                    or _support_ratio(a, b) >= _MIN_SUPPORT_RATIO):
                adj[i].add(j)
                adj[j].add(i)

    visited = [False] * n
    stacks: List[List[PlacedBox]] = []
    for start in range(n):
        if visited[start]:
            continue
        component: List[int] = []
        queue = [start]
        visited[start] = True
        while queue:
            node = queue.pop(0)
            component.append(node)
            for nb in adj[node]:
                if not visited[nb]:
                    visited[nb] = True
                    queue.append(nb)
        stacks.append([p1_boxes[i] for i in component])

    return stacks


def _lateral_braced_height(
    bb_x: float, bb_y: float, bb_x_max: float, bb_y_max: float,
    bb_z: float, bb_z_max: float,
    exclude_ids: set,
    all_boxes: List[PlacedBox],
    axis: str,
) -> float:
    """Z-coverage of P1 boxes outside *exclude_ids* bracing the bounding box."""
    intervals = []

    for pb in all_boxes:
        if pb.priority != 1 or id(pb) in exclude_ids:
            continue

        touching = False
        if axis == "x":
            if abs(pb.x_max - bb_x) <= FLOAT_TOL or abs(bb_x_max - pb.x) <= FLOAT_TOL:
                if min(bb_y_max, pb.y_max) - max(bb_y, pb.y) > FLOAT_TOL:
                    touching = True
        else:
            if abs(pb.y_max - bb_y) <= FLOAT_TOL or abs(bb_y_max - pb.y) <= FLOAT_TOL:
                if min(bb_x_max, pb.x_max) - max(bb_x, pb.x) > FLOAT_TOL:
                    touching = True

        if touching:
            oz_lo = max(bb_z, pb.z)
            oz_hi = min(bb_z_max, pb.z_max)
            if oz_hi > oz_lo + FLOAT_TOL:
                intervals.append((oz_lo, oz_hi))

    if not intervals:
        return 0.0

    intervals.sort()
    merged = [list(intervals[0])]
    for lo, hi in intervals[1:]:
        if lo <= merged[-1][1] + FLOAT_TOL:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    return sum(hi - lo for lo, hi in merged)


def _effective_ratio(
    col_height: float, narrow_dim: float, narrow_axis: str,
    bb_x: float, bb_y: float, bb_x_max: float, bb_y_max: float,
    bb_z: float, bb_z_max: float,
    exclude_ids: set, all_boxes: List[PlacedBox],
) -> float:
    """effective_height / narrow_dim after subtracting lateral bracing."""
    if narrow_dim <= 0 or col_height <= 0:
        return 0.0
    braced = _lateral_braced_height(
        bb_x, bb_y, bb_x_max, bb_y_max, bb_z, bb_z_max,
        exclude_ids, all_boxes, narrow_axis,
    )
    effective = col_height - braced
    return max(0.0, effective / narrow_dim)


def _compute_worst_stability_ratio(placed_boxes: List[PlacedBox]) -> float:
    """
    Returns the worst (highest) effective stability ratio across all P1
    support-connected stacks, considering sub-columns and lateral bracing.

    Stacks are built from physical support relationships: two P1 boxes
    are connected when one rests on the other with support area ≥ 75%
    of the upper box's base.  This prevents unrelated boxes (minor XY
    overlap) from being grouped together.
    """
    p1_boxes = [pb for pb in placed_boxes if pb.priority == 1]
    if not p1_boxes:
        return 0.0

    stacks = _build_support_stacks(p1_boxes)
    worst = 0.0

    for stack in stacks:
        # ── Full-stack bounding box ratio ───────────────────────────────
        z_tops = [pb.z_max for pb in stack]
        z_bots = [pb.z for pb in stack]
        stack_z_min, stack_z_max = min(z_bots), max(z_tops)
        stack_height = stack_z_max - stack_z_min

        all_xs = [pb.x for pb in stack] + [pb.x_max for pb in stack]
        all_ys = [pb.y for pb in stack] + [pb.y_max for pb in stack]
        bb_x, bb_x_max = min(all_xs), max(all_xs)
        bb_y, bb_y_max = min(all_ys), max(all_ys)
        base_x = bb_x_max - bb_x
        base_y = bb_y_max - bb_y
        full_min_base = min(base_x, base_y)

        stack_ids = {id(pb) for pb in stack}

        # ── Full-stack bounding box — check BOTH axes independently ────
        for axis, dim in (("x", base_x), ("y", base_y)):
            if dim <= 0:
                continue
            r = _effective_ratio(
                stack_height, dim, axis,
                bb_x, bb_y, bb_x_max, bb_y_max,
                stack_z_min, stack_z_max,
                stack_ids, placed_boxes,
            )
            worst = max(worst, r)

        # ── Sub-columns from each box in the stack upward ───────────────
        for anchor in stack:
            sub = [anchor]
            sub_ids = {id(anchor)}
            for pb in stack:
                if pb is anchor:
                    continue
                # Include only boxes that are no wider than the anchor
                # on EITHER axis and start at or above anchor
                if pb.z < anchor.z - FLOAT_TOL:
                    continue
                if (pb.x_max - pb.x) <= anchor.length + FLOAT_TOL and \
                   (pb.y_max - pb.y) <= anchor.width  + FLOAT_TOL:
                    sub.append(pb)
                    sub_ids.add(id(pb))

            sub_z_top  = max(pb.z_max for pb in sub)
            sub_height = sub_z_top - anchor.z

            sub_xs = [pb.x for pb in sub] + [pb.x_max for pb in sub]
            sub_ys = [pb.y for pb in sub] + [pb.y_max for pb in sub]
            sub_bb_x, sub_bb_x_max = min(sub_xs), max(sub_xs)
            sub_bb_y, sub_bb_y_max = min(sub_ys), max(sub_ys)

            # Check both axes of the sub-column
            for axis, dim in (("x", anchor.length), ("y", anchor.width)):
                if dim <= 0:
                    continue
                r = _effective_ratio(
                    sub_height, dim, axis,
                    sub_bb_x, sub_bb_y, sub_bb_x_max, sub_bb_y_max,
                    anchor.z, sub_z_top,
                    sub_ids, placed_boxes,
                )
                worst = max(worst, r)

    return round(worst, 4)
