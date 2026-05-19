"""
Unit tests for utils/geometry.py

Tests cover:
- intervals_overlap: strict interior intersection, touching edges, nested
- xy_overlap: 2-D rectangles
- xy_intersection_area: exact overlap area
- boxes_intersect_3d: full 3-D AABB check
- clamp: lower / upper / mid clamping
"""

import pytest
from utils.geometry import (
    intervals_overlap,
    xy_overlap,
    xy_intersection_area,
    boxes_intersect_3d,
    clamp,
)


# ── intervals_overlap ─────────────────────────────────────────────────────────

class TestIntervalsOverlap:
    # Clearly overlapping
    def test_overlapping_intervals(self):
        assert intervals_overlap(0.0, 6.0, 5.0, 10.0) is True

    def test_fully_nested(self):
        assert intervals_overlap(0.0, 10.0, 2.0, 8.0) is True

    def test_same_interval(self):
        assert intervals_overlap(0.0, 5.0, 0.0, 5.0) is True

    def test_partial_overlap_from_left(self):
        assert intervals_overlap(0.0, 5.0, 3.0, 10.0) is True

    # Touching edges (strict interior — must NOT overlap)
    def test_touching_right(self):
        # [0, 5] and [5, 10] — only share endpoint 5
        assert intervals_overlap(0.0, 5.0, 5.0, 10.0) is False

    def test_touching_left(self):
        assert intervals_overlap(5.0, 10.0, 0.0, 5.0) is False

    # Disjoint
    def test_disjoint_no_gap(self):
        # [0,5] and [6,10] — gap between them
        assert intervals_overlap(0.0, 5.0, 6.0, 10.0) is False

    def test_disjoint_large_gap(self):
        assert intervals_overlap(0.0, 1.0, 100.0, 200.0) is False

    # Real-world sizes from tournee_type2026.csv
    def test_two_adjacent_boxes_on_pallet_x(self):
        # Box 1 at x=0, length=87.1 → [0, 87.1]
        # Box 2 at x=87.1, length=43.0 → [87.1, 130.1]
        # They touch at x=87.1 — not overlapping
        assert intervals_overlap(0.0, 87.1, 87.1, 130.1) is False

    def test_two_overlapping_boxes_on_pallet_x(self):
        # Box 1: [0, 70.8]; Box 2: [60.0, 130.0] — overlap [60, 70.8]
        assert intervals_overlap(0.0, 70.8, 60.0, 130.0) is True


# ── xy_overlap ────────────────────────────────────────────────────────────────

class TestXYOverlap:
    def test_fully_overlapping_squares(self):
        assert xy_overlap(0, 0, 10, 10, 0, 0, 10, 10) is True

    def test_partial_overlap(self):
        assert xy_overlap(0, 0, 10, 10, 5, 5, 15, 15) is True

    def test_touching_right_edge_no_overlap(self):
        # Box 1: [0,10]×[0,10]; Box 2: [10,20]×[0,10]
        assert xy_overlap(0, 0, 10, 10, 10, 0, 20, 10) is False

    def test_touching_top_edge_no_overlap(self):
        assert xy_overlap(0, 0, 10, 10, 0, 10, 10, 20) is False

    def test_corner_touch_no_overlap(self):
        # Boxes share only a single corner point
        assert xy_overlap(0, 0, 5, 5, 5, 5, 10, 10) is False

    def test_disjoint_no_overlap(self):
        assert xy_overlap(0, 0, 5, 5, 10, 10, 20, 20) is False

    def test_one_nested_inside_other(self):
        assert xy_overlap(0, 0, 20, 20, 5, 5, 15, 15) is True

    def test_real_world_two_p1_boxes_side_by_side(self):
        # 927184009000101 at (0,0): length=211.7 → x:[0,211.7], but pallet=130
        # In practice placed as HWL: placed (62.2, 62.3, 211.7) at x=0
        # Second box at x=62.2: placed (62.2, 62.3, ...) → x:[62.2, 124.4]
        # They are adjacent: 62.2 == 62.2 → no overlap
        assert xy_overlap(0, 0, 62.2, 62.3, 62.2, 0, 124.4, 62.3) is False

    def test_real_world_two_boxes_overlapping_in_y(self):
        # Box at (0, 0, 62.3) and Box at (0, 30, 62.3) overlap in y
        assert xy_overlap(0, 0, 62.2, 62.3, 0, 30, 62.2, 92.3) is True


# ── xy_intersection_area ──────────────────────────────────────────────────────

class TestXYIntersectionArea:
    def test_same_rectangle(self):
        area = xy_intersection_area(0, 0, 10, 10, 0, 0, 10, 10)
        assert area == pytest.approx(100.0)

    def test_partial_overlap(self):
        # [0,10]×[0,10] ∩ [5,15]×[5,15] = [5,10]×[5,10] = 5×5 = 25
        area = xy_intersection_area(0, 0, 10, 10, 5, 5, 15, 15)
        assert area == pytest.approx(25.0)

    def test_no_overlap_returns_zero(self):
        area = xy_intersection_area(0, 0, 5, 5, 10, 10, 20, 20)
        assert area == pytest.approx(0.0)

    def test_touching_edge_returns_zero(self):
        area = xy_intersection_area(0, 0, 5, 5, 5, 0, 10, 5)
        assert area == pytest.approx(0.0)

    def test_nested_returns_inner_area(self):
        # Inner [2,8]×[2,8] fully inside [0,10]×[0,10] → area = 36
        area = xy_intersection_area(0, 0, 10, 10, 2, 2, 8, 8)
        assert area == pytest.approx(36.0)

    def test_full_support_real_box(self):
        # Box 70.8×62.3 fully on top of a box 70.8×62.3 → intersection = full base
        area = xy_intersection_area(
            0, 0, 70.8, 62.3,
            0, 0, 70.8, 62.3,
        )
        assert area == pytest.approx(70.8 * 62.3)

    def test_partial_support_overhang(self):
        # Upper box: [0,70.8]×[0,62.3]; Lower box: [0,40.0]×[0,62.3]
        # Overlap: [0,40]×[0,62.3] = 40×62.3 = 2492
        area = xy_intersection_area(0, 0, 70.8, 62.3, 0, 0, 40.0, 62.3)
        assert area == pytest.approx(40.0 * 62.3)


# ── boxes_intersect_3d ────────────────────────────────────────────────────────

class TestBoxesIntersect3D:
    def test_same_box_intersects(self):
        assert boxes_intersect_3d(0, 0, 0, 10, 10, 10,
                                  0, 0, 0, 10, 10, 10) is True

    def test_overlapping_boxes(self):
        assert boxes_intersect_3d(0, 0, 0, 10, 10, 10,
                                  5, 5, 5, 10, 10, 10) is True

    def test_touching_face_x_no_intersection(self):
        # Box1: x=[0,10]; Box2: x=[10,20] — faces touch, no interior overlap
        assert boxes_intersect_3d(0, 0, 0, 10, 10, 10,
                                  10, 0, 0, 10, 10, 10) is False

    def test_touching_face_y_no_intersection(self):
        assert boxes_intersect_3d(0, 0, 0, 10, 10, 10,
                                  0, 10, 0, 10, 10, 10) is False

    def test_touching_face_z_no_intersection(self):
        # Box resting on top — touching top/bottom face
        assert boxes_intersect_3d(0, 0, 0, 10, 10, 10,
                                  0, 0, 10, 10, 10, 10) is False

    def test_disjoint_boxes_no_intersection(self):
        assert boxes_intersect_3d(0, 0, 0, 10, 10, 10,
                                  20, 20, 20, 10, 10, 10) is False

    def test_one_inside_other_intersects(self):
        assert boxes_intersect_3d(0, 0, 0, 20, 20, 20,
                                  5, 5, 5, 5, 5, 5) is True

    def test_real_stacked_boxes_no_collision(self):
        # Box1: (0,0,0) 87.1×62.3×62.2; Box2: (0,0,62.2) 87.1×62.3×32.3
        # They touch at z=62.2 — not colliding
        assert boxes_intersect_3d(0, 0, 0, 87.1, 62.3, 62.2,
                                  0, 0, 62.2, 87.1, 62.3, 32.3) is False

    def test_real_boxes_side_by_side_no_collision(self):
        # Box1: (0,0,0) 62.2×62.3×211.7; Box2: (62.2,0,0) 62.2×62.3×211.7
        assert boxes_intersect_3d(0, 0, 0, 62.2, 62.3, 211.7,
                                  62.2, 0, 0, 62.2, 62.3, 211.7) is False

    def test_real_boxes_slightly_overlapping(self):
        # If second box starts at 62.1 instead of 62.2
        assert boxes_intersect_3d(0, 0, 0, 62.2, 62.3, 211.7,
                                  62.1, 0, 0, 62.2, 62.3, 211.7) is True


# ── clamp ─────────────────────────────────────────────────────────────────────

class TestClamp:
    def test_value_within_range(self):
        assert clamp(5.0, 0.0, 10.0) == pytest.approx(5.0)

    def test_value_below_min(self):
        assert clamp(-3.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_value_above_max(self):
        assert clamp(15.0, 0.0, 10.0) == pytest.approx(10.0)

    def test_value_at_min_boundary(self):
        assert clamp(0.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_value_at_max_boundary(self):
        assert clamp(10.0, 0.0, 10.0) == pytest.approx(10.0)

    def test_min_equals_max(self):
        assert clamp(7.0, 5.0, 5.0) == pytest.approx(5.0)
