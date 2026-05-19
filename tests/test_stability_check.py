"""
Unit tests for core/stability_check.py

Tests cover:
- compute_support_area: returns the XY area of lower boxes supporting an upper box
- check_support_ratio: floor always passes / sufficient support / insufficient
- check_stack_stability: reasonable stacks pass / too-tall towers fail /
  degenerate (single-point) stacks always stable
"""

import pytest
from core.stability_check import (
    compute_support_area,
    check_support_ratio,
    check_stack_stability,
)
from tests.conftest import make_placed_box

# min_support_ratio used across tests
MIN_RATIO = 0.80


# ── compute_support_area ──────────────────────────────────────────────────────

class TestComputeSupportArea:
    def test_no_boxes_returns_zero(self):
        area = compute_support_area(0, 0, 10.0, 60.0, 40.0, [])
        assert area == pytest.approx(0.0)

    def test_full_support_same_footprint(self):
        # Lower box exactly matches upper footprint
        lower = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=10.0)
        area = compute_support_area(0, 0, 10.0, 60.0, 40.0, [lower])
        assert area == pytest.approx(60.0 * 40.0)

    def test_partial_support_half_footprint(self):
        # Lower box supports only the left half of the upper box
        lower = make_placed_box(x=0, y=0, z=0, length=30.0, width=40.0, height=10.0)
        area = compute_support_area(0, 0, 10.0, 60.0, 40.0, [lower])
        assert area == pytest.approx(30.0 * 40.0)

    def test_box_at_wrong_z_not_counted(self):
        # Lower box top is at z=5 but upper needs support at z=10
        lower = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=5.0)
        area = compute_support_area(0, 0, 10.0, 60.0, 40.0, [lower])
        assert area == pytest.approx(0.0)

    def test_two_supporting_boxes(self):
        # Two adjacent lower boxes together cover the full upper footprint
        lower1 = make_placed_box(box_id="L1", x=0, y=0, z=0,
                                  length=30.0, width=40.0, height=10.0)
        lower2 = make_placed_box(box_id="L2", x=30.0, y=0, z=0,
                                  length=30.0, width=40.0, height=10.0)
        area = compute_support_area(0, 0, 10.0, 60.0, 40.0, [lower1, lower2])
        assert area == pytest.approx(60.0 * 40.0)

    def test_real_box_partial_support(self):
        # Real scenario: box 87.1×62.3 on top of box 70.8×62.3
        # overlap area = 70.8 × 62.3
        lower = make_placed_box(x=0, y=0, z=0, length=70.8, width=62.3, height=62.2)
        area = compute_support_area(0, 0, 62.2, 87.1, 62.3, [lower])
        assert area == pytest.approx(70.8 * 62.3)


# ── check_support_ratio ───────────────────────────────────────────────────────

class TestCheckSupportRatio:
    def test_floor_box_always_passes(self):
        # z=0 → floor support, always valid regardless of what's below
        assert check_support_ratio(0, 0, 0.0, 60.0, 40.0, [], MIN_RATIO) is True

    def test_floor_box_with_nothing_below(self):
        assert check_support_ratio(0, 0, 0.0, 87.1, 62.3, [], MIN_RATIO) is True

    def test_full_support_above_floor_passes(self):
        lower = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=10.0)
        assert check_support_ratio(0, 0, 10.0, 60.0, 40.0, [lower], MIN_RATIO) is True

    def test_exactly_min_ratio_passes(self):
        # Support area exactly equals min_ratio * base_area
        # Base: 100×40 = 4000; min_ratio=0.80 → need 3200; support 80×40=3200
        lower = make_placed_box(x=0, y=0, z=0, length=80.0, width=40.0, height=10.0)
        assert check_support_ratio(0, 0, 10.0, 100.0, 40.0, [lower], MIN_RATIO) is True

    def test_just_below_min_ratio_fails(self):
        # Support area just below threshold: 79.9×40 / (100×40) ≈ 0.799 < 0.80
        lower = make_placed_box(x=0, y=0, z=0, length=79.9, width=40.0, height=10.0)
        assert check_support_ratio(0, 0, 10.0, 100.0, 40.0, [lower], MIN_RATIO) is False

    def test_no_support_above_floor_fails(self):
        # Box floating at z=10 with nothing below
        assert check_support_ratio(0, 0, 10.0, 60.0, 40.0, [], MIN_RATIO) is False

    def test_real_scenario_87x62_on_top_of_87x62(self):
        # 927184009000801 (87.1×62.3) stacked on identical box → 100% support
        lower = make_placed_box(x=0, y=0, z=0, length=87.1, width=62.3, height=62.2)
        result = check_support_ratio(0, 0, 62.2, 87.1, 62.3, [lower], MIN_RATIO)
        assert result is True

    def test_real_scenario_large_on_small_fails(self):
        # 211.7×62.3 on top of 87.1×62.3 at same y
        # overlap = 87.1×62.3; base = 211.7×62.3
        # ratio = 87.1/211.7 ≈ 0.41 < 0.80 → should fail
        lower = make_placed_box(x=0, y=0, z=0, length=87.1, width=62.3, height=62.2)
        result = check_support_ratio(0, 0, 62.2, 211.7, 62.3, [lower], MIN_RATIO)
        assert result is False

    def test_degenerate_zero_base_area_fails(self):
        assert check_support_ratio(0, 0, 10.0, 0.0, 0.0, [], MIN_RATIO) is False

    def test_tolerance_z_nearly_zero_treated_as_floor(self):
        # z = 1e-8 < FLOAT_TOL (1e-6) — treated as floor → always passes
        assert check_support_ratio(0, 0, 1e-8, 60.0, 40.0, [], MIN_RATIO) is True


# ── check_stack_stability ─────────────────────────────────────────────────────

class TestCheckStackStability:
    RATIO = 7.0  # default stability_ratio from OptimizationParameters

    def test_single_flat_box_on_floor_stable(self):
        # 70.8×62.3×6 → stack_height=6, min_base=62.3 → ratio=0.096 < 7
        assert check_stack_stability(
            0, 0, 0, 70.8, 62.3, 6.0, [], self.RATIO
        ) is True

    def test_single_tall_narrow_box_unstable(self):
        # 6×6×226 → stack_height=226, min_base=6 → ratio≈37.7 > 7
        assert check_stack_stability(
            0, 0, 0, 6.0, 6.0, 226.0, [], self.RATIO
        ) is False

    def test_stacked_reasonable_tower_stable(self):
        # Two 62.3×62.3×62.2 boxes → total height=124.4, min_base=62.3
        # ratio ≈ 2.0 < 7
        lower = make_placed_box(x=0, y=0, z=0,
                                 length=62.3, width=62.3, height=62.2)
        assert check_stack_stability(
            0, 0, 62.2, 62.3, 62.3, 62.2, [lower], self.RATIO
        ) is True

    def test_empty_pallet_first_box_stable(self):
        # Any standard box as first placement
        assert check_stack_stability(
            0, 0, 0, 87.1, 62.3, 62.2, [], self.RATIO
        ) is True

    def test_real_scenario_three_stacked_standard_boxes(self):
        # Three 87.1×62.3×62.2 boxes stacked → height=186.6, min_base=62.3
        # ratio ≈ 3.0 < 7 → stable
        pb1 = make_placed_box(box_id="P1", x=0, y=0, z=0,
                               length=87.1, width=62.3, height=62.2)
        pb2 = make_placed_box(box_id="P2", x=0, y=0, z=62.2,
                               length=87.1, width=62.3, height=62.2)
        assert check_stack_stability(
            0, 0, 124.4, 87.1, 62.3, 62.2, [pb1, pb2], self.RATIO
        ) is True

    def test_degenerate_single_point_always_stable(self):
        # min_base = 0 → guard clause returns True
        assert check_stack_stability(
            0, 0, 0, 0.0, 0.0, 100.0, [], self.RATIO
        ) is True

    def test_non_overlapping_box_not_added_to_stack(self):
        # Placed box far away in x should not affect the stack
        far_box = make_placed_box(x=100.0, y=0, z=0,
                                   length=10.0, width=10.0, height=200.0)
        # New box at (0,0,0) 10×10×10 — its own stack: height=10, min_base=10
        assert check_stack_stability(
            0, 0, 0, 10.0, 10.0, 10.0, [far_box], self.RATIO
        ) is True

    def test_strict_boundary_ratio_fails_above(self):
        # Create a stack where height / min_base is exactly 7.0 → NOT strictly < 7
        # min_base=10, so height=70 → ratio=7.0 is NOT < 7 → False
        assert check_stack_stability(
            0, 0, 0, 10.0, 10.0, 70.0, [], self.RATIO
        ) is False

    def test_strict_boundary_ratio_passes_just_below(self):
        # height=69.9, min_base=10 → ratio=6.99 < 7 → True
        assert check_stack_stability(
            0, 0, 0, 10.0, 10.0, 69.9, [], self.RATIO
        ) is True
