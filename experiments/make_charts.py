"""Génère les graphiques d'analyse du sweep2_results.csv."""
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import Normalize
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_DIR, "sweep2_results.csv")

with open(CSV_PATH, encoding="utf-8") as f:
    raw = list(csv.DictReader(f))

def flt(v):
    try: return float(v)
    except: return float("nan")

data = [{k: flt(v) for k, v in r.items()} for r in raw]
for i, r in enumerate(data):
    r["trial_number"] = int(raw[i]["trial_number"])
    r["pareto"]       = int(raw[i]["pareto"])
    r["mc_delta"]     = r["multi_client_maximum_ratio"] - r["multi_client_minimum_ratio"]

pareto = [d for d in data if d["pareto"] == 1]
dom    = [d for d in data if d["pareto"] == 0]

def arr(key, subset=data):
    return np.array([d[key] for d in subset])

PAL    = "final_pallets"
RATIO  = "multi_client_ratio"
MC_MIN = "multi_client_minimum_ratio"
FILL   = "min_filling_ratio"


# ── Fig 1 : Front de Pareto ──────────────────────────────────────────────────
fig1, ax = plt.subplots(figsize=(10, 6))
ax.scatter(arr(PAL, dom),    arr(RATIO, dom)*100,
           c="#CCCCCC", s=25, label="Dominé", zorder=2, alpha=0.5)
ax.scatter(arr(PAL, pareto), arr(RATIO, pareto)*100,
           c="#2196F3", s=55, label="Pareto", zorder=3,
           edgecolors="#1565C0", linewidths=0.7)
pareto_s = sorted(pareto, key=lambda d: d[PAL])
ax.plot([d[PAL] for d in pareto_s], [d[RATIO]*100 for d in pareto_s],
        c="#1565C0", lw=1.1, ls="--", zorder=2, alpha=0.6)
knee = min(pareto, key=lambda d: abs(d[RATIO]*100 - 17) + abs(d[PAL]-3900)/50)
ax.annotate(
    f"Genou\n{int(knee[PAL])} pal / {knee[RATIO]*100:.1f}% MC",
    xy=(knee[PAL], knee[RATIO]*100), fontsize=8.5, color="#1565C0",
    arrowprops=dict(arrowstyle="->", color="#1565C0", lw=1.1),
    xytext=(knee[PAL]+120, knee[RATIO]*100+4),
)
ax.set_xlabel("Palettes totales", fontsize=11)
ax.set_ylabel("Taux multi-AR (%)", fontsize=11)
ax.set_title(
    "Front de Pareto  —  palettes vs taux multi-AR\n(200 essais NSGA-II, PP off)",
    fontsize=12,
)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)
fig1.tight_layout()
fig1.savefig(os.path.join(_DIR, "sweep2_fig1_pareto.png"), dpi=150)
plt.close(fig1)
print("Fig 1 OK")


# ── Fig 2 : Influence des paramètres (2x3) ───────────────────────────────────
fig2, axes = plt.subplots(2, 3, figsize=(14, 8))
params = [
    (MC_MIN,     "mc_min"),
    ("mc_delta", "mc_max - mc_min"),
    (FILL,       "min_filling_ratio"),
]
objectives = [
    (PAL,   "Palettes totales",  "RdYlGn_r"),
    (RATIO, "Taux multi-AR (%)", "RdYlGn"),
]
for row, (obj_key, obj_label, cmap) in enumerate(objectives):
    vals_raw = arr(obj_key)
    norm = Normalize(vmin=np.nanmin(vals_raw), vmax=np.nanmax(vals_raw))
    for col, (param_key, param_label) in enumerate(params):
        ax = axes[row, col]
        x = arr(param_key)
        y = vals_raw * (100 if obj_key == RATIO else 1)
        sc = ax.scatter(x, y, c=vals_raw, cmap=cmap, norm=norm, s=22, alpha=0.75)
        mask = ~(np.isnan(x) | np.isnan(y))
        if mask.sum() > 3:
            z = np.polyfit(x[mask], y[mask], 1)
            xl = np.linspace(x[mask].min(), x[mask].max(), 50)
            ax.plot(xl, np.polyval(z, xl), "k--", lw=1, alpha=0.45)
            r = np.corrcoef(x[mask], y[mask])[0, 1]
            ax.text(0.97, 0.95, f"r={r:+.2f}", transform=ax.transAxes,
                    fontsize=8.5, ha="right", va="top")
        ax.set_xlabel(param_label, fontsize=9)
        ax.set_ylabel("% multi-AR" if obj_key == RATIO else "Palettes", fontsize=9)
        plt.colorbar(sc, ax=ax, label=obj_label, pad=0.02)
        ax.grid(True, alpha=0.25)
fig2.suptitle("Influence des paramètres sur les deux objectifs  (tous essais)", fontsize=13)
fig2.tight_layout()
fig2.savefig(os.path.join(_DIR, "sweep2_fig2_influence.png"), dpi=150, bbox_inches="tight")
plt.close(fig2)
print("Fig 2 OK")


# ── Fig 3 : Distributions Pareto vs dominé ───────────────────────────────────
fig3, axes = plt.subplots(1, 3, figsize=(13, 4))
param_info = [
    (MC_MIN,     "mc_min",           (0.02, 0.23), 14),
    ("mc_delta", "mc_delta",         (0.01, 0.25), 14),
    (FILL,       "min_filling_ratio", (0.20, 0.55), 14),
]
for ax, (key, label, rng, bins) in zip(axes, param_info):
    kw = dict(bins=bins, range=rng, density=True, alpha=0.6, edgecolor="white", lw=0.4)
    ax.hist(arr(key, dom),    color="#BBBBBB", label=f"Dominé ({len(dom)})",    **kw)
    ax.hist(arr(key, pareto), color="#2196F3", label=f"Pareto ({len(pareto)})", **kw)
    ax.set_xlabel(label, fontsize=10)
    ax.set_ylabel("Densité", fontsize=9)
    ax.set_title(label, fontsize=10)
    ax.legend(fontsize=8.5)
    ax.grid(True, alpha=0.3)
fig3.suptitle("Distribution des paramètres : Pareto vs dominé", fontsize=12)
fig3.tight_layout()
fig3.savefig(os.path.join(_DIR, "sweep2_fig3_distributions.png"), dpi=150)
plt.close(fig3)
print("Fig 3 OK")


# ── Fig 4 : Carte de chaleur mc_min x fill (Pareto) ──────────────────────────
fig4, axes = plt.subplots(1, 2, figsize=(13, 5))
for ax, (obj_key, obj_label, cmap) in zip(axes, [
    (PAL,   "Palettes totales",  "RdYlGn_r"),
    (RATIO, "Taux multi-AR (%)", "RdYlGn"),
]):
    x = arr(MC_MIN, pareto)
    y = arr(FILL,   pareto)
    z = arr(obj_key, pareto) * (100 if obj_key == RATIO else 1)
    sc = ax.scatter(x, y, c=z, cmap=cmap, s=75, edgecolors="grey", lw=0.3, zorder=3)
    plt.colorbar(sc, ax=ax, label=obj_label)
    ax.set_xlabel("mc_min", fontsize=10)
    ax.set_ylabel("min_filling_ratio", fontsize=10)
    ax.set_title(f"Pareto — {obj_label}", fontsize=11)
    ax.grid(True, alpha=0.3)
fig4.suptitle("Carte de chaleur mc_min x fill_ratio  (solutions Pareto)", fontsize=12)
fig4.tight_layout()
fig4.savefig(os.path.join(_DIR, "sweep2_fig4_heatmap.png"), dpi=150)
plt.close(fig4)
print("Fig 4 OK")


# ── Fig 5 : Runtime vs objectifs ─────────────────────────────────────────────
fig5, axes = plt.subplots(1, 2, figsize=(12, 4.5))
for ax, (obj_key, obj_label) in zip(axes, [
    (PAL,   "Palettes totales"),
    (RATIO, "Taux multi-AR (%)"),
]):
    x = arr("total_runtime_s")
    y = arr(obj_key) * (100 if obj_key == RATIO else 1)
    colors = ["#2196F3" if d["pareto"] == 1 else "#BBBBBB" for d in data]
    ax.scatter(x, y, c=colors, s=22, alpha=0.7)
    mask = ~(np.isnan(x) | np.isnan(y))
    z = np.polyfit(x[mask], y[mask], 1)
    xl = np.linspace(x[mask].min(), x[mask].max(), 50)
    ax.plot(xl, np.polyval(z, xl), "r--", lw=1, alpha=0.5)
    r = np.corrcoef(x[mask], y[mask])[0, 1]
    ax.text(0.97, 0.95, f"r={r:+.2f}", transform=ax.transAxes,
            fontsize=9, ha="right", va="top", color="red")
    ax.set_xlabel("Runtime total (s)", fontsize=10)
    ax.set_ylabel(obj_label, fontsize=10)
    ax.set_title(f"Runtime vs {obj_label}", fontsize=11)
    ax.grid(True, alpha=0.3)
fig5.legend(
    handles=[
        mpatches.Patch(color="#2196F3", label="Pareto"),
        mpatches.Patch(color="#BBBBBB", label="Dominé"),
    ],
    loc="upper center", ncol=2, fontsize=9,
)
fig5.suptitle("Temps de calcul vs objectifs", fontsize=12, y=1.03)
fig5.tight_layout()
fig5.savefig(os.path.join(_DIR, "sweep2_fig5_runtime.png"), dpi=150, bbox_inches="tight")
plt.close(fig5)
print("Fig 5 OK")

print("Tous les graphiques sauvegardes.")
