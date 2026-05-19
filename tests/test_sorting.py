"""
Unit tests for heuristics/sorting.py

Tests cover:
- sort_boxes_for_packing:
    * Priority ascending (P1 before P2)
    * Within same priority: volume descending
    * Within same priority and volume: weight descending
    * Original list not modified
    * Single / empty list
- sort_boxes_by_client:
    * Groups by client_id correctly
    * Each group is sorted by the packing heuristic
    * Clients not present in input are not created
"""

import pytest
from models.orientation import ALL_ORIENTATIONS, Orientation
from models.box import Box
from heuristics.sorting import sort_boxes_for_packing, sort_boxes_by_client
from tests.conftest import make_box


# ── sort_boxes_for_packing ────────────────────────────────────────────────────

class TestSortBoxesForPacking:
    def test_priority_ascending(self):
        b1 = make_box(box_id="P1A", priority=1, length=20.0, width=20.0, height=20.0)
        b2 = make_box(box_id="P2A", priority=2, length=20.0, width=20.0, height=20.0)
        result = sort_boxes_for_packing([b2, b1])
        assert result[0].priority == 1
        assert result[1].priority == 2

    def test_all_p1_before_all_p2(self):
        boxes = [
            make_box(box_id=f"P2_{i}", priority=2, length=60.0, width=40.0, height=30.0)
            for i in range(3)
        ] + [
            make_box(box_id=f"P1_{i}", priority=1, length=60.0, width=40.0, height=30.0)
            for i in range(3)
        ]
        result = sort_boxes_for_packing(boxes)
        priorities = [b.priority for b in result]
        p1_indices = [i for i, p in enumerate(priorities) if p == 1]
        p2_indices = [i for i, p in enumerate(priorities) if p == 2]
        assert max(p1_indices) < min(p2_indices)

    def test_within_p1_volume_descending(self):
        # Three P1 boxes with different volumes
        small  = make_box(box_id="S", priority=1, length=30.0, width=20.0, height=10.0)  # 6000
        medium = make_box(box_id="M", priority=1, length=60.0, width=40.0, height=30.0)  # 72000
        large  = make_box(box_id="L", priority=1, length=87.1, width=62.3, height=62.2) # ~338k
        result = sort_boxes_for_packing([small, medium, large])
        assert result[0].id == "L"
        assert result[1].id == "M"
        assert result[2].id == "S"

    def test_within_same_volume_weight_descending(self):
        # Same dimensions → same volume; differ in weight
        light  = make_box(box_id="LIGHT",  priority=1,
                          length=60.0, width=40.0, height=30.0, weight=5.0)
        heavy  = make_box(box_id="HEAVY",  priority=1,
                          length=60.0, width=40.0, height=30.0, weight=50.0)
        medium = make_box(box_id="MEDIUM", priority=1,
                          length=60.0, width=40.0, height=30.0, weight=25.0)
        result = sort_boxes_for_packing([light, medium, heavy])
        assert result[0].id == "HEAVY"
        assert result[1].id == "MEDIUM"
        assert result[2].id == "LIGHT"

    def test_original_list_not_modified(self):
        boxes = [
            make_box(box_id="B1", priority=2, length=60.0, width=40.0, height=30.0),
            make_box(box_id="B2", priority=1, length=60.0, width=40.0, height=30.0),
        ]
        original_ids = [b.id for b in boxes]
        sort_boxes_for_packing(boxes)
        assert [b.id for b in boxes] == original_ids

    def test_empty_list(self):
        assert sort_boxes_for_packing([]) == []

    def test_single_box_returned(self):
        b = make_box()
        result = sort_boxes_for_packing([b])
        assert len(result) == 1
        assert result[0] is b

    def test_real_data_from_tournee_type2026(self):
        """
        Subset of tournee_type2026.csv — 3 P1 and 3 P2 boxes.
        Verify P1 first and largest P1 at front.
        """
        # P1 boxes (volume order: 211.7×62.3×62.2 > 122.3×70.8×38.7 > 87.1×62.3×62.2)
        p1_large  = make_box(box_id="P1L",  priority=1,
                             length=211.7, width=62.3, height=62.2, weight=72.1)
        p1_medium = make_box(box_id="P1M",  priority=1,
                             length=122.3, width=70.8, height=38.7, weight=45.8)
        p1_small  = make_box(box_id="P1S",  priority=1,
                             length=87.1,  width=62.3, height=62.2, weight=31.6)
        # P2 boxes (all smaller volume)
        p2_a = make_box(box_id="P2A", priority=2,
                        length=70.8, width=62.3, height=6.0, weight=3.7)
        p2_b = make_box(box_id="P2B", priority=2,
                        length=62.3, width=15.6, height=6.0, weight=0.9)
        p2_c = make_box(box_id="P2C", priority=2,
                        length=65.0, width=47.5, height=3.2, weight=7.4)

        result = sort_boxes_for_packing([p2_a, p1_small, p2_b, p1_large, p2_c, p1_medium])

        # All P1 before P2
        p1_result = [b for b in result if b.priority == 1]
        p2_result = [b for b in result if b.priority == 2]
        assert len(p1_result) == 3
        assert len(p2_result) == 3
        assert result.index(p1_result[-1]) < result.index(p2_result[0])

        # Largest P1 first
        assert result[0].id == "P1L"

    def test_complex_priority_volume_weight_ordering(self):
        """
        Mixed scenario: P2 box heavier and larger than some P1 boxes.
        P1 must still come first.
        """
        p1_tiny  = make_box(box_id="P1tiny",  priority=1,
                             length=10.0, width=5.0, height=5.0, weight=1.0)
        p2_huge  = make_box(box_id="P2huge",  priority=2,
                             length=100.0, width=80.0, height=50.0, weight=200.0)
        result = sort_boxes_for_packing([p2_huge, p1_tiny])
        assert result[0].id == "P1tiny"
        assert result[1].id == "P2huge"


# ── sort_boxes_by_client ──────────────────────────────────────────────────────

class TestSortBoxesByClient:
    def test_single_client_returns_one_key(self):
        boxes = [
            make_box(box_id="A", client_id=927184),
            make_box(box_id="B", client_id=927184),
        ]
        result = sort_boxes_by_client(boxes)
        assert list(result.keys()) == [927184]

    def test_two_clients_returns_two_keys(self):
        boxes = [
            make_box(box_id="A", client_id=927184),
            make_box(box_id="B", client_id=943139),
        ]
        result = sort_boxes_by_client(boxes)
        assert set(result.keys()) == {927184, 943139}

    def test_each_group_contains_only_its_client(self):
        boxes = [
            make_box(box_id="A1", client_id=927184),
            make_box(box_id="B1", client_id=943139),
            make_box(box_id="A2", client_id=927184),
            make_box(box_id="B2", client_id=943139),
        ]
        result = sort_boxes_by_client(boxes)
        for box in result[927184]:
            assert box.client_id == 927184
        for box in result[943139]:
            assert box.client_id == 943139

    def test_each_group_is_sorted_by_packing_heuristic(self):
        # Client 927184 has one P2 and two P1 boxes of different sizes
        p1_large = make_box(box_id="L", priority=1, client_id=927184,
                             length=211.7, width=62.3, height=62.2, weight=72.1)
        p1_small = make_box(box_id="S", priority=1, client_id=927184,
                             length=87.1,  width=62.3, height=62.2, weight=31.6)
        p2_flat  = make_box(box_id="F", priority=2, client_id=927184,
                             length=70.8,  width=62.3, height=6.0,  weight=3.7)
        result = sort_boxes_by_client([p2_flat, p1_small, p1_large])
        group = result[927184]
        assert group[0].id == "L"   # largest P1 first
        assert group[1].id == "S"
        assert group[2].id == "F"   # P2 last

    def test_box_count_preserved(self):
        boxes = [make_box(box_id=str(i), client_id=i % 3) for i in range(9)]
        result = sort_boxes_by_client(boxes)
        total = sum(len(v) for v in result.values())
        assert total == 9

    def test_empty_input_returns_empty_dict(self):
        assert sort_boxes_by_client([]) == {}

    def test_three_clients_from_tournee_type2026(self):
        """
        Clients 927184, 931475, 943139 — each with one box.
        """
        b1 = make_box(box_id="927184", client_id=927184, priority=1,
                       length=211.7, width=62.3, height=62.2, weight=72.1)
        b2 = make_box(box_id="931475", client_id=931475, priority=1,
                       length=82.3,  width=43.2, height=38.2, weight=19.2)
        b3 = make_box(box_id="943139", client_id=943139, priority=1,
                       length=197.9, width=62.3, height=62.2, weight=69.3)
        result = sort_boxes_by_client([b1, b2, b3])
        assert set(result.keys()) == {927184, 931475, 943139}
        assert len(result[927184]) == 1
        assert len(result[931475]) == 1
        assert len(result[943139]) == 1
