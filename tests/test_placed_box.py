"""
Unit tests for models/placed_box.py

Tests cover:
- __post_init__ automatically computes x_max, y_max, z_max
- base_area and volume properties
- bounds() returns all 6 coordinates
- Immutability guarantee (x_max etc. reflect initial position)
- __repr__
"""

import pytest
from pallet_optimizer.models.orientation import Orientation
from pallet_optimizer.models.placed_box import PlacedBox
from tests.conftest import make_placed_box


class TestPostInit:
    """x_max / y_max / z_max are computed from position + dims."""

    def test_xmax_computed_correctly(self):
        pb = make_placed_box(x=10.0, length=60.0)
        assert pb.x_max == pytest.approx(70.0)

    def test_ymax_computed_correctly(self):
        pb = make_placed_box(y=5.0, width=40.0)
        assert pb.y_max == pytest.approx(45.0)

    def test_zmax_computed_correctly(self):
        pb = make_placed_box(z=30.0, height=20.0)
        assert pb.z_max == pytest.approx(50.0)

    def test_origin_box_maxes_equal_dims(self):
        pb = make_placed_box(x=0.0, y=0.0, z=0.0, length=70.8, width=62.3, height=6.0)
        assert pb.x_max == pytest.approx(70.8)
        assert pb.y_max == pytest.approx(62.3)
        assert pb.z_max == pytest.approx(6.0)

    def test_real_box_at_non_zero_position(self):
        # 927184009000101 placed at (43.0, 0.0, 0.0) in orientation HWL
        # HWL of 211.7×62.3×62.2 → placed (62.2, 62.3, 211.7)
        pb = PlacedBox(
            box_id="927184009000101",
            x=43.0, y=0.0, z=0.0,
            orientation=Orientation.HWL,
            length=62.2, width=62.3, height=211.7,
            priority=1, weight=72.1, client_id=927184, stackable=True,
        )
        assert pb.x_max == pytest.approx(43.0 + 62.2)
        assert pb.y_max == pytest.approx(0.0 + 62.3)
        assert pb.z_max == pytest.approx(0.0 + 211.7)


class TestBaseAreaAndVolume:
    def test_base_area_is_length_times_width(self):
        pb = make_placed_box(length=70.8, width=62.3)
        assert pb.base_area == pytest.approx(70.8 * 62.3)

    def test_volume_is_lwh(self):
        pb = make_placed_box(length=70.8, width=62.3, height=6.0)
        assert pb.volume == pytest.approx(70.8 * 62.3 * 6.0)

    def test_unit_box_base_area(self):
        pb = make_placed_box(length=1.0, width=1.0, height=1.0)
        assert pb.base_area == pytest.approx(1.0)

    def test_unit_box_volume(self):
        pb = make_placed_box(length=1.0, width=1.0, height=1.0)
        assert pb.volume == pytest.approx(1.0)

    def test_volume_matches_manual_calculation(self):
        pb = make_placed_box(length=87.1, width=62.3, height=62.2, weight=31.6)
        expected = 87.1 * 62.3 * 62.2
        assert pb.volume == pytest.approx(expected, rel=1e-9)


class TestBounds:
    def test_bounds_returns_six_values(self):
        pb = make_placed_box(x=1.0, y=2.0, z=3.0, length=4.0, width=5.0, height=6.0)
        result = pb.bounds()
        assert len(result) == 6

    def test_bounds_correct_values(self):
        pb = make_placed_box(x=1.0, y=2.0, z=3.0, length=4.0, width=5.0, height=6.0)
        x_min, x_max, y_min, y_max, z_min, z_max = pb.bounds()
        assert x_min == pytest.approx(1.0)
        assert x_max == pytest.approx(5.0)
        assert y_min == pytest.approx(2.0)
        assert y_max == pytest.approx(7.0)
        assert z_min == pytest.approx(3.0)
        assert z_max == pytest.approx(9.0)

    def test_bounds_at_origin(self):
        pb = make_placed_box(x=0.0, y=0.0, z=0.0, length=70.8, width=62.3, height=6.0)
        x_min, x_max, y_min, y_max, z_min, z_max = pb.bounds()
        assert x_min == 0.0
        assert x_max == pytest.approx(70.8)
        assert y_min == 0.0
        assert y_max == pytest.approx(62.3)
        assert z_min == 0.0
        assert z_max == pytest.approx(6.0)


class TestMetadataCopied:
    def test_priority_stored(self):
        pb = make_placed_box(priority=2)
        assert pb.priority == 2

    def test_weight_stored(self):
        pb = make_placed_box(weight=72.1)
        assert pb.weight == pytest.approx(72.1)

    def test_client_id_stored(self):
        pb = make_placed_box(client_id=927184)
        assert pb.client_id == 927184

    def test_stackable_stored(self):
        pb_stack = make_placed_box(stackable=True)
        pb_no_stack = make_placed_box(stackable=False)
        assert pb_stack.stackable is True
        assert pb_no_stack.stackable is False

    def test_sequence_defaults_to_zero(self):
        pb = make_placed_box()
        assert pb.sequence == 0

    def test_sequence_can_be_set(self):
        pb = make_placed_box()
        pb.sequence = 3
        assert pb.sequence == 3

    def test_designation_location_default_empty(self):
        pb = make_placed_box()
        assert pb.designation == ""
        assert pb.location == ""

    def test_orientation_stored(self):
        pb = make_placed_box(orientation=Orientation.HWL)
        assert pb.orientation == Orientation.HWL


class TestRepr:
    def test_repr_contains_box_id(self):
        pb = make_placed_box(box_id="927184009000101")
        assert "927184009000101" in repr(pb)

    def test_repr_contains_position(self):
        pb = make_placed_box(x=10.0, y=20.0, z=30.0)
        r = repr(pb)
        assert "10" in r and "20" in r and "30" in r

    def test_repr_contains_orientation(self):
        pb = make_placed_box(orientation=Orientation.HWL)
        assert "HWL" in repr(pb)
