"""
Defines the 6 possible orientations for a 3D rectangular box.

A box originally has dimensions (L, W, H) — length, width, height.
When rotated, these three axes can be permuted, producing 6 distinct orientations.
Each orientation maps the original dimensions to new placed (length, width, height).

Coordinate system reminder:
    X axis → pallet length
    Y axis → pallet width
    Z axis → vertical (height)
"""

from enum import Enum
from typing import Tuple


class Orientation(Enum):
    """
    Enum representing the 6 possible box orientations.

    Naming convention: three letters show which original dimension
    maps to placed (length, width, height).

    Example:
        WLH → placed_length = original W
               placed_width  = original L
               placed_height = original H
    """
    LWH = "LWH"   # No rotation: placed (L, W, H)
    LHW = "LHW"   # 90° rotation around X-axis: placed (L, H, W)
    WLH = "WLH"   # 90° rotation around Z-axis: placed (W, L, H)
    WHL = "WHL"   # Combination: placed (W, H, L)
    HLW = "HLW"   # Combination: placed (H, L, W)
    HWL = "HWL"   # Combination: placed (H, W, L)


# Convenience list of all orientations
ALL_ORIENTATIONS: list = list(Orientation)


def get_oriented_dimensions(
    length: float,
    width: float,
    height: float,
    orientation: Orientation
) -> Tuple[float, float, float]:
    """
    Returns (placed_length, placed_width, placed_height) for the given orientation.

    Args:
        length:      Original box length (X dimension before rotation)
        width:       Original box width  (Y dimension before rotation)
        height:      Original box height (Z dimension before rotation)
        orientation: The target orientation to apply

    Returns:
        Tuple (placed_length, placed_width, placed_height)
    """
    mapping = {
        Orientation.LWH: (length, width,  height),
        Orientation.LHW: (length, height, width),
        Orientation.WLH: (width,  length, height),
        Orientation.WHL: (width,  height, length),
        Orientation.HLW: (height, length, width),
        Orientation.HWL: (height, width,  length),
    }
    return mapping[orientation]
