"""
run_profile.py — Profiling cProfile du pipeline pallet_optimizer.

Usage :
    python run_profile.py

Sorties :
    - Rapport texte dans la console (top 20 tottime + top 20 cumtime)
    - profile_output.prof  — visualisable avec snakeviz :
          pip install snakeviz
          snakeviz profile_output.prof
"""

import cProfile
import glob
import pstats
import io
import sys
import os

# ── Path setup ────────────────────────────────────────────────────────────────
_DIR  = os.path.dirname(os.path.abspath(__file__))   # .../pallet_optimizer/profiling/
_BASE = os.path.dirname(_DIR)                         # .../pallet_optimizer/
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from config.parameters import OptimizationParameters
from file_io.csv_reader import read_boxes_from_csv
from optimizer.pallet_optimizer import optimize_palletization
from heuristics.post_processing import postprocess

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_DIR   = os.path.join(_BASE, r"input\tournee_type2026\SL18in")
PROF_FILE   = os.path.join(_DIR, "profile_output.prof")
TOP_N       = 20

params = OptimizationParameters()


# ── Pipeline profilée ─────────────────────────────────────────────────────────
def pipeline():
    csv_files   = sorted(glob.glob(os.path.join(INPUT_DIR, "*.csv")))
    all_pallets = []
    for csv_file in csv_files:
        fname   = os.path.basename(csv_file)
        boxes   = read_boxes_from_csv(csv_file)
        pallets = optimize_palletization(boxes, params)
        if params.enable_post_processing:
            pallets = postprocess(pallets, boxes, params)
        print(f"  {fname}: {len(pallets)} palette(s), {sum(len(p.boxes) for p in pallets)} colis")
        all_pallets.extend(pallets)
    return all_pallets


# ── Lancement ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _csv_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.csv")))
    print(f"[Profile] Dossier d'entrée : {INPUT_DIR}")
    print(f"[Profile] Fichiers CSV     : {len(_csv_files)}")
    print(f"[Profile] Post-processing  : {params.enable_post_processing}")
    print("[Profile] Démarrage du profiler...\n")

    profiler = cProfile.Profile()
    profiler.enable()
    result = pipeline()
    profiler.disable()

    total_colis    = sum(len(p.boxes) for p in result)
    total_palettes = len(result)
    print(f"\n[Profile] Pipeline terminé — {total_colis} colis placés "
          f"sur {total_palettes} palette(s) sur {len(_csv_files)} fichier(s).\n")

    # ── Rapport console ───────────────────────────────────────────────────────
    stream = io.StringIO()
    ps = pstats.Stats(profiler, stream=stream)
    ps.strip_dirs()

    sep = "=" * 70

    print(sep)
    print(f"  TOP {TOP_N} — CUMTIME  (temps cumulé, inclut les sous-fonctions)")
    print(sep)
    ps.sort_stats("cumulative")
    ps.print_stats(TOP_N)
    print(stream.getvalue())

    stream = io.StringIO()
    ps = pstats.Stats(profiler, stream=stream)
    ps.strip_dirs()

    print(sep)
    print(f"  TOP {TOP_N} — TOTTIME  (temps propre à la fonction, hors sous-appels)")
    print(sep)
    ps.sort_stats("tottime")
    ps.print_stats(TOP_N)
    print(stream.getvalue())

    # ── Sauvegarde .prof ──────────────────────────────────────────────────────
    profiler.dump_stats(PROF_FILE)
    print(f"[Profile] Fichier .prof sauvegardé : {PROF_FILE}")
    print(f"[Profile] Visualiser avec : snakeviz {PROF_FILE}")
