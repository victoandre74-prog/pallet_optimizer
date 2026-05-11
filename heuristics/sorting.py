"""
Box sorting heuristics.

The specification requires sorting boxes by:
    1. Priority     ascending   (priority 1 must be placed before priority 2)
    2. Volume       descending  (large boxes first — they are harder to fit)
    3. Weight       descending  (heavy boxes should go low)

Placing all P1 boxes first ensures priority constraints are always respected.
Within each priority group, large heavy boxes are handled first when pallets
are still empty and offer the most freedom.
"""

from typing import List

from models.box import Box


def sort_boxes_for_packing(boxes: List[Box]) -> List[Box]:
    """
    Returns a new list of boxes sorted according to the packing heuristic:
        primary key:   priority (ascending — P1 before P2)
        secondary key: volume   (descending)
        tertiary key:  weight   (descending)

    The original list is not modified.
    """
    return sorted(
        boxes,
        key=lambda b: (b.priority, -b.volume, -b.weight)
    )


def sort_boxes_by_client(boxes: List[Box]) -> dict:
    """
    Groups and sorts boxes by client_id.

    Returns a dict:  {client_id: [sorted Box, ...]}

    Each client's list is sorted by the packing heuristic.
    This is used in Phase 1 (mono-client packing).
    """
    groups: dict = {}
    for box in boxes:
        groups.setdefault(box.client_id, []).append(box)

    # Sort within each group
    return {
        cid: sort_boxes_for_packing(group)
        for cid, group in groups.items()
    }
