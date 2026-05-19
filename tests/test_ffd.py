"""
Integration tests for heuristics/first_fit_decreasing.py

Tests cover the full FFD pipeline (placement_engine + collision + stability):
- Single box → single pallet with that box placed
- Multiple boxes fit on one pallet
- Weight limit forces a second pallet
- Geometry forces a second pallet (box too wide)
- allow_multi_client=False prevents mixing clients
- Boxes from tournee_type2026.csv (real-world subset)
- All boxes are present exactly once in output
- Sequence numbers are assigned (1-based, increasing within pallet)
"""

import pytest
from models.pallet import Pallet
from config.parameters import OptimizationParameters
from heuristics.first_fit_decreasing import pack_boxes_ffd
from heuristics.sorting import sort_boxes_for_packing
from tests.conftest import make_box


# ── Helpers ───────────────────────────────────────────────────────────────────

def _params(**overrides) -> OptimizationParameters:
    p = OptimizationParameters()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _all_box_ids(pallets):
    return [pb.box_id for p in pallets for pb in p.boxes]


# ── Single box ────────────────────────────────────────────────────────────────

class TestFFDSingleBox:
    def test_single_box_placed_on_one_pallet(self):
        box = make_box(box_id="B1", length=60.0, width=40.0, height=30.0, weight=10.0)
        pallets = pack_boxes_ffd(sort_boxes_for_packing([box]), _params())
        assert len(pallets) == 1
        assert len(pallets[0].boxes) == 1

    def test_single_box_id_matches(self):
        box = make_box(box_id="MYBOX")
        pallets = pack_boxes_ffd(sort_boxes_for_packing([box]), _params())
        assert pallets[0].boxes[0].box_id == "MYBOX"

    def test_single_box_at_z_zero(self):
        box = make_box(length=60.0, width=40.0, height=30.0)
        pallets = pack_boxes_ffd(sort_boxes_for_packing([box]), _params())
        assert pallets[0].boxes[0].z == pytest.approx(0.0)

    def test_single_box_sequence_is_one(self):
        box = make_box()
        pallets = pack_boxes_ffd(sort_boxes_for_packing([box]), _params())
        assert pallets[0].boxes[0].sequence == 1


# ── Multiple boxes, single pallet ─────────────────────────────────────────────

class TestFFDMultipleBoxesSinglePallet:
    def test_two_small_boxes_on_one_pallet(self):
        boxes = [
            make_box(box_id="A", length=60.0, width=40.0, height=30.0, weight=10.0),
            make_box(box_id="B", length=60.0, width=40.0, height=30.0, weight=10.0),
        ]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), _params())
        assert len(pallets) == 1
        assert len(pallets[0].boxes) == 2

    def test_all_box_ids_present(self):
        boxes = [make_box(box_id=f"B{i}", weight=5.0) for i in range(5)]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), _params())
        placed_ids = set(_all_box_ids(pallets))
        assert placed_ids == {f"B{i}" for i in range(5)}

    def test_no_box_placed_twice(self):
        boxes = [make_box(box_id=f"B{i}", weight=5.0) for i in range(5)]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), _params())
        ids = _all_box_ids(pallets)
        assert len(ids) == len(set(ids))

    def test_sequence_numbers_ascending_within_pallet(self):
        boxes = [make_box(box_id=f"B{i}", weight=5.0) for i in range(4)]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), _params())
        for pallet in pallets:
            sequences = [pb.sequence for pb in pallet.boxes]
            assert sequences == list(range(1, len(pallet.boxes) + 1))


# ── Weight limit forces new pallet ────────────────────────────────────────────

class TestFFDWeightLimit:
    def test_single_heavy_box_per_pallet(self):
        # Each box weighs 400 kg; max_weight=600 → max 1 per pallet
        params = _params(pallet_max_weight=600.0)
        boxes = [
            make_box(box_id="H1", length=60.0, width=40.0, height=30.0, weight=400.0),
            make_box(box_id="H2", length=60.0, width=40.0, height=30.0, weight=400.0),
        ]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), params)
        assert len(pallets) == 2

    def test_three_boxes_spanning_two_pallets_by_weight(self):
        # 3 boxes × 250 kg = 750 kg total; pallet max = 600 → 2 pallets
        params = _params(pallet_max_weight=600.0)
        boxes = [
            make_box(box_id=f"H{i}", length=60.0, width=40.0, height=30.0, weight=250.0)
            for i in range(3)
        ]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), params)
        assert len(pallets) == 2

    def test_weight_per_pallet_respected(self):
        params = _params(pallet_max_weight=300.0)
        boxes = [
            make_box(box_id=f"W{i}", length=30.0, width=30.0, height=20.0, weight=200.0)
            for i in range(4)
        ]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), params)
        for p in pallets:
            assert p.total_weight <= 300.0 + 1e-9


# ── Geometry forces new pallet ────────────────────────────────────────────────

class TestFFDGeometryLimit:
    def test_two_wide_boxes_need_two_pallets(self):
        # Box with LWH: length=65, width=80 (exactly pallet width).
        # Second identical box cannot be placed beside it (no room in x for 65+65=130 ok,
        # but also check stacking height exceeds if we go tall).
        # Use boxes that are wide enough that only one fits per row.
        # Pallet: 130×80×226; box: 65×80×120 — one fits, second cannot (no x-room)
        params = _params(pallet_length=130.0, pallet_width=80.0, pallet_max_height=226.0)
        # Force only LWH orientation to keep dims predictable
        boxes = [
            make_box(box_id="G1", length=65.1, width=80.0, height=120.0,
                     all_orientations=False, weight=10.0),
            make_box(box_id="G2", length=65.1, width=80.0, height=120.0,
                     all_orientations=False, weight=10.0),
        ]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), params)
        assert len(pallets) == 2

    def test_all_boxes_placed_despite_multiple_pallets(self):
        params = _params(pallet_length=130.0, pallet_width=80.0)
        boxes = [
            make_box(box_id=f"G{i}", length=65.1, width=80.0, height=60.0,
                     all_orientations=False, weight=5.0)
            for i in range(4)
        ]
        pallets = pack_boxes_ffd(sort_boxes_for_packing(boxes), params)
        placed = set(_all_box_ids(pallets))
        expected = {f"G{i}" for i in range(4)}
        assert placed == expected


# ── allow_multi_client ────────────────────────────────────────────────────────

class TestFFDMonoClientConstraint:
    def test_mono_client_no_mixing(self):
        # Two clients, each with one large box — must be on separate pallets
        params = _params(pallet_length=130.0, pallet_width=80.0)
        boxes = [
            make_box(box_id="C1_B1", client_id=927184,
                     length=65.0, width=80.0, height=60.0,
                     all_orientations=False, weight=5.0),
            make_box(box_id="C2_B1", client_id=943139,
                     length=65.0, width=80.0, height=60.0,
                     all_orientations=False, weight=5.0),
        ]
        pallets = pack_boxes_ffd(
            sort_boxes_for_packing(boxes), params,
            allow_multi_client=False,
        )
        for p in pallets:
            assert not p.is_multi_client

    def test_mono_client_same_client_can_share_pallet(self):
        params = _params(pallet_length=130.0, pallet_width=80.0)
        boxes = [
            make_box(box_id=f"C1_{i}", client_id=927184,
                     length=60.0, width=40.0, height=30.0, weight=5.0)
            for i in range(2)
        ]
        pallets = pack_boxes_ffd(
            sort_boxes_for_packing(boxes), params,
            allow_multi_client=False,
        )
        # Same client → allowed to share → one pallet
        assert len(pallets) == 1

    def test_multi_client_allowed_when_flag_true(self):
        params = _params(pallet_length=130.0, pallet_width=80.0)
        boxes = [
            make_box(box_id="C1", client_id=927184,
                     length=60.0, width=40.0, height=30.0, weight=5.0),
            make_box(box_id="C2", client_id=943139,
                     length=60.0, width=40.0, height=30.0, weight=5.0),
        ]
        pallets = pack_boxes_ffd(
            sort_boxes_for_packing(boxes), params,
            allow_multi_client=True,
        )
        # Both fit; multi-client allowed → should fit on one pallet
        assert len(pallets) == 1
        assert pallets[0].is_multi_client


# ── Real-world subset from tournee_type2026.csv ───────────────────────────────

class TestFFDRealWorldSubset:
    def test_first_four_client927184_boxes(self):
        """
        Pack the first 4 P1 boxes of client 927184.
        All should be placed; no box duplicated.
        """
        from models.orientation import Orientation
        from models.box import Box

        def _make(box_id, L, W, H, wt, orients):
            o = [Orientation[s] for s in orients]
            return Box(
                id=box_id, priority=1,
                length=L, width=W, height=H, weight=wt,
                client_id=927184,
                allowed_orientations=o,
                stackable={x: True for x in o},
            )

        boxes = [
            _make("927184009000101", 211.7, 62.3, 62.2, 72.1, ["HWL","WHL","HLW","LHW"]),
            _make("927184009000201", 211.7, 62.3, 62.2, 75.6, ["HWL","WHL","HLW","LHW"]),
            _make("927184009000701", 87.1, 62.3, 62.2, 36.3, ["HLW","LHW"]),
            _make("927184009000801", 87.1, 62.3, 62.2, 31.6, ["HLW","LHW"]),
        ]
        sorted_boxes = sort_boxes_for_packing(boxes)
        pallets = pack_boxes_ffd(sorted_boxes, _params())

        placed_ids = set(_all_box_ids(pallets))
        assert placed_ids == {b.id for b in boxes}

        # No box appears twice
        all_ids = _all_box_ids(pallets)
        assert len(all_ids) == len(set(all_ids))

    def test_mixed_p1_p2_client927184(self):
        """
        Mix of P1 and P2 boxes.  P2 ergonomic limit applies (z ≤ 160 cm).
        All boxes must be placed.
        """
        from models.orientation import Orientation, ALL_ORIENTATIONS
        from models.box import Box

        p1 = Box(
            id="P1", priority=1, length=87.1, width=62.3, height=62.2, weight=31.6,
            client_id=927184,
            allowed_orientations=[Orientation.HLW, Orientation.LHW],
            stackable={Orientation.HLW: True, Orientation.LHW: True},
        )
        p2_flat = Box(
            id="P2FLAT", priority=2, length=70.8, width=62.3, height=6.0, weight=3.7,
            client_id=927184,
            allowed_orientations=list(ALL_ORIENTATIONS),
            stackable={o: False for o in ALL_ORIENTATIONS},
        )
        sorted_boxes = sort_boxes_for_packing([p2_flat, p1])
        pallets = pack_boxes_ffd(sorted_boxes, _params())

        placed_ids = set(_all_box_ids(pallets))
        assert placed_ids == {"P1", "P2FLAT"}

    def test_ergonomic_height_limit_for_p2(self):
        """
        P2 box bottom may not exceed priority2_max_deposit_height (default 160 cm).
        The P2 box must be placed at z ≤ 160.
        """
        params = _params(priority2_max_deposit_height=160.0)
        from models.orientation import Orientation, ALL_ORIENTATIONS
        from models.box import Box

        p2 = Box(
            id="P2", priority=2, length=60.0, width=40.0, height=6.0, weight=2.0,
            client_id=1,
            allowed_orientations=list(ALL_ORIENTATIONS),
            stackable={o: False for o in ALL_ORIENTATIONS},
        )
        pallets = pack_boxes_ffd(sort_boxes_for_packing([p2]), params)
        assert len(pallets) == 1
        pb = pallets[0].boxes[0]
        assert pb.z <= 160.0

    def test_initial_pallets_used_first(self):
        """
        When initial_pallets is supplied, FFD fills them before opening new ones.
        """
        params = _params()
        existing = Pallet(
            id=1,
            length=params.pallet_length, width=params.pallet_width,
            max_height=params.pallet_max_height, max_weight=params.pallet_max_weight,
        )
        box = make_box(box_id="NEW", length=60.0, width=40.0, height=30.0, weight=5.0)
        pallets = pack_boxes_ffd(
            sort_boxes_for_packing([box]), params,
            initial_pallets=[existing],
        )
        # The existing pallet should have the box
        assert any(pb.box_id == "NEW" for pb in pallets[0].boxes)
