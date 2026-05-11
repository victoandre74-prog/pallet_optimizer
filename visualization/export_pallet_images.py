"""
Pallet 3-D Image Exporter
=========================

Renders each pallet from a palletization result CSV as a PNG file and
saves them into an output folder.

Les images produites reproduisent fidèlement la "Vue Zoom" du dashboard :
    - Couleurs cohérentes : palette client construite une seule fois sur
      l'ensemble des clients du CSV (un client garde la même couleur sur
      toutes les palettes, comme dans le dashboard).
    - Contours : noirs pour P1, blancs pour P2.
    - Panneau de droite : liste des colis P2 de la palette
      (colonnes Emplacement / Désignation / ID) — identique au tableau
      "Colis P2" de la zoom view.
    - Mode --per-sequence : le colis posé à l'étape courante est mis en
      évidence (jaune sur le graphe + surlignage dans le tableau P2 si
      c'est un P2) et un libellé "#N · P? · Client X · …" apparaît sous
      le graphe.

Usage:
    # One image per pallet (default):
    python export_pallet_images.py <results.csv> [output_folder]

    # One image per sequence step per pallet:
    python export_pallet_images.py <results.csv> [output_folder] --per-sequence

Requirements:
    pip install kaleido   (Plotly static image export backend)
"""

import argparse
import sys
import os

# ── Path setup ─────────────────────────────────────────────────────────────────
_DIR  = os.path.dirname(os.path.abspath(__file__))   # .../visualization/
_ROOT = os.path.dirname(_DIR)                          # .../pallet_optimizer/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import plotly.graph_objects as go

from visualization.pallet_dashboard import load_pallet_data
from visualization.pallet_visualizer import render_pallet, build_client_color_map


# ── Layout constants ───────────────────────────────────────────────────────────

_SCENE_X = (0.00, 0.357)  # 3-D scene domain (paper-relative) — width −36% total
_SCENE_Y = (0.04, 0.92)   # 3-D scene vertical range — height +10%
_TABLE_X = (0.38, 1.00)   # P2 table domain (shifted left to use freed space)
_TABLE_Y = (0.08, 0.88)   # P2 table vertical range
_SCENE_CX = (_SCENE_X[0] + _SCENE_X[1]) / 2   # horizontal center of 3-D scene
_HIGHLIGHT_BG = "#ffc107" # Yellow highlight for active P2 row (matches dashboard)
_ACCENT      = "#e67e22"  # Orange accent for "Colis P2" title + ID column

_LEGEND_TEXT = (
    "Contour noir = Priorité 1 (Meubles)   │   "
    "Contour blanc = Priorité 2 (Colis)"
)


# ── Layout helpers ─────────────────────────────────────────────────────────────

def _add_p2_table(fig: go.Figure, df_p: pd.DataFrame,
                  highlight_seq: int = None) -> None:
    """Adds a go.Table trace to fig showing every P2 box of the pallet.
    Columns: Casier, Désignation (tronquée à 20 car.), ID, Dimensions, Poids.
    Reproduit le tableau "Colis P2" de la zoom view du dashboard."""
    df_p2 = df_p[df_p["priority"] == 2].copy()
    if "sequence" in df_p2.columns:
        df_p2 = df_p2.sort_values("sequence")

    # Title above the table
    fig.add_annotation(
        x=_TABLE_X[0] + 0.005, y=_TABLE_Y[1] + 0.06,
        xref="paper", yref="paper",
        text="<b>Colis P2</b>",
        showarrow=False, font=dict(size=20, color=_ACCENT),
        align="left", xanchor="left",
    )

    if df_p2.empty:
        fig.add_annotation(
            x=(_TABLE_X[0] + _TABLE_X[1]) / 2,
            y=(_TABLE_Y[0] + _TABLE_Y[1]) / 2,
            xref="paper", yref="paper",
            text="Aucun colis P2 sur cette palette.",
            showarrow=False, font=dict(size=14, color="#aaa"),
            align="center", xanchor="center",
        )
        return

    has_loc = "location"    in df_p2.columns
    has_des = "designation" in df_p2.columns

    locs, dess, ids, dims, wgts, row_bg = [], [], [], [], [], []
    for i, (_, row) in enumerate(df_p2.iterrows()):
        seq       = int(row["sequence"]) if "sequence" in df_p2.columns else 0
        is_active = (highlight_seq is not None and seq == highlight_seq)

        loc      = str(row["location"])    if has_loc and pd.notna(row["location"])    else ""
        des_full = str(row["designation"]) if has_des and pd.notna(row["designation"]) else ""
        des      = des_full[:20] + ("…" if len(des_full) > 20 else "")

        locs.append(loc)
        dess.append(des)
        ids.append(str(row["box_id"]))
        dims.append(f"{row['length']}×{row['width']}×{row['height']}")
        wgts.append(f"{row['weight']} kg")

        if is_active:
            row_bg.append(_HIGHLIGHT_BG)
        else:
            row_bg.append("white" if i % 2 == 0 else "#fafafa")

    fig.add_trace(go.Table(
        domain=dict(x=list(_TABLE_X), y=list(_TABLE_Y)),
        columnwidth=[70, 220, 130, 170, 90],
        header=dict(
            values=["<b>Casier</b>", "<b>Désignation</b>", "<b>ID</b>",
                    "<b>Dimensions</b>", "<b>Poids</b>"],
            fill_color="#fafafa",
            line_color="#ddd",
            align="left",
            font=dict(size=20, color="#888"),
            height=50,
        ),
        cells=dict(
            values=[locs, dess, ids, dims, wgts],
            fill_color=[row_bg, row_bg, row_bg, row_bg, row_bg],
            line_color="#eee",
            align="left",
            font=dict(size=21, color=["#222", "#222", _ACCENT, "#222", "#222"]),
            height=42,
        ),
    ))


def _apply_layout(fig: go.Figure, pallet_label: str, df_p: pd.DataFrame,
                  highlight_seq: int = None, box_label: str = "",
                  source_label: str = "") -> None:
    """Compose the image: title + 3D scene on the left + P2 table on the right
    + legend & box-label at the bottom."""
    fig.update_layout(
        width=1600,
        height=900,
        margin=dict(l=40, r=40, t=90, b=70),
        scene=dict(domain=dict(x=list(_SCENE_X), y=list(_SCENE_Y))),
        title=dict(text=pallet_label, x=0.5, y=0.955, font=dict(size=22)),
        paper_bgcolor="white",
    )

    # Source-file subtitle (under "Palette xx — Client xx")
    if source_label:
        fig.add_annotation(
            x=0.5, y=0.995, xref="paper", yref="paper",
            text=f"<span style='color:#888'>{source_label}</span>",
            showarrow=False, font=dict(size=14),
            align="center", xanchor="center",
        )

    _add_p2_table(fig, df_p, highlight_seq=highlight_seq)

    # Bottom legend (contour noir / contour blanc)
    fig.add_annotation(
        x=_SCENE_CX, y=0.04, xref="paper", yref="paper",
        text=f"<span style='color:#666'>{_LEGEND_TEXT}</span>",
        showarrow=False, font=dict(size=13),
        align="center", xanchor="center",
    )

    # Per-step box label (only in --per-sequence mode)
    if box_label:
        fig.add_annotation(
            x=_SCENE_CX, y=0.005, xref="paper", yref="paper",
            text=f"<b>{box_label}</b>",
            showarrow=False, font=dict(size=15, color="#222"),
            align="center", xanchor="center",
        )


def _client_suffix(df_p: pd.DataFrame) -> str:
    clients = df_p["client_id"].unique()
    return "Multi" if len(clients) > 1 else str(clients[0])


def _pallet_label(pallet_id: int, df_p: pd.DataFrame) -> str:
    """Title: base font 22 px; the client number (or "Multi") is enlarged to
    60 px via an inline span."""
    clients = df_p["client_id"].unique()
    if len(clients) > 1:
        big = "Multi"
    else:
        big = str(clients[0])
    return (
        f"Palette {pallet_id} — Client "
        f"<span style='font-size:60px'>{big}</span>"
    )


def _build_box_label(df_p: pd.DataFrame, seq: int) -> str:
    """Libellé "#N · Pn · Client X · …" identique à la zoom view."""
    if "sequence" not in df_p.columns:
        return ""
    row = df_p[df_p["sequence"] == seq]
    if row.empty:
        return ""
    r        = row.iloc[0]
    loc      = str(r["location"])    if "location"    in r.index and pd.notna(r["location"])    else ""
    des_full = str(r["designation"]) if "designation" in r.index and pd.notna(r["designation"]) else ""
    des      = des_full[:20] + ("…" if len(des_full) > 20 else "")
    parts = [f"#{int(r['sequence'])}",
             f"P{int(r['priority'])}",
             f"Client {int(r['client_id'])}"]
    if loc:
        parts.append(loc)
    if des:
        parts.append(des)
    parts += [str(r['box_id']),
              f"{r['length']}×{r['width']}×{r['height']} cm",
              f"{r['weight']} kg"]
    return "  ·  ".join(parts)


# ── Export functions ────────────────────────────────────────────────────────────

def export_pallet_images(csv_path: str, output_folder: str) -> None:
    """One image per pallet (no highlight)."""
    df = load_pallet_data(csv_path)
    os.makedirs(output_folder, exist_ok=True)

    color_map    = build_client_color_map(df["client_id"].unique())
    source_label = os.path.basename(csv_path)

    pallet_ids = sorted(df["pallet_id"].unique())
    print(f"[Export] Exporting {len(pallet_ids)} pallets to '{output_folder}' …")

    for pallet_id in pallet_ids:
        df_p   = df[df["pallet_id"] == pallet_id].copy()
        fig    = render_pallet(df_p, color_map=color_map)
        label  = _pallet_label(pallet_id, df_p)
        suffix = _client_suffix(df_p)

        _apply_layout(fig, label, df_p, source_label=source_label)

        out_path = os.path.join(output_folder, f"pallet_{pallet_id}_{suffix}.png")
        fig.write_image(out_path, format="png")
        print(f"[Export]   {os.path.basename(out_path)}")

    print(f"[Export] Done. {len(pallet_ids)} images saved to '{output_folder}'.")


def export_pallet_images_per_sequence(csv_path: str, output_folder: str) -> None:
    """One image per placement step per pallet, with yellow highlight on the
    box placed at that step (replay style — like the zoom view slider)."""
    df = load_pallet_data(csv_path)
    os.makedirs(output_folder, exist_ok=True)

    color_map    = build_client_color_map(df["client_id"].unique())
    source_label = os.path.basename(csv_path)

    pallet_ids = sorted(df["pallet_id"].unique())
    total_images = sum(
        int(df[df["pallet_id"] == pid]["sequence"].max())
        for pid in pallet_ids
        if "sequence" in df.columns
    )
    print(
        f"[Export] Per-sequence export: {len(pallet_ids)} pallets, "
        f"~{total_images} images → '{output_folder}' …"
    )

    for pallet_id in pallet_ids:
        df_p   = df[df["pallet_id"] == pallet_id].copy()
        label  = _pallet_label(pallet_id, df_p)
        suffix = _client_suffix(df_p)

        if "sequence" in df_p.columns:
            n_total    = int(df_p["sequence"].max())
            seq_values = sorted(df_p["sequence"].unique())
        else:
            df_p = df_p.reset_index(drop=True)
            df_p["sequence"] = df_p.index + 1
            n_total    = len(df_p)
            seq_values = list(range(1, n_total + 1))

        digits = len(str(n_total))

        for seq in seq_values:
            df_seq    = df_p[df_p["sequence"] <= seq]
            fig       = render_pallet(df_seq, color_map=color_map, highlight_seq=seq)
            box_label = _build_box_label(df_p, seq)
            seq_label = f"{label}  —  Étape {seq}/{n_total}"

            _apply_layout(fig, seq_label, df_p,
                          highlight_seq=seq, box_label=box_label,
                          source_label=source_label)

            fname = (
                f"pallet_{pallet_id}_{suffix}"
                f"_seq_{str(seq).zfill(digits)}_of_{n_total}.png"
            )
            out_path = os.path.join(output_folder, fname)
            fig.write_image(out_path, format="png")

        print(f"[Export]   Pallet {pallet_id} ({suffix}): {n_total} images")

    print(f"[Export] Done. {total_images} images saved to '{output_folder}'.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Export pallet 3-D views as PNG images (zoom-view style).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("results", help="Path to the palletization result CSV.")
    parser.add_argument(
        "output_folder", nargs="?", default=None,
        help="Destination folder (default: pallet_images/ next to the CSV).",
    )
    parser.add_argument(
        "--per-sequence", action="store_true",
        help="Export one image per placement step per pallet (with highlight).",
    )
    args = parser.parse_args()

    if args.output_folder is None:
        csv_dir            = os.path.dirname(os.path.abspath(args.results))
        args.output_folder = os.path.join(csv_dir, "pallet_images")

    if args.per_sequence:
        export_pallet_images_per_sequence(args.results, args.output_folder)
    else:
        export_pallet_images(args.results, args.output_folder)


if __name__ == "__main__":
    main()
