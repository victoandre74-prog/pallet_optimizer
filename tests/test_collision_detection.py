"""
Unit tests for core/collision_detection.py

Tests cover:
- is_within_pallet: inside / exact fit / 1 mm over / negative coordinates
- collides_with_any: no boxes / clear space / exact touch (no collision) /
  genuine overlap
- is_placement_geometrically_valid: combined gate
"""

import pytest
from models.pallet import Pallet
from core.collision_detection import (
    is_within_pallet,
    collides_with_any,
    is_placement_geometrically_valid,
)
from tests.conftest import make_placed_box


# ── Helper ────────────────────────────────────────────────────────────────────

def _pallet(length=130.0, width=80.0, max_height=226.0, max_weight=600.0) -> Pallet:
    return Pallet(id=1, length=length, width=width,
                  max_height=max_height, max_weight=max_weight)


# ── is_within_pallet ──────────────────────────────────────────────────────────

class TestIsWithinPallet:
    def test_box_at_origin_fits(self):
        # 87.1×62.3×62.2 at (0,0,0) — well within 130×80×226
        assert is_within_pallet(0, 0, 0, 87.1, 62.3, 62.2, _pallet()) is True

    def test_box_exactly_fills_pallet(self):
        # Box exactly the size of the pallet
        assert is_within_pallet(0, 0, 0, 130.0, 80.0, 226.0, _pallet()) is True

    def test_box_one_mm_over_length(self):
        # 130.1 > 130 → False
        assert is_within_pallet(0, 0, 0, 130.1, 80.0, 226.0, _pallet()) is False

    def test_box_one_mm_over_width(self):
        assert is_within_pallet(0, 0, 0, 130.0, 80.1, 226.0, _pallet()) is False

    def test_box_one_mm_over_height(self):
        assert is_within_pallet(0, 0, 0, 130.0, 80.0, 226.1, _pallet()) is False

    def test_negative_x_rejected(self):
        assert is_within_pallet(-1, 0, 0, 60.0, 40.0, 30.0, _pallet()) is False

    def test_negative_y_rejected(self):
        assert is_within_pallet(0, -1, 0, 60.0, 40.0, 30.0, _pallet()) is False

    def test_negative_z_rejected(self):
        assert is_within_pallet(0, 0, -1, 60.0, 40.0, 30.0, _pallet()) is False

    def test_box_at_far_corner_fits(self):
        # Box at (67.9, 17.7, 163.8) + (62.1, 62.3, 62.2) = (130.0, 80.0, 226.0)
        assert is_within_pallet(67.9, 17.7, 163.8, 62.1, 62.3, 62.2, _pallet()) is True

    def test_box_at_far_corner_one_over(self):
        assert is_within_pallet(68.0, 17.7, 163.8, 62.1, 62.3, 62.2, _pallet()) is False

    def test_real_flat_box_at_top(self):
        # Flat 70.8×62.3×6.0 placed at z=220.0 → z+h=226.0 → fits
        assert is_within_pallet(0, 0, 220.0, 70.8, 62.3, 6.0, _pallet()) is True

    def test_real_flat_box_one_cm_over_top(self):
        assert is_within_pallet(0, 0, 221.0, 70.8, 62.3, 6.0, _pallet()) is False


# ── collides_with_any ─────────────────────────────────────────────────────────

class TestCollidesWithAny:
    def test_no_placed_boxes_no_collision(self):
        assert collides_with_any(0, 0, 0, 60.0, 40.0, 30.0, []) is False

    def test_adjacent_boxes_in_x_no_collision(self):
        # Placed box at (0,0,0) 87.1×62.3×62.2
        # Candidate at (87.1,0,0) — touching face, no interior overlap
        pb = make_placed_box(x=0, y=0, z=0, length=87.1, width=62.3, height=62.2)
        assert collides_with_any(87.1, 0, 0, 42.9, 62.3, 62.2, [pb]) is False

    def test_adjacent_boxes_in_y_no_collision(self):
        pb = make_placed_box(x=0, y=0, z=0, length=70.8, width=62.3, height=6.0)
        # Candidate starts at y=62.3
        assert collides_with_any(0, 62.3, 0, 70.8, 17.7, 6.0, [pb]) is False

    def test_box_stacked_on_top_no_collision(self):
        # Placed box: z=0, h=62.2; candidate: z=62.2, h=32.3
        pb = make_placed_box(x=0, y=0, z=0, length=87.1, width=62.3, height=62.2)
        assert collides_with_any(0, 0, 62.2, 87.1, 62.3, 32.3, [pb]) is False

    def test_overlapping_boxes_collide(self):
        pb = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=30.0)
        # Candidate overlaps: starts at (10, 10, 10) but shares interior
        assert collides_with_any(10, 10, 10, 60.0, 40.0, 30.0, [pb]) is True

    def test_candidate_inside_placed_box_collides(self):
        pb = make_placed_box(x=0, y=0, z=0, length=100.0, width=80.0, height=80.0)
        assert collides_with_any(10, 10, 10, 10.0, 10.0, 10.0, [pb]) is True

    def test_real_two_p1_boxes_adjacent_x(self):
        # Simulates two real boxes placed side by side on pallet in orientation HWL
        # Box1 at (0,0,0): placed (62.2, 62.3, 211.7)
        # Box2 at (62.2,0,0): placed (62.2, 62.3, 211.7)
        pb1 = make_placed_box(box_id="B1", x=0, y=0, z=0,
                               length=62.2, width=62.3, height=211.7)
        # Candidate at (62.2, 0, 0) — faces touch
        assert collides_with_any(62.2, 0, 0, 62.2, 62.3, 211.7, [pb1]) is False

    def test_collides_with_second_of_two_boxes(self):
        pb1 = make_placed_box(box_id="B1", x=0, y=0, z=0,
                               length=60.0, width=40.0, height=30.0)
        pb2 = make_placed_box(box_id="B2", x=60.0, y=0, z=0,
                               length=60.0, width=40.0, height=30.0)
        # Candidate overlaps with pb2
        assert collides_with_any(65.0, 0, 0, 10.0, 10.0, 10.0, [pb1, pb2]) is True

    def test_does_not_collide_with_either_of_two_boxes(self):
        pb1 = make_placed_box(box_id="B1", x=0, y=0, z=0,
                               length=60.0, width=40.0, height=30.0)
        pb2 = make_placed_box(box_id="B2", x=60.0, y=0, z=0,
                               length=60.0, width=40.0, height=30.0)
        # Candidate clearly to the side
        assert collides_with_any(0, 40.0, 0, 60.0, 40.0, 30.0, [pb1, pb2]) is False


# ── is_placement_geometrically_valid ─────────────────────────────────────────

class TestIsPlacementGeometricallyValid:
    def test_empty_pallet_valid_placement(self):
        p = _pallet()
        assert is_placement_geometrically_valid(0, 0, 0, 87.1, 62.3, 62.2, p) is True

    def test_out_of_bounds_rejected(self):
        p = _pallet()
        assert is_placement_geometrically_valid(0, 0, 0, 200.0, 80.0, 226.0, p) is False

    def test_collision_rejected(self):
        p = _pallet()
        p.boxes.append(make_placed_box(x=0, y=0, z=0,
                                       length=60.0, width=40.0, height=30.0))
        # Overlapping candidate
        assert is_placement_geometrically_valid(10, 10, 10, 60.0, 40.0, 30.0, p) is False

    def test_valid_adjacent_placement_accepted(self):
        p = _pallet()
        p.boxes.append(make_placed_box(x=0, y=0, z=0,
                                       length=60.0, width=40.0, height=30.0))
        # Candidate starts exactly at x=60.0 — no collision
        assert is_placement_geometrically_valid(60.0, 0, 0, 60.0, 40.0, 30.0, p) is True

    def test_valid_stacked_placement_accepted(self):
        p = _pallet()
        p.boxes.append(make_placed_box(x=0, y=0, z=0,
                                       length=87.1, width=62.3, height=62.2))
        # Box on top
        assert is_placement_geometrically_valid(0, 0, 62.2, 87.1, 62.3, 32.3, p) is True
