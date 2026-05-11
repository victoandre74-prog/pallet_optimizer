"""
3-D pallet visualization using Plotly.

Each box is rendered as a solid 3-D cuboid built from 12 triangles
(two per face).  A separate Scatter3d trace draws the box edges.

Color rules (from spec):
    Multi-client pallet → boxes colored by client_id
    Mono-client pallet  → all boxes share one base color

Edge thickness rules (from spec):
    Priority 1 → thick black edges  (line width 3)
    Priority 2 → thick white edges  (line width 3)
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from typing import List, Optional

# ── Color palettes ─────────────────────────────────────────────────────────────

# Single color for mono-client pallets
MONO_CLIENT_COLOR = "rgba(100, 149, 237, 0.75)"   # cornflower blue

# Pallet floor color
PALLET_FLOOR_COLOR = "rgba(200, 180, 140, 0.4)"

# 24-color explicit palette — covers the full spectrum in three brightness tiers.
# Colors are assigned by sorted rank so arbitrary client IDs never collide.
_PALETTE_RGB = [
    # Tier 1 — vivid, mid-light
    (220,  50,  50),   # red
    (255, 140,   0),   # orange
    (220, 200,   0),   # yellow
    ( 50, 190,  50),   # green
    (  0, 175, 175),   # teal
    ( 50, 100, 220),   # blue
    (140,  50, 220),   # purple
    (220,  50, 175),   # pink
    # Tier 2 — darker / deeper
    (170,  25,  25),   # dark red
    (200,  95,   0),   # burnt orange
    (155, 135,   0),   # olive
    ( 25, 135,  25),   # dark green
    (  0, 115, 135),   # dark teal
    ( 25,  55, 175),   # dark blue
    ( 95,  15, 175),   # dark purple
    (175,  15, 135),   # dark pink
    # Tier 3 — lighter / pastel
    (255, 130, 130),   # light red
    (255, 195, 110),   # light orange
    (255, 242, 110),   # light yellow
    (130, 225, 130),   # light green
    (110, 220, 220),   # light teal
    (130, 165, 255),   # light blue
    (195, 135, 255),   # light purple
    (255, 140, 220),   # light pink
]


def build_client_color_map(client_ids, alpha: float = 0.75) -> dict:
    """
    Returns a dict mapping each client_id to a unique RGBA color string.

    Colors are assigned by sorted rank of client_id, so the mapping is
    stable and independent of the actual ID values.
    """
    sorted_ids = sorted(set(int(c) for c in client_ids))
    return {
        cid: "rgba({}, {}, {}, {})".format(*_PALETTE_RGB[i % len(_PALETTE_RGB)], alpha)
        for i, cid in enumerate(sorted_ids)
    }


# ── Box geometry ───────────────────────────────────────────────────────────────

def _box_vertices(x: float, y: float, z: float,
                  l: float, w: float, h: float):
    """
    Returns the 8 vertices of an axis-aligned cuboid.
    Vertex numbering:
        0 = (x,   y,   z  )   bottom-left-back
        1 = (x+l, y,   z  )   bottom-right-back
        2 = (x+l, y+w, z  )   bottom-right-front
        3 = (x,   y+w, z  )   bottom-left-front
        4 = (x,   y,   z+h)   top-left-back
        5 = (x+l, y,   z+h)   top-right-back
        6 = (x+l, y+w, z+h)   top-right-front
        7 = (x,   y+w, z+h)   top-left-front
    """
    vx = [x,   x+l, x+l, x,   x,   x+l, x+l, x  ]
    vy = [y,   y,   y+w, y+w, y,   y,   y+w, y+w]
    vz = [z,   z,   z,   z,   z+h, z+h, z+h, z+h]
    return vx, vy, vz


def create_box_mesh(
    row: pd.Series,
    color: str,
    name: str = ""
) -> go.Mesh3d:
    """
    Creates a Plotly Mesh3d trace for one box (filled solid faces).

    Args:
        row:   A DataFrame row with columns x, y, z, length, width, height.
        color: RGBA fill color string.
        name:  Hover label for the box.

    Returns:
        A go.Mesh3d trace.
    """
    vx, vy, vz = _box_vertices(
        row["x"], row["y"], row["z"],
        row["length"], row["width"], row["height"]
    )

    # 12 triangular faces (2 per cuboid face)
    # Each face defined by 3 vertex indices
    i = [0, 0, 1, 1, 0, 0, 2, 2, 0, 0, 3, 3]
    j = [1, 2, 2, 5, 4, 5, 3, 6, 3, 7, 7, 6]
    k = [2, 3, 5, 6, 5, 1, 6, 7, 7, 4, 4, 2]

    # Correct triangulation for all 6 faces:
    # Bottom (z): 0-1-2, 0-2-3
    # Top    (z): 4-5-6, 4-6-7
    # Front  (y): 0-1-5, 0-5-4
    # Back   (y): 2-3-7, 2-7-6
    # Right  (x): 1-2-6, 1-6-5
    # Left   (x): 0-3-7, 0-7-4
    i = [0, 0,  4, 4,  0, 0,  2, 2,  1, 1,  0, 0]
    j = [1, 2,  5, 6,  1, 5,  3, 7,  2, 6,  3, 7]
    k = [2, 3,  6, 7,  5, 4,  7, 6,  6, 5,  7, 4]

    return go.Mesh3d(
        x=vx, y=vy, z=vz,
        i=i, j=j, k=k,
        color=color,
        opacity=0.75,
        flatshading=True,
        hovertext=name,
        hoverinfo="text",
        showlegend=False,
        lighting=dict(ambient=0.6, diffuse=0.8, roughness=0.5),
    )


def create_box_edges(
    row: pd.Series,
    priority: int,
    highlight: bool = False,
) -> go.Scatter3d:
    """
    Creates a Plotly Scatter3d trace drawing the 12 edges of a box.

    Edge line width and color reflect priority (or highlight state):
        highlighted → bright-yellow edges, width 6
        Priority 1  → thick black edges, width 3
        Priority 2  → thick white edges, width 3
    """
    x0, y0, z0 = row["x"], row["y"], row["z"]
    l, w, h = row["length"], row["width"], row["height"]

    # Define the 12 edges of the cuboid as pairs of corners.
    # None values create line breaks (separate segments in one trace).
    edges_x, edges_y, edges_z = [], [], []

    def _add_edge(p1, p2):
        edges_x.extend([p1[0], p2[0], None])
        edges_y.extend([p1[1], p2[1], None])
        edges_z.extend([p1[2], p2[2], None])

    corners = [
        (x0,   y0,   z0),   # 0
        (x0+l, y0,   z0),   # 1
        (x0+l, y0+w, z0),   # 2
        (x0,   y0+w, z0),   # 3
        (x0,   y0,   z0+h), # 4
        (x0+l, y0,   z0+h), # 5
        (x0+l, y0+w, z0+h), # 6
        (x0,   y0+w, z0+h), # 7
    ]

    # Bottom face
    _add_edge(corners[0], corners[1])
    _add_edge(corners[1], corners[2])
    _add_edge(corners[2], corners[3])
    _add_edge(corners[3], corners[0])
    # Top face
    _add_edge(corners[4], corners[5])
    _add_edge(corners[5], corners[6])
    _add_edge(corners[6], corners[7])
    _add_edge(corners[7], corners[4])
    # Vertical edges
    _add_edge(corners[0], corners[4])
    _add_edge(corners[1], corners[5])
    _add_edge(corners[2], corners[6])
    _add_edge(corners[3], corners[7])

    if highlight:
        line_width, line_color = 6, "yellow"
    else:
        line_width = 3
        line_color = "black" if priority == 1 else "white"

    return go.Scatter3d(
        x=edges_x, y=edges_y, z=edges_z,
        mode="lines",
        line=dict(color=line_color, width=line_width),
        hoverinfo="none",
        showlegend=False,
    )


def _create_pallet_floor(pallet_length: float, pallet_width: float) -> go.Mesh3d:
    """Creates a flat semi-transparent rectangle representing the pallet floor."""
    return go.Mesh3d(
        x=[0, pallet_length, pallet_length, 0],
        y=[0, 0, pallet_width, pallet_width],
        z=[0, 0, 0, 0],
        i=[0], j=[1], k=[2],
        color=PALLET_FLOOR_COLOR,
        opacity=0.4,
        hoverinfo="none",
        showlegend=False,
        flatshading=True,
    )


# ── Pallet renderer ────────────────────────────────────────────────────────────

def render_pallet(df_pallet: pd.DataFrame, color_map: dict = None,
                  highlight_seq: int = None) -> go.Figure:
    """
    Creates a complete Plotly 3-D figure for one pallet.

    Args:
        df_pallet:     DataFrame for a single pallet_id.
        color_map:     Optional dict mapping client_id (int) → RGBA color string.
        highlight_seq: If set, the box whose sequence equals this value is
                       rendered in solid black with bright-yellow edges.

    Returns:
        A Plotly Figure with all box meshes, edges, and the pallet floor.
    """
    if df_pallet.empty:
        return go.Figure()

    pallet_length = float(df_pallet["pallet_length"].iloc[0])
    pallet_width  = float(df_pallet["pallet_width"].iloc[0])
    pallet_height = float(df_pallet["pallet_height"].iloc[0])

    if color_map is None:
        color_map = build_client_color_map(df_pallet["client_id"].unique())

    traces = []

    # Pallet floor
    traces.append(_create_pallet_floor(pallet_length, pallet_width))

    # One mesh + one edge trace per box
    for _, row in df_pallet.iterrows():
        seq       = int(row["sequence"]) if "sequence" in row.index else 0
        is_hi     = (highlight_seq is not None and seq == highlight_seq)
        color     = "rgba(0, 0, 0, 0.92)" if is_hi else color_map.get(int(row["client_id"]), MONO_CLIENT_COLOR)

        label = (
            f"#{seq} — Box: {row['box_id']}<br>"
            f"Client: {row['client_id']}<br>"
            f"Priority: {row['priority']}<br>"
            f"Dims: {row['length']}×{row['width']}×{row['height']} cm<br>"
            f"Weight: {row['weight']} kg<br>"
            f"Pos: ({row['x']}, {row['y']}, {row['z']})"
        )

        traces.append(create_box_mesh(row, color, name=label))
        traces.append(create_box_edges(row, priority=int(row["priority"]), highlight=is_hi))

    fig = go.Figure(data=traces)

    _axis_common = dict(
        tickfont=dict(size=10, color="#222", family="Arial Black"),
        title_font=dict(size=10, family="Arial Black"),
        ticklen=8,
        tickcolor="#444",
    )

    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X (cm)", range=[0, pallet_length], **_axis_common),
            yaxis=dict(title="Y (cm)", range=[0, pallet_width],  **_axis_common),
            zaxis=dict(title="Z (cm)", range=[0, pallet_height], **_axis_common),
            aspectmode="manual",
            aspectratio=dict(
                x=pallet_length / pallet_height,
                y=pallet_width  / pallet_height,
                z=1.0,
            ),
            bgcolor="rgb(240, 240, 245)",
        ),
        margin=dict(l=20, r=20, t=30, b=20),
        paper_bgcolor="white",
        uirevision="pallet",   # preserves camera angle on data updates
    )

    return fig
