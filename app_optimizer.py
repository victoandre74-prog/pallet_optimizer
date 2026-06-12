"""
app.py — Interface Dash centralisée pour Pallet Optimizer.

Deux sections :
  1. Paramétrage & Exécution
  2. Visualisation & Export (ouvre le Visualiseur sur port 8053)

Usage :
    python app.py
"""

import sys
import os
import json
import uuid
import base64
import subprocess
from dataclasses import asdict
from pathlib import Path

_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_DIR, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from config.parameters import OptimizationParameters, PARAM_BOUNDS


def _load_logo(filename: str) -> str:
    path = os.path.join(_DIR, "assets", filename)
    if not os.path.exists(path):
        return ""
    ext  = filename.rsplit(".", 1)[-1].lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(path, "rb") as f:
        return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()


_LOGO_FOURNIER = _load_logo("logo_fournier.png")
_LOGO_U4LOG    = _load_logo("logo_u4log.jpg")

import dash
from dash import dcc, html, Input, Output, State, ctx

# ── Global subprocess store ────────────────────────────────────────────────────
_runs: dict = {}   # run_id → {proc: Popen, output_dir: str, ...}

# True quand l'app tourne dans un container Docker (PALLET_HOST=0.0.0.0).
_IS_DOCKER = os.environ.get("PALLET_HOST", "127.0.0.1") == "0.0.0.0"


# ── Batch-status contract (produced by main.py) ───────────────────────────────
# Every batch log ({stem}_log_*.txt) contains exactly one line of the form:
#     [BATCH-STATUS] stem=<stem> code=<CODE> [detail="<free text>"]
# emitted just before the log file is closed. This marker is the authoritative
# success/failure signal — do NOT grep for free-form error text anywhere else
# in the log file (the phrasing can change; the marker is the stable contract).
#
# Codes we expect (defined in main.py — keep in sync):
#     OK               Batch fully succeeded
#     ERR_VALIDATION   Phase 0 — CSV validation failed
#     ERR_EMPTY_INPUT  Phase 0 — CSV parsed but no boxes
#     ERR_SECURITY     Phase 6 — input/output box mismatch
#     ERR_EXCEPTION    Unhandled exception
#     ERR_UNKNOWN      Fallback (should not occur)
#
# Missing marker = the batch was killed before reaching main.py's finally-block
# (e.g. process terminated externally). In that case we fall back to: results
# CSV present → treat as "ok" (the core computation did write results).
_BATCH_STATUS_MARKER = "[BATCH-STATUS]"


def _read_batch_status(log_path: Path) -> str:
    """Return the batch-status code from the log file, or '' if not found.

    Reads only the last ~8 KB of the file (the marker is always at the end)
    and returns the `code=` value from the last BATCH-STATUS line.
    See the contract docstring above and main.py::BATCH_STATUS_MARKER.
    """
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    for line in reversed(tail.splitlines()):
        if _BATCH_STATUS_MARKER in line:
            idx = line.find("code=")
            if idx < 0:
                return ""
            # Code is a bare token: ends at whitespace or the opening quote of
            # the optional detail= field.
            rest = line[idx + len("code="):].lstrip()
            code = rest.split()[0].split('"')[0] if rest else ""
            return code
    return ""


# ── Valeurs par défaut ───────────────────────────────────────────────────────
# Dérivées directement du dataclass `OptimizationParameters` pour avoir une
# seule source de vérité : toute modification de config/parameters.py est
# immédiatement reflétée dans l'UI.
DEFAULTS = asdict(OptimizationParameters())

# ── Styles ─────────────────────────────────────────────────────────────────────
S = dict(
    page={
        "fontFamily": "'Segoe UI', Arial, sans-serif",
        "background": "#f0f4f8",
        "minHeight": "100vh",
        "padding": "0 0 40px 0",
    },
    header={
        "background": "linear-gradient(135deg, #1e293b 0%, #334155 100%)",
        "color": "white",
        "padding": "18px 32px",
        "marginBottom": "24px",
        "display": "flex",
        "alignItems": "center",
        "gap": "12px",
    },
    header_title={
        "fontSize": "22px",
        "fontWeight": "700",
        "letterSpacing": "0.5px",
        "margin": "0",
    },
    header_sub={
        "fontSize": "13px",
        "opacity": "0.7",
        "margin": "2px 0 0 0",
    },
    content={"margin": "0 auto", "padding": "0 20px"},
    card={
        "background": "white",
        "borderRadius": "12px",
        "boxShadow": "0 1px 4px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.04)",
        "padding": "24px 28px",
        "marginBottom": "20px",
    },
    section_num={
        "display": "inline-flex",
        "alignItems": "center",
        "justifyContent": "center",
        "width": "28px",
        "height": "28px",
        "borderRadius": "50%",
        "background": "#2563eb",
        "color": "white",
        "fontWeight": "700",
        "fontSize": "14px",
        "flexShrink": "0",
    },
    section_title={
        "fontSize": "17px",
        "fontWeight": "700",
        "color": "#1e293b",
        "margin": "0 0 18px 0",
        "display": "flex",
        "alignItems": "center",
        "gap": "10px",
        "paddingBottom": "12px",
        "borderBottom": "2px solid #e2e8f0",
    },
    label={
        "fontSize": "12px",
        "fontWeight": "600",
        "color": "#374151",
        "marginBottom": "5px",
        "display": "block",
        "textTransform": "uppercase",
        "letterSpacing": "0.4px",
    },
    hint={
        "fontSize": "11px",
        "color": "#9ca3af",
        "marginTop": "3px",
        "fontStyle": "italic",
        "lineHeight": "1.4",
    },
    input={
        "width": "100%",
        "padding": "8px 10px",
        "border": "1px solid #d1d5db",
        "borderRadius": "6px",
        "fontSize": "13px",
        "color": "#111827",
        "boxSizing": "border-box",
    },
    btn_primary={
        "background": "#2563eb",
        "color": "white",
        "border": "none",
        "borderRadius": "8px",
        "padding": "10px 22px",
        "fontSize": "14px",
        "fontWeight": "600",
        "cursor": "pointer",
        "letterSpacing": "0.3px",
    },
    btn_sm={
        "background": "#f1f5f9",
        "color": "#374151",
        "border": "1px solid #d1d5db",
        "borderRadius": "6px",
        "padding": "7px 14px",
        "fontSize": "12px",
        "fontWeight": "600",
        "cursor": "pointer",
        "whiteSpace": "nowrap",
    },
    btn_success={
        "background": "#16a34a",
        "color": "white",
        "border": "none",
        "borderRadius": "8px",
        "padding": "10px 22px",
        "fontSize": "14px",
        "fontWeight": "600",
        "cursor": "pointer",
    },
    btn_disabled={
        "background": "#94a3b8",
        "color": "white",
        "border": "none",
        "borderRadius": "8px",
        "padding": "10px 22px",
        "fontSize": "14px",
        "fontWeight": "600",
        "cursor": "not-allowed",
        "opacity": "0.7",
    },
    log={
        "fontFamily": "Consolas, 'Courier New', monospace",
        "fontSize": "12px",
        "background": "#0f172a",
        "color": "#94a3b8",
        "padding": "14px 16px",
        "borderRadius": "8px",
        "minHeight": "120px",
        "maxHeight": "340px",
        "overflowY": "auto",
        "whiteSpace": "pre-wrap",
        "marginTop": "16px",
        "lineHeight": "1.6",
        "wordBreak": "break-all",
    },
    details={
        "border": "1px solid #e2e8f0",
        "borderRadius": "8px",
        "marginBottom": "10px",
        "overflow": "hidden",
    },
    summary={
        "padding": "11px 14px",
        "fontSize": "13px",
        "fontWeight": "600",
        "color": "#374151",
        "cursor": "pointer",
        "background": "#f8fafc",
        "userSelect": "none",
    },
    param_grid={
        "display": "grid",
        "gridTemplateColumns": "repeat(auto-fill, minmax(180px, 1fr))",
        "gap": "14px",
        "padding": "14px",
        "background": "white",
    },
    row={
        "display": "flex",
        "gap": "16px",
        "alignItems": "flex-start",
        "flexWrap": "wrap",
    },
    badge_info={
        "display": "inline-block",
        "background": "#dbeafe",
        "color": "#1d4ed8",
        "borderRadius": "20px",
        "padding": "2px 10px",
        "fontSize": "12px",
        "fontWeight": "600",
    },
    badge_ok={
        "display": "inline-block",
        "background": "#dcfce7",
        "color": "#16a34a",
        "borderRadius": "20px",
        "padding": "2px 10px",
        "fontSize": "12px",
        "fontWeight": "600",
    },
    badge_warn={
        "display": "inline-block",
        "background": "#fef9c3",
        "color": "#92400e",
        "borderRadius": "20px",
        "padding": "2px 10px",
        "fontSize": "12px",
        "fontWeight": "600",
    },
    badge_err={
        "display": "inline-block",
        "background": "#fee2e2",
        "color": "#dc2626",
        "borderRadius": "20px",
        "padding": "2px 10px",
        "fontSize": "12px",
        "fontWeight": "600",
    },
    toggle_row={
        "display": "flex",
        "gap": "12px",
        "marginBottom": "18px",
        "flexWrap": "wrap",
    },
    toggle_label={
        "fontSize": "13px",
        "fontWeight": "500",
        "color": "#374151",
    },
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _browse_folder(title: str = "Sélectionner un dossier") -> str:
    """Ouvre une boîte de dialogue OS pour choisir un dossier (côté serveur)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        path = filedialog.askdirectory(title=title)
        root.destroy()
        return path or ""
    except Exception:
        return ""


def _count_csvs(folder: str) -> int:
    """Nombre de fichiers .csv dans le dossier."""
    try:
        return len(list(Path(folder).glob("*.csv")))
    except Exception:
        return 0




def _count_output_files(folder: str) -> int:
    """Nombre de fichiers dans le dossier de sortie (hors sous-dossiers)."""
    try:
        p = Path(folder)
        if not p.is_dir():
            return 0
        return len([f for f in p.iterdir() if f.is_file()])
    except Exception:
        return 0




# ── Composants réutilisables ───────────────────────────────────────────────────

def _section_title(num: str, text: str) -> html.Div:
    return html.Div([
        html.Span(num, style=S["section_num"]),
        text,
    ], style=S["section_title"])


def _param_field(label: str, input_id: str, value, step=None, hint: str = "",
                 min_val=None, max_val=None) -> html.Div:
    """Un champ de paramètre : étiquette + input numérique + hint."""
    inp_kwargs = {"value": value, "id": input_id, "type": "number", "style": S["input"]}
    if step is not None:
        inp_kwargs["step"] = step
    if min_val is not None:
        inp_kwargs["min"] = min_val
    if max_val is not None:
        inp_kwargs["max"] = max_val
    return html.Div([
        html.Label(label, style=S["label"]),
        dcc.Input(**inp_kwargs),
        html.Div(hint, style=S["hint"]) if hint else None,
    ], style={"display": "flex", "flexDirection": "column"})


def _folder_row(label: str, path_id: str, browse_id: str, badge_id: str,
                badge_text: str, hint: str = None,
                default_path: str = "", browse_disabled: bool = False) -> html.Div:
    """Rangée : étiquette + champ chemin + bouton Browse + badge (+ hint optionnel)."""
    children = [
        html.Label(label, style=S["label"]),
        html.Div([
            dcc.Input(id=path_id, type="text", placeholder="Chemin du dossier...",
                      value=default_path,
                      style={**S["input"], "flex": "1"}),
            html.Button("Parcourir", id=browse_id, n_clicks=0, style=S["btn_sm"],
                        disabled=browse_disabled,
                        title="Non disponible en mode serveur — chemin pré-rempli" if browse_disabled else ""),
        ], style={"display": "flex", "gap": "8px", "alignItems": "center"}),
        html.Div(html.Span(badge_text, id=badge_id, style=S["badge_info"]),
                 style={"marginTop": "6px"}),
    ]
    if hint:
        children.append(html.Div(
            hint,
            style={"marginTop": "6px", "fontSize": "12px",
                   "color": "#6b7280", "fontStyle": "italic"},
        ))
    return html.Div(children, style={"flex": "1", "minWidth": "260px"})


def _details_group(summary: str, children: list, open_by_default: bool = False) -> html.Details:
    """Section pliable."""
    attrs = {"style": S["details"]}
    if open_by_default:
        attrs["open"] = True
    return html.Details([
        html.Summary(summary, style=S["summary"]),
        html.Div(children, style=S["param_grid"]),
    ], **attrs)


# ── Layout ─────────────────────────────────────────────────────────────────────

def _build_layout() -> html.Div:

    _sub_header = lambda text: html.Div(text, style={
        **S["label"], "textTransform": "none", "fontSize": "12px",
        "color": "#6b7280", "gridColumn": "1 / -1",
        "paddingBottom": "4px", "borderBottom": "1px solid #e2e8f0",
        "marginBottom": "4px", "marginTop": "6px",
    })

    # ── Section 1 ─────────────────────────────────────────────────────────────
    section1 = html.Div([
        _section_title("1", "Paramétrage et Exécution"),

        # Dossiers
        html.Div([
            _folder_row("Dossier d'entrée (input)",
                        "input-dir", "browse-input", "input-badge",
                        "Aucun dossier sélectionné",
                        hint="Tous les fichiers .csv dans le dossier seront traités l'un après l'autre.",
                        default_path="/app/input" if _IS_DOCKER else "",
                        browse_disabled=_IS_DOCKER),
            _folder_row("Dossier de sortie (output)",
                        "output-dir", "browse-output", "output-badge",
                        "Aucun dossier sélectionné",
                        hint="Tous les fichiers de résultats seront stockés dans le dossier.",
                        default_path="/app/output" if _IS_DOCKER else "",
                        browse_disabled=_IS_DOCKER),
        ], style={**S["row"], "marginBottom": "18px"}),

        # Toggles
        html.Div([
            html.Div([
                html.Label("Multi-client", style={**S["label"], "marginBottom": "0"}),
                dcc.Checklist(
                    id="toggle-multi-client",
                    options=[{"label": " Autoriser les palettes multi-client", "value": "on"}],
                    value=["on"],
                    inputStyle={"marginRight": "6px", "cursor": "pointer",
                                "width": "16px", "height": "16px"},
                    labelStyle={"fontSize": "13px", "color": "#374151",
                                "display": "flex", "alignItems": "center"},
                ),
            ], style={"background": "#f8fafc", "border": "1px solid #e2e8f0",
                      "borderRadius": "8px", "padding": "12px 16px", "flex": "1",
                      "minWidth": "200px", "display": "flex", "flexDirection": "column",
                      "gap": "6px"}),
            html.Div([
                html.Label("Post-traitement", style={**S["label"], "marginBottom": "0"}),
                dcc.Checklist(
                    id="toggle-post-pro",
                    options=[{"label": " Activer le post-traitement", "value": "on"}],
                    value=["on"],
                    inputStyle={"marginRight": "6px", "cursor": "pointer",
                                "width": "16px", "height": "16px"},
                    labelStyle={"fontSize": "13px", "color": "#374151",
                                "display": "flex", "alignItems": "center"},
                ),
            ], style={"background": "#f8fafc", "border": "1px solid #e2e8f0",
                      "borderRadius": "8px", "padding": "12px 16px", "flex": "1",
                      "minWidth": "200px", "display": "flex", "flexDirection": "column",
                      "gap": "6px"}),
        ], style=S["toggle_row"]),

        # Groupes de paramètres
        _details_group("Dimensions de la palette", [
            _param_field("Longueur (cm) — axe X", "p-pallet-length",
                         DEFAULTS["pallet_length"], step=1,
                         hint="Ex : 120 cm pour une palette standard EUR",
                         min_val=PARAM_BOUNDS["pallet_length"][0], max_val=PARAM_BOUNDS["pallet_length"][1]),
            _param_field("Largeur (cm) — axe Y", "p-pallet-width",
                         DEFAULTS["pallet_width"], step=1,
                         hint="Ex : 80 cm pour une palette standard EUR",
                         min_val=PARAM_BOUNDS["pallet_width"][0], max_val=PARAM_BOUNDS["pallet_width"][1]),
            _param_field("Hauteur max (cm) — axe Z", "p-pallet-max-height",
                         DEFAULTS["pallet_max_height"], step=1,
                         hint="Hauteur maximale d'empilement",
                         min_val=PARAM_BOUNDS["pallet_max_height"][0], max_val=PARAM_BOUNDS["pallet_max_height"][1]),
            _param_field("Poids max (kg)", "p-pallet-max-weight",
                         DEFAULTS["pallet_max_weight"], step=10,
                         hint="Capacité de charge maximale",
                         min_val=PARAM_BOUNDS["pallet_max_weight"][0], max_val=PARAM_BOUNDS["pallet_max_weight"][1]),
        ], open_by_default=True),

        _details_group("Contraintes physiques et stabilité", [
            _param_field("Ratio de support minimum", "p-min-support-ratio",
                         DEFAULTS["min_support_ratio"], step=0.01,
                         hint="Fraction de la base devant reposer sur un support (0.75 = 75 %)",
                         min_val=PARAM_BOUNDS["min_support_ratio"][0], max_val=PARAM_BOUNDS["min_support_ratio"][1]),
            _param_field("Ratio de stabilité", "p-stability-ratio",
                         DEFAULTS["stability_ratio"], step=0.1,
                         hint="Rapport max hauteur/base d'une pile — empêche les tours instables",
                         min_val=PARAM_BOUNDS["stability_ratio"][0], max_val=PARAM_BOUNDS["stability_ratio"][1]),
        ], open_by_default=True),

        _details_group("Contrainte ergonomique", [
            _param_field("Hauteur max dépôt P2 (cm)", "p-priority2-max-deposit-height",
                         DEFAULTS["priority2_max_deposit_height"], step=5,
                         hint="Hauteur max à laquelle le bas d'un colis priorité 2 peut être déposé manuellement",
                         min_val=PARAM_BOUNDS["priority2_max_deposit_height"][0], max_val=PARAM_BOUNDS["priority2_max_deposit_height"][1]),
        ], open_by_default=True),

        html.Div(_details_group("Repacking Multi-Client", [
            _param_field("Seuil de remplissage min.", "p-min-filling-ratio",
                         DEFAULTS["min_filling_ratio"], step=0.01,
                         hint="Régime ≤10 palettes : on continue de fusionner tant que la moyenne du remplissage du futur pool multi reste sous ce seuil (0.30 = 30 %).",
                         min_val=PARAM_BOUNDS["min_filling_ratio"][0], max_val=PARAM_BOUNDS["min_filling_ratio"][1]),
            _param_field("Seuil d'arrêt multi-client (min)", "p-multi-client-minimum-ratio",
                         DEFAULTS["multi_client_minimum_ratio"], step=0.01,
                         hint="Régime ≥11 palettes : arrêt doux quand multi/total > ce seuil ET la palette mono la moins remplie est déjà bien remplie (0.13 = 13 %).",
                         min_val=PARAM_BOUNDS["multi_client_minimum_ratio"][0], max_val=PARAM_BOUNDS["multi_client_minimum_ratio"][1]),
            _param_field("Seuil d'arrêt multi-client (max)", "p-multi-client-maximum-ratio",
                         DEFAULTS["multi_client_maximum_ratio"], step=0.01,
                         hint="Régime ≥11 palettes : arrêt forcé dès que multi/total > ce seuil, quelles que soient les conditions (0.17 = 17 %).",
                         min_val=PARAM_BOUNDS["multi_client_maximum_ratio"][0], max_val=PARAM_BOUNDS["multi_client_maximum_ratio"][1]),
        ], open_by_default=True), id="mc-param-wrapper"),

        _details_group("Paramètres avancés - LNS Mono", [
            _sub_header("Budget"),
            _param_field("Temps par palette (s)", "p-lns-mono-time-per-pallet",
                         DEFAULTS["lns_mono_time_per_pallet"], step=0.05,
                         hint="Budget temps par palette du groupe. Ex : 0.7s × 40 pal = 28s total."),
            _param_field("Itérations par palette", "p-lns-mono-iter-per-pallet",
                         DEFAULTS["lns_mono_iter_per_pallet"], step=1,
                         hint="Nombre d'itérations allouées par palette. Ex : 5 × 40 pal = 200 iters.",
                         min_val=PARAM_BOUNDS["lns_mono_iter_per_pallet"][0], max_val=PARAM_BOUNDS["lns_mono_iter_per_pallet"][1]),
            _param_field("Graine aléatoire", "p-lns-mono-random-seed",
                         DEFAULTS["lns_mono_random_seed"], step=1,
                         hint="Graine pour reproductibilité.",
                         min_val=PARAM_BOUNDS["lns_mono_random_seed"][0], max_val=PARAM_BOUNDS["lns_mono_random_seed"][1]),
            _sub_header("Comportement"),
            _param_field("Volume petit colis (cm³)", "p-lns-mono-small-box-volume",
                         DEFAULTS["lns_mono_small_box_volume"], step=1000,
                         hint="Colis sous ce volume extraits des palettes survivantes à chaque itération.",
                         min_val=PARAM_BOUNDS["lns_mono_small_box_volume"][0], max_val=PARAM_BOUNDS["lns_mono_small_box_volume"][1]),
            _param_field("Pool de positions (top-k)", "p-lns-mono-repair-top-k",
                         DEFAULTS["lns_mono_repair_top_k"], step=1,
                         hint="Tirage aléatoire parmi les k meilleures positions EP × orientation.",
                         min_val=PARAM_BOUNDS["lns_mono_repair_top_k"][0], max_val=PARAM_BOUNDS["lns_mono_repair_top_k"][1]),
            _sub_header("Fonction de coût"),
            _param_field("Poids nombre de palettes", "p-cost-mono-pallet-count",
                         DEFAULTS["cost_mono_pallet_count"], step=10,
                         hint="Pénalité par palette supplémentaire.",
                         min_val=PARAM_BOUNDS["cost_mono_pallet_count"][0], max_val=PARAM_BOUNDS["cost_mono_pallet_count"][1]),
            _param_field("Poids remplissage dernière palette", "p-cost-mono-last-pallet-filling",
                         DEFAULTS["cost_mono_last_pallet_filling"], step=10,
                         hint="Pénalise le taux de remplissage élevé de la palette la moins remplie.",
                         min_val=PARAM_BOUNDS["cost_mono_last_pallet_filling"][0], max_val=PARAM_BOUNDS["cost_mono_last_pallet_filling"][1]),
        ]),

        html.Div(_details_group("Paramètres avancés - LNS Multi", [
            _sub_header("Budget"),
            _param_field("Temps par palette (s)", "p-lns-multi-time-per-pallet",
                         DEFAULTS["lns_multi_time_per_pallet"], step=0.1,
                         hint="Budget temps par palette du pool multi. Ex : 0.5s × 10 pal = 5s total."),
            _param_field("Itérations par palette", "p-lns-multi-iter-per-pallet",
                         DEFAULTS["lns_multi_iter_per_pallet"], step=1,
                         hint="Nombre d'itérations allouées par palette. Ex : 10 × 10 pal = 100 iters.",
                         min_val=PARAM_BOUNDS["lns_multi_iter_per_pallet"][0], max_val=PARAM_BOUNDS["lns_multi_iter_per_pallet"][1]),
            _param_field("Graine aléatoire", "p-lns-multi-random-seed",
                         DEFAULTS["lns_multi_random_seed"], step=1,
                         hint="Graine pour reproductibilité.",
                         min_val=PARAM_BOUNDS["lns_multi_random_seed"][0], max_val=PARAM_BOUNDS["lns_multi_random_seed"][1]),
            _sub_header("Comportement"),
            _param_field("Ratio destruction (destroy_ratio)", "p-lns-multi-destroy-ratio",
                         DEFAULTS["lns_multi_destroy_ratio"], step=0.01,
                         hint="Fraction des palettes les moins remplies détruites à chaque itération (min 1).",
                         min_val=PARAM_BOUNDS["lns_multi_destroy_ratio"][0], max_val=PARAM_BOUNDS["lns_multi_destroy_ratio"][1]),
            _param_field("Pool de positions (top-k)", "p-lns-multi-repair-top-k",
                         DEFAULTS["lns_multi_repair_top_k"], step=1,
                         hint="Tirage aléatoire parmi les k meilleures positions lors de la réparation.",
                         min_val=PARAM_BOUNDS["lns_multi_repair_top_k"][0], max_val=PARAM_BOUNDS["lns_multi_repair_top_k"][1]),
            _sub_header("Fonction de coût"),
            _param_field("Poids nombre de palettes", "p-cost-multi-pallet-count",
                         DEFAULTS["cost_multi_pallet_count"], step=1,
                         hint="Pénalité par palette supplémentaire (multi-client).",
                         min_val=PARAM_BOUNDS["cost_multi_pallet_count"][0], max_val=PARAM_BOUNDS["cost_multi_pallet_count"][1]),
        ]), id="lns-multi-param-wrapper"),

        html.Div(_details_group("Paramètres avancés - Post-traitement", [
            _sub_header("Budget"),
            _param_field("Temps par palette (s)", "p-pp-time-per-pallet",
                         DEFAULTS["pp_time_per_pallet"], step=0.1,
                         hint="Budget temps par palette du groupe. Ex : 0.5s × 3 pal = 1.5s total."),
            _param_field("Itérations par palette", "p-pp-iter-per-pallet",
                         DEFAULTS["pp_iter_per_pallet"], step=1,
                         hint="Nombre d'itérations allouées par palette. Ex : 30 × 3 pal = 90 iters.",
                         min_val=PARAM_BOUNDS["pp_iter_per_pallet"][0], max_val=PARAM_BOUNDS["pp_iter_per_pallet"][1]),
            _param_field("Graine aléatoire", "p-pp-random-seed",
                         DEFAULTS["pp_random_seed"], step=1,
                         hint="Graine pour reproductibilité.",
                         min_val=PARAM_BOUNDS["pp_random_seed"][0], max_val=PARAM_BOUNDS["pp_random_seed"][1]),
            _param_field("Pool de candidats (top_k)", "p-pp-top-k",
                         DEFAULTS["pp_top_k"], step=1,
                         hint="Taille du pool de positions candidates lors du placement.",
                         min_val=PARAM_BOUNDS["pp_top_k"][0], max_val=PARAM_BOUNDS["pp_top_k"][1]),
            _sub_header("Pondérations"),
            _param_field("Poids contact P2→P1", "p-pp-w-contact",
                         DEFAULTS["pp_w_contact"], step=1.0,
                         hint="Récompense / cm² de contact vertical P2→P1.",
                         min_val=PARAM_BOUNDS["pp_w_contact"][0], max_val=PARAM_BOUNDS["pp_w_contact"][1]),
            _param_field("Poids variance remplissage", "p-pp-w-fill",
                         DEFAULTS["pp_w_fill"], step=0.5,
                         hint="Pénalité sur la variance du taux de remplissage entre palettes.",
                         min_val=PARAM_BOUNDS["pp_w_fill"][0], max_val=PARAM_BOUNDS["pp_w_fill"][1]),
            _param_field("Poids variance P2", "p-pp-w-p2",
                         DEFAULTS["pp_w_p2"], step=100.0,
                         hint="Pénalité sur la variance du nombre de colis P2 entre palettes.",
                         min_val=PARAM_BOUNDS["pp_w_p2"][0], max_val=PARAM_BOUNDS["pp_w_p2"][1]),
            _param_field("Poids hauteur moyenne", "p-pp-w-height",
                         DEFAULTS["pp_w_height"], step=1.0,
                         hint="Pénalité sur le ratio hauteur/hauteur max moyen — favorise les palettes basses.",
                         min_val=PARAM_BOUNDS["pp_w_height"][0], max_val=PARAM_BOUNDS["pp_w_height"][1]),
            _param_field("Poids stabilité", "p-pp-w-stability",
                         DEFAULTS["pp_w_stability"], step=1.0,
                         hint="Pénalité sur le pire ratio de stabilité — favorise les empilements stables.",
                         min_val=PARAM_BOUNDS["pp_w_stability"][0], max_val=PARAM_BOUNDS["pp_w_stability"][1]),
            _param_field("Décalage min centrage (cm)", "p-pp-center-min-shift",
                         DEFAULTS["pp_center_min_shift"], step=0.5,
                         hint="Seuil de déplacement en cm pour appliquer le centrage de charge.",
                         min_val=PARAM_BOUNDS["pp_center_min_shift"][0], max_val=PARAM_BOUNDS["pp_center_min_shift"][1]),
        ]), id="pp-param-wrapper"),

        # Parallélisme
        html.Div(
            _details_group("Parallélisation calcul", [
                _param_field("Nombre de travailleurs parallèles", "p-max-workers", 1, step=1,
                             hint="Fichiers CSV traités en parallèle (max 4). "
                                  "Nécessite ≥ 4 CSV dans le dossier d'entrée.",
                             min_val=1, max_val=4),
            ]),
            id="workers-param-wrapper",
            style={"marginTop": "4px", "opacity": "0.4", "pointerEvents": "none", "userSelect": "none"},
        ),

        # Bouton Lancer
        html.Div([
            html.Button(
                "▶  Lancer l'exécution",
                id="run-btn", n_clicks=0, disabled=True,
                style={**S["btn_disabled"], "fontSize": "15px", "padding": "12px 28px"},
            ),
            html.Span("", id="run-status-badge", style={"marginLeft": "12px"}),
        ], style={"display": "flex", "alignItems": "center", "marginTop": "20px"}),

        html.Pre("En attente du lancement...", id="log-display", style=S["log"]),

    ], style=S["card"])

    # ── Section 2 — Visualisation & Export ───────────────────────────────────
    # ── Assemblage ────────────────────────────────────────────────────────────
    return html.Div([
        # En-tête
        html.Div(
            style={"display": "flex", "alignItems": "center", "position": "relative",
                   "background": "#f0f4f8", "padding": "6px 24px",
                   "marginBottom": "20px"},
            children=[
                html.Img(src=_LOGO_FOURNIER,
                         style={"height": "68px", "objectFit": "contain"}) if _LOGO_FOURNIER else html.Div(),
                html.Div(
                    style={"position": "absolute", "width": "100%",
                           "textAlign": "center", "pointerEvents": "none", "left": "0"},
                    children=[html.H2("Calculateur de Palettes - UI",
                                      style={"color": "#333", "margin": "0"})],
                ),
                html.Img(src=_LOGO_U4LOG,
                         style={"height": "68px", "objectFit": "contain",
                                "marginLeft": "auto"}) if _LOGO_U4LOG else html.Div(style={"marginLeft": "auto"}),
            ],
        ),

        html.Div([section1], style=S["content"]),

        # Composants invisibles
        dcc.Interval(id="poll-interval", interval=500, n_intervals=0, disabled=True),
        dcc.Store(id="run-state", data={"active": False, "run_id": None}),

    ], style=S["page"])


# ── Application ────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    title="Pallet Optimizer",
    suppress_callback_exceptions=True,
)
app.layout = _build_layout()


# Auto-scroll log-style <pre> box (#log-display) to the bottom whenever its
# content is updated, so the latest line is always visible — like a terminal.
# Uses MutationObserver so no per-update Dash callback needed.
app.index_string = app.index_string.replace(
    "<head>",
    "<head>"
    "<script>"
    "(function() {"
    "  var SEL = '#log-display';"
    "  function attach() {"
    "    document.querySelectorAll(SEL).forEach(function(el) {"
    "      if (el.dataset.autoScrollAttached) return;"
    "      el.dataset.autoScrollAttached = '1';"
    "      new MutationObserver(function() {"
    "        el.scrollTop = el.scrollHeight;"
    "      }).observe(el, {childList: true, characterData: true, subtree: true});"
    "      el.scrollTop = el.scrollHeight;"
    "    });"
    "  }"
    "  if (document.readyState === 'loading') {"
    "    document.addEventListener('DOMContentLoaded', attach);"
    "  } else { attach(); }"
    "  new MutationObserver(attach).observe("
    "    document.documentElement, {childList: true, subtree: true});"
    "})();"
    "</script>"
)



# ── Callbacks — Sélection des dossiers ────────────────────────────────────────

@app.callback(
    Output("input-dir", "value"),
    Input("browse-input", "n_clicks"),
    prevent_initial_call=True,
)
def browse_input(_):
    return _browse_folder("Sélectionner le dossier d'entrée (input)") or dash.no_update


@app.callback(
    Output("output-dir", "value"),
    Input("browse-output", "n_clicks"),
    prevent_initial_call=True,
)
def browse_output(_):
    return _browse_folder("Sélectionner le dossier de sortie (output)") or dash.no_update


# ── Callback — Badge dossier d'entrée + activation bouton Run ─────────────────

@app.callback(
    Output("input-badge", "children"),
    Output("input-badge", "style"),
    Output("run-btn", "disabled"),
    Output("run-btn", "style"),
    Input("input-dir", "value"),
    Input("run-state", "data"),
)
def update_input_badge(folder, run_state):
    running = run_state and run_state.get("active", False)
    if not folder:
        return "Aucun dossier sélectionné", S["badge_info"], True, {**S["btn_disabled"],
                                                                      "fontSize": "15px",
                                                                      "padding": "12px 28px"}
    n = _count_csvs(folder)
    if n == 0:
        badge_text = "Aucun fichier CSV trouvé"
        badge_style = S["badge_err"]
        disabled = True
        btn_style = {**S["btn_disabled"], "fontSize": "15px", "padding": "12px 28px"}
    else:
        if n > 1:
            badge_text = f"{n} fichiers CSV"
        else:
            badge_text = "1 fichier CSV"
        badge_style = S["badge_ok"]
        disabled = running
        btn_style = ({**S["btn_disabled"], "fontSize": "15px", "padding": "12px 28px"}
                     if running else
                     {**S["btn_primary"], "fontSize": "15px", "padding": "12px 28px"})
    return badge_text, badge_style, disabled, btn_style


# ── Callback — Badge dossier de sortie ────────────────────────────────────────

@app.callback(
    Output("output-badge", "children"),
    Output("output-badge", "style"),
    Input("output-dir",  "value"),
    Input("run-state",   "data"),
)
def update_output_info(folder, _run_state):
    if not folder:
        return "Aucun dossier sélectionné", S["badge_info"]

    n_files    = _count_output_files(folder)
    badge_text = f"{n_files} fichier{'s' if n_files != 1 else ''} dans le dossier"
    badge_style = S["badge_ok"] if n_files > 0 else S["badge_warn"]

    return badge_text, badge_style


# ── Callback — Lancement de l'optimisation ────────────────────────────────────

@app.callback(
    Output("run-state", "data"),
    Output("poll-interval", "disabled"),
    Output("log-display", "children"),
    Input("run-btn", "n_clicks"),
    State("input-dir", "value"),
    State("output-dir", "value"),
    State("toggle-multi-client", "value"),
    State("toggle-post-pro", "value"),
    # Paramètres palette
    State("p-pallet-length", "value"),
    State("p-pallet-width", "value"),
    State("p-pallet-max-height", "value"),
    State("p-pallet-max-weight", "value"),
    # Contraintes physiques
    State("p-min-support-ratio", "value"),
    State("p-stability-ratio", "value"),
    # Ergonomique
    State("p-priority2-max-deposit-height", "value"),
    # Repacking multi-client
    State("p-min-filling-ratio", "value"),
    State("p-multi-client-minimum-ratio", "value"),
    State("p-multi-client-maximum-ratio", "value"),
    # LNS mono
    State("p-lns-mono-time-per-pallet", "value"),
    State("p-lns-mono-iter-per-pallet", "value"),
    State("p-lns-mono-random-seed", "value"),
    State("p-lns-mono-small-box-volume", "value"),
    State("p-lns-mono-repair-top-k", "value"),
    State("p-cost-mono-pallet-count", "value"),
    State("p-cost-mono-last-pallet-filling", "value"),
    # LNS multi
    State("p-lns-multi-time-per-pallet", "value"),
    State("p-lns-multi-iter-per-pallet", "value"),
    State("p-lns-multi-random-seed", "value"),
    State("p-lns-multi-destroy-ratio", "value"),
    State("p-lns-multi-repair-top-k", "value"),
    State("p-cost-multi-pallet-count", "value"),
    # Post-traitement
    State("p-pp-time-per-pallet", "value"),
    State("p-pp-iter-per-pallet", "value"),
    State("p-pp-random-seed", "value"),
    State("p-pp-top-k", "value"),
    State("p-pp-w-contact", "value"),
    State("p-pp-w-fill", "value"),
    State("p-pp-w-p2", "value"),
    State("p-pp-w-height", "value"),
    State("p-pp-w-stability", "value"),
    State("p-pp-center-min-shift", "value"),
    State("p-max-workers", "value"),
    prevent_initial_call=True,
)
def launch_run(n_clicks, input_dir, output_dir, multi_client, post_pro,
               pallet_length, pallet_width, pallet_max_height, pallet_max_weight,
               min_support_ratio, stability_ratio, priority2_max_deposit_height,
               min_filling_ratio, multi_client_minimum_ratio, multi_client_maximum_ratio,
               lns_mono_time_per_pallet, lns_mono_iter_per_pallet, lns_mono_random_seed,
               lns_mono_small_box_volume, lns_mono_repair_top_k,
               cost_mono_pallet_count, cost_mono_last_pallet_filling,
               lns_multi_time_per_pallet, lns_multi_iter_per_pallet, lns_multi_random_seed,
               lns_multi_destroy_ratio, lns_multi_repair_top_k, cost_multi_pallet_count,
               pp_time_per_pallet, pp_iter_per_pallet, pp_random_seed, pp_top_k,
               pp_w_contact, pp_w_fill, pp_w_p2, pp_w_height, pp_w_stability,
               pp_center_min_shift, max_workers):

    if not n_clicks or not input_dir or not output_dir:
        return dash.no_update, True, dash.no_update

    def _int(v): return int(v) if v is not None else None

    field_map = {
        "pallet_length": pallet_length,
        "pallet_width": pallet_width,
        "pallet_max_height": pallet_max_height,
        "pallet_max_weight": pallet_max_weight,
        "min_support_ratio": min_support_ratio,
        "stability_ratio": stability_ratio,
        "priority2_max_deposit_height": priority2_max_deposit_height,
        "enable_multi_client": bool(multi_client),
        "min_filling_ratio": min_filling_ratio,
        "multi_client_minimum_ratio": multi_client_minimum_ratio,
        "multi_client_maximum_ratio": multi_client_maximum_ratio,
        "enable_post_processing": "on" in (post_pro or []),
        "lns_mono_time_per_pallet":  lns_mono_time_per_pallet,
        "lns_mono_iter_per_pallet":  _int(lns_mono_iter_per_pallet),
        "lns_mono_random_seed":      _int(lns_mono_random_seed),
        "lns_mono_small_box_volume": lns_mono_small_box_volume,
        "lns_mono_repair_top_k":     _int(lns_mono_repair_top_k),
        "cost_mono_pallet_count":         cost_mono_pallet_count,
        "cost_mono_last_pallet_filling":  cost_mono_last_pallet_filling,
        "lns_multi_time_per_pallet": lns_multi_time_per_pallet,
        "lns_multi_iter_per_pallet": _int(lns_multi_iter_per_pallet),
        "lns_multi_random_seed":     _int(lns_multi_random_seed),
        "lns_multi_destroy_ratio":   lns_multi_destroy_ratio,
        "lns_multi_repair_top_k":    _int(lns_multi_repair_top_k),
        "cost_multi_pallet_count":   cost_multi_pallet_count,
        "pp_time_per_pallet": pp_time_per_pallet,
        "pp_iter_per_pallet": _int(pp_iter_per_pallet),
        "pp_random_seed": _int(pp_random_seed),
        "pp_top_k": _int(pp_top_k),
        "pp_w_contact": pp_w_contact,
        "pp_w_fill": pp_w_fill,
        "pp_w_p2": pp_w_p2,
        "pp_w_height": pp_w_height,
        "pp_w_stability": pp_w_stability,
        "pp_center_min_shift": pp_center_min_shift,
    }
    params = {k: v for k, v in field_map.items() if v is not None}

    # ── Validation des plages avant lancement ─────────────────────────────────
    validation_errors: list[str] = []
    for key, val in params.items():
        if key not in PARAM_BOUNDS:
            continue
        lo, hi = PARAM_BOUNDS[key]
        if not (lo <= val <= hi):
            validation_errors.append(f"{key} = {val}  (plage autorisée : [{lo}, {hi}])")
    if (multi_client_minimum_ratio is not None and multi_client_maximum_ratio is not None
            and multi_client_minimum_ratio >= multi_client_maximum_ratio):
        validation_errors.append(
            "Seuil min multi-client doit être strictement inférieur au seuil max"
        )
    if validation_errors:
        msg = "❌ Paramètres invalides — lancement annulé :\n" + "\n".join(
            f"  • {e}" for e in validation_errors
        )
        return dash.no_update, False, msg

    runner = os.path.join(_DIR, "main.py")

    cmd = [
        sys.executable, runner,
        "--input-dir", input_dir,
        "--output-dir", output_dir,
        "--params-json", json.dumps(params),
        "--max-workers", str(int(max_workers) if max_workers else 1),
    ]

    run_id = str(uuid.uuid4())

    # Input stems (sorted same way as main.py) + start timestamp for batch tracking.
    import time
    input_stems = sorted(p.stem for p in Path(input_dir).glob("*.csv"))
    t_start     = time.time()

    creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, creationflags=creation_flags)
    _runs[run_id] = {
        "proc":        proc,
        "output_dir":  output_dir,
        "input_stems": input_stems,
        "t_start":     t_start,
    }

    new_state = {"active": True, "run_id": run_id}
    total = len(input_stems)
    first_file = f'"{input_stems[0]}.csv"' if input_stems else ""
    log_msg = (f"⟳  Exécution Batch 1/{total} : {first_file}\n"
               f"    Suivez la progression dans la fenêtre terminal.")
    return new_state, False, log_msg


# ── Callback — Polling du log de l'optimisation ───────────────────────────────

@app.callback(
    Output("run-state", "data", allow_duplicate=True),
    Output("poll-interval", "disabled", allow_duplicate=True),
    Output("log-display", "children", allow_duplicate=True),
    Output("run-status-badge", "children"),
    Output("run-status-badge", "style"),
    Input("poll-interval", "n_intervals"),
    State("run-state", "data"),
    prevent_initial_call=True,
)
def poll_run(_, state):
    if not state or not state.get("active"):
        return dash.no_update, True, dash.no_update, "", {}

    run_id = state.get("run_id")
    if not run_id or run_id not in _runs:
        return state, True, "Erreur : processus introuvable.", "Erreur", S["badge_err"]

    run = _runs[run_id]
    proc = run["proc"]
    done = proc.poll() is not None

    new_state = {**state, "active": not done}

    # Count completed batches by checking for results CSVs created since run start.
    # Input files are processed sequentially, so completions are in list order.
    input_stems = run.get("input_stems", [])
    output_dir  = run.get("output_dir", "")
    t_start     = run.get("t_start", 0)
    total       = len(input_stems)

    # Per-batch status: each input stem is "ok" / "fail" / "pending".
    # main.py creates a {stem}_log_*.txt at the START of processing a file, and
    # a {stem}_results_*.csv at the END on success. So:
    #   fresh results          → succeeded
    #   fresh log, no results  → failed (or currently running; we disambiguate
    #                             below: only the last log-without-results
    #                             while the proc is alive is "in progress")
    #   neither                → not yet started
    #
    # Single directory scan per tick: O(files), not O(stems × files). Using
    # glob per stem would become O(N²) as the batch grows and quickly exceeds
    # the 500 ms polling interval — freezing the UI in effect.
    out_p       = Path(output_dir) if output_dir else None
    has_results = set()
    log_by_stem = {}   # stem → Path of its fresh _log_*.txt (if any)
    stem_set    = set(input_stems)
    if out_p and out_p.is_dir():
        try:
            entries = list(out_p.iterdir())
        except Exception:
            entries = []
        for entry in entries:
            try:
                st = entry.stat()
            except (FileNotFoundError, PermissionError):
                continue
            if st.st_mtime < t_start:
                continue
            name = entry.name
            if name.endswith(".csv") and "_results_" in name:
                stem = name.rsplit("_results_", 1)[0]
                if stem in stem_set:
                    has_results.add(stem)
            elif name.endswith(".txt") and "_log_" in name:
                stem = name.rsplit("_log_", 1)[0]
                if stem in stem_set:
                    log_by_stem[stem] = entry
    # Logged but not (yet) succeeded — either currently running or failed.
    has_log_only = set(log_by_stem) - has_results

    statuses = []
    for stem in input_stems:
        if stem in has_results:
            statuses.append("ok")
        elif stem in has_log_only:
            if done:
                statuses.append("fail")
            else:
                # Seek to last 8 KB only — negligible I/O (~500 µs per file).
                # Marker absent → worker still running; present → finished with error.
                code = _read_batch_status(log_by_stem[stem])
                statuses.append("fail" if code else "running")
        else:
            statuses.append("pending")

    # When the run is over, catch silent failures: batches that produced a
    # results CSV but were flagged failed by main.py (Phase 6 integrity check).
    if done:
        for i, stem in enumerate(input_stems):
            if statuses[i] != "ok":
                continue
            log_path = log_by_stem.get(stem)
            if log_path is None:
                continue
            code = _read_batch_status(log_path)
            if code and code != "OK":
                statuses[i] = "fail"

    lines = []
    for i, (stem, status) in enumerate(zip(input_stems, statuses), start=1):
        if status == "ok":
            lines.append(
                f'✓  Exécution Batch {i}/{total} : "{stem}.csv" terminée avec succès.'
            )
        elif status == "fail":
            lines.append(
                f'✗  Erreur lors de l\'exécution Batch {i}/{total} : "{stem}.csv" '
                f"— Veuillez consulter le rapport d'exécution (log) dans le dossier de sortie."
            )
        elif status == "running":
            lines.append(
                f'⟳  Exécution Batch {i}/{total} : "{stem}.csv"'
            )
            lines.append("    Suivez la progression dans la fenêtre terminal.")
        # "pending" → not printed yet (file not started)

    if done:
        # With the BATCH-STATUS marker now authoritative, per-stem fail count
        # is the single source of truth for the badge. The subprocess return
        # code is just a by-product (failed > 0 → rc=1) and not displayed.
        n_fail = sum(1 for s in statuses if s == "fail")
        if n_fail == 0:
            badge_text  = "✓  Terminé avec succès"
            badge_style = {**S["badge_ok"], "fontSize": "13px", "padding": "4px 12px"}
        else:
            badge_text  = f"✗  {n_fail} échec(s) sur {total}"
            badge_style = {**S["badge_err"], "fontSize": "13px", "padding": "4px 12px"}
        log_msg = "\n".join(lines) if lines else "✓  Exécution terminée."
        return new_state, True, log_msg, badge_text, badge_style
    else:
        # No "running" marker yet? Add one for the first pending file so the
        # user sees something between "Batch started" and "log file created".
        if not any(s == "running" for s in statuses):
            for i, s in enumerate(statuses):
                if s == "pending":
                    lines.append(
                        f'⟳  Exécution Batch {i+1}/{total} : "{input_stems[i]}.csv"'
                    )
                    lines.append("    Suivez la progression dans la fenêtre terminal.")
                    break
        badge_text  = "⟳  En cours..."
        badge_style = {**S["badge_warn"], "fontSize": "13px", "padding": "4px 12px"}
        return new_state, False, "\n".join(lines), badge_text, badge_style




# ── Callbacks — Grisage conditionnel des groupes de paramètres ───────────────

_STYLE_ENABLED  = {}
_STYLE_DISABLED = {"opacity": "0.4", "pointerEvents": "none", "userSelect": "none"}

_WORKERS_BASE = {"marginTop": "4px"}


@app.callback(
    Output("workers-param-wrapper", "style"),
    Input("input-dir", "value"),
)
def toggle_workers(folder):
    n = _count_csvs(folder) if folder else 0
    if n >= 4:
        return _WORKERS_BASE
    return {**_WORKERS_BASE, **_STYLE_DISABLED}

@app.callback(
    Output("mc-param-wrapper", "style"),
    Output("p-min-filling-ratio", "disabled"),
    Output("p-multi-client-minimum-ratio", "disabled"),
    Output("p-multi-client-maximum-ratio", "disabled"),
    Output("lns-multi-param-wrapper", "style"),
    Output("p-lns-multi-time-per-pallet", "disabled"),
    Output("p-lns-multi-iter-per-pallet", "disabled"),
    Output("p-lns-multi-random-seed", "disabled"),
    Output("p-lns-multi-destroy-ratio", "disabled"),
    Output("p-lns-multi-repair-top-k", "disabled"),
    Output("p-cost-multi-pallet-count", "disabled"),
    Input("toggle-multi-client", "value"),
)
def toggle_mc_params(value):
    enabled = "on" in (value or [])
    dis = not enabled
    style = _STYLE_ENABLED if enabled else _STYLE_DISABLED
    return style, dis, dis, dis, style, dis, dis, dis, dis, dis, dis


@app.callback(
    Output("pp-param-wrapper", "style"),
    Output("p-pp-time-per-pallet", "disabled"),
    Output("p-pp-iter-per-pallet", "disabled"),
    Output("p-pp-random-seed", "disabled"),
    Output("p-pp-w-contact", "disabled"),
    Output("p-pp-w-fill", "disabled"),
    Output("p-pp-w-p2", "disabled"),
    Output("p-pp-w-height", "disabled"),
    Output("p-pp-w-stability", "disabled"),
    Output("p-pp-center-min-shift", "disabled"),
    Output("p-pp-top-k", "disabled"),
    Input("toggle-post-pro", "value"),
)
def toggle_pp_params(value):
    enabled = "on" in (value or [])
    dis = not enabled
    style = _STYLE_ENABLED if enabled else _STYLE_DISABLED
    return style, dis, dis, dis, dis, dis, dis, dis, dis, dis, dis


# ── Auto-scroll du log via callback côté client ───────────────────────────────
app.clientside_callback(
    """
    function(log_text) {
        var el = document.getElementById('log-display');
        if (el) { el.scrollTop = el.scrollHeight; }
        return '';
    }
    """,
    Output("log-display", "data-autoscroll"),
    Input("log-display", "children"),
)


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    import webbrowser
    from threading import Timer

    host = os.environ.get("PALLET_HOST", "127.0.0.1")
    port = int(os.environ.get("PALLET_PORT", "8050"))
    url  = f"http://{host}:{port}"

    print(f"\n[App] Interface Pallet Optimizer disponible sur : {url}")
    print("[App] Appuyez sur Ctrl+C pour arrêter.\n")

    if host == "127.0.0.1":
        Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(debug=False, host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    main()
