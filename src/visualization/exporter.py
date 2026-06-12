"""
exporter.py — Export d'images PNG statiques

Rend chaque palette d'un CSV de résultats sous forme d'image PNG
et les enregistre dans un dossier de sortie.

Usage :
    # Une image par palette (défaut) :
    python visualization/exporter.py <results.csv> [output_folder]

    # Une image par étape de placement par palette :
    python visualization/exporter.py <results.csv> [output_folder] --per-sequence

Prérequis :
    pip install kaleido
"""

import argparse
import sys
import os

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import plotly.graph_objects as go

from visualization.data     import load_pallet_data
from visualization.renderer import render_pallet, build_client_color_map


# ── Layout constants ───────────────────────────────────────────────────────────

_SCENE_X = (0.00, 0.357)
_SCENE_Y = (0.04, 0.92)
_TABLE_X = (0.38, 1.00)
_TABLE_Y = (0.08, 0.88)
_SCENE_CX    = (_SCENE_X[0] + _SCENE_X[1]) / 2
_HIGHLIGHT_BG = "#ffc107"
_ACCENT       = "#e67e22"

_LEGEND_TEXT = (
    "Contour noir = Priorité 1 (Meubles)   │   "
    "Contour blanc = Priorité 2 (Colis)"
)


# ── Layout helpers ─────────────────────────────────────────────────────────────

def _add_p2_table(fig: go.Figure, df_p: pd.DataFrame, highlight_seq: int = None) -> None:
    df_p2 = df_p[df_p["priority"] == 2].copy()
    if "sequence" in df_p2.columns:
        df_p2 = df_p2.sort_values("sequence")

    fig.add_annotation(x=_TABLE_X[0] + 0.005, y=_TABLE_Y[1] + 0.06,
                       xref="paper", yref="paper", text="<b>Colis P2</b>",
                       showarrow=False, font=dict(size=20, color=_ACCENT),
                       align="left", xanchor="left")

    if df_p2.empty:
        fig.add_annotation(x=(_TABLE_X[0] + _TABLE_X[1]) / 2, y=(_TABLE_Y[0] + _TABLE_Y[1]) / 2,
                           xref="paper", yref="paper", text="Aucun colis P2 sur cette palette.",
                           showarrow=False, font=dict(size=14, color="#aaa"),
                           align="center", xanchor="center")
        return

    has_loc = "location"    in df_p2.columns
    has_des = "designation" in df_p2.columns

    locs, dess, ids, dims, wgts, row_bg = [], [], [], [], [], []
    for i, (_, row) in enumerate(df_p2.iterrows()):
        seq      = int(row["sequence"]) if "sequence" in df_p2.columns else 0
        is_active = (highlight_seq is not None and seq == highlight_seq)
        loc      = str(row["location"])    if has_loc and pd.notna(row["location"])    else ""
        des_full = str(row["designation"]) if has_des and pd.notna(row["designation"]) else ""
        des      = des_full[:20] + ("…" if len(des_full) > 20 else "")
        locs.append(loc); dess.append(des); ids.append(str(row["box_id"]))
        dims.append(f"{row['length']}×{row['width']}×{row['height']}")
        wgts.append(f"{row['weight']} kg")
        row_bg.append(_HIGHLIGHT_BG if is_active else ("white" if i % 2 == 0 else "#fafafa"))

    fig.add_trace(go.Table(
        domain=dict(x=list(_TABLE_X), y=list(_TABLE_Y)),
        columnwidth=[70, 220, 130, 170, 90],
        header=dict(values=["<b>Casier</b>", "<b>Désignation</b>", "<b>ID</b>",
                             "<b>Dimensions</b>", "<b>Poids</b>"],
                    fill_color="#fafafa", line_color="#ddd", align="left",
                    font=dict(size=20, color="#888"), height=50),
        cells=dict(values=[locs, dess, ids, dims, wgts],
                   fill_color=[row_bg, row_bg, row_bg, row_bg, row_bg],
                   line_color="#eee", align="left",
                   font=dict(size=21, color=["#222", "#222", _ACCENT, "#222", "#222"]),
                   height=42),
    ))


def _apply_layout(fig: go.Figure, pallet_label: str, df_p: pd.DataFrame,
                  highlight_seq: int = None, box_label: str = "", source_label: str = "") -> None:
    fig.update_layout(width=1600, height=900, margin=dict(l=40, r=40, t=90, b=70),
                      scene=dict(domain=dict(x=list(_SCENE_X), y=list(_SCENE_Y))),
                      title=dict(text=pallet_label, x=0.5, y=0.955, font=dict(size=22)),
                      paper_bgcolor="white")
    if source_label:
        fig.add_annotation(x=0.5, y=0.995, xref="paper", yref="paper",
                           text=f"<span style='color:#888'>{source_label}</span>",
                           showarrow=False, font=dict(size=14), align="center", xanchor="center")
    _add_p2_table(fig, df_p, highlight_seq=highlight_seq)
    fig.add_annotation(x=_SCENE_CX, y=0.04, xref="paper", yref="paper",
                       text=f"<span style='color:#666'>{_LEGEND_TEXT}</span>",
                       showarrow=False, font=dict(size=13), align="center", xanchor="center")
    if box_label:
        fig.add_annotation(x=_SCENE_CX, y=0.005, xref="paper", yref="paper",
                           text=f"<b>{box_label}</b>",
                           showarrow=False, font=dict(size=15, color="#222"),
                           align="center", xanchor="center")


def _client_suffix(df_p: pd.DataFrame) -> str:
    clients = df_p["client_id"].unique()
    return "Multi" if len(clients) > 1 else str(clients[0])


def _pallet_label(pallet_id: int, df_p: pd.DataFrame) -> str:
    clients = df_p["client_id"].unique()
    big = "Multi" if len(clients) > 1 else str(clients[0])
    return f"Palette {pallet_id} — Client <span style='font-size:60px'>{big}</span>"


def _build_box_label(df_p: pd.DataFrame, seq: int) -> str:
    if "sequence" not in df_p.columns:
        return ""
    row = df_p[df_p["sequence"] == seq]
    if row.empty:
        return ""
    r        = row.iloc[0]
    loc      = str(r["location"])    if "location"    in r.index and pd.notna(r["location"])    else ""
    des_full = str(r["designation"]) if "designation" in r.index and pd.notna(r["designation"]) else ""
    des      = des_full[:20] + ("…" if len(des_full) > 20 else "")
    parts = [f"#{int(r['sequence'])}", f"P{int(r['priority'])}", f"Client {int(r['client_id'])}"]
    if loc:  parts.append(loc)
    if des:  parts.append(des)
    parts += [str(r['box_id']), f"{r['length']}×{r['width']}×{r['height']} cm", f"{r['weight']} kg"]
    return "  ·  ".join(parts)


# ── Export functions ────────────────────────────────────────────────────────────

def export_pallet_images(csv_path: str, output_folder: str) -> None:
    """Une image par palette (sans highlight)."""
    df = load_pallet_data(csv_path)
    os.makedirs(output_folder, exist_ok=True)

    color_map    = build_client_color_map(df["client_id"].unique())
    source_label = os.path.basename(csv_path)
    pallet_ids   = sorted(df["pallet_id"].unique())
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
    """Une image par étape de placement par palette (mode relecture)."""
    df = load_pallet_data(csv_path)
    os.makedirs(output_folder, exist_ok=True)

    color_map    = build_client_color_map(df["client_id"].unique())
    source_label = os.path.basename(csv_path)
    pallet_ids   = sorted(df["pallet_id"].unique())
    total_images = sum(int(df[df["pallet_id"] == pid]["sequence"].max())
                       for pid in pallet_ids if "sequence" in df.columns)
    print(f"[Export] Per-sequence : {len(pallet_ids)} palettes, ~{total_images} images → '{output_folder}' …")

    for pallet_id in pallet_ids:
        df_p   = df[df["pallet_id"] == pallet_id].copy()
        label  = _pallet_label(pallet_id, df_p)
        suffix = _client_suffix(df_p)

        if "sequence" in df_p.columns:
            n_total    = int(df_p["sequence"].max())
            seq_values = sorted(df_p["sequence"].unique())
        else:
            df_p = df_p.reset_index(drop=True); df_p["sequence"] = df_p.index + 1
            n_total    = len(df_p); seq_values = list(range(1, n_total + 1))

        digits = len(str(n_total))
        for seq in seq_values:
            df_seq    = df_p[df_p["sequence"] <= seq]
            fig       = render_pallet(df_seq, color_map=color_map, highlight_seq=seq)
            box_label = _build_box_label(df_p, seq)
            seq_label = f"{label}  —  Étape {seq}/{n_total}"
            _apply_layout(fig, seq_label, df_p, highlight_seq=seq, box_label=box_label,
                          source_label=source_label)
            fname    = f"pallet_{pallet_id}_{suffix}_seq_{str(seq).zfill(digits)}_of_{n_total}.png"
            out_path = os.path.join(output_folder, fname)
            fig.write_image(out_path, format="png")
        print(f"[Export]   Palette {pallet_id} ({suffix}) : {n_total} images")

    print(f"[Export] Done. {total_images} images saved to '{output_folder}'.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export pallet 3-D views as PNG images.")
    parser.add_argument("results", help="Chemin vers le CSV de résultats.")
    parser.add_argument("output_folder", nargs="?", default=None,
                        help="Dossier de destination (défaut : pallet_images/ à côté du CSV).")
    parser.add_argument("--per-sequence", action="store_true",
                        help="Exporter une image par étape de placement par palette.")
    args = parser.parse_args()

    if args.output_folder is None:
        csv_dir = os.path.dirname(os.path.abspath(args.results))
        args.output_folder = os.path.join(csv_dir, "pallet_images")

    if args.per_sequence:
        export_pallet_images_per_sequence(args.results, args.output_folder)
    else:
        export_pallet_images(args.results, args.output_folder)


if __name__ == "__main__":
    main()
