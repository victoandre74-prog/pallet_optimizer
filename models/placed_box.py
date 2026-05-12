"""
PlacedBox data model.

A PlacedBox is the result of committing a Box to a specific position
and orientation inside a pallet.  It carries all geometry and metadata
needed for constraint checking, so the original Box registry does not
need to be consulted repeatedly.
"""

from dataclasses import dataclass, field

from models.orientation import Orientation


@dataclass
class PlacedBox:
    """
    A box that has been positioned inside a pallet.

    Coordinates (x, y, z) are the bottom-left-back corner of the box,
    matching the pallet coordinate system where (0,0,0) is the
    bottom-left-back corner of the pallet.

    Attributes:
        box_id:     Reference to the original Box.id
        x, y, z:   Bottom-left-back corner position (cm)
        orientation: The orientation the box was placed in
        length:     Placed dimension along X (already rotated), cm
        width:      Placed dimension along Y (already rotated), cm
        height:     Placed dimension along Z (already rotated), cm
        priority:   Copied from Box for fast stacking-rule checks
        weight:     Box weight, kg
        client_id:  Client ownership (used for coloring and statistics)
        stackable:  Whether OTHER boxes may be placed on top of this
                    placed box in its current orientation
    """

    box_id: str
    x: float
    y: float
    z: float
    orientation: Orientation

    # Pre-computed oriented dimensions (avoid repeated lookups)
    length: float
    width: float
    height: float

    # Metadata copied from Box for fast access
    priority: int
    weight: float
    client_id: int
    stackable: bool   # True → surface can bear boxes above it

    designation: str = ""
    location: str = ""

    # Placement order (1-based) within the pallet — set after packing
    sequence: int = 0

    # Pre-computed max coordinates — set once at creation, never mutated.
    # PlacedBox is always created via make_placed_box(); x/y/z are never
    # reassigned after construction, so these stay consistent.
    x_max: float = field(init=False)
    y_max: float = field(init=False)
    z_max: float = field(init=False)

    def __post_init__(self):
        self.x_max = self.x + self.length
        self.y_max = self.y + self.width
        self.z_max = self.z + self.height

    # ── Geometry helpers ───────────────────────────────────────────────────────

    @property
    def base_area(self) -> float:
        """XY footprint area of this box."""
        return self.length * self.width

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    def bounds(self):
        """
        Returns axis-aligned bounding box as:
        (x_min, x_max, y_min, y_max, z_min, z_max)
        """
        return (
            self.x, self.x_max,
            self.y, self.y_max,
            self.z, self.z_max,
        )

    def __repr__(self) -> str:
        return (
            f"PlacedBox(id={self.box_id!r}, "
            f"pos=({self.x},{self.y},{self.z}), "
            f"dims={self.length}×{self.width}×{self.height}, "
            f"orient={self.orientation.value})"
        )
