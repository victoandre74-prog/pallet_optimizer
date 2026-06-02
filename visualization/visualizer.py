"""
visualizer.py — App Dash unifiée du Visualiseur Palettes (port 8053).

Page principale : sélection du dossier + 4 slots (Vue Multiple, Vue Zoom,
Rapport KPI, Export). Chaque vue s'ouvre dans un nouvel onglet.

Routes :
    /      → page principale (dashboard)
    /grid  → vue grille paginée  (ouverte en nouvel onglet)
    /zoom  → vue zoom            (ouverte en nouvel onglet)
    /kpi   → rapport KPI         (ouvert en nouvel onglet)
"""

import sys
import os
import base64
import subprocess
import threading
import uuid

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_logo(filename: str) -> str:
    path = os.path.join(_ROOT, filename)
    if not os.path.exists(path):
        return ""
    ext  = filename.rsplit(".", 1)[-1].lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(path, "rb") as f:
        return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()


_LOGO_FOURNIER = _load_logo("logo_fournier.png")
_LOGO_U4LOG    = _load_logo("logo_u4log.jpg")

from pathlib import Path

import dash
from dash import dcc, html, Input, Output, State
from flask import Response as _FlaskResponse

from visualization.data     import load_pallet_data
from visualization.renderer import build_client_color_map
import visualization.view_palette as view_palette
import visualization.view_kpi     as view_kpi

_IS_DOCKER = os.environ.get("PALLET_HOST", "127.0.0.1") == "0.0.0.0"
N_PER_PAGE = view_palette.N_PER_PAGE

# ── État serveur ───────────────────────────────────────────────────────────────
_state: dict = {
    "df":               None,
    "csv_path":         None,
    "output_dir":       None,
    "color_map":        None,
    "pallet_ids":       None,
    "dropdown_options": None,
    "n_pages_val":      1,
    "kpi_ready":        False,
    "kpi_rows_by_file": None,   # données brutes (thread background)
    "kpi_output_dir":   None,   # dossier associé aux données KPI
    "zoom_initial_pid": None,
}

_exports: dict = {}


# ── Page de chargement Flask ───────────────────────────────────────────────────
_LOADING_PAGE_HTML = """\
<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<title>Démarrage en cours…</title>
<style>*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f3f4f6;display:flex;
     align-items:center;justify-content:center;min-height:100vh}
.card{background:#fff;border-radius:12px;padding:48px 56px;
      box-shadow:0 4px 16px rgba(0,0,0,.10);text-align:center;max-width:440px}
.spinner{font-size:48px;animation:spin 1.4s linear infinite;margin-bottom:20px;display:inline-block}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
h2{font-size:22px;color:#1f2937;margin-bottom:12px}
p{font-size:14px;color:#6b7280;line-height:1.6}
.dot{animation:blink 1.4s step-start infinite}
.dot:nth-child(2){animation-delay:.2s}.dot:nth-child(3){animation-delay:.4s}
@keyframes blink{50%{opacity:0}}</style>
<script>var t=new URLSearchParams(window.location.search).get('url');
function p(){fetch(t,{mode:'no-cors'}).then(function(){window.location.href=t;})
  .catch(function(){setTimeout(p,2000);});}if(t){p();}</script>
</head><body><div class="card"><div class="spinner">⚙️</div>
<h2>Démarrage en cours<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></h2>
<p>L'application démarre, veuillez patienter quelques secondes.<br>
Redirection automatique dès que le serveur est prêt.</p>
</div></body></html>"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _list_csvs(folder: str) -> list[dict]:
    try:
        p = Path(folder)
        if not p.is_dir():
            return []
        csvs = sorted(p.glob("*_results*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        post  = [f for f in csvs if "postprocessed" in f.name]
        other = [f for f in csvs if "postprocessed" not in f.name]
        return [{"label": f.name, "value": str(f)} for f in (post + other)]
    except Exception:
        return []


def _load_csv_into_state(csv_path: str, output_dir: str) -> str:
    """Charge le CSV dans _state. Retourne '' ou un message d'erreur."""
    try:
        df = load_pallet_data(csv_path)
    except Exception as exc:
        return f"Erreur : {exc}"

    color_map  = build_client_color_map(df["client_id"].unique())
    pallet_ids = sorted(df["pallet_id"].unique())
    n_pages    = max(1, -(-len(pallet_ids) // N_PER_PAGE))

    def _label(pid):
        clients = df[df["pallet_id"] == pid]["client_id"].unique()
        return f"Palette {pid} - Multi" if len(clients) > 1 else f"Palette {pid} - {clients[0]}"

    _state["df"]               = df
    _state["csv_path"]         = csv_path
    _state["output_dir"]       = output_dir
    _state["color_map"]        = color_map
    _state["pallet_ids"]       = pallet_ids
    _state["n_pages_val"]      = n_pages
    _state["dropdown_options"] = [{"label": _label(p), "value": p} for p in pallet_ids]
    return ""


def _start_kpi_build(output_dir: str) -> None:
    """Démarre le calcul KPI (données pures) en arrière-plan.

    Le thread ne construit PAS le layout Dash — il calcule seulement rows_by_file
    (dict Python pur). Le layout HTML est construit dans le router (thread principal),
    ce qui évite tout problème de thread-safety avec les composants Dash.
    """
    if _state.get("kpi_output_dir") == output_dir and _state.get("kpi_ready"):
        return
    _state["kpi_ready"]        = False
    _state["kpi_rows_by_file"] = None
    _state["kpi_output_dir"]   = output_dir

    def _build():
        try:
            from visualization.view_kpi import (
                _load_kpi_cache, _load_all_results, _per_pallet_rows, _save_kpi_cache
            )
            from pathlib import Path
            current_names = {f.name for f in Path(output_dir).glob("*_results_*.csv")}
            rows = _load_kpi_cache(output_dir, current_names)
            if rows is None:
                all_data = _load_all_results(output_dir)
                rows     = {fname: _per_pallet_rows(df) for fname, df in all_data.items()}
                _save_kpi_cache(output_dir, rows)
            _state["kpi_rows_by_file"] = rows
            _state["kpi_ready"]        = True
        except Exception as exc:
            print(f"[KPI] Erreur calcul données : {exc}")
            _state["kpi_ready"] = False

    threading.Thread(target=_build, daemon=True).start()


# ── Styles ─────────────────────────────────────────────────────────────────────

_S = {
    "page":  {"fontFamily": "Arial, sans-serif", "background": "#f0f4f8", "minHeight": "100vh"},
    "card":  {"background": "white", "borderRadius": "12px", "padding": "22px 24px",
              "boxShadow": "0 1px 4px rgba(0,0,0,0.08)"},
    "label":  {"fontSize": "11px", "fontWeight": "700", "color": "#6b7280",
               "textTransform": "uppercase", "letterSpacing": "0.5px",
               "display": "block", "marginBottom": "5px"},
    "input":  {"width": "100%", "padding": "8px 10px", "border": "1px solid #d1d5db",
               "borderRadius": "6px", "fontSize": "13px", "color": "#111827",
               "boxSizing": "border-box"},
}

def _btn(kind: str, label: str, btn_id: str, disabled: bool = False, **kwargs) -> html.Button:
    colors = {
        "primary": ("#2563eb", "white"),
        "success": ("#16a34a", "white"),
        "ghost":   ("#f1f5f9", "#374151"),
        "disabled":("#94a3b8", "white"),
    }
    bg, fg = colors.get(kind, colors["primary"])
    style = {
        "background": bg, "color": fg, "border": "none" if kind != "ghost" else "1px solid #d1d5db",
        "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
        "fontWeight": "600", "cursor": "not-allowed" if disabled else "pointer",
        "opacity": "0.6" if disabled else "1", "whiteSpace": "nowrap",
    }
    return html.Button(label, id=btn_id, disabled=disabled, style=style, **kwargs)


def _status_badge(text: str, color: str) -> html.Span:
    colors = {"green": "#dcfce7/#166534", "yellow": "#fef9c3/#92400e",
              "grey": "#f1f5f9/#6b7280", "red": "#fee2e2/#991b1b"}
    bg, fg = colors.get(color, "#f1f5f9/#6b7280").split("/")
    return html.Span(text, style={
        "display": "inline-block", "background": bg, "color": fg,
        "borderRadius": "20px", "padding": "3px 10px",
        "fontSize": "12px", "fontWeight": "600",
    })


# ── Layout principal ───────────────────────────────────────────────────────────

def _slot_card(slot_id: str, icon: str, title: str, children: list) -> html.Div:
    return html.Div(
        id=slot_id,
        style={**_S["card"], "display": "flex", "flexDirection": "column", "gap": "14px"},
        children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px",
                            "borderBottom": "2px solid #e2e8f0", "paddingBottom": "10px"},
                     children=[
                         html.Span(icon, style={"fontSize": "22px"}),
                         html.Span(title, style={"fontSize": "16px", "fontWeight": "700",
                                                  "color": "#1e293b"}),
                     ]),
            *children,
        ],
    )


def _main_layout() -> html.Div:
    default_dir = "/app/output" if _IS_DOCKER else ""

    # ── En-tête (même design que app.py) ─────────────────────────────────────
    header = html.Div(
        style={"display": "flex", "alignItems": "center", "position": "relative",
               "background": "#f0f4f8", "padding": "6px 24px", "marginBottom": "0"},
        children=[
            html.Img(src=_LOGO_FOURNIER,
                     style={"height": "68px", "objectFit": "contain"})
            if _LOGO_FOURNIER else html.Div(),
            html.Div(
                style={"position": "absolute", "width": "100%",
                       "textAlign": "center", "pointerEvents": "none", "left": "0"},
                children=[html.H2("Visualiseur de Palettes - UI",
                                  style={"color": "#333", "margin": "0"})],
            ),
            html.Img(src=_LOGO_U4LOG,
                     style={"height": "68px", "objectFit": "contain", "marginLeft": "auto"})
            if _LOGO_U4LOG else html.Div(style={"marginLeft": "auto"}),
        ],
    )

    # ── Sélection du dossier ──────────────────────────────────────────────────
    folder_row = html.Div(
        style={**_S["card"], "margin": "20px 24px 4px",
               "display": "flex", "alignItems": "flex-end", "gap": "12px"},
        children=[
            html.Div(style={"flex": "1"}, children=[
                html.Label("Dossier de sortie à analyser", style=_S["label"]),
                dcc.Input(id="vis-folder", type="text", value=default_dir,
                          placeholder="Ex : C:/pallet_optimizer/output",
                          debounce=True,
                          style={**_S["input"]}),
            ]),
            html.Button("Parcourir", id="vis-browse-btn", n_clicks=0,
                        disabled=_IS_DOCKER,
                        style={"padding": "8px 14px", "fontSize": "12px", "fontWeight": "600",
                               "background": "#f1f5f9", "color": "#374151",
                               "border": "1px solid #d1d5db", "borderRadius": "6px",
                               "cursor": "not-allowed" if _IS_DOCKER else "pointer"},
                        title="Non disponible en mode serveur" if _IS_DOCKER else ""),
            html.Button("↻", id="vis-refresh-btn", n_clicks=0,
                        style={"padding": "8px 12px", "fontSize": "14px", "fontWeight": "700",
                               "background": "#2563eb", "color": "white",
                               "border": "none", "borderRadius": "6px", "cursor": "pointer"},
                        title="Rafraîchir les listes CSV"),
        ],
    )

    # ── Slot 1 : Vue Multiple ─────────────────────────────────────────────────
    slot_grid = _slot_card("slot-grid", "🖥", "Vue Grille", [
        html.Div([
            html.Label("Fichier de résultats", style=_S["label"]),
            dcc.Dropdown(id="csv-grid", options=[], clearable=False,
                         placeholder="Sélectionnez un CSV…",
                         style={"fontSize": "13px"}),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center",
                        "justifyContent": "space-between"},
                 children=[
            html.Span(id="status-grid"),
            html.Button("🖥 Ouvrir ↗", id="btn-open-grid", n_clicks=0,
                        disabled=True,
                        style={"background": "#94a3b8", "color": "white", "border": "none",
                               "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                               "fontWeight": "600", "cursor": "not-allowed", "whiteSpace": "nowrap"}),
        ]),
    ])

    # ── Slot 2 : Vue Zoom ─────────────────────────────────────────────────────
    slot_zoom = _slot_card("slot-zoom", "🔍", "Vue Zoom", [
        html.Div([
            html.Label("Fichier de résultats", style=_S["label"]),
            dcc.Dropdown(id="csv-zoom", options=[], clearable=False,
                         placeholder="Sélectionnez un CSV…",
                         style={"fontSize": "13px"}),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center",
                        "justifyContent": "space-between"},
                 children=[
            html.Span(id="status-zoom"),
            html.Button("🔍 Ouvrir ↗", id="btn-open-zoom", n_clicks=0,
                        disabled=True,
                        style={"background": "#94a3b8", "color": "white", "border": "none",
                               "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                               "fontWeight": "600", "cursor": "not-allowed", "whiteSpace": "nowrap"}),
        ]),
    ])

    # ── Slot 3 : Rapport KPI ──────────────────────────────────────────────────
    slot_kpi = _slot_card("slot-kpi", "📊", "Rapport KPI", [
        html.P("Analyse tous les fichiers de résultats du dossier sélectionné.",
               style={"color": "#6b7280", "fontSize": "13px", "margin": "0"}),
        html.Div(style={"display": "flex", "alignItems": "center",
                        "justifyContent": "space-between"},
                 children=[
            html.Span(id="status-kpi"),
            html.Button("📊 Ouvrir ↗", id="btn-open-kpi", n_clicks=0,
                        disabled=True,
                        style={"background": "#94a3b8", "color": "white", "border": "none",
                               "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                               "fontWeight": "600", "cursor": "not-allowed", "whiteSpace": "nowrap"}),
        ]),
    ])

    # ── Slot 4 : Export Images ────────────────────────────────────────────────
    slot_export = _slot_card("slot-export", "💾", "Export Images PNG", [
        html.Div([
            html.Label("Fichier de résultats à exporter", style=_S["label"]),
            dcc.Dropdown(id="csv-export", options=[], clearable=False,
                         placeholder="Sélectionnez un CSV…",
                         style={"fontSize": "13px"}),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px",
                        "justifyContent": "space-between"},
                 children=[
            html.Span(id="status-export"),
            html.Button("💾 Exporter", id="btn-export", n_clicks=0,
                        disabled=True,
                        style={"background": "#94a3b8", "color": "white", "border": "none",
                               "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                               "fontWeight": "600", "cursor": "not-allowed", "whiteSpace": "nowrap"}),
        ]),
        html.Pre(id="exp-log", style={
            "fontFamily": "Consolas, monospace", "fontSize": "11px",
            "background": "#0f172a", "color": "#94a3b8", "borderRadius": "6px",
            "padding": "10px", "margin": "0", "maxHeight": "100px",
            "overflowY": "auto", "whiteSpace": "pre-wrap", "display": "none",
        }),
    ])

    # ── Assemblage ────────────────────────────────────────────────────────────
    return html.Div(style=_S["page"], children=[
        header,
        folder_row,
        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                   "gap": "16px", "padding": "16px 24px"},
            children=[slot_grid, slot_zoom, slot_kpi, slot_export],
        ),
    ])


# ── App builder ────────────────────────────────────────────────────────────────

def build_app() -> dash.Dash:
    _prefix = os.environ.get("PALLET_VISUALIZER_PREFIX", "")
    if _prefix and _prefix != "/":
        app = dash.Dash(__name__, title="Visualiseur Palettes",
                        suppress_callback_exceptions=True,
                        routes_pathname_prefix=_prefix,
                        requests_pathname_prefix=_prefix)
    else:
        app = dash.Dash(__name__, title="Visualiseur Palettes",
                        suppress_callback_exceptions=True)

    app.layout = html.Div([
        dcc.Location(id="url-viz", refresh=False),
        html.Span(id="_title-dummy", style={"display": "none"}),
        # Signaux d'ouverture d'onglet (incrémentés côté serveur → clientside ouvre le tab)
        dcc.Store(id="sig-open-grid", data=0),
        dcc.Store(id="sig-open-zoom", data=0),
        dcc.Store(id="sig-open-kpi",  data=0),
        # Polling KPI
        dcc.Interval(id="kpi-poll", interval=600, n_intervals=0, disabled=True),
        # Export
        dcc.Interval(id="exp-poll-interval", interval=800, n_intervals=0, disabled=True),
        dcc.Store(id="exp-state", data={"active": False, "export_id": None}),
        html.Div(id="page-viz"),
    ])

    app.clientside_callback(
        """function(pathname) {
            var p = (pathname || '/').replace(/\\/$/, '') || '/';
            var titles = {
                '/grid': 'Vue Grid Palettes',
                '/zoom': 'Vue Zoom Palette',
                '/kpi':  'Rapport KPI'
            };
            var suffix = Object.keys(titles).find(function(k){ return p.endsWith(k); });
            document.title = suffix ? titles[suffix] : 'Visualiseur Palettes';
            return '';
        }""",
        Output("_title-dummy", "children"),
        Input("url-viz", "pathname"),
    )

    # Enregistrement des callbacks vue palette + KPI (pour /grid, /zoom, /kpi)
    view_palette.register(app, _state)
    view_kpi.register(app, _state)

    # ── Router ────────────────────────────────────────────────────────────────

    @app.callback(Output("page-viz", "children"), Input("url-viz", "pathname"))
    def route(pathname):
        p = (pathname or "/").rstrip("/") or "/"
        if p.endswith("/grid") and _state["df"] is not None:
            return view_palette.grid_layout(_state)
        if p.endswith("/zoom") and _state["df"] is not None:
            return view_palette.zoom_layout(_state)
        if p.endswith("/kpi") and _state.get("kpi_ready"):
            # Données prêtes → construire le layout HTML maintenant (thread principal, rapide)
            return view_kpi.kpi_layout(
                _state.get("kpi_output_dir", ""),
                rows_by_file=_state.get("kpi_rows_by_file"),
            )
        if p.endswith("/kpi"):
            # Données pas encore prêtes → spinner + polling
            return html.Div([
                html.Div(id="kpi-content-area", children=html.Div(
                    style={"padding": "60px", "textAlign": "center", "color": "#6b7280"},
                    children=[
                        html.Div("⚙️", style={"fontSize": "48px", "marginBottom": "16px"}),
                        html.H3("Calcul du rapport KPI en cours…",
                                style={"color": "#1e293b"}),
                        html.P("La page se rafraîchira automatiquement."),
                    ],
                )),
                dcc.Interval(id="kpi-view-poll", interval=600, n_intervals=0),
            ])
        return _main_layout()

    # ── Polling KPI dans la vue /kpi quand pas encore prêt ───────────────────

    @app.callback(
        Output("kpi-content-area", "children"),
        Output("kpi-view-poll",    "disabled"),
        Input("kpi-view-poll",     "n_intervals"),
        prevent_initial_call=True,
    )
    def poll_kpi_view(n):
        if _state.get("kpi_ready"):
            layout = view_kpi.kpi_layout(
                _state.get("kpi_output_dir", ""),
                rows_by_file=_state.get("kpi_rows_by_file"),
            )
            return layout, True
        return dash.no_update, False

    # ── Ouverture d'onglets (clientside) ──────────────────────────────────────
    # Utilise une URL relative pour être compatible avec le préfixe Docker.

    app.clientside_callback(
        "function(n){if(n>0){window.open('grid','_blank');}return '';}",
        Output("sig-open-grid", "data"),
        Input("sig-open-grid",  "data"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        "function(n){if(n>0){window.open('zoom','_blank');}return '';}",
        Output("sig-open-zoom", "data"),
        Input("sig-open-zoom",  "data"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        "function(n){if(n>0){window.open('kpi','_blank');}return '';}",
        Output("sig-open-kpi",  "data"),
        Input("sig-open-kpi",   "data"),
        prevent_initial_call=True,
    )

    # ── Rafraîchir les dropdowns CSV ──────────────────────────────────────────

    @app.callback(
        Output("csv-grid",   "options"), Output("csv-grid",   "value"),
        Output("csv-zoom",   "options"), Output("csv-zoom",   "value"),
        Output("csv-export", "options"), Output("csv-export", "value"),
        Input("vis-refresh-btn", "n_clicks"),
        Input("vis-folder",      "value"),
    )
    def refresh_csv_lists(_, folder):
        opts = _list_csvs(folder or "")
        val  = opts[0]["value"] if opts else None
        return opts, val, opts, val, opts, val

    # ── Bouton Parcourir ──────────────────────────────────────────────────────

    @app.callback(
        Output("vis-folder", "value"),
        Input("vis-browse-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def browse(_):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw()
            root.wm_attributes("-topmost", True)
            path = filedialog.askdirectory(title="Dossier de sortie")
            root.destroy()
            return path or dash.no_update
        except Exception:
            return dash.no_update

    # ── Démarrage KPI en arrière-plan dès que le dossier change ──────────────

    @app.callback(
        Output("kpi-poll", "disabled"),
        Input("vis-folder", "value"),
    )
    def start_kpi_on_folder_change(folder):
        if not folder or not os.path.isdir(folder):
            return True
        _start_kpi_build(folder)
        return False   # active le polling

    # ── Polling KPI (page principale) ─────────────────────────────────────────

    @app.callback(
        Output("status-kpi",   "children"),
        Output("btn-open-kpi", "disabled"),
        Output("btn-open-kpi", "style"),
        Output("kpi-poll",     "disabled", allow_duplicate=True),
        Input("kpi-poll",      "n_intervals"),
        State("vis-folder",    "value"),
        prevent_initial_call=True,
    )
    def poll_kpi_status(_, folder):
        _btn_ready = {
            "background": "#7c3aed", "color": "white", "border": "none",
            "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
            "fontWeight": "600", "cursor": "pointer", "whiteSpace": "nowrap",
        }
        _btn_wait = {
            **_btn_ready, "background": "#94a3b8", "cursor": "not-allowed",
        }
        if _state.get("kpi_ready"):
            badge = _status_badge("✓ Prêt", "green")
            return badge, False, _btn_ready, True   # arrêt du polling
        if folder and os.path.isdir(folder):
            badge = _status_badge("⚙ Calcul en cours…", "yellow")
            return badge, True, _btn_wait, False
        badge = _status_badge("● Sélectionnez un dossier", "grey")
        return badge, True, _btn_wait, True

    # ── Activation des boutons Grid / Zoom ────────────────────────────────────

    @app.callback(
        Output("status-grid",   "children"),
        Output("btn-open-grid", "disabled"),
        Output("btn-open-grid", "style"),
        Input("csv-grid", "value"),
    )
    def update_grid_btn(csv_val):
        _btn_on  = {"background": "#2563eb", "color": "white", "border": "none",
                    "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                    "fontWeight": "600", "cursor": "pointer", "whiteSpace": "nowrap"}
        _btn_off = {**_btn_on, "background": "#94a3b8", "cursor": "not-allowed"}
        if csv_val:
            return _status_badge("✓ Prêt", "green"), False, _btn_on
        return _status_badge("● Sélectionnez un fichier", "grey"), True, _btn_off

    @app.callback(
        Output("status-zoom",   "children"),
        Output("btn-open-zoom", "disabled"),
        Output("btn-open-zoom", "style"),
        Input("csv-zoom", "value"),
    )
    def update_zoom_btn(csv_val):
        _btn_on  = {"background": "#0891b2", "color": "white", "border": "none",
                    "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                    "fontWeight": "600", "cursor": "pointer", "whiteSpace": "nowrap"}
        _btn_off = {**_btn_on, "background": "#94a3b8", "cursor": "not-allowed"}
        if csv_val:
            return _status_badge("✓ Prêt", "green"), False, _btn_on
        return _status_badge("● Sélectionnez un fichier", "grey"), True, _btn_off

    # ── Activation du bouton Export ───────────────────────────────────────────

    @app.callback(
        Output("status-export", "children"),
        Output("btn-export",    "disabled"),
        Output("btn-export",    "style"),
        Input("csv-export", "value"),
    )
    def update_export_btn(csv_val):
        _btn_on  = {"background": "#16a34a", "color": "white", "border": "none",
                    "borderRadius": "8px", "padding": "9px 18px", "fontSize": "14px",
                    "fontWeight": "600", "cursor": "pointer", "whiteSpace": "nowrap"}
        _btn_off = {**_btn_on, "background": "#94a3b8", "cursor": "not-allowed"}
        if csv_val:
            return _status_badge("✓ Prêt", "green"), False, _btn_on
        return _status_badge("● Sélectionnez un fichier", "grey"), True, _btn_off

    # ── Clic "Ouvrir Vue Multiple" ────────────────────────────────────────────

    @app.callback(
        Output("sig-open-grid", "data", allow_duplicate=True),
        Output("status-grid",   "children", allow_duplicate=True),
        Input("btn-open-grid",  "n_clicks"),
        State("csv-grid",       "value"),
        State("vis-folder",     "value"),
        State("sig-open-grid",  "data"),
        prevent_initial_call=True,
    )
    def open_grid(n, csv_path, folder, sig):
        if not n or not csv_path:
            return dash.no_update, dash.no_update
        err = _load_csv_into_state(csv_path, folder or "")
        if err:
            return dash.no_update, _status_badge(f"✗ {err}", "red")
        return (sig or 0) + 1, _status_badge("✓ Prêt", "green")

    # ── Clic "Ouvrir Vue Zoom" ────────────────────────────────────────────────

    @app.callback(
        Output("sig-open-zoom", "data", allow_duplicate=True),
        Output("status-zoom",   "children", allow_duplicate=True),
        Input("btn-open-zoom",  "n_clicks"),
        State("csv-zoom",       "value"),
        State("vis-folder",     "value"),
        State("sig-open-zoom",  "data"),
        prevent_initial_call=True,
    )
    def open_zoom(n, csv_path, folder, sig):
        if not n or not csv_path:
            return dash.no_update, dash.no_update
        err = _load_csv_into_state(csv_path, folder or "")
        if err:
            return dash.no_update, _status_badge(f"✗ {err}", "red")
        return (sig or 0) + 1, _status_badge("✓ Prêt", "green")

    # ── Clic "Ouvrir KPI" ─────────────────────────────────────────────────────

    @app.callback(
        Output("sig-open-kpi", "data", allow_duplicate=True),
        Input("btn-open-kpi",  "n_clicks"),
        State("sig-open-kpi",  "data"),
        prevent_initial_call=True,
    )
    def open_kpi(n, sig):
        if not n or not _state.get("kpi_ready"):
            return dash.no_update
        return (sig or 0) + 1

    # ── Export : lancer ───────────────────────────────────────────────────────

    @app.callback(
        Output("exp-state",         "data"),
        Output("exp-poll-interval", "disabled"),
        Output("exp-log",           "style"),
        Output("exp-log",           "children"),
        Input("btn-export",         "n_clicks"),
        State("csv-export",         "value"),
        State("vis-folder",         "value"),
        prevent_initial_call=True,
    )
    def launch_export(n, csv_path, output_dir):
        if not n or not csv_path:
            return dash.no_update, True, {"display": "none"}, ""
        img_dir = os.path.join(output_dir or os.path.dirname(csv_path), "pallet_images")
        os.makedirs(img_dir, exist_ok=True)
        cmd = [sys.executable, os.path.join(_DIR, "exporter.py"), csv_path, img_dir]
        creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        proc = subprocess.Popen(cmd, creationflags=creation_flags)
        eid  = str(uuid.uuid4())
        _exports[eid] = {"proc": proc, "img_dir": img_dir}
        log_style = {
            "fontFamily": "Consolas, monospace", "fontSize": "11px",
            "background": "#0f172a", "color": "#94a3b8", "borderRadius": "6px",
            "padding": "10px", "margin": "0", "maxHeight": "100px",
            "overflowY": "auto", "whiteSpace": "pre-wrap", "display": "block",
        }
        return (
            {"active": True, "export_id": eid},
            False,
            log_style,
            f"⟳ Export lancé dans la fenêtre terminal.\n   Destination : {img_dir}",
        )

    # ── Export : polling ──────────────────────────────────────────────────────

    @app.callback(
        Output("exp-state",         "data",     allow_duplicate=True),
        Output("exp-poll-interval", "disabled", allow_duplicate=True),
        Output("exp-log",           "children", allow_duplicate=True),
        Input("exp-poll-interval",  "n_intervals"),
        State("exp-state",          "data"),
        prevent_initial_call=True,
    )
    def poll_export(_, sd):
        if not sd or not sd.get("active"):
            return dash.no_update, True, dash.no_update
        eid = sd.get("export_id")
        if not eid or eid not in _exports:
            return sd, True, "Erreur : processus introuvable."
        done = _exports[eid]["proc"].poll() is not None
        new  = {**sd, "active": not done}
        if done:
            rc  = _exports[eid]["proc"].returncode
            msg = "✓ Export terminé." if rc == 0 else f"✗ Erreur (code {rc})."
            return new, True, msg
        return new, False, dash.no_update

    # ── No-cache ──────────────────────────────────────────────────────────────

    @app.server.after_request
    def _no_cache(resp):
        resp.headers.update({
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0",
        })
        return resp

    if not _IS_DOCKER:
        @app.server.route("/loading")
        def _loading_page():
            return _FlaskResponse(_LOADING_PAGE_HTML,
                                  content_type="text/html; charset=utf-8")

    # ── Routes Flask pour navigation depuis le rapport KPI ────────────────────
    # Les liens dans le KPI utilisent des URLs relatives (open-grid / open-zoom).
    # Flask charge le CSV et redirige vers la vue correspondante.

    from flask import request as _flask_req, redirect as _flask_redirect
    from urllib.parse import unquote as _unquote

    _prefix = os.environ.get("PALLET_VISUALIZER_PREFIX", "").rstrip("/")

    @app.server.route(f"{_prefix}/open-grid" if _prefix else "/open-grid")
    def _open_grid():
        csv_path = _unquote(_flask_req.args.get("csv", ""))
        if csv_path and os.path.isfile(csv_path):
            _load_csv_into_state(csv_path, os.path.dirname(csv_path))
        target = f"{_prefix}/grid" if _prefix else "/grid"
        return _flask_redirect(target)

    @app.server.route(f"{_prefix}/open-zoom" if _prefix else "/open-zoom")
    def _open_zoom():
        csv_path = _unquote(_flask_req.args.get("csv", ""))
        pid_str  = _flask_req.args.get("pid", "")
        if csv_path and os.path.isfile(csv_path):
            _load_csv_into_state(csv_path, os.path.dirname(csv_path))
        if pid_str:
            try:
                _state["zoom_initial_pid"] = int(pid_str)
            except ValueError:
                pass
        target = f"{_prefix}/zoom" if _prefix else "/zoom"
        return _flask_redirect(target)

    return app


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    import webbrowser
    from threading import Timer

    app  = build_app()
    host = os.environ.get("PALLET_HOST", "127.0.0.1")
    port = int(os.environ.get("PALLET_VISUALIZER_PORT", "8053"))
    url  = f"http://{host}:{port}"

    print(f"\n[Visualiseur] Disponible sur : {url}")
    print("[Visualiseur] Ctrl+C pour arrêter.\n")

    if host == "127.0.0.1":
        Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(debug=False, host=host, port=port)


if __name__ == "__main__":
    main()
