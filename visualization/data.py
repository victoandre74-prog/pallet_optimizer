"""
data.py — Chargement et statistiques des données de palettisation

Couche données pure (sans Dash, sans Plotly).
Importé par view_palette.py, view_kpi.py et exporter.py.
"""

import os
import pandas as pd


_REQUIRED_COLS = {
    "pallet_id", "box_id", "client_id", "priority",
    "x", "y", "z", "orientation",
    "length", "width", "height", "weight",
    "pallet_length", "pallet_width", "pallet_height",
}


def load_pallet_data(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Results file not found: {csv_path}")

    df = pd.read_csv(csv_path, sep=";")

    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {missing}\n"
            f"Found columns: {list(df.columns)}"
        )

    numeric_cols = ["x", "y", "z", "length", "width", "height",
                    "weight", "pallet_length", "pallet_width", "pallet_height"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col])

    df["pallet_id"] = df["pallet_id"].astype(int)
    df["client_id"] = df["client_id"].astype(int)
    df["priority"]  = df["priority"].astype(int)

    print(f"[Data] Loaded {len(df)} placed boxes across "
          f"{df['pallet_id'].nunique()} pallets.")
    return df


def compute_pallet_statistics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}

    pallet_id    = int(df["pallet_id"].iloc[0])
    p_len        = float(df["pallet_length"].iloc[0])
    p_wid        = float(df["pallet_width"].iloc[0])
    p_hgt        = float(df["pallet_height"].iloc[0])

    pallet_vol   = p_len * p_wid * p_hgt
    box_vol      = (df["length"] * df["width"] * df["height"]).sum()
    fill_ratio   = box_vol / pallet_vol if pallet_vol > 0 else 0.0

    current_h    = (df["z"] + df["height"]).max()
    total_weight = df["weight"].sum()
    n_clients    = df["client_id"].nunique()
    multi_client = "Oui" if n_clients > 1 else "Non"

    return {
        "Palette N°":              pallet_id,
        "Total colis":             len(df),
        "Priorité 1 (Meubles)":   int((df["priority"] == 1).sum()),
        "Priorité 2 (Colis)":     int((df["priority"] == 2).sum()),
        "Taux volumétrique":       f"{fill_ratio:.1%}",
        "Hauteur (cm)":            f"{current_h:.1f}",
        "Poids (kg)":              f"{total_weight:.1f}",
        "Multi-client":            multi_client,
        "Clients":                 ", ".join(
                                       str(c) for c in sorted(df["client_id"].unique())
                                   ),
    }
