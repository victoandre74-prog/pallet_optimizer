"""
Shared pytest fixtures for the pallet_optimizer test suite.

Test data is derived from real-world delivery routes
(input/tournee_type2026/tournee_type2026.csv) combined with minimal
synthetic cases designed to exercise specific constraints.

Pallet reference: 130 × 80 × 227 cm, 600 kg  (default OptimizationParameters)
"""

import sys
import os

# Add the pallet_optimizer package directory to sys.path so tests can import
# models, core, config, heuristics, utils directly.
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import pytest

from models.orientation import Orientation, ALL_ORIENTATIONS
from models.box import Box
from models.placed_box import PlacedBox
from models.pallet import Pallet
from config.parameters import OptimizationParameters


# ── Parameters ────────────────────────────────────────────────────────────────

@pytest.fixture
def params() -> OptimizationParameters:
    """Default optimization parameters (130×80×226 cm, 600 kg)."""
    return OptimizationParameters()


# ── Pallet ────────────────────────────────────────────────────────────────────

@pytest.fixture
def empty_pallet(params: OptimizationParameters) -> Pallet:
    """Standard empty pallet with default dimensions."""
    return Pallet(
        id=1,
        length=params.pallet_length,
        width=params.pallet_width,
        max_height=params.pallet_max_height,
        max_weight=params.pallet_max_weight,
    )


# ── Boxes — real data from input/tournee_type2026/tournee_type2026.csv ─────────

@pytest.fixture
def box_large_p1() -> Box:
    """
    927184009000101 — Large priority-1 box (client 927184).
    Dims: 211.7 × 62.3 × 62.2 cm, 72.1 kg
    Orientations: HWL, WHL, HLW, LHW
    Stackable: True
    """
    orients = [Orientation.HWL, Orientation.WHL, Orientation.HLW, Orientation.LHW]
    return Box(
        id="927184009000101",
        priority=1,
        length=211.7,
        width=62.3,
        height=62.2,
        weight=72.1,
        client_id=927184,
        allowed_orientations=orients,
        stackable={o: True for o in orients},
    )


@pytest.fixture
def box_flat_p2() -> Box:
    """
    927184009000601 — Flat priority-2 (hand-deposited) box (client 927184).
    Dims: 70.8 × 62.3 × 6.0 cm, 3.7 kg
    Orientations: all 6
    Stackable: False — nothing may be placed on top.
    """
    orients = list(ALL_ORIENTATIONS)
    return Box(
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


@pytest.fixture
def box_medium_p1() -> Box:
    """
    927184009000801 — Medium priority-1 box (client 927184).
    Dims: 87.1 × 62.3 × 62.2 cm, 31.6 kg
    Orientations: HLW, LHW
    Stackable: True
    """
    orients = [Orientation.HLW, Orientation.LHW]
    return Box(
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


@pytest.fixture
def box_small_p2() -> Box:
    """
    927184009002101 — Small priority-2 box (client 927184).
    Dims: 62.3 × 15.6 × 6.0 cm, 0.9 kg
    Orientations: all 6
    Stackable: False
    """
    orients = list(ALL_ORIENTATIONS)
    return Box(
        id="927184009002101",
        priority=2,
        length=62.3,
        width=15.6,
        height=6.0,
        weight=0.9,
        client_id=927184,
        allowed_orientations=orients,
        stackable={o: False for o in orients},
    )


@pytest.fixture
def box_square_p1() -> Box:
    """
    927184009001601 — Half-height priority-1 box (client 927184).
    Dims: 87.1 × 62.2 × 32.3 cm, 28.3 kg
    Orientations: WLH, LWH
    Stackable: True
    """
    orients = [Orientation.WLH, Orientation.LWH]
    return Box(
        id="927184009001601",
        priority=1,
        length=87.1,
        width=62.2,
        height=32.3,
        weight=28.3,
        client_id=927184,
        allowed_orientations=orients,
        stackable={o: True for o in orients},
    )


@pytest.fixture
def box_xlarge_p1() -> Box:
    """
    943139009001001 — Extra-large priority-1 box (client 943139).
    Dims: 197.9 × 62.3 × 62.2 cm, 69.3 kg
    Orientations: HWL, WHL, HLW, LHW
    Stackable: True
    """
    orients = [Orientation.HWL, Orientation.WHL, Orientation.HLW, Orientation.LHW]
    return Box(
        id="943139009001001",
        priority=1,
        length=197.9,
        width=62.3,
        height=62.2,
        weight=69.3,
        client_id=943139,
        allowed_orientations=orients,
        stackable={o: True for o in orients},
    )


# ── Synthetic factory helpers (importable, not fixtures) ─────────────────────

def make_box(
    box_id: str = "BOX001",
    priority: int = 1,
    length: float = 60.0,
    width: float = 40.0,
    height: float = 30.0,
    weight: float = 10.0,
    client_id: int = 1001,
    all_orientations: bool = True,
    stackable: bool = True,
) -> Box:
    """
    Factory for synthetic test boxes.
    By default creates a box that accepts all 6 orientations.
    """
    orients = list(ALL_ORIENTATIONS) if all_orientations else [Orientation.LWH]
    return Box(
        id=box_id,
        priority=priority,
        length=length,
        width=width,
        height=height,
        weight=weight,
        client_id=client_id,
        allowed_orientations=orients,
        stackable={o: stackable for o in orients},
    )


def make_placed_box(
    box_id: str = "PB001",
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    orientation: Orientation = Orientation.LWH,
    length: float = 60.0,
    width: float = 40.0,
    height: float = 30.0,
    priority: int = 1,
    weight: float = 10.0,
    client_id: int = 1001,
    stackable: bool = True,
) -> PlacedBox:
    """Factory for synthetic placed boxes at an explicit position."""
    return PlacedBox(
        box_id=box_id,
        x=x,
        y=y,
        z=z,
        orientation=orientation,
        length=length,
        width=width,
        height=height,
        priority=priority,
        weight=weight,
        client_id=client_id,
        stackable=stackable,
    )
