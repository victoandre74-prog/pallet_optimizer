"""
app.py — Interface Dash centralisée pour Pallet Optimizer.

Page unique avec trois sections :
  1. Paramétrage & Exécution
  2. Visualisation
  3. Export

Usage :
    python app.py
"""

import sys
import os
import json
import uuid
import atexit
import base64
import subprocess
from dataclasses import asdict
from pathlib import Path

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from config.parameters import OptimizationParameters


def _load_logo(filename: str) -> str:
    path = os.path.join(_DIR, filename)
    if not os.path.exists(path):
        return ""
    ext  = filename.rsplit(".", 1)[-1].lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(path, "rb") as f:
        return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()


_LOGO_FOURNIER = _load_logo("logo_fournier.png")
_LOGO_U4LOG    = _load_logo("logo_u4log.jpg")
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import dash
from dash import dcc, html, Input, Output, State, ctx
import pandas as pd

# ── Global subprocess store ────────────────────────────────────────────────────
# stdout du subprocess est redirigé vers un fichier log (pas de PIPE).
# Le parent lit ce fichier toutes les 500ms — aucun overhead inter-processus.
_runs: dict = {}    # run_id   → {proc: Popen, log_file: str}
_exports: dict = {} # export_id → {proc: Popen, log_file: str}

# Dashboard / Rapport KPI : un seul subprocess vivant à la fois par type
# (sinon le nouveau bind échoue silencieusement sur le port et l'ancien sert
# des données périmées).
_dashboard_proc = None  # subprocess.Popen | None
_kpi_proc       = None  # subprocess.Popen | None


def _kill_if_alive(proc):
    """Termine un subprocess s'il existe et tourne encore. Silencieux."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
    except Exception:
        pass


def _cleanup_subprocesses():
    """Tue dashboard + KPI à la sortie d'app.py pour éviter les processus
    orphelins qui continuent de servir d'anciennes données sur 8051/8052."""
    _kill_if_alive(_dashboard_proc)
    _kill_if_alive(_kpi_proc)


atexit.register(_cleanup_subprocesses)


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


def _list_output_csvs(folder: str) -> list[dict]:
    """
    Liste les CSV de résultats dans le dossier de sortie.
    Priorité : postprocessed > results > autres.
    Retourne une liste d'options pour dcc.Dropdown.
    """
    try:
        p = Path(folder)
        if not p.is_dir():
            return []
        csvs = sorted(p.glob("*_results*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not csvs:
            return []
        # Trier : postprocessed d'abord
        post = [f for f in csvs if "postprocessed" in f.name]
        other = [f for f in csvs if "postprocessed" not in f.name]
        ordered = post + other
        return [{"label": f.name, "value": str(f)} for f in ordered]
    except Exception:
        return []


def _count_pallets(csv_path: str) -> int:
    """Compte le nombre de palettes uniques dans un CSV de résultats."""
    try:
        df = pd.read_csv(csv_path, sep=";", usecols=["pallet_id"])
        return int(df["pallet_id"].nunique())
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


def _param_field(label: str, input_id: str, value, step=None, hint: str = "") -> html.Div:
    """Un champ de paramètre : étiquette + input numérique + hint."""
    inp_type = "number"
    inp_kwargs = {"value": value, "id": input_id, "type": inp_type, "style": S["input"]}
    if step is not None:
        inp_kwargs["step"] = step
    return html.Div([
        html.Label(label, style=S["label"]),
        dcc.Input(**inp_kwargs),
        html.Div(hint, style=S["hint"]) if hint else None,
    ], style={"display": "flex", "flexDirection": "column"})


def _folder_row(label: str, path_id: str, browse_id: str, badge_id: str,
                badge_text: str, hint: str = None) -> html.Div:
    """Rangée : étiquette + champ chemin + bouton Browse + badge (+ hint optionnel)."""
    children = [
        html.Label(label, style=S["label"]),
        html.Div([
            dcc.Input(id=path_id, type="text", placeholder="Chemin du dossier...",
                      style={**S["input"], "flex": "1"}),
            html.Button("Parcourir", id=browse_id, n_clicks=0, style=S["btn_sm"]),
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
                        hint="Tous les fichiers .csv dans le dossier seront traités l'un après l'autre."),
            _folder_row("Dossier de sortie (output)",
                        "output-dir", "browse-output", "output-badge",
                        "Aucun dossier sélectionné",
                        hint="Tous les fichiers de résultats seront stockés dans le dossier."),
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
                         hint="Ex : 130 cm pour une palette standard EUR"),
            _param_field("Largeur (cm) — axe Y", "p-pallet-width",
                         DEFAULTS["pallet_width"], step=1,
                         hint="Ex : 80 cm pour une palette standard EUR"),
            _param_field("Hauteur max (cm) — axe Z", "p-pallet-max-height",
                         DEFAULTS["pallet_max_height"], step=1,
                         hint="Hauteur maximale d'empilement"),
            _param_field("Poids max (kg)", "p-pallet-max-weight",
                         DEFAULTS["pallet_max_weight"], step=10,
                         hint="Capacité de charge maximale"),
        ], open_by_default=True),

        _details_group("Contraintes physiques et stabilité", [
            _param_field("Ratio de support minimum", "p-min-support-ratio",
                         DEFAULTS["min_support_ratio"], step=0.01,
                         hint="Fraction de la base devant reposer sur un support (0.75 = 75 %)"),
            _param_field("Ratio de stabilité", "p-stability-ratio",
                         DEFAULTS["stability_ratio"], step=0.1,
                         hint="Rapport max hauteur/base d'une pile — empêche les tours instables"),
        ], open_by_default=True),

        _details_group("Contrainte ergonomique", [
            _param_field("Hauteur max dépôt P2 (cm)", "p-priority2-max-deposit-height",
                         DEFAULTS["priority2_max_deposit_height"], step=5,
                         hint="Hauteur max à laquelle le bas d'un colis priorité 2 peut être déposé manuellement"),
        ], open_by_default=True),

        html.Div(_details_group("Repacking Multi-Client", [
            _param_field("Seuil de remplissage min.", "p-min-filling-ratio",
                         DEFAULTS["min_filling_ratio"], step=0.01,
                         hint="Régime ≤10 palettes : on continue de fusionner tant que la moyenne du remplissage du futur pool multi reste sous ce seuil (0.30 = 30 %)."),
            _param_field("Seuil d'arrêt multi-client (min)", "p-multi-client-minimum-ratio",
                         DEFAULTS["multi_client_minimum_ratio"], step=0.01,
                         hint="Régime ≥11 palettes : arrêt doux quand multi/total > ce seuil ET la palette mono la moins remplie est déjà bien remplie (0.13 = 13 %)."),
            _param_field("Seuil d'arrêt multi-client (max)", "p-multi-client-maximum-ratio",
                         DEFAULTS["multi_client_maximum_ratio"], step=0.01,
                         hint="Régime ≥11 palettes : arrêt forcé dès que multi/total > ce seuil, quelles que soient les conditions (0.17 = 17 %)."),
        ], open_by_default=True), id="mc-param-wrapper"),

        _details_group("Paramètres avancés - LNS Mono", [
            _sub_header("Budget"),
            _param_field("Temps max (s)", "p-lns-mono-time-limit",
                         DEFAULTS["lns_mono_time_limit"], step=10,
                         hint="Réduire pour accélérer."),
            _param_field("Itérations max", "p-lns-mono-max-iterations",
                         DEFAULTS["lns_mono_max_iterations"], step=100,
                         hint="Plafond d'itérations."),
            _param_field("Graine aléatoire", "p-lns-mono-random-seed",
                         DEFAULTS["lns_mono_random_seed"], step=1,
                         hint="Graine pour reproductibilité."),
            _sub_header("Comportement"),
            _param_field("Volume petit colis (cm³)", "p-lns-mono-small-box-volume",
                         DEFAULTS["lns_mono_small_box_volume"], step=1000,
                         hint="Colis sous ce volume extraits des palettes survivantes à chaque itération."),
            _param_field("Pool de positions (top-k)", "p-lns-mono-repair-top-k",
                         DEFAULTS["lns_mono_repair_top_k"], step=1,
                         hint="Tirage aléatoire parmi les k meilleures positions EP × orientation."),
            _sub_header("Fonction de coût"),
            _param_field("Poids nombre de palettes", "p-cost-mono-pallet-count",
                         DEFAULTS["cost_mono_pallet_count"], step=10,
                         hint="Pénalité par palette supplémentaire."),
            _param_field("Poids remplissage dernière palette", "p-cost-mono-last-pallet-filling",
                         DEFAULTS["cost_mono_last_pallet_filling"], step=10,
                         hint="Pénalise le taux de remplissage élevé de la palette la moins remplie."),
        ]),

        html.Div(_details_group("Paramètres avancés - LNS Multi", [
            _sub_header("Budget"),
            _param_field("Temps max (s)", "p-lns-multi-time-limit",
                         DEFAULTS["lns_multi_time_limit"], step=5,
                         hint="Phase 4."),
            _param_field("Itérations max", "p-lns-multi-max-iterations",
                         DEFAULTS["lns_multi_max_iterations"], step=100,
                         hint="Plafond d'itérations."),
            _param_field("Graine aléatoire", "p-lns-multi-random-seed",
                         DEFAULTS["lns_multi_random_seed"], step=1,
                         hint="Graine pour reproductibilité."),
            _sub_header("Comportement"),
            _param_field("Ratio destruction (destroy_ratio)", "p-lns-multi-destroy-ratio",
                         DEFAULTS["lns_multi_destroy_ratio"], step=0.01,
                         hint="Fraction des palettes les moins remplies détruites à chaque itération (min 1)."),
            _param_field("Pool de positions (top-k)", "p-lns-multi-repair-top-k",
                         DEFAULTS["lns_multi_repair_top_k"], step=1,
                         hint="Tirage aléatoire parmi les k meilleures positions lors de la réparation."),
            _sub_header("Fonction de coût"),
            _param_field("Poids nombre de palettes", "p-cost-multi-pallet-count",
                         DEFAULTS["cost_multi_pallet_count"], step=1,
                         hint="Pénalité par palette supplémentaire (multi-client)."),
        ]), id="lns-multi-param-wrapper"),

        html.Div(_details_group("Paramètres avancés - Post-traitement", [
            _sub_header("Budget"),
            _param_field("Temps max (s)", "p-pp-time-limit",
                         DEFAULTS["pp_time_limit"], step=10,
                         hint="Par groupe client."),
            _param_field("Itérations max", "p-pp-max-iterations",
                         DEFAULTS["pp_max_iterations"], step=50,
                         hint="Plafond d'itérations post-traitement."),
            _param_field("Graine aléatoire", "p-pp-random-seed",
                         DEFAULTS["pp_random_seed"], step=1,
                         hint="Graine pour reproductibilité."),
            _param_field("Pool de candidats (top_k)", "p-pp-top-k",
                         DEFAULTS["pp_top_k"], step=1,
                         hint="Taille du pool de positions candidates lors du placement."),
            _sub_header("Pondérations"),
            _param_field("Poids contact P2→P1", "p-pp-w-contact",
                         DEFAULTS["pp_w_contact"], step=1.0,
                         hint="Récompense / cm² de contact vertical P2→P1."),
            _param_field("Poids variance remplissage", "p-pp-w-fill",
                         DEFAULTS["pp_w_fill"], step=0.5,
                         hint="Pénalité sur la variance du taux de remplissage entre palettes."),
            _param_field("Poids variance P2", "p-pp-w-p2",
                         DEFAULTS["pp_w_p2"], step=100.0,
                         hint="Pénalité sur la variance du nombre de colis P2 entre palettes."),
            _param_field("Poids hauteur moyenne", "p-pp-w-height",
                         DEFAULTS["pp_w_height"], step=1.0,
                         hint="Pénalité sur le ratio hauteur/hauteur max moyen — favorise les palettes basses."),
            _param_field("Poids stabilité", "p-pp-w-stability",
                         DEFAULTS["pp_w_stability"], step=1.0,
                         hint="Pénalité sur le pire ratio de stabilité — favorise les empilements stables."),
            _param_field("Décalage min centrage (cm)", "p-pp-center-min-shift",
                         DEFAULTS["pp_center_min_shift"], step=0.5,
                         hint="Seuil de déplacement en cm pour appliquer le centrage de charge."),
        ]), id="pp-param-wrapper"),

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

    # ── Section 3 — Visualisation ─────────────────────────────────────────────
    section2 = html.Div([
        _section_title("3", "Visualisation"),
        html.Div([
            html.Div([
                html.Label("Fichier de résultats à visualiser", style=S["label"]),
                dcc.Dropdown(id="viz-file-dropdown", options=[],
                             placeholder="Sélectionnez un fichier de résultats...",
                             style={"fontSize": "13px"}, clearable=False),
            ], style={"flex": "1"}),
            html.Div([
                html.Br(),
                html.Button("🖥  Ouvrir le Dashboard", id="open-dashboard-btn",
                            n_clicks=0, disabled=True,
                            style={**S["btn_primary"], "whiteSpace": "nowrap"}),
            ], style={"display": "flex", "flexDirection": "column", "justifyContent": "flex-end"}),
        ], style={**S["row"], "alignItems": "flex-end"}),
        html.Div("", id="viz-status", style={"marginTop": "8px", "fontSize": "13px"}),
    ], style=S["card"])

    # ── Section 4 — Export ────────────────────────────────────────────────────
    section3 = html.Div([
        _section_title("4", "Export Images"),
        html.Div([
            html.Div([
                html.Label("Fichier de résultats à exporter", style=S["label"]),
                dcc.Dropdown(id="export-file-dropdown", options=[],
                             placeholder="Sélectionnez un fichier de résultats...",
                             style={"fontSize": "13px"}, clearable=False),
                html.Div("", id="export-time-estimate",
                         style={**S["hint"], "marginTop": "8px", "fontSize": "12px",
                                "color": "#6b7280"}),
            ], style={"flex": "1"}),
            html.Div([
                html.Br(),
                html.Button("💾  Exporter les images", id="export-btn",
                            n_clicks=0, disabled=True,
                            style={**S["btn_success"], "whiteSpace": "nowrap"}),
            ], style={"display": "flex", "flexDirection": "column", "justifyContent": "flex-end"}),
        ], style={**S["row"], "alignItems": "flex-end"}),
        html.Pre("", id="export-log",
                 style={**S["log"], "minHeight": "60px", "display": "none"}),
        html.Div("", id="export-status", style={"marginTop": "8px", "fontSize": "13px"}),
    ], style=S["card"])

    # ── Section 2 — Rapport KPI ───────────────────────────────────────────────
    section4 = html.Div([
        _section_title("2", "Rapport KPI"),
        html.Div([
            html.Div([
                html.Label("Dossier de sortie analysé", style=S["label"]),
                html.Div(id="kpi-output-dir-display",
                         style={"fontSize": "13px", "color": "#6b7280",
                                "fontStyle": "italic", "padding": "6px 0"}),
            ], style={"flex": "1"}),
            html.Div([
                html.Br(),
                html.Button("📊  Ouvrir le Rapport KPI", id="open-kpi-btn",
                            n_clicks=0, disabled=True,
                            style={**S["btn_disabled"], "whiteSpace": "nowrap"}),
            ], style={"display": "flex", "flexDirection": "column", "justifyContent": "flex-end"}),
        ], style={**S["row"], "alignItems": "flex-end"}),
        html.Div("", id="kpi-status", style={"marginTop": "8px", "fontSize": "13px"}),
    ], style=S["card"])

    # ── Assemblage 2 colonnes ─────────────────────────────────────────────────
    return html.Div([
        # En-tête — même charte graphique que le dashboard
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
                    children=[html.H2("Pallet Optimizer — Interface de contrôle",
                                      style={"color": "#333", "margin": "0"})],
                ),
                html.Img(src=_LOGO_U4LOG,
                         style={"height": "68px", "objectFit": "contain",
                                "marginLeft": "auto"}) if _LOGO_U4LOG else html.Div(style={"marginLeft": "auto"}),
            ],
        ),

        # Grille 2 colonnes (70 % / 30 %)
        html.Div([
            html.Div([section1],
                     style={"flex": "70", "minWidth": "0"}),
            html.Div([section4, section2, section3],
                     style={"flex": "30", "minWidth": "0"}),
        ], style={**S["content"], "display": "flex", "gap": "20px",
                  "alignItems": "flex-start"}),

        # Composants invisibles
        dcc.Interval(id="poll-interval", interval=500, n_intervals=0, disabled=True),
        dcc.Interval(id="export-poll-interval", interval=600, n_intervals=0, disabled=True),
        # Single-shot timer that re-enables the "Ouvrir le Rapport KPI" button
        # ~40 s after a click — measured cold-start of the kpi_report.py
        # subprocess on a large batch (cold Python imports + ~141 CSV parse +
        # Dash boot + browser tab opening). Prevents accidental double-launches
        # that would race on port 8052.
        dcc.Interval(id="kpi-relock-interval", interval=40000, n_intervals=0,
                     max_intervals=1, disabled=True),
        dcc.Store(id="run-state", data={"active": False, "run_id": None}),
        dcc.Store(id="export-state", data={"active": False, "export_id": None}),
        dcc.Store(id="kpi-launching", data=False),

    ], style=S["page"])


# ── Application ────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    title="Pallet Optimizer",
    suppress_callback_exceptions=True,
)
app.layout = _build_layout()


# Auto-scroll log-style <pre> boxes (#log-display, #export-log) to the bottom
# whenever their content is updated, so the latest line is always visible —
# like a terminal. Uses MutationObserver so no per-update Dash callback needed.
app.index_string = app.index_string.replace(
    "<head>",
    "<head>"
    "<script>"
    "(function() {"
    "  var SEL = '#log-display, #export-log';"
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


# ── Callback — Badge dossier de sortie + mise à jour des dropdowns ─────────────

@app.callback(
    Output("output-badge", "children"),
    Output("output-badge", "style"),
    Output("viz-file-dropdown", "options"),
    Output("viz-file-dropdown", "value"),
    Output("export-file-dropdown", "options"),
    Output("export-file-dropdown", "value"),
    Input("output-dir", "value"),
    Input("run-state", "data"),
)
def update_output_info(folder, run_state):
    """Rafraîchit badge + dropdowns à chaque changement de dossier ou fin de run."""
    if not folder:
        no_opts = []
        return ("Aucun dossier sélectionné", S["badge_info"],
                no_opts, None, no_opts, None)

    n_files = _count_output_files(folder)
    badge_text = f"{n_files} fichier{'s' if n_files != 1 else ''} dans le dossier"
    badge_style = S["badge_ok"] if n_files > 0 else S["badge_warn"]

    opts = _list_output_csvs(folder)
    default = opts[0]["value"] if opts else None

    return badge_text, badge_style, opts, default, opts, default


# ── Callback — Activation boutons viz + export ─────────────────────────────────

@app.callback(
    Output("open-dashboard-btn", "disabled"),
    Output("open-dashboard-btn", "style"),
    Output("export-btn", "disabled"),
    Output("export-btn", "style"),
    Input("viz-file-dropdown", "value"),
    Input("export-file-dropdown", "value"),
    Input("export-state", "data"),
)
def update_action_buttons(viz_file, export_file, export_state):
    exporting = export_state and export_state.get("active", False)

    viz_has_file = bool(viz_file)
    dash_disabled = not viz_has_file
    dash_style = (S["btn_primary"] if viz_has_file
                  else {**S["btn_disabled"]})

    exp_has_file = bool(export_file)
    exp_disabled = not exp_has_file or exporting
    exp_style = ({**S["btn_disabled"]} if exp_disabled else S["btn_success"])

    return dash_disabled, dash_style, exp_disabled, exp_style


# ── Callback — Estimation du temps d'export ───────────────────────────────────

@app.callback(
    Output("export-time-estimate", "children"),
    Input("export-file-dropdown", "value"),
)
def update_export_estimate(csv_path):
    if not csv_path:
        return ""
    n = _count_pallets(csv_path)
    if n == 0:
        return "Impossible de lire le fichier sélectionné."
    secs = n * 5
    mins = secs // 60
    rem = secs % 60
    time_str = f"{mins}m {rem}s" if mins > 0 else f"{rem}s"
    return f"⏱  Temps estimé : {n} palette{'s' if n > 1 else ''} × 5 s ≈ {time_str}"


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
    State("p-lns-mono-time-limit", "value"),
    State("p-lns-mono-max-iterations", "value"),
    State("p-lns-mono-random-seed", "value"),
    State("p-lns-mono-small-box-volume", "value"),
    State("p-lns-mono-repair-top-k", "value"),
    State("p-cost-mono-pallet-count", "value"),
    State("p-cost-mono-last-pallet-filling", "value"),
    # LNS multi
    State("p-lns-multi-time-limit", "value"),
    State("p-lns-multi-max-iterations", "value"),
    State("p-lns-multi-random-seed", "value"),
    State("p-lns-multi-destroy-ratio", "value"),
    State("p-lns-multi-repair-top-k", "value"),
    State("p-cost-multi-pallet-count", "value"),
    # Post-traitement
    State("p-pp-time-limit", "value"),
    State("p-pp-max-iterations", "value"),
    State("p-pp-random-seed", "value"),
    State("p-pp-top-k", "value"),
    State("p-pp-w-contact", "value"),
    State("p-pp-w-fill", "value"),
    State("p-pp-w-p2", "value"),
    State("p-pp-w-height", "value"),
    State("p-pp-w-stability", "value"),
    State("p-pp-center-min-shift", "value"),
    prevent_initial_call=True,
)
def launch_run(n_clicks, input_dir, output_dir, multi_client, post_pro,
               pallet_length, pallet_width, pallet_max_height, pallet_max_weight,
               min_support_ratio, stability_ratio, priority2_max_deposit_height,
               min_filling_ratio, multi_client_minimum_ratio, multi_client_maximum_ratio,
               lns_mono_time_limit, lns_mono_max_iterations, lns_mono_random_seed,
               lns_mono_small_box_volume, lns_mono_repair_top_k,
               cost_mono_pallet_count, cost_mono_last_pallet_filling,
               lns_multi_time_limit, lns_multi_max_iterations, lns_multi_random_seed,
               lns_multi_destroy_ratio, lns_multi_repair_top_k, cost_multi_pallet_count,
               pp_time_limit, pp_max_iterations, pp_random_seed, pp_top_k,
               pp_w_contact, pp_w_fill, pp_w_p2, pp_w_height, pp_w_stability,
               pp_center_min_shift):

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
        "lns_mono_time_limit": lns_mono_time_limit,
        "lns_mono_max_iterations": _int(lns_mono_max_iterations),
        "lns_mono_random_seed": _int(lns_mono_random_seed),
        "lns_mono_small_box_volume": lns_mono_small_box_volume,
        "lns_mono_repair_top_k": _int(lns_mono_repair_top_k),
        "cost_mono_pallet_count": cost_mono_pallet_count,
        "cost_mono_last_pallet_filling": cost_mono_last_pallet_filling,
        "lns_multi_time_limit": lns_multi_time_limit,
        "lns_multi_max_iterations": _int(lns_multi_max_iterations),
        "lns_multi_random_seed": _int(lns_multi_random_seed),
        "lns_multi_destroy_ratio": lns_multi_destroy_ratio,
        "lns_multi_repair_top_k": _int(lns_multi_repair_top_k),
        "cost_multi_pallet_count": cost_multi_pallet_count,
        "pp_time_limit": pp_time_limit,
        "pp_max_iterations": _int(pp_max_iterations),
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

    runner = os.path.join(_DIR, "main.py")

    cmd = [
        sys.executable, runner,
        "--input-dir", input_dir,
        "--output-dir", output_dir,
        "--params-json", json.dumps(params),
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
            statuses.append("fail" if done else "running")
        else:
            statuses.append("pending")

    # When the run is over, consult the batch-status contract marker (see
    # _read_batch_status / main.py::BATCH_STATUS_MARKER) to catch silent
    # failures: batches that produced a results CSV but were still flagged as
    # failed by main.py (typically Phase 6 integrity check). File presence
    # alone cannot tell those apart from true successes.
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

    # While proc is running, the file currently being processed has its log
    # already written but no result yet. Treat only the LAST such entry as
    # "running"; any earlier log-without-results means a genuine failure
    # (main.py moved on to the next file).
    if not done:
        last_running = None
        for i, s in enumerate(statuses):
            if s == "running":
                last_running = i
        if last_running is not None:
            for i in range(last_running):
                if statuses[i] == "running":
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


# ── Callback — Ouvrir le Dashboard ───────────────────────────────────────────

@app.callback(
    Output("viz-status", "children"),
    Input("open-dashboard-btn", "n_clicks"),
    State("viz-file-dropdown", "value"),
    prevent_initial_call=True,
)
def open_dashboard(n_clicks, csv_path):
    if not n_clicks or not csv_path:
        return ""
    if not os.path.isfile(csv_path):
        return html.Span("Fichier introuvable.", style=S["badge_err"])

    global _dashboard_proc
    _kill_if_alive(_dashboard_proc)

    dashboard_script = os.path.join(_DIR, "visualization", "pallet_dashboard.py")
    _dashboard_proc = subprocess.Popen(
        [sys.executable, dashboard_script, csv_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return html.Span("Dashboard en cours d'ouverture veuillez patienter..", style=S["badge_ok"])


# ── Callback — Dossier de sortie affiché dans section 4 ──────────────────────

@app.callback(
    Output("kpi-output-dir-display", "children"),
    Output("open-kpi-btn", "disabled"),
    Output("open-kpi-btn", "style"),
    Input("output-dir", "value"),
    Input("run-state", "data"),
    Input("kpi-launching", "data"),
)
def update_kpi_dir_display(folder, _run_state, launching):
    """Disabled when:
       - the output folder is empty / has no CSV  → can't open anything, OR
       - a KPI subprocess was just launched and is still spinning up
         (`kpi-launching` flag) → prevents double-clicks racing on port 8052.
    """
    has_dir  = bool(folder) and os.path.isdir(folder or "")
    has_csvs = has_dir and _list_output_csvs(folder)
    disabled = (not has_csvs) or bool(launching)
    style = ({**S["btn_disabled"], "whiteSpace": "nowrap"} if disabled
             else {**S["btn_primary"], "whiteSpace": "nowrap"})
    return folder or "Aucun dossier sélectionné", disabled, style


# ── Callback — Ouvrir le Rapport KPI ─────────────────────────────────────────

@app.callback(
    Output("kpi-status", "children"),
    Output("kpi-launching", "data", allow_duplicate=True),
    Output("kpi-relock-interval", "disabled", allow_duplicate=True),
    Output("kpi-relock-interval", "n_intervals"),
    Input("open-kpi-btn", "n_clicks"),
    State("output-dir", "value"),
    prevent_initial_call=True,
)
def open_kpi_report(n_clicks, output_dir):
    if not n_clicks:
        return "", False, True, 0
    global _kpi_proc
    _kill_if_alive(_kpi_proc)

    kpi_script = os.path.join(_DIR, "visualization", "kpi_report.py")
    cmd = [sys.executable, kpi_script]
    if output_dir and os.path.isdir(output_dir):
        cmd.append(output_dir)
    _kpi_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    # Set launching=True (button gets greyed out via update_kpi_dir_display)
    # and start the single-shot relock interval (n_intervals reset to 0 so the
    # interval fires its 1 tick from a fresh state on each click).
    return (
        html.Span("Rapport KPI en cours d'ouverture, veuillez patienter…",
                  style=S["badge_ok"]),
        True,    # kpi-launching = True
        False,   # kpi-relock-interval enabled
        0,       # reset interval tick counter
    )


# ── Callback — Réactivation du bouton après le délai ──────────────────────────

@app.callback(
    Output("kpi-launching", "data"),
    Output("kpi-relock-interval", "disabled"),
    Input("kpi-relock-interval", "n_intervals"),
    prevent_initial_call=True,
)
def _clear_kpi_launching(n_intervals):
    """Fires once ~8 s after the click, clears the launching flag (which
    re-enables the button via update_kpi_dir_display) and disables the
    interval until the next click."""
    if not n_intervals:
        raise dash.exceptions.PreventUpdate
    return False, True


# ── Callback — Lancer l'export d'images ───────────────────────────────────────

@app.callback(
    Output("export-state", "data"),
    Output("export-poll-interval", "disabled"),
    Output("export-log", "style"),
    Output("export-log", "children"),
    Input("export-btn", "n_clicks"),
    State("export-file-dropdown", "value"),
    State("output-dir", "value"),
    prevent_initial_call=True,
)
def launch_export(n_clicks, csv_path, output_dir):
    if not n_clicks or not csv_path:
        return dash.no_update, True, {"display": "none"}, ""
    if not os.path.isfile(csv_path):
        return dash.no_update, True, {**S["log"], "display": "block"}, "Fichier introuvable."

    # Dossier de sortie des images : {output_dir}/pallet_images/ ou à côté du CSV
    if output_dir and os.path.isdir(output_dir):
        img_dir = os.path.join(output_dir, "pallet_images")
    else:
        img_dir = os.path.join(os.path.dirname(csv_path), "pallet_images")

    exporter = os.path.join(_DIR, "visualization", "export_pallet_images.py")
    cmd = [sys.executable, exporter, csv_path, img_dir]

    export_id = str(uuid.uuid4())
    os.makedirs(img_dir, exist_ok=True)
    creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, creationflags=creation_flags)
    _exports[export_id] = {"proc": proc}

    new_state = {"active": True, "export_id": export_id}
    log_style = {**S["log"], "display": "block"}
    log_msg = f"⟳  Export lancé dans la fenêtre terminal.\n    Suivez la progression dans cette fenêtre.\n    Destination : {img_dir}"
    return new_state, False, log_style, log_msg


# ── Callback — Polling de l'export ───────────────────────────────────────────

@app.callback(
    Output("export-state", "data", allow_duplicate=True),
    Output("export-poll-interval", "disabled", allow_duplicate=True),
    Output("export-log", "children", allow_duplicate=True),
    Output("export-status", "children"),
    Input("export-poll-interval", "n_intervals"),
    State("export-state", "data"),
    prevent_initial_call=True,
)
def poll_export(_, state):
    if not state or not state.get("active"):
        return dash.no_update, True, dash.no_update, ""

    export_id = state.get("export_id")
    if not export_id or export_id not in _exports:
        return state, True, "Erreur : processus introuvable.", ""

    run = _exports[export_id]
    proc = run["proc"]
    done = proc.poll() is not None

    new_state = {**state, "active": not done}
    running_msg = "⟳  Export lancé dans la fenêtre terminal.\n    Suivez la progression dans cette fenêtre."

    if done:
        rc = proc.returncode
        if rc == 0:
            status = html.Span("✓  Export terminé avec succès.", style=S["badge_ok"])
            log_msg = "✓  Export terminé avec succès."
        else:
            status = html.Span(f"✗  Erreur lors de l'export (code {rc}).", style=S["badge_err"])
            log_msg = f"✗  Erreur lors de l'export (code {rc})."
        return new_state, True, log_msg, status
    else:
        return new_state, False, running_msg, html.Span("⟳  Export en cours...", style=S["badge_warn"])


# ── Callbacks — Grisage conditionnel des groupes de paramètres ───────────────

_STYLE_ENABLED  = {}
_STYLE_DISABLED = {"opacity": "0.4", "pointerEvents": "none", "userSelect": "none"}

@app.callback(
    Output("mc-param-wrapper", "style"),
    Output("p-min-filling-ratio", "disabled"),
    Output("p-multi-client-minimum-ratio", "disabled"),
    Output("p-multi-client-maximum-ratio", "disabled"),
    Output("lns-multi-param-wrapper", "style"),
    Output("p-lns-multi-time-limit", "disabled"),
    Output("p-lns-multi-max-iterations", "disabled"),
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
    Output("p-pp-time-limit", "disabled"),
    Output("p-pp-max-iterations", "disabled"),
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

app.clientside_callback(
    """
    function(log_text) {
        var el = document.getElementById('export-log');
        if (el) { el.scrollTop = el.scrollHeight; }
        return '';
    }
    """,
    Output("export-log", "data-autoscroll"),
    Input("export-log", "children"),
)


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    import os
    import webbrowser
    from threading import Timer

    host = os.environ.get("PALLET_HOST", "127.0.0.1")
    port = int(os.environ.get("PALLET_PORT", "8050"))

    url = f"http://{host}:{port}"
    print(f"\n[App] Interface Pallet Optimizer disponible sur : {url}")
    print("[App] Appuyez sur Ctrl+C pour arrêter.\n")

    if host == "127.0.0.1":
        Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(debug=False, host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    main()
