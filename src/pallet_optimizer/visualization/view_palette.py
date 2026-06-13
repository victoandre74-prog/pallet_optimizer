"""
view_palette.py — Vues interactives des palettes (grille + zoom)

Deux vues servies par la même app Dash :
    /      → grille paginée (N_PER_PAGE palettes par page)
    /zoom  → vue zoom avec slider de relecture séquentielle

Usage standalone :
    python visualization/view_palette.py results.csv
"""

import os

_DIR    = os.path.dirname(os.path.abspath(__file__))
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(_DIR)), "assets")

import base64

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import dash
from dash import dcc, html, Input, Output, State

from pallet_optimizer.visualization.renderer import render_pallet, build_client_color_map
from pallet_optimizer.visualization.data import load_pallet_data, compute_pallet_statistics


# ── Plan view definitions ──────────────────────────────────────────────────────

_PLAN_VIEWS = {
    "back": dict(
        proj_x="x", proj_y="z", w_col="length", h_col="height",
        sort_col="y", sort_asc=False,
        mirror_x=False, mirror_y=False,
        reverse_x=False, reverse_y=False,
        xlabel="X (cm)", ylabel="Z (cm)",
        pallet_dim_x="pallet_length", pallet_dim_y="pallet_height",
    ),
    "left": dict(
        proj_x="y", proj_y="z", w_col="width", h_col="height",
        sort_col="x", sort_asc=True,
        mirror_x=False, mirror_y=False,
        reverse_x=False, reverse_y=False,
        xlabel="Y (cm)", ylabel="Z (cm)",
        pallet_dim_x="pallet_width", pallet_dim_y="pallet_height",
    ),
    "front": dict(
        proj_x="x", proj_y="z", w_col="length", h_col="height",
        sort_col="y", sort_asc=True,
        mirror_x=False, mirror_y=False,
        reverse_x=True, reverse_y=False,
        xlabel="X (cm)", ylabel="Z (cm)",
        pallet_dim_x="pallet_length", pallet_dim_y="pallet_height",
    ),
    "right": dict(
        proj_x="y", proj_y="z", w_col="width", h_col="height",
        sort_col="x", sort_asc=False,
        mirror_x=False, mirror_y=False,
        reverse_x=True, reverse_y=False,
        xlabel="Y (cm)", ylabel="Z (cm)",
        pallet_dim_x="pallet_width", pallet_dim_y="pallet_height",
    ),
    "top": dict(
        proj_x="x", proj_y="y", w_col="length", h_col="width",
        sort_col="z", sort_asc=True,
        mirror_x=False, mirror_y=False,
        reverse_x=True, reverse_y=True,
        xlabel="X (cm)", ylabel="Y (cm)",
        pallet_dim_x="pallet_length", pallet_dim_y="pallet_width",
    ),
}

_MODEBAR_DEFAULT = ["select2d", "lasso2d"]

_VIEW_BTN_STYLE = {
    "fontSize": "22px", "padding": "4px 14px", "cursor": "pointer",
    "borderRadius": "4px", "border": "1px solid #bbb",
    "backgroundColor": "#f5f5f5", "color": "#333",
}
_VIEW_BTN_ACTIVE = {
    "fontSize": "22px", "padding": "4px 14px", "cursor": "default",
    "borderRadius": "4px", "border": "1px solid #999",
    "backgroundColor": "#bbb", "color": "#777",
}

_VIEW_NAMES = ["back", "left", "front", "right", "top", "3d"]

PAGE_ZOOM = 1.0


# ── 2D plan-view renderer ──────────────────────────────────────────────────────

def _render_slot_2d(pallet_id, df: pd.DataFrame, color_map: dict, view: str) -> go.Figure:
    df_p = df[df["pallet_id"] == pallet_id].copy()
    if df_p.empty:
        return go.Figure()

    v = _PLAN_VIEWS[view]
    pallet_w = float(df_p[v["pallet_dim_x"]].iloc[0])
    pallet_h = float(df_p[v["pallet_dim_y"]].iloc[0])

    traces = []
    traces.append(go.Scatter(
        x=[0, pallet_w, pallet_w, 0, 0],
        y=[0, 0, pallet_h, pallet_h, 0],
        mode="lines",
        line=dict(color="#555", width=2, dash="dash"),
        showlegend=False, hoverinfo="skip",
    ))

    df_sorted = df_p.sort_values(v["sort_col"], ascending=v["sort_asc"])

    for _, row in df_sorted.iterrows():
        rx = float(row[v["proj_x"]])
        ry = float(row[v["proj_y"]])
        rw = float(row[v["w_col"]])
        rh = float(row[v["h_col"]])

        if v["mirror_x"]:
            rx = pallet_w - rx - rw
        if v["mirror_y"]:
            ry = pallet_h - ry - rh

        color      = color_map.get(int(row["client_id"]), "#888")
        line_color = "#000" if int(row["priority"]) == 1 else "#fff"

        xs = [rx, rx + rw, rx + rw, rx, rx]
        ys = [ry, ry,      ry + rh, ry + rh, ry]

        hover_text = (
            f"<b>{row['box_id']}</b><br>"
            f"Client : {row['client_id']}<br>"
            f"Priorité : {row['priority']}<br>"
            f"Dims : {row['length']}×{row['width']}×{row['height']} cm"
        )

        traces.append(go.Scatter(
            x=xs, y=ys, fill="toself", fillcolor=color,
            mode="lines", line=dict(color=line_color, width=2),
            showlegend=False, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[rx + rw / 2], y=[ry + rh / 2], mode="markers",
            marker=dict(size=max(8, min(rw, rh) * 0.4), color=line_color, opacity=0.5),
            showlegend=False,
            hovertemplate=hover_text + "<extra></extra>",
        ))

    pad = 5
    x_range = [pallet_w + pad, -pad] if v["reverse_x"] else [-pad, pallet_w + pad]
    y_range = [pallet_h + pad, -pad] if v["reverse_y"] else [-pad, pallet_h + pad]
    fig = go.Figure(data=traces)
    fig.update_layout(
        xaxis=dict(title="", range=x_range, showgrid=True, zeroline=False,
                   tickfont=dict(size=13, family="Arial Black"), constrain="domain"),
        yaxis=dict(title=v["ylabel"], range=y_range, showgrid=True, zeroline=False,
                   tickfont=dict(size=13, family="Arial Black"),
                   title_font=dict(size=18, family="Arial Black"),
                   scaleanchor="x", scaleratio=1, constrain="domain"),
        plot_bgcolor="rgb(240, 240, 245)", paper_bgcolor="white",
        margin=dict(l=50, r=20, t=10, b=70), showlegend=False, dragmode="pan",
        annotations=[dict(
            text=v["xlabel"], x=0.5, y=-0.10, xref="paper", yref="paper",
            showarrow=False, font=dict(size=18, family="Arial Black", color="#000"),
        )],
    )
    return fig


# ── Per-slot render helper ─────────────────────────────────────────────────────

def _render_slot(pallet_id, df: pd.DataFrame, color_map: dict,
                 seq_max: int = None, highlight_seq: int = None):
    if pallet_id is None:
        return go.Figure(), [], [], ""

    df_p   = df[df["pallet_id"] == pallet_id].copy()
    df_fig = df_p if seq_max is None else df_p[df_p["sequence"] <= seq_max]
    fig    = render_pallet(df_fig, color_map=color_map, highlight_seq=highlight_seq)
    stats  = compute_pallet_statistics(df_p)

    box_label = ""
    if highlight_seq is not None and "sequence" in df_p.columns:
        row = df_p[df_p["sequence"] == highlight_seq]
        if not row.empty:
            r        = row.iloc[0]
            loc      = str(r["location"])    if "location"    in r.index and pd.notna(r["location"])    else ""
            des_full = str(r["designation"]) if "designation" in r.index and pd.notna(r["designation"]) else ""
            des      = des_full[:20] + ("…" if len(des_full) > 20 else "")
            parts = [f"#{int(r['sequence'])}", f"P{r['priority']}", f"Client {r['client_id']}"]
            if loc:  parts.append(loc)
            if des:  parts.append(des)
            parts += [str(r['box_id']), f"{r['length']}×{r['width']}×{r['height']} cm", f"{r['weight']} kg"]
            box_label = "  ·  ".join(parts)

    stat_rows = [
        html.H4(f"Palette {pallet_id} — Statistiques",
                style={"color": "#333", "borderBottom": "1px solid #ddd",
                       "paddingBottom": "6px", "marginTop": "0", "fontSize": "20px"})
    ]
    for label, value in stats.items():
        color = "#c0392b" if (label == "Multi-client" and value == "Oui") else "#555"
        stat_rows.append(html.Div(
            style={"display": "flex", "justifyContent": "space-between",
                   "padding": "3px 0", "borderBottom": "1px solid #eee"},
            children=[
                html.Span(label, style={"fontWeight": "bold", "color": "#333", "fontSize": "17px"}),
                html.Span(str(value), style={"color": color, "fontSize": "17px"}),
            ]
        ))

    multi = df_p["client_id"].nunique() > 1
    legend_items = []
    if multi:
        for cid in sorted(df_p["client_id"].unique()):
            color = color_map.get(int(cid), "#888")
            legend_items.append(html.Span(style={"marginRight": "12px"}, children=[
                html.Span("■ ", style={"color": color, "fontSize": "24px"}),
                html.Span(f"Client {cid}", style={"fontSize": "17px"}),
            ]))
    legend_items += [
        html.Span("  │  "),
        html.Span("Contour noir = Priorité 1 (Meubles)", style={"fontSize": "17px"}),
        html.Span("  │  "),
        html.Span("Contour blanc = Priorité 2 (Colis)", style={"fontSize": "17px"}),
    ]

    return fig, stat_rows, legend_items, box_label


def _compute_cog_offset(df_p: pd.DataFrame) -> float:
    tw = df_p["weight"].sum()
    if tw <= 0:
        return 0.0
    cx = (df_p["weight"] * (df_p["x"] + df_p["length"] / 2)).sum() / tw
    cy = (df_p["weight"] * (df_p["y"] + df_p["width"]  / 2)).sum() / tw
    dx = cx - float(df_p["pallet_length"].iloc[0]) / 2
    dy = cy - float(df_p["pallet_width"].iloc[0])  / 2
    return (dx ** 2 + dy ** 2) ** 0.5


N_PER_PAGE = 10


# ── Layout helpers ─────────────────────────────────────────────────────────────

def _slot_card(slot: int, dropdown_options: list) -> html.Div:
    return html.Div(
        style={"backgroundColor": "white", "borderRadius": "8px", "padding": "12px",
               "boxShadow": "0 2px 4px rgba(0,0,0,0.1)", "display": "flex",
               "flexDirection": "column", "gap": "8px"},
        children=[
            html.Div(
                style={"display": "flex", "alignItems": "center", "gap": "10px"},
                children=[
                    dcc.Dropdown(id=f"pallet-select-{slot}", options=dropdown_options,
                                 clearable=False, style={"width": "260px", "fontSize": "13px", "flexShrink": "0"}),
                    html.Button("Arrière", id=f"btn-back-{slot}",  n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Gauche", id=f"btn-left-{slot}",  n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Face",   id=f"btn-front-{slot}", n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Droite", id=f"btn-right-{slot}", n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Dessus", id=f"btn-top-{slot}",   n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("3D",     id=f"btn-3d-{slot}",    n_clicks=0, style=_VIEW_BTN_ACTIVE),
                    html.Div(id=f"header-{slot}", style={"display": "none"}),
                ]
            ),
            html.Div(
                style={"display": "flex", "gap": "8px", "alignItems": "flex-start"},
                children=[
                    dcc.Graph(id=f"graph-{slot}", style={"flex": "1", "height": "480px"},
                              config={"displayModeBar": True, "scrollZoom": True,
                                      "modeBarButtonsToRemove": ["select2d", "lasso2d"]}),
                    html.Div(id=f"stats-{slot}", style={"width": "285px", "flexShrink": "0", "paddingTop": "4px"}),
                ]
            ),
            html.Div(id=f"legend-{slot}", style={"fontSize": "17px", "color": "#666"}),
        ]
    )


def _header_div(title: str, logo_b64: str, logo2_b64: str = "") -> html.Div:
    children = [html.Img(src=logo_b64, style={"height": "68px", "objectFit": "contain"}),
                html.Div(style={"position": "absolute", "width": "100%", "textAlign": "center",
                                "pointerEvents": "none"},
                         children=[html.H2(title, style={"color": "#333", "margin": "0"})])]
    if logo2_b64:
        children.append(html.Img(src=logo2_b64, style={"height": "68px", "objectFit": "contain",
                                                         "marginLeft": "auto"}))
    return html.Div(style={"display": "flex", "alignItems": "center", "marginBottom": "8px",
                           "position": "relative"}, children=children)


def _dashboard_layout(pallet_ids, dropdown_options, n_pages, logo_b64, logo2_b64="", csv_name=""):
    btn_style = {"padding": "6px 18px", "fontSize": "14px", "cursor": "pointer",
                 "borderRadius": "4px", "border": "1px solid #aaa", "backgroundColor": "#fff"}
    pagination = html.Div(
        style={"display": "flex", "justifyContent": "center", "alignItems": "center",
               "gap": "16px", "marginBottom": "16px"},
        children=[html.Button("◀  Préc.", id="btn-prev", n_clicks=0, style=btn_style),
                  html.Span(id="page-label", style={"fontSize": "14px", "color": "#333"}),
                  html.Button("Suiv.  ▶", id="btn-next", n_clicks=0, style=btn_style)])
    pagination_bottom = html.Div(
        style={"display": "flex", "justifyContent": "center", "alignItems": "center",
               "gap": "16px", "marginTop": "16px"},
        children=[html.Button("◀  Préc.", id="btn-prev-bottom", n_clicks=0, style=btn_style),
                  html.Span(id="page-label-bottom", style={"fontSize": "14px", "color": "#333"}),
                  html.Button("Suiv.  ▶", id="btn-next-bottom", n_clicks=0, style=btn_style)])
    return html.Div(
        id="dashboard-top",
        style={"fontFamily": "Arial, sans-serif", "backgroundColor": "#f5f5f5",
               "minHeight": "100vh", "padding": "16px"},
        children=[
            _header_div("Vue Grille", logo_b64, logo2_b64),
            html.P(csv_name, style={"textAlign": "center", "color": "#888",
                                    "marginTop": "0", "marginBottom": "12px", "fontSize": "13px"}),
            pagination,
            html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "16px"},
                     children=[_slot_card(i, dropdown_options) for i in range(N_PER_PAGE)]),
            pagination_bottom,
            dcc.Store(id="page-store", data=0),
        ]
    )


def _build_p2_table(df_p: pd.DataFrame, highlight_seq: int = None) -> html.Div:
    df_p2 = df_p[df_p["priority"] == 2].copy()
    if "sequence" in df_p2.columns:
        df_p2 = df_p2.sort_values("sequence")

    if df_p2.empty:
        return html.Div("Aucun colis P2 sur cette palette.",
                        style={"color": "#aaa", "fontSize": "15px", "padding": "6px 0"})

    has_loc = "location"    in df_p2.columns
    has_des = "designation" in df_p2.columns

    th_style = {"padding": "6px 12px", "textAlign": "left", "fontSize": "16.5px", "color": "#888",
                "borderBottom": "1px solid #ddd", "position": "sticky", "top": "0",
                "backgroundColor": "#fafafa"}
    td_base = {"padding": "5px 12px", "fontSize": "17.5px", "whiteSpace": "nowrap"}

    rows = []
    for _, row in df_p2.iterrows():
        seq       = int(row["sequence"]) if "sequence" in df_p2.columns else 0
        is_active = (highlight_seq is not None and seq == highlight_seq)
        bg        = "#ffc107" if is_active else ("white" if len(rows) % 2 == 0 else "#fafafa")
        fw        = "bold"    if is_active else "normal"
        loc       = str(row["location"])    if has_loc and pd.notna(row["location"])    else ""
        des_full  = str(row["designation"]) if has_des and pd.notna(row["designation"]) else ""
        des       = des_full[:20] + ("…" if len(des_full) > 20 else "")
        rows.append(html.Tr(id=f"p2-row-{seq}", style={"backgroundColor": bg},
                            children=[html.Td(loc, style={**td_base, "fontWeight": fw}),
                                      html.Td(des, style={**td_base, "fontWeight": fw}),
                                      html.Td(str(row["box_id"]), style={**td_base, "fontWeight": fw,
                                                                          "color": "#e67e22"})]))

    return html.Div(style={"marginTop": "12px"}, children=[
        html.H5("Colis P2", style={"margin": "0 0 8px 0", "color": "#e67e22",
                                    "fontSize": "17px", "borderBottom": "2px solid #e67e22",
                                    "paddingBottom": "4px"}),
        html.Div(style={"maxHeight": "420px", "overflowY": "auto", "border": "1px solid #ddd",
                        "borderRadius": "4px"},
                 children=[html.Table(style={"width": "100%", "borderCollapse": "collapse"},
                                      children=[html.Thead(html.Tr([
                                          html.Th("Casier", style=th_style),
                                          html.Th("Désignation", style=th_style),
                                          html.Th("ID", style=th_style),
                                      ])), html.Tbody(rows)])]),
    ])


def _zoom_layout(dropdown_options, logo_b64, logo2_b64="", default_pid=None, csv_name=""):
    return html.Div(
        style={"fontFamily": "Arial, sans-serif", "backgroundColor": "#f5f5f5",
               "minHeight": "100vh", "padding": "16px"},
        children=[
            _header_div("Vue Zoom", logo_b64, logo2_b64),
            html.P(csv_name, style={"textAlign": "center", "color": "#888",
                                    "marginTop": "0", "marginBottom": "12px", "fontSize": "13px"}),
            html.Div(
                style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "12px"},
                children=[
                    dcc.Dropdown(id="zoom-pallet-select", options=dropdown_options,
                                 value=default_pid, clearable=False,
                                 style={"width": "280px", "fontSize": "14px"}),
                    html.Button("Arrière", id="zoom-btn-back",  n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Gauche", id="zoom-btn-left",  n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Face",   id="zoom-btn-front", n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Droite", id="zoom-btn-right", n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("Dessus", id="zoom-btn-top",   n_clicks=0, style=_VIEW_BTN_STYLE),
                    html.Button("3D",     id="zoom-btn-3d",    n_clicks=0, style=_VIEW_BTN_ACTIVE),
                    html.Div(id="zoom-header", style={"display": "none"}),
                ]
            ),
            html.Div(
                style={"display": "flex", "gap": "12px", "alignItems": "flex-start"},
                children=[
                    dcc.Graph(id="zoom-graph", style={"flex": "1", "minWidth": "0", "height": "720px"},
                              config={"displayModeBar": True, "scrollZoom": True,
                                      "modeBarButtonsToRemove": ["select2d", "lasso2d"]}),
                    html.Div(style={"width": "590px", "flexShrink": "0", "paddingTop": "4px",
                                    "display": "flex", "flexDirection": "column", "gap": "0px"},
                             children=[html.Div(id="zoom-stats"), html.Div(id="zoom-p2-table")]),
                ]
            ),
            html.Div(style={"padding": "12px 0 4px 0"}, children=[
                html.Div("Afficher les colis jusqu'à l'étape :",
                         style={"fontSize": "12px", "color": "#888", "marginBottom": "4px"}),
                dcc.Slider(id="zoom-seq-slider", min=1, max=1, step=1, value=1,
                           marks={1: "1"}, tooltip={"placement": "bottom", "always_visible": True}),
            ]),
            html.Div(id="zoom-legend", style={"fontSize": "15px", "color": "#666", "marginTop": "8px"}),
            html.Div(id="zoom-box-label", style={"fontSize": "26px", "fontWeight": "bold",
                                                  "color": "#222", "padding": "8px 0", "minHeight": "36px"}),
        ]
    )


# ── Dashboard callbacks ────────────────────────────────────────────────────────

def _register_dashboard_callbacks(app, df, color_map, pallet_ids, n_pages):

    @app.callback(
        Output("page-store", "data"),
        Input("btn-prev",        "n_clicks"),
        Input("btn-next",        "n_clicks"),
        Input("btn-prev-bottom", "n_clicks"),
        Input("btn-next-bottom", "n_clicks"),
        State("page-store", "data"),
    )
    def update_page(n_prev, n_next, _n_prev_b, _n_next_b, page):
        from dash import ctx
        if ctx.triggered_id in ("btn-prev", "btn-prev-bottom"):
            return max(0, page - 1)
        if ctx.triggered_id in ("btn-next", "btn-next-bottom"):
            return min(n_pages - 1, page + 1)
        return page

    @app.callback(
        [Output(f"pallet-select-{i}", "value") for i in range(N_PER_PAGE)],
        Input("page-store", "data"),
    )
    def update_dropdown_values(page):
        start = page * N_PER_PAGE
        return [pallet_ids[start + i] if (start + i) < len(pallet_ids) else None
                for i in range(N_PER_PAGE)]

    meta_outputs = []
    for i in range(N_PER_PAGE):
        meta_outputs += [
            Output(f"header-{i}", "children"),
            Output(f"graph-{i}",  "figure"),
            Output(f"stats-{i}",  "children"),
            Output(f"legend-{i}", "children"),
        ]

    @app.callback(meta_outputs,
                  [Input(f"pallet-select-{i}", "value") for i in range(N_PER_PAGE)])
    def update_slot_meta(*selected_pids):
        result = []
        for pid in selected_pids:
            if pid is None:
                result += ["", go.Figure(), [], []]
                continue
            df_p    = df[df["pallet_id"] == pid]
            clients = df_p["client_id"].unique()
            label   = (f"Palette {pid} — Multi-Client" if len(clients) > 1
                       else f"Palette {pid} — Client {clients[0]}")
            fig, stat_rows, legend_items, _ = _render_slot(pid, df, color_map)
            result += [label, fig, stat_rows, legend_items]
        return result

    @app.callback(
        Output("page-label",        "children"),
        Output("page-label-bottom", "children"),
        Input("page-store", "data"),
    )
    def update_label(page):
        start = page * N_PER_PAGE + 1
        end   = min((page + 1) * N_PER_PAGE, len(pallet_ids))
        label = f"Palettes {start}–{end}  /  {len(pallet_ids)}  (page {page+1}/{n_pages})"
        return label, label

    app.clientside_callback(
        "function(page) { window.scrollTo({top: 0, behavior: 'smooth'}); return null; }",
        Output("dashboard-top", "data-scroll"),
        Input("page-store", "data"),
    )

    def _make_view_callback(slot):
        btn_style_outputs = [Output(f"btn-{v}-{slot}", "style") for v in _VIEW_NAMES]

        @app.callback(
            [Output(f"graph-{slot}", "figure", allow_duplicate=True),
             Output(f"graph-{slot}", "config", allow_duplicate=True)]
            + btn_style_outputs,
            Input(f"btn-back-{slot}",  "n_clicks"),
            Input(f"btn-left-{slot}",  "n_clicks"),
            Input(f"btn-front-{slot}", "n_clicks"),
            Input(f"btn-right-{slot}", "n_clicks"),
            Input(f"btn-top-{slot}",   "n_clicks"),
            Input(f"btn-3d-{slot}",    "n_clicks"),
            State(f"pallet-select-{slot}", "value"),
            prevent_initial_call=True,
        )
        def _set_view(n_back, n_left, n_front, n_right, n_top, n_3d, pid):
            from dash import ctx
            tid    = ctx.triggered_id
            active = tid.replace(f"btn-", "").replace(f"-{slot}", "")
            styles = [_VIEW_BTN_ACTIVE if v == active else _VIEW_BTN_STYLE for v in _VIEW_NAMES]
            if pid is None:
                return [go.Figure(), {"displayModeBar": False}] + styles
            config = {"displayModeBar": True, "scrollZoom": True,
                      "modeBarButtonsToRemove": _MODEBAR_DEFAULT}
            if active == "3d":
                fig, _, _, _ = _render_slot(pid, df, color_map)
            else:
                fig = _render_slot_2d(pid, df, color_map, active)
            return [fig, config] + styles

    for _s in range(N_PER_PAGE):
        _make_view_callback(_s)


# ── Zoom callbacks ─────────────────────────────────────────────────────────────

def _register_zoom_callbacks(app, df, color_map, pallet_ids):

    @app.callback(
        Output("zoom-header",     "children"),
        Output("zoom-stats",      "children"),
        Output("zoom-legend",     "children"),
        Output("zoom-seq-slider", "min"),
        Output("zoom-seq-slider", "max"),
        Output("zoom-seq-slider", "value"),
        Output("zoom-seq-slider", "marks"),
        Input("zoom-pallet-select", "value"),
    )
    def update_zoom_meta(pid):
        if pid is None:
            return "", [], [], 1, 1, 1, {1: "1"}
        df_p    = df[df["pallet_id"] == pid]
        clients = df_p["client_id"].unique()
        label   = (f"Palette {pid} — Multi-Client" if len(clients) > 1
                   else f"Palette {pid} — Client {clients[0]}")
        _, stat_rows, legend_items, _ = _render_slot(pid, df, color_map)
        n     = int(df_p["sequence"].max()) if "sequence" in df_p.columns else len(df_p)
        step  = max(1, n // 10)
        marks = {j: str(j) for j in range(1, n + 1, step)}
        marks[n] = str(n)
        return label, stat_rows, legend_items, 1, n, n, marks

    @app.callback(
        Output("zoom-graph",     "figure"),
        Output("zoom-box-label", "children"),
        Output("zoom-p2-table",  "children"),
        Input("zoom-seq-slider", "value"),
        State("zoom-pallet-select", "value"),
    )
    def update_zoom_figure(seq_max, pid):
        if pid is None or seq_max is None:
            return go.Figure(), "", []
        seq  = int(seq_max)
        df_p = df[df["pallet_id"] == pid]
        fig, _, _, box_label = _render_slot(pid, df, color_map, seq_max=seq, highlight_seq=seq)
        is_p2_step = not df_p[(df_p["sequence"] == seq) & (df_p["priority"] == 2)].empty
        p2_table = _build_p2_table(df_p, highlight_seq=seq if is_p2_step else None)
        return fig, box_label, p2_table

    zoom_btn_style_outputs = [Output(f"zoom-btn-{v}", "style") for v in _VIEW_NAMES]

    @app.callback(
        [Output("zoom-graph", "figure", allow_duplicate=True),
         Output("zoom-graph", "config", allow_duplicate=True)]
        + zoom_btn_style_outputs,
        Input("zoom-btn-back",  "n_clicks"),
        Input("zoom-btn-left",  "n_clicks"),
        Input("zoom-btn-front", "n_clicks"),
        Input("zoom-btn-right", "n_clicks"),
        Input("zoom-btn-top",   "n_clicks"),
        Input("zoom-btn-3d",    "n_clicks"),
        State("zoom-pallet-select", "value"),
        prevent_initial_call=True,
    )
    def update_zoom_view(n_back, n_left, n_front, n_right, n_top, n_3d, pid):
        from dash import ctx
        tid    = ctx.triggered_id
        active = tid.replace("zoom-btn-", "")
        styles = [_VIEW_BTN_ACTIVE if v == active else _VIEW_BTN_STYLE for v in _VIEW_NAMES]
        if pid is None:
            return [go.Figure(), {"displayModeBar": False}] + styles
        config = {"displayModeBar": True, "scrollZoom": True,
                  "modeBarButtonsToRemove": _MODEBAR_DEFAULT}
        if active == "3d":
            fig, _, _, _ = _render_slot(pid, df, color_map)
        else:
            fig = _render_slot_2d(pid, df, color_map, active)
            fig.update_layout(margin=dict(b=100))
        return [fig, config] + styles


# ── Unified app builder ────────────────────────────────────────────────────────

def build_app(df: pd.DataFrame, csv_path: str = "") -> dash.Dash:
    """Crée une app Dash standalone avec les vues grille et zoom."""
    def _load_logo(filename):
        path = os.path.join(_ASSETS, filename)
        if not os.path.exists(path):
            return ""
        ext  = filename.rsplit(".", 1)[-1].lower()
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        with open(path, "rb") as _f:
            return f"data:image/{mime};base64," + base64.b64encode(_f.read()).decode()

    logo_b64  = _load_logo("logo_fournier.png")
    logo2_b64 = _load_logo("logo_u4log.jpg")

    color_map  = build_client_color_map(df["client_id"].unique())
    pallet_ids = sorted(df["pallet_id"].unique())
    n_pages    = max(1, -(-len(pallet_ids) // N_PER_PAGE))

    def _pallet_label(pid):
        clients = df[df["pallet_id"] == pid]["client_id"].unique()
        return f"Palette {pid} - Multi" if len(clients) > 1 else f"Palette {pid} - {clients[0]}"

    dropdown_options = [{"label": _pallet_label(pid), "value": pid} for pid in pallet_ids]
    csv_name         = os.path.basename(csv_path) if csv_path else ""
    dashboard_html   = _dashboard_layout(pallet_ids, dropdown_options, n_pages, logo_b64, logo2_b64, csv_name=csv_name)
    zoom_html        = _zoom_layout(dropdown_options, logo_b64, logo2_b64, default_pid=pallet_ids[0], csv_name=csv_name)

    _prefix = os.environ.get("PALLET_DASH_PREFIX", "")
    if _prefix and _prefix != "/":
        app = dash.Dash(__name__, title="Visualiseur Palettes 3D",
                        suppress_callback_exceptions=True,
                        routes_pathname_prefix=_prefix,
                        requests_pathname_prefix=_prefix)
    else:
        app = dash.Dash(__name__, title="Visualiseur Palettes 3D",
                        suppress_callback_exceptions=True)

    _zoom_style = f"<style>body {{ zoom: {PAGE_ZOOM}; }}</style>" if PAGE_ZOOM != 1.0 else ""
    app.index_string = app.index_string.replace(
        "<head>",
        f"<head>{_zoom_style}"
        f"<script>window.addEventListener('pageshow', function(e) {{"
        f"  if (e.persisted) {{ window.location.reload(true); }}"
        f"}});</script>",
    )

    @app.server.after_request
    def _no_cache(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"]        = "no-cache"
        response.headers["Expires"]       = "0"
        return response

    app.layout = html.Div([
        dcc.Location(id="url", refresh=False),
        html.Span(id="_title_dummy", style={"display": "none"}),
        html.Div(id="page-content"),
    ])

    app.clientside_callback(
        """function(pathname) {
            var titles = {'/': 'Vue Grille', '/zoom': 'Vue Zoom'};
            document.title = titles[pathname] || 'Vue Slots Palettes';
            return '';
        }""",
        Output("_title_dummy", "children"),
        Input("url", "pathname"),
    )

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def render_page(pathname):
        if pathname and pathname.endswith("/zoom"):
            return zoom_html
        return dashboard_html

    _register_dashboard_callbacks(app, df, color_map, pallet_ids, n_pages)
    _register_zoom_callbacks(app, df, color_map, pallet_ids)

    return app


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python visualization/view_palette.py <results.csv>")
        sys.exit(1)

    csv_path = sys.argv[1]
    df  = load_pallet_data(csv_path)
    app = build_app(df, csv_path=csv_path)

    host = os.environ.get("PALLET_HOST", "127.0.0.1")
    port = int(os.environ.get("PALLET_PORT", "8051"))

    print(f"\n[Palette] Serveur démarré sur http://{host}:{port}")
    print(f"[Palette] Routes : /  (grille)  |  /zoom  (zoom)")
    print("[Palette] Ctrl+C pour arrêter.\n")

    app.run(debug=False, host=host, port=port)


if __name__ == "__main__":
    main()


# ── Integrated mode (used by visualizer.py) ───────────────────────────────────

def _load_logo_vp(filename: str) -> str:
    path = os.path.join(_ASSETS, filename)
    if not os.path.exists(path):
        return ""
    ext  = filename.rsplit(".", 1)[-1].lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(path, "rb") as _f:
        return f"data:image/{mime};base64," + base64.b64encode(_f.read()).decode()


def grid_layout(state: dict) -> html.Div:
    """Retourne le layout grille paginée depuis le dict state partagé."""
    logo_b64         = _load_logo_vp("logo_fournier.png")
    logo2_b64        = _load_logo_vp("logo_u4log.jpg")
    pallet_ids       = state["pallet_ids"]
    dropdown_options = state["dropdown_options"]
    n_pages          = state["n_pages_val"]
    csv_name         = os.path.basename(state["csv_path"]) if state["csv_path"] else ""
    return _dashboard_layout(pallet_ids, dropdown_options, n_pages,
                             logo_b64, logo2_b64, csv_name=csv_name)


def zoom_layout(state: dict) -> html.Div:
    """Retourne le layout vue zoom depuis le dict state partagé."""
    logo_b64         = _load_logo_vp("logo_fournier.png")
    logo2_b64        = _load_logo_vp("logo_u4log.jpg")
    dropdown_options = state["dropdown_options"]
    pallet_ids       = state["pallet_ids"]
    csv_name         = os.path.basename(state["csv_path"]) if state["csv_path"] else ""
    # Si une palette a été sélectionnée depuis le KPI, l'utiliser comme valeur initiale
    initial_pid = state.get("zoom_initial_pid") or (pallet_ids[0] if pallet_ids else None)
    return _zoom_layout(dropdown_options, logo_b64, logo2_b64,
                        default_pid=initial_pid,
                        csv_name=csv_name)


def register(app: dash.Dash, state: dict) -> None:
    """Enregistre les callbacks grille + zoom dans l'app Dash partagée.

    Tous les callbacks lisent df/color_map/pallet_ids depuis `state` à
    l'exécution — pas à l'enregistrement. Le dict étant passé par référence,
    les mises à jour faites par visualizer.py (après validation du CSV) sont
    immédiatement visibles.
    """
    _reg_dash_callbacks(app, state)
    _reg_zoom_callbacks(app, state)


def _reg_dash_callbacks(app: dash.Dash, state: dict) -> None:

    @app.callback(
        Output("page-store", "data"),
        Input("btn-prev",        "n_clicks"),
        Input("btn-next",        "n_clicks"),
        Input("btn-prev-bottom", "n_clicks"),
        Input("btn-next-bottom", "n_clicks"),
        State("page-store", "data"),
    )
    def _update_page(n_prev, n_next, _np_b, _nn_b, page):
        from dash import ctx
        n_pages = state.get("n_pages_val", 1)
        if ctx.triggered_id in ("btn-prev", "btn-prev-bottom"):
            return max(0, page - 1)
        if ctx.triggered_id in ("btn-next", "btn-next-bottom"):
            return min(n_pages - 1, page + 1)
        return page

    @app.callback(
        [Output(f"pallet-select-{i}", "value") for i in range(N_PER_PAGE)],
        Input("page-store", "data"),
    )
    def _update_dropdown_values(page):
        pallet_ids = state.get("pallet_ids") or []
        start = page * N_PER_PAGE
        return [pallet_ids[start + i] if (start + i) < len(pallet_ids) else None
                for i in range(N_PER_PAGE)]

    meta_outputs = []
    for i in range(N_PER_PAGE):
        meta_outputs += [
            Output(f"header-{i}", "children"),
            Output(f"graph-{i}",  "figure"),
            Output(f"stats-{i}",  "children"),
            Output(f"legend-{i}", "children"),
        ]

    @app.callback(meta_outputs,
                  [Input(f"pallet-select-{i}", "value") for i in range(N_PER_PAGE)])
    def _update_slot_meta(*selected_pids):
        df        = state.get("df")
        color_map = state.get("color_map")
        if df is None:
            return (["", go.Figure(), [], []] * N_PER_PAGE)
        result = []
        for pid in selected_pids:
            if pid is None:
                result += ["", go.Figure(), [], []]
                continue
            df_p    = df[df["pallet_id"] == pid]
            clients = df_p["client_id"].unique()
            label   = (f"Palette {pid} — Multi-Client" if len(clients) > 1
                       else f"Palette {pid} — Client {clients[0]}")
            fig, stat_rows, legend_items, _ = _render_slot(pid, df, color_map)
            result += [label, fig, stat_rows, legend_items]
        return result

    @app.callback(
        Output("page-label",        "children"),
        Output("page-label-bottom", "children"),
        Input("page-store", "data"),
    )
    def _update_label(page):
        pallet_ids = state.get("pallet_ids") or []
        n_pages    = state.get("n_pages_val", 1)
        start = page * N_PER_PAGE + 1
        end   = min((page + 1) * N_PER_PAGE, len(pallet_ids))
        label = f"Palettes {start}–{end}  /  {len(pallet_ids)}  (page {page+1}/{n_pages})"
        return label, label

    app.clientside_callback(
        "function(page) { window.scrollTo({top:0,behavior:'smooth'}); return null; }",
        Output("dashboard-top", "data-scroll"),
        Input("page-store", "data"),
    )

    def _make_view_cb(slot):
        btn_outs = [Output(f"btn-{v}-{slot}", "style") for v in _VIEW_NAMES]

        @app.callback(
            [Output(f"graph-{slot}", "figure", allow_duplicate=True),
             Output(f"graph-{slot}", "config", allow_duplicate=True)]
            + btn_outs,
            Input(f"btn-back-{slot}",  "n_clicks"),
            Input(f"btn-left-{slot}",  "n_clicks"),
            Input(f"btn-front-{slot}", "n_clicks"),
            Input(f"btn-right-{slot}", "n_clicks"),
            Input(f"btn-top-{slot}",   "n_clicks"),
            Input(f"btn-3d-{slot}",    "n_clicks"),
            State(f"pallet-select-{slot}", "value"),
            prevent_initial_call=True,
        )
        def _set_view(n_back, n_left, n_front, n_right, n_top, n_3d, pid):
            from dash import ctx
            df        = state.get("df")
            color_map = state.get("color_map")
            tid    = ctx.triggered_id
            active = tid.replace("btn-", "").replace(f"-{slot}", "")
            styles = [_VIEW_BTN_ACTIVE if v == active else _VIEW_BTN_STYLE
                      for v in _VIEW_NAMES]
            if pid is None or df is None:
                return [go.Figure(), {"displayModeBar": False}] + styles
            config = {"displayModeBar": True, "scrollZoom": True,
                      "modeBarButtonsToRemove": _MODEBAR_DEFAULT}
            fig = (_render_slot(pid, df, color_map)[0] if active == "3d"
                   else _render_slot_2d(pid, df, color_map, active))
            return [fig, config] + styles

    for _s in range(N_PER_PAGE):
        _make_view_cb(_s)


def _reg_zoom_callbacks(app: dash.Dash, state: dict) -> None:

    @app.callback(
        Output("zoom-header",     "children"),
        Output("zoom-stats",      "children"),
        Output("zoom-legend",     "children"),
        Output("zoom-seq-slider", "min"),
        Output("zoom-seq-slider", "max"),
        Output("zoom-seq-slider", "value"),
        Output("zoom-seq-slider", "marks"),
        Input("zoom-pallet-select", "value"),
    )
    def _update_zoom_meta(pid):
        df        = state.get("df")
        color_map = state.get("color_map")
        if pid is None or df is None:
            return "", [], [], 1, 1, 1, {1: "1"}
        df_p    = df[df["pallet_id"] == pid]
        clients = df_p["client_id"].unique()
        label   = (f"Palette {pid} — Multi-Client" if len(clients) > 1
                   else f"Palette {pid} — Client {clients[0]}")
        _, stat_rows, legend_items, _ = _render_slot(pid, df, color_map)
        n     = int(df_p["sequence"].max()) if "sequence" in df_p.columns else len(df_p)
        step  = max(1, n // 10)
        marks = {j: str(j) for j in range(1, n + 1, step)}
        marks[n] = str(n)
        return label, stat_rows, legend_items, 1, n, n, marks

    @app.callback(
        Output("zoom-graph",     "figure"),
        Output("zoom-box-label", "children"),
        Output("zoom-p2-table",  "children"),
        Input("zoom-seq-slider", "value"),
        State("zoom-pallet-select", "value"),
    )
    def _update_zoom_figure(seq_max, pid):
        df        = state.get("df")
        color_map = state.get("color_map")
        if pid is None or seq_max is None or df is None:
            return go.Figure(), "", []
        seq  = int(seq_max)
        df_p = df[df["pallet_id"] == pid]
        fig, _, _, box_label = _render_slot(pid, df, color_map,
                                            seq_max=seq, highlight_seq=seq)
        is_p2 = not df_p[(df_p["sequence"] == seq) & (df_p["priority"] == 2)].empty
        p2_table = _build_p2_table(df_p, highlight_seq=seq if is_p2 else None)
        return fig, box_label, p2_table

    zoom_btn_outs = [Output(f"zoom-btn-{v}", "style") for v in _VIEW_NAMES]

    @app.callback(
        [Output("zoom-graph", "figure", allow_duplicate=True),
         Output("zoom-graph", "config", allow_duplicate=True)]
        + zoom_btn_outs,
        Input("zoom-btn-back",  "n_clicks"),
        Input("zoom-btn-left",  "n_clicks"),
        Input("zoom-btn-front", "n_clicks"),
        Input("zoom-btn-right", "n_clicks"),
        Input("zoom-btn-top",   "n_clicks"),
        Input("zoom-btn-3d",    "n_clicks"),
        State("zoom-pallet-select", "value"),
        prevent_initial_call=True,
    )
    def _update_zoom_view(n_back, n_left, n_front, n_right, n_top, n_3d, pid):
        from dash import ctx
        df        = state.get("df")
        color_map = state.get("color_map")
        tid    = ctx.triggered_id
        active = tid.replace("zoom-btn-", "")
        styles = [_VIEW_BTN_ACTIVE if v == active else _VIEW_BTN_STYLE
                  for v in _VIEW_NAMES]
        if pid is None or df is None:
            return [go.Figure(), {"displayModeBar": False}] + styles
        config = {"displayModeBar": True, "scrollZoom": True,
                  "modeBarButtonsToRemove": _MODEBAR_DEFAULT}
        if active == "3d":
            fig, _, _, _ = _render_slot(pid, df, color_map)
        else:
            fig = _render_slot_2d(pid, df, color_map, active)
            fig.update_layout(margin=dict(b=100))
        return [fig, config] + styles
