"""
Unit tests for models/pallet.py

Tests cover:
- Empty pallet initial state
- Weight aggregation (total_weight, remaining_weight)
- Geometry (pallet_volume, used_volume, volumetric_fill_ratio, current_height)
- Client-related properties (client_ids, is_multi_client)
- Priority counts (priority1_count, priority2_count)
- is_empty
- worst_stability_ratio (single-box and simple stacked cases)
- __repr__
"""

import pytest
from models.pallet import Pallet
from models.placed_box import PlacedBox
from models.orientation import Orientation
from tests.conftest import make_placed_box


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pallet(length=130.0, width=80.0, max_height=226.0, max_weight=600.0) -> Pallet:
    return Pallet(id=1, length=length, width=width,
                  max_height=max_height, max_weight=max_weight)


# ── Empty pallet ──────────────────────────────────────────────────────────────

class TestEmptyPallet:
    def test_is_empty(self):
        p = _pallet()
        assert p.is_empty()

    def test_total_weight_zero(self):
        assert _pallet().total_weight == pytest.approx(0.0)

    def test_remaining_weight_equals_max(self):
        p = _pallet(max_weight=600.0)
        assert p.remaining_weight == pytest.approx(600.0)

    def test_used_volume_zero(self):
        assert _pallet().used_volume == pytest.approx(0.0)

    def test_fill_ratio_zero(self):
        assert _pallet().volumetric_fill_ratio == pytest.approx(0.0)

    def test_current_height_zero(self):
        assert _pallet().current_height == pytest.approx(0.0)

    def test_client_ids_empty_set(self):
        assert _pallet().client_ids == set()

    def test_is_not_multi_client(self):
        assert _pallet().is_multi_client is False

    def test_priority_counts_zero(self):
        p = _pallet()
        assert p.priority1_count == 0
        assert p.priority2_count == 0

    def test_worst_stability_ratio_zero(self):
        assert _pallet().worst_stability_ratio == pytest.approx(0.0)


# ── Pallet volume ─────────────────────────────────────────────────────────────

class TestPalletVolume:
    def test_default_dimensions(self, empty_pallet):
        # 130 × 80 × 227 cm  (pallet_max_height = 227.0 dans OptimizationParameters)
        expected = 130.0 * 80.0 * 227.0
        assert empty_pallet.pallet_volume == pytest.approx(expected)

    def test_custom_dimensions(self):
        p = _pallet(length=100.0, width=60.0, max_height=200.0)
        assert p.pallet_volume == pytest.approx(100.0 * 60.0 * 200.0)


# ── Weight with one box ───────────────────────────────────────────────────────

class TestWeightSingleBox:
    def test_total_weight_matches_box(self, empty_pallet):
        # 927184009000101: 72.1 kg
        pb = make_placed_box(weight=72.1)
        empty_pallet.boxes.append(pb)
        assert empty_pallet.total_weight == pytest.approx(72.1)

    def test_remaining_weight_decreases(self, empty_pallet):
        pb = make_placed_box(weight=72.1)
        empty_pallet.boxes.append(pb)
        expected = 600.0 - 72.1
        assert empty_pallet.remaining_weight == pytest.approx(expected)

    def test_is_not_empty_after_adding_box(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box())
        assert not empty_pallet.is_empty()


# ── Weight with multiple boxes ────────────────────────────────────────────────

class TestWeightMultipleBoxes:
    def test_total_weight_sum(self, empty_pallet):
        # Real weights from tournee_type2026.csv: 72.1 + 75.6 + 36.3 = 184.0
        for w in [72.1, 75.6, 36.3]:
            empty_pallet.boxes.append(make_placed_box(weight=w))
        assert empty_pallet.total_weight == pytest.approx(184.0)

    def test_remaining_weight_after_multiple(self, empty_pallet):
        for w in [72.1, 75.6, 36.3]:
            empty_pallet.boxes.append(make_placed_box(weight=w))
        assert empty_pallet.remaining_weight == pytest.approx(600.0 - 184.0)


# ── Fill ratio ────────────────────────────────────────────────────────────────

class TestFillRatio:
    def test_single_box_fill_ratio(self, empty_pallet):
        # Box: 70.8×62.3×6.0 = 26,481.84 cm³
        # Pallet: 130×80×227 = 2,360,800 cm³  (pallet_max_height = 227.0)
        pb = make_placed_box(length=70.8, width=62.3, height=6.0, weight=3.7)
        empty_pallet.boxes.append(pb)
        box_vol = 70.8 * 62.3 * 6.0
        pallet_vol = 130.0 * 80.0 * 227.0
        expected = box_vol / pallet_vol
        assert empty_pallet.volumetric_fill_ratio == pytest.approx(expected)

    def test_fill_ratio_between_0_and_1(self, empty_pallet):
        pb = make_placed_box(length=60.0, width=40.0, height=30.0, weight=10.0)
        empty_pallet.boxes.append(pb)
        ratio = empty_pallet.volumetric_fill_ratio
        assert 0.0 <= ratio <= 1.0

    def test_fill_ratio_zero_volume_pallet(self):
        p = Pallet(id=1, length=0.0, width=0.0, max_height=0.0, max_weight=600.0)
        assert p.volumetric_fill_ratio == pytest.approx(0.0)


# ── Current height ────────────────────────────────────────────────────────────

class TestCurrentHeight:
    def test_single_floor_box(self, empty_pallet):
        # Floor box: z=0, height=62.2 → current_height = 62.2
        pb = make_placed_box(z=0.0, height=62.2)
        empty_pallet.boxes.append(pb)
        assert empty_pallet.current_height == pytest.approx(62.2)

    def test_stacked_boxes_height(self, empty_pallet):
        # Two boxes stacked: 62.2 + 32.3 = 94.5
        pb1 = make_placed_box(box_id="P1", z=0.0, height=62.2)
        pb2 = make_placed_box(box_id="P2", z=62.2, height=32.3)
        empty_pallet.boxes.extend([pb1, pb2])
        assert empty_pallet.current_height == pytest.approx(94.5)

    def test_tallest_column_wins(self, empty_pallet):
        # Side by side: one 62.2 tall, one 87.1 tall
        pb1 = make_placed_box(box_id="P1", x=0.0, z=0.0, length=60.0, height=62.2)
        pb2 = make_placed_box(box_id="P2", x=60.0, z=0.0, length=60.0, height=87.1)
        empty_pallet.boxes.extend([pb1, pb2])
        assert empty_pallet.current_height == pytest.approx(87.1)


# ── Client properties ─────────────────────────────────────────────────────────

class TestClientProperties:
    def test_single_client(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box(client_id=927184))
        assert empty_pallet.client_ids == {927184}

    def test_two_different_clients(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box(box_id="A", client_id=927184))
        empty_pallet.boxes.append(make_placed_box(box_id="B", client_id=943139))
        assert empty_pallet.client_ids == {927184, 943139}

    def test_is_multi_client_false_for_one_client(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box(client_id=927184))
        empty_pallet.boxes.append(make_placed_box(client_id=927184))
        assert empty_pallet.is_multi_client is False

    def test_is_multi_client_true_for_two_clients(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box(box_id="A", client_id=927184))
        empty_pallet.boxes.append(make_placed_box(box_id="B", client_id=943139))
        assert empty_pallet.is_multi_client is True


# ── Priority counts ───────────────────────────────────────────────────────────

class TestPriorityCounts:
    def test_counts_p1_and_p2(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box(box_id="A", priority=1))
        empty_pallet.boxes.append(make_placed_box(box_id="B", priority=1))
        empty_pallet.boxes.append(make_placed_box(box_id="C", priority=2))
        assert empty_pallet.priority1_count == 2
        assert empty_pallet.priority2_count == 1

    def test_only_p1(self, empty_pallet):
        for i in range(3):
            empty_pallet.boxes.append(make_placed_box(box_id=f"P{i}", priority=1))
        assert empty_pallet.priority1_count == 3
        assert empty_pallet.priority2_count == 0

    def test_only_p2(self, empty_pallet):
        for i in range(2):
            empty_pallet.boxes.append(make_placed_box(box_id=f"P{i}", priority=2))
        assert empty_pallet.priority1_count == 0
        assert empty_pallet.priority2_count == 2


# ── Stability ratio ───────────────────────────────────────────────────────────

class TestWorstStabilityRatio:
    def test_only_p2_boxes_returns_zero(self, empty_pallet):
        pb = make_placed_box(priority=2, z=0.0, length=60.0, width=40.0, height=10.0)
        empty_pallet.boxes.append(pb)
        assert empty_pallet.worst_stability_ratio == pytest.approx(0.0)

    def test_single_flat_p1_box_is_stable(self, empty_pallet):
        # 70.8×62.3×6 → ratio = 6 / min(70.8, 62.3) ≈ 0.096 — very stable
        pb = make_placed_box(
            priority=1, z=0.0, length=70.8, width=62.3, height=6.0
        )
        empty_pallet.boxes.append(pb)
        ratio = empty_pallet.worst_stability_ratio
        assert ratio < 1.0  # clearly stable

    def test_single_tall_p1_box(self, empty_pallet):
        # 62.2×62.3×211.7 → ratio ~ 211.7 / 62.2 ≈ 3.4
        pb = make_placed_box(
            priority=1, z=0.0, length=62.2, width=62.3, height=211.7
        )
        empty_pallet.boxes.append(pb)
        ratio = empty_pallet.worst_stability_ratio
        assert ratio > 1.0  # noticeably tall

    def test_two_p1_stacked_increases_ratio(self, empty_pallet):
        # Bottom: 62.3×62.3×62.2, top: same box stacked → total height 124.4
        pb1 = make_placed_box(
            box_id="P1", priority=1, x=0.0, y=0.0, z=0.0,
            length=62.3, width=62.3, height=62.2, stackable=True,
        )
        pb2 = make_placed_box(
            box_id="P2", priority=1, x=0.0, y=0.0, z=62.2,
            length=62.3, width=62.3, height=62.2, stackable=True,
        )
        empty_pallet.boxes.extend([pb1, pb2])
        ratio = empty_pallet.worst_stability_ratio
        # stack_height=124.4, min_base=62.3 → ≈ 2.0
        assert ratio > 1.5


# ── __repr__ ──────────────────────────────────────────────────────────────────

class TestPalletRepr:
    def test_repr_contains_id(self, empty_pallet):
        assert "id=1" in repr(empty_pallet)

    def test_repr_contains_boxes_count(self, empty_pallet):
        empty_pallet.boxes.append(make_placed_box())
        assert "boxes=1" in repr(empty_pallet)

    def test_repr_contains_fill_info(self, empty_pallet):
        r = repr(empty_pallet)
        assert "fill=" in r
