"""
Unit tests for models/orientation.py

Tests cover:
- All 6 Orientation enum values exist
- get_oriented_dimensions maps each orientation correctly
- Volume is invariant across all orientations
- ALL_ORIENTATIONS list is complete
"""

import pytest
from models.orientation import Orientation, ALL_ORIENTATIONS, get_oriented_dimensions


# ── Real-world box dimensions from tournee_type2026.csv ───────────────────────
# 927184009000101: L=211.7, W=62.3, H=62.2 cm
L, W, H = 211.7, 62.3, 62.2

# Small asymmetric box for non-degenerate tests: L≠W≠H
Ls, Ws, Hs = 10.0, 20.0, 30.0


class TestOrientationEnum:
    def test_six_orientations_exist(self):
        assert len(Orientation) == 6

    def test_all_values_are_unique(self):
        values = [o.value for o in Orientation]
        assert len(values) == len(set(values))

    def test_all_orientations_list_complete(self):
        assert set(ALL_ORIENTATIONS) == set(Orientation)
        assert len(ALL_ORIENTATIONS) == 6

    def test_enum_values_match_names(self):
        for o in Orientation:
            assert o.value == o.name


class TestGetOrientedDimensions:
    """Each orientation maps (L, W, H) to a specific permutation."""

    def test_lwh_is_identity(self):
        # LWH: placed (L, W, H) — no rotation
        pl, pw, ph = get_oriented_dimensions(L, W, H, Orientation.LWH)
        assert pl == L
        assert pw == W
        assert ph == H

    def test_lhw(self):
        # LHW: placed (L, H, W)
        pl, pw, ph = get_oriented_dimensions(L, W, H, Orientation.LHW)
        assert pl == L
        assert pw == H
        assert ph == W

    def test_wlh(self):
        # WLH: placed (W, L, H)
        pl, pw, ph = get_oriented_dimensions(L, W, H, Orientation.WLH)
        assert pl == W
        assert pw == L
        assert ph == H

    def test_whl(self):
        # WHL: placed (W, H, L)
        pl, pw, ph = get_oriented_dimensions(L, W, H, Orientation.WHL)
        assert pl == W
        assert pw == H
        assert ph == L

    def test_hlw(self):
        # HLW: placed (H, L, W)
        pl, pw, ph = get_oriented_dimensions(L, W, H, Orientation.HLW)
        assert pl == H
        assert pw == L
        assert ph == W

    def test_hwl(self):
        # HWL: placed (H, W, L)
        pl, pw, ph = get_oriented_dimensions(L, W, H, Orientation.HWL)
        assert pl == H
        assert pw == W
        assert ph == L

    def test_all_six_permutations_are_distinct_for_asymmetric_box(self):
        """For a box where L≠W≠H all 6 permutations must be distinct triples."""
        results = set()
        for o in Orientation:
            dims = get_oriented_dimensions(Ls, Ws, Hs, o)
            results.add(dims)
        assert len(results) == 6

    def test_volume_invariant_across_all_orientations(self):
        """Volume must be the same regardless of orientation."""
        expected_vol = L * W * H
        for o in Orientation:
            pl, pw, ph = get_oriented_dimensions(L, W, H, o)
            assert abs(pl * pw * ph - expected_vol) < 1e-9, (
                f"Volume changed under orientation {o}: "
                f"{pl}×{pw}×{ph} = {pl*pw*ph} ≠ {expected_vol}"
            )

    def test_each_orientation_is_a_permutation(self):
        """Each output triple must contain exactly {L, W, H}."""
        original = sorted([L, W, H])
        for o in Orientation:
            result = sorted(get_oriented_dimensions(L, W, H, o))
            assert result == original, (
                f"Orientation {o} produced dims {result} which is not a "
                f"permutation of {original}"
            )

    def test_lwh_with_real_flat_box(self):
        # 927184009000601: L=70.8, W=62.3, H=6.0
        pl, pw, ph = get_oriented_dimensions(70.8, 62.3, 6.0, Orientation.LWH)
        assert pl == 70.8
        assert pw == 62.3
        assert ph == 6.0

    def test_hwl_with_real_flat_box_raises_height_to_length(self):
        # HWL of 70.8×62.3×6.0 → placed (6.0, 62.3, 70.8)
        pl, pw, ph = get_oriented_dimensions(70.8, 62.3, 6.0, Orientation.HWL)
        assert pl == 6.0
        assert pw == 62.3
        assert ph == 70.8
