"""
Box data model.

A Box represents an unplaced item with its physical properties and
packing constraints (which orientations are allowed, which surfaces
can bear weight above them).
"""

from dataclasses import dataclass, field
from typing import List, Dict

from models.orientation import Orientation, get_oriented_dimensions, ALL_ORIENTATIONS


@dataclass
class Box:
    """
    Represents an unplaced rectangular box to be packed onto a pallet.

    Attributes:
        id:                   Unique identifier for this box
        priority:             Stacking priority (1 = must go low, 2 = can go higher)
        length:               Original length along X (before any rotation), cm
        width:                Original width along Y  (before any rotation), cm
        height:               Original height along Z (before any rotation), cm
        weight:               Box weight, kg
        client_id:            Client this box belongs to (used for mono-client strategy)
        allowed_orientations: List of orientations this box may be placed in
        stackable:            Per-orientation flag — True means OTHER boxes may be
                              placed ON TOP of this box when in that orientation
    """

    id: str
    priority: int
    length: float
    width: float
    height: float
    weight: float
    client_id: int
    allowed_orientations: List[Orientation] = field(
        default_factory=lambda: list(ALL_ORIENTATIONS)
    )
    stackable: Dict[Orientation, bool] = field(
        default_factory=lambda: {o: True for o in ALL_ORIENTATIONS}
    )
    designation: str = ""
    location: str = ""

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def volume(self) -> float:
        """Returns the box volume (same in any orientation)."""
        return self.length * self.width * self.height

    def get_oriented_dims(self, orientation: Orientation):
        """
        Shortcut: returns (placed_length, placed_width, placed_height)
        for the specified orientation.
        """
        return get_oriented_dimensions(
            self.length, self.width, self.height, orientation
        )

    def is_stackable_in(self, orientation: Orientation) -> bool:
        """
        Returns True if OTHER boxes may be stacked on top of this box
        when it is placed in the given orientation.
        """
        return self.stackable.get(orientation, False)

    def __repr__(self) -> str:
        return (
            f"Box(id={self.id!r}, priority={self.priority}, "
            f"dims={self.length}×{self.width}×{self.height}, "
            f"weight={self.weight}kg, client={self.client_id})"
        )
