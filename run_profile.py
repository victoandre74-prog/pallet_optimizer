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
import pstats
import io
import sys
import os

# ── Path setup identique à main.py ───────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from config.parameters import OptimizationParameters
from file_io.csv_reader import read_boxes_from_csv
from optimizer.pallet_optimizer import optimize_palletization
from heuristics.post_processing import postprocess

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_CSV   = r"input\tournee_type2026\tournee_type2026.csv"
OUTPUT_FAKE = r"output\profile_run_results.csv"   # chemin fictif, le fichier n'est pas écrit
PROF_FILE   = "profile_output.prof"
TOP_N       = 20

params = OptimizationParameters()


# ── Pipeline profilée ─────────────────────────────────────────────────────────
def pipeline():
    boxes   = read_boxes_from_csv(INPUT_CSV)
    pallets = optimize_palletization(boxes, params, output_path=OUTPUT_FAKE)
    if params.enable_post_processing:
        pallets = postprocess(pallets, boxes, params)
    return pallets


# ── Lancement ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[Profile] Fichier d'entrée : {INPUT_CSV}")
    print(f"[Profile] Post-processing  : {params.enable_post_processing}")
    print("[Profile] Démarrage du profiler...\n")

    profiler = cProfile.Profile()
    profiler.enable()
    result = pipeline()
    profiler.disable()

    print(f"\n[Profile] Pipeline terminé — {sum(len(p.boxes) for p in result)} colis placés "
          f"sur {len(result)} palette(s).\n")

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
