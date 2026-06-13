"""
Unit tests for models/box.py

Tests cover:
- Box construction (required + optional fields)
- Default allowed_orientations and stackable
- volume property
- get_oriented_dims shortcut
- is_stackable_in helper
- __repr__
"""

import pytest
from pallet_optimizer.models.orientation import Orientation, ALL_ORIENTATIONS
from pallet_optimizer.models.box import Box
from tests.conftest import make_box


class TestBoxConstruction:
    def test_minimal_construction_uses_all_orientations(self):
        box = Box(
            id="927184009000101",
            priority=1,
            length=211.7,
            width=62.3,
            height=62.2,
            weight=72.1,
            client_id=927184,
        )
        assert set(box.allowed_orientations) == set(ALL_ORIENTATIONS)

    def test_minimal_construction_stackable_defaults_true(self):
        box = Box(
            id="927184009000601",
            priority=2,
            length=70.8,
            width=62.3,
            height=6.0,
            weight=3.7,
            client_id=927184,
        )
        for o in ALL_ORIENTATIONS:
            assert box.stackable[o] is True

    def test_restricted_orientations_stored_correctly(self):
        orients = [Orientation.HLW, Orientation.LHW]
        box = Box(
            id="927184009000801",
            priority=1,
            length=87.1,
            width=62.3,
            height=62.2,
            weight=31.6,
            client_id=927184,
            allowed_orientations=orients,
            stackable={o: True for o in orients},
        )
        assert box.allowed_orientations == orients

    def test_unstackable_box_stores_false_for_all_orientations(self):
        orients = list(ALL_ORIENTATIONS)
        box = Box(
            id="927184009000601",
            priority=2,
            length=70.8,
            width=62.3,
            height=6.0,
            weight=3.7,
            client_id=927184,
            allowed_orientations=orients,
            stackable={o: False for o in orients},
        )
        for o in orients:
            assert box.stackable[o] is False

    def test_designation_and_location_default_empty(self):
        box = make_box()
        assert box.designation == ""
        assert box.location == ""

    def test_priority_1_and_2_accepted(self):
        b1 = make_box(priority=1)
        b2 = make_box(priority=2)
        assert b1.priority == 1
        assert b2.priority == 2

    def test_client_id_stored(self):
        box = make_box(client_id=927184)
        assert box.client_id == 927184


class TestBoxVolume:
    def test_volume_product_of_dims(self, box_large_p1):
        # 211.7 × 62.3 × 62.2
        expected = 211.7 * 62.3 * 62.2
        assert abs(box_large_p1.volume - expected) < 1e-6

    def test_volume_flat_box(self, box_flat_p2):
        # 70.8 × 62.3 × 6.0
        expected = 70.8 * 62.3 * 6.0
        assert abs(box_flat_p2.volume - expected) < 1e-6

    def test_volume_unit_box(self):
        box = make_box(length=1.0, width=1.0, height=1.0)
        assert box.volume == pytest.approx(1.0)

    def test_volume_independent_of_orientation(self, box_large_p1):
        vol = box_large_p1.volume
        assert vol > 0
        assert abs(vol - 211.7 * 62.3 * 62.2) < 1e-6


class TestGetOrientedDims:
    def test_lwh_returns_original_dims(self, box_large_p1):
        pl, pw, ph = box_large_p1.get_oriented_dims(Orientation.LWH)
        assert pl == 211.7
        assert pw == 62.3
        assert ph == 62.2

    def test_hwl_swaps_height_to_length(self, box_large_p1):
        # HWL: placed (H, W, L)
        pl, pw, ph = box_large_p1.get_oriented_dims(Orientation.HWL)
        assert pl == 62.2
        assert pw == 62.3
        assert ph == 211.7

    def test_flat_box_lhw_raises_height_to_width(self, box_flat_p2):
        # box_flat_p2: L=70.8, W=62.3, H=6.0
        # LHW: placed (L, H, W) → (70.8, 6.0, 62.3)
        pl, pw, ph = box_flat_p2.get_oriented_dims(Orientation.LHW)
        assert pl == 70.8
        assert pw == 6.0
        assert ph == 62.3

    def test_volume_preserved_in_get_oriented_dims(self, box_medium_p1):
        original_vol = box_medium_p1.volume
        for o in box_medium_p1.allowed_orientations:
            pl, pw, ph = box_medium_p1.get_oriented_dims(o)
            assert abs(pl * pw * ph - original_vol) < 1e-9


class TestIsStackableIn:
    def test_stackable_box_returns_true_for_allowed_orientations(self, box_medium_p1):
        for o in box_medium_p1.allowed_orientations:
            assert box_medium_p1.is_stackable_in(o) is True

    def test_unstackable_box_returns_false_for_all_orientations(self, box_flat_p2):
        for o in box_flat_p2.allowed_orientations:
            assert box_flat_p2.is_stackable_in(o) is False

    def test_missing_orientation_key_returns_false(self):
        # Box with only LWH in stackable dict
        box = Box(
            id="TEST",
            priority=1,
            length=50.0,
            width=40.0,
            height=30.0,
            weight=5.0,
            client_id=1,
            allowed_orientations=[Orientation.LWH],
            stackable={Orientation.LWH: True},
        )
        # Querying an orientation not in the dict → False (safe default)
        assert box.is_stackable_in(Orientation.HWL) is False


class TestBoxRepr:
    def test_repr_contains_id(self, box_large_p1):
        r = repr(box_large_p1)
        assert "927184009000101" in r

    def test_repr_contains_priority(self, box_large_p1):
        assert "priority=1" in repr(box_large_p1)

    def test_repr_contains_client(self, box_large_p1):
        assert "927184" in repr(box_large_p1)

    def test_repr_contains_weight(self, box_large_p1):
        assert "72.1" in repr(box_large_p1)
