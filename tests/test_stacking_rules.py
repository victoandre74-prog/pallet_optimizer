"""
Unit tests for core/stacking_rules.py

Tests cover:
- get_supporting_boxes: finds boxes directly below and XY-overlapping
- can_place_on_floor: always True
- check_stacking_rules:
    * Floor placement (z=0): always allowed for any priority
    * Above floor with no support: always rejected
    * P1 on P1: allowed
    * P1 on stackable P2: allowed
    * P1 on non-stackable P2: rejected
    * P2 on stackable (P1 or P2): allowed
    * P2 on non-stackable: rejected
    * Mixed supports where one is non-stackable: rejected
"""

import pytest
from pallet_optimizer.core.stacking_rules import (
    get_supporting_boxes,
    can_place_on_floor,
    check_stacking_rules,
)
from tests.conftest import make_placed_box


# ── get_supporting_boxes ──────────────────────────────────────────────────────

class TestGetSupportingBoxes:
    def test_no_boxes_returns_empty(self):
        result = get_supporting_boxes(0, 0, 10.0, 60.0, 40.0, [])
        assert result == []

    def test_box_directly_below_and_overlapping(self):
        lower = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=10.0)
        result = get_supporting_boxes(0, 0, 10.0, 60.0, 40.0, [lower])
        assert len(result) == 1
        assert result[0] is lower

    def test_box_at_wrong_z_not_returned(self):
        lower = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=5.0)
        # top of lower is at z=5, but we ask for support at z=10
        result = get_supporting_boxes(0, 0, 10.0, 60.0, 40.0, [lower])
        assert result == []

    def test_box_not_overlapping_in_xy_not_returned(self):
        # Lower box is beside the candidate in X, no XY overlap
        lower = make_placed_box(x=100.0, y=0, z=0, length=60.0, width=40.0, height=10.0)
        result = get_supporting_boxes(0, 0, 10.0, 60.0, 40.0, [lower])
        assert result == []

    def test_two_supporting_boxes_both_returned(self):
        lower1 = make_placed_box(box_id="L1", x=0, y=0, z=0,
                                  length=30.0, width=40.0, height=10.0)
        lower2 = make_placed_box(box_id="L2", x=30.0, y=0, z=0,
                                  length=30.0, width=40.0, height=10.0)
        result = get_supporting_boxes(0, 0, 10.0, 60.0, 40.0, [lower1, lower2])
        assert len(result) == 2

    def test_box_at_z_tolerance_counts(self):
        # Lower box top at z=10 - 1e-8 ≈ 10 (within FLOAT_TOL)
        lower = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0,
                                 height=10.0 - 1e-8)
        result = get_supporting_boxes(0, 0, 10.0 - 1e-8, 60.0, 40.0, [lower])
        assert len(result) == 1


# ── can_place_on_floor ────────────────────────────────────────────────────────

class TestCanPlaceOnFloor:
    def test_p1_on_floor(self):
        assert can_place_on_floor(1) is True

    def test_p2_on_floor(self):
        assert can_place_on_floor(2) is True


# ── check_stacking_rules — floor ──────────────────────────────────────────────

class TestCheckStackingRulesFloor:
    def test_p1_on_floor_always_valid(self):
        assert check_stacking_rules(0, 0, 0.0, 87.1, 62.3, 1, []) is True

    def test_p2_on_floor_always_valid(self):
        assert check_stacking_rules(0, 0, 0.0, 70.8, 62.3, 2, []) is True

    def test_floor_valid_even_with_non_stackable_below(self):
        # Non-stackable box present but z=0 so stacking rule doesn't apply
        pb = make_placed_box(x=0, y=0, z=0, length=60.0, width=40.0, height=0,
                              stackable=False)
        assert check_stacking_rules(0, 0, 0.0, 60.0, 40.0, 1, [pb]) is True

    def test_floor_with_tolerance_z(self):
        # z = 5e-7 < FLOAT_TOL → treated as floor
        assert check_stacking_rules(0, 0, 5e-7, 60.0, 40.0, 1, []) is True


# ── check_stacking_rules — no support above floor ─────────────────────────────

class TestCheckStackingRulesNoSupport:
    def test_p1_floating_in_air_rejected(self):
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 1, []) is False

    def test_p2_floating_in_air_rejected(self):
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 2, []) is False

    def test_non_overlapping_lower_box_not_support(self):
        # Lower box is to the side — no XY overlap → not a support
        pb = make_placed_box(x=100.0, y=0, z=0, length=60.0, width=40.0, height=10.0)
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 1, [pb]) is False


# ── check_stacking_rules — P1 placement ──────────────────────────────────────

class TestCheckStackingRulesP1:
    def test_p1_on_p1_stackable_allowed(self):
        lower_p1 = make_placed_box(x=0, y=0, z=0, priority=1,
                                    length=87.1, width=62.3, height=62.2,
                                    stackable=True)
        assert check_stacking_rules(0, 0, 62.2, 87.1, 62.3, 1, [lower_p1]) is True

    def test_p1_on_p1_non_stackable_still_allowed(self):
        # P1 on P1 is always allowed regardless of stackable flag
        lower_p1 = make_placed_box(x=0, y=0, z=0, priority=1,
                                    length=87.1, width=62.3, height=62.2,
                                    stackable=False)
        assert check_stacking_rules(0, 0, 62.2, 87.1, 62.3, 1, [lower_p1]) is True

    def test_p1_on_stackable_p2_allowed(self):
        lower_p2 = make_placed_box(x=0, y=0, z=0, priority=2,
                                    length=70.8, width=62.3, height=6.0,
                                    stackable=True)
        assert check_stacking_rules(0, 0, 6.0, 70.8, 62.3, 1, [lower_p2]) is True

    def test_p1_on_non_stackable_p2_rejected(self):
        # Non-stackable P2 surface — P1 may not rest on it
        lower_p2 = make_placed_box(x=0, y=0, z=0, priority=2,
                                    length=70.8, width=62.3, height=6.0,
                                    stackable=False)
        assert check_stacking_rules(0, 0, 6.0, 70.8, 62.3, 1, [lower_p2]) is False

    def test_p1_on_mixed_supports_one_non_stackable_p2_rejected(self):
        # Two supports: one P1 (ok) and one non-stackable P2 (not ok) → rejected
        lower_p1 = make_placed_box(box_id="LP1", x=0, y=0, z=0, priority=1,
                                    length=30.0, width=40.0, height=10.0,
                                    stackable=True)
        lower_p2 = make_placed_box(box_id="LP2", x=30.0, y=0, z=0, priority=2,
                                    length=30.0, width=40.0, height=10.0,
                                    stackable=False)
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 1,
                                     [lower_p1, lower_p2]) is False

    def test_p1_on_two_p1_supports_allowed(self):
        lower1 = make_placed_box(box_id="L1", x=0, y=0, z=0, priority=1,
                                  length=30.0, width=40.0, height=10.0)
        lower2 = make_placed_box(box_id="L2", x=30.0, y=0, z=0, priority=1,
                                  length=30.0, width=40.0, height=10.0)
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 1,
                                     [lower1, lower2]) is True


# ── check_stacking_rules — P2 placement ──────────────────────────────────────

class TestCheckStackingRulesP2:
    def test_p2_on_stackable_p1_allowed(self):
        lower_p1 = make_placed_box(x=0, y=0, z=0, priority=1,
                                    length=70.8, width=62.3, height=62.2,
                                    stackable=True)
        assert check_stacking_rules(0, 0, 62.2, 70.8, 62.3, 2, [lower_p1]) is True

    def test_p2_on_stackable_p2_allowed(self):
        lower_p2 = make_placed_box(x=0, y=0, z=0, priority=2,
                                    length=70.8, width=62.3, height=6.0,
                                    stackable=True)
        assert check_stacking_rules(0, 0, 6.0, 70.8, 62.3, 2, [lower_p2]) is True

    def test_p2_on_non_stackable_p1_rejected(self):
        lower_p1 = make_placed_box(x=0, y=0, z=0, priority=1,
                                    length=70.8, width=62.3, height=62.2,
                                    stackable=False)
        assert check_stacking_rules(0, 0, 62.2, 70.8, 62.3, 2, [lower_p1]) is False

    def test_p2_on_non_stackable_p2_rejected(self):
        lower_p2 = make_placed_box(x=0, y=0, z=0, priority=2,
                                    length=70.8, width=62.3, height=6.0,
                                    stackable=False)
        assert check_stacking_rules(0, 0, 6.0, 70.8, 62.3, 2, [lower_p2]) is False

    def test_p2_on_mixed_one_non_stackable_rejected(self):
        # One support is non-stackable → entire placement rejected
        s1 = make_placed_box(box_id="S1", x=0, y=0, z=0, priority=1,
                              length=30.0, width=40.0, height=10.0, stackable=True)
        s2 = make_placed_box(box_id="S2", x=30.0, y=0, z=0, priority=1,
                              length=30.0, width=40.0, height=10.0, stackable=False)
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 2, [s1, s2]) is False

    def test_p2_on_all_stackable_supports_allowed(self):
        s1 = make_placed_box(box_id="S1", x=0, y=0, z=0, priority=1,
                              length=30.0, width=40.0, height=10.0, stackable=True)
        s2 = make_placed_box(box_id="S2", x=30.0, y=0, z=0, priority=2,
                              length=30.0, width=40.0, height=10.0, stackable=True)
        assert check_stacking_rules(0, 0, 10.0, 60.0, 40.0, 2, [s1, s2]) is True


# ── Real-world scenario ───────────────────────────────────────────────────────

class TestRealWorldScenario:
    def test_p1_on_p1_from_tournee_type2026(self):
        """
        927184009000101 (P1, 87.1×62.3 base in LHW orientation, h=62.2)
        stacked under 927184009000201 (P1, same dims).
        P1 on P1 → allowed.
        """
        lower = make_placed_box(
            box_id="927184009000101", x=0, y=0, z=0,
            priority=1, length=87.1, width=62.3, height=62.2, stackable=True,
        )
        assert check_stacking_rules(0, 0, 62.2, 87.1, 62.3, 1, [lower]) is True

    def test_p2_flat_on_stackable_p1(self):
        """
        927184009000601 (P2, flat 70.8×62.3×6) placed on top of a stackable P1.
        P2 on stackable → allowed.
        """
        lower = make_placed_box(
            box_id="927184009000101", x=0, y=0, z=0,
            priority=1, length=70.8, width=62.3, height=62.2, stackable=True,
        )
        assert check_stacking_rules(0, 0, 62.2, 70.8, 62.3, 2, [lower]) is True

    def test_p2_flat_on_non_stackable_p1(self):
        """
        Same scenario but support is not stackable → rejected.
        """
        lower = make_placed_box(
            box_id="BASE", x=0, y=0, z=0,
            priority=1, length=70.8, width=62.3, height=62.2, stackable=False,
        )
        assert check_stacking_rules(0, 0, 62.2, 70.8, 62.3, 2, [lower]) is False
