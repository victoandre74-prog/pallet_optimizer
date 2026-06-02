"""
main.py — Point d'entrée de l'optimiseur de palettisation.

Ce fichier est le « lanceur » du programme. Il coordonne le traitement
de tous les fichiers CSV d'entrée et produit les fichiers de sortie.

Comment l'utiliser :
    python main.py
    python main.py --input-dir input/ --output-dir output/
    python main.py --max-workers 4  (traitement parallèle de 4 fichiers)

Pour chaque fichier CSV d'entrée (ex. commande42.csv), les sorties créées sont :
    commande42_log_<ts>.txt       — journal complet de l'exécution
    commande42_results_<ts>.csv   — positions optimisées (UNIQUEMENT si succès total)

Le fichier résultats n'est créé QUE si la Phase 6 (vérification de sécurité)
valide l'intégrité : tous les colis d'entrée sont présents en sortie, sans
modification de leurs propriétés. Sa présence est donc un signal de succès fiable.

Contrat BATCH-STATUS :
    Chaque traitement de fichier émet exactement une ligne de la forme :
        [BATCH-STATUS] stem=<nom> code=<CODE> [detail="<texte>"]
    en dernière ligne meaningful du log.
    Codes possibles :
        OK               — succès complet
        ERR_VALIDATION   — Phase 0 : CSV invalide (structure / dimensions)
        ERR_EMPTY_INPUT  — Phase 0 : CSV vide ou sans boîtes
        ERR_SECURITY     — Phase 6 : boîtes perdues ou mutées
        ERR_EXCEPTION    — exception non gérée dans le pipeline
        ERR_UNKNOWN      — fallback (ne devrait jamais apparaître)

Tuning des paramètres :
    Modifiez config/parameters.py ou passez --params-json '{"pallet_length": 120}'.
"""

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Force l'encodage UTF-8 sur Windows pour que les caractères Unicode (boîtes,
# flèches, accents) s'affichent correctement dans la console PowerShell.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Configuration du chemin Python ─────────────────────────────────────────────
# Ajoute le répertoire du fichier courant au sys.path pour permettre les imports
# relatifs depuis les sous-modules (config/, models/, etc.).
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from config.parameters import OptimizationParameters

# Séparateur visuel pour les sections de log
_SEP = "=" * 55


# ── Contrat BATCH-STATUS ───────────────────────────────────────────────────────
# Marqueur que app.py utilise pour lire le statut de chaque traitement.
# NE PAS modifier le format sans mettre à jour app.py::_read_batch_status.
BATCH_STATUS_MARKER = "[BATCH-STATUS]"


def _emit_batch_status(stem: str, code: str, detail: str = "") -> None:
    """
    Émet la ligne de contrat BATCH-STATUS dans le log.

    Format : [BATCH-STATUS] stem=<stem> code=<CODE> [detail="<texte>"]

    La ligne est sur une seule ligne (les newlines dans detail sont remplacés).
    Elle est émise dans le bloc finally pour être toujours présente, même
    en cas d'exception.
    """
    parts = [BATCH_STATUS_MARKER, f"stem={stem}", f"code={code}"]
    if detail:
        # Garantit que la ligne reste sur une seule ligne (parsing simplifié côté app.py)
        safe = detail.replace("\n", " ").replace("\r", " ").strip()
        parts.append(f'detail="{safe}"')
    print(" ".join(parts))


def _phase_header(n: int, title: str) -> None:
    """Affiche un en-tête de phase dans la console."""
    print(f"\n{_SEP}")
    print(f"Phase {n} — {title}")
    print(_SEP)


def _phase_footer(n: int) -> None:
    """Affiche un pied de phase dans la console."""
    print(f"{_SEP}")
    print(f"Fin de la Phase {n}")
    print(f"{_SEP}")


class _Tee:
    """
    Redirige la sortie standard vers un fichier log ET vers la console.

    Utilisé pour capturer tout ce que print() produit dans un fichier journal,
    tout en continuant d'afficher en temps réel dans la console.

    Paramètre mirror : si False, écrit uniquement dans le fichier (mode silencieux).
    Ce mode est utilisé en traitement parallèle (max_workers > 1) pour éviter
    que les sorties de plusieurs workers se mélangent dans la console.
    """
    def __init__(self, stream, path, mirror: bool = True):
        self._stream = stream if mirror else None
        self._file   = open(path, "w", encoding="utf-8", errors="replace")

    def write(self, data):
        if self._stream:
            self._stream.write(data)
        self._file.write(data)

    def flush(self):
        if self._stream:
            self._stream.flush()
        self._file.flush()

    def close(self):
        self._file.close()

    def __getattr__(self, name):
        """Délègue les autres accès (ex. .encoding) au stream original."""
        return getattr(self._stream, name)


# ── Imports du pipeline (après la config du path) ──────────────────────────────
from file_io.csv_reader import read_boxes_from_csv, validate_csv
from file_io.csv_writer import write_results_to_csv
from file_io.kpi_writer import compute_kpi_rows
from optimizer.pallet_optimizer import optimize_palletization
from heuristics.post_processing import postprocess


def parse_args():
    """
    Analyse les arguments de la ligne de commande.

    Arguments disponibles :
        --input-dir    : dossier contenant les CSV d'entrée (défaut : input/)
        --output-dir   : dossier de sortie (défaut : output/)
        --params-json  : surcharge JSON des paramètres (ex. '{"pallet_length": 120}')
        --max-workers  : nombre de fichiers traités en parallèle (défaut : 1)
    """
    parser = argparse.ArgumentParser(
        description="Optimiseur de palettisation 3D",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        default="input",
        help="Dossier contenant les CSV d'entrée (défaut : input/)."
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Dossier de sortie pour tous les fichiers (défaut : output/)."
    )
    parser.add_argument(
        "--params-json",
        default="{}",
        help="JSON de surcharge des paramètres OptimizationParameters."
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        metavar="N",
        help="Nombre de fichiers CSV traités en parallèle (défaut : 1 = séquentiel).",
    )
    return parser.parse_args()


def _collect_inputs(input_dir: str) -> list[Path]:
    """
    Collecte tous les fichiers .csv du dossier d'entrée, triés alphabétiquement.

    Arrête le programme si le dossier n'existe pas ou ne contient aucun CSV.
    """
    folder = Path(input_dir)
    if not folder.is_dir():
        print(f"ERREUR : Dossier d'entrée introuvable : {input_dir}")
        sys.exit(1)
    files = sorted(folder.glob("*.csv"))
    if not files:
        print(f"ERREUR : Aucun fichier CSV trouvé dans : {input_dir}")
        sys.exit(1)
    return files


def _process_one(
    input_path: Path,
    output_dir: Path,
    params: OptimizationParameters,
    quiet: bool = False,
) -> tuple:
    """
    Exécute le pipeline complet d'optimisation pour un seul fichier CSV d'entrée.

    Phases exécutées :
        Phase 0 — Validation CSV et chargement des boîtes
        Phases 1–4 — Optimisation (FFD + LNS mono + fusion + LNS multi)
        Phase 5 — Post-traitement (P2 contact, équilibrage fill, centrage)
        Phase 6 — Vérification de sécurité (intégrité des boîtes)
        (Écriture du CSV résultats — uniquement si Phase 6 passe)

    Retourne un tuple (check_ok, status_code, status_detail) :
        check_ok     : True si tout s'est bien passé
        status_code  : code du contrat BATCH-STATUS (OK, ERR_*, ...)
        status_detail: texte libre décrivant l'erreur (vide si OK)

    Le log est capturé dans {stem}_log_<ts>.txt via la classe _Tee.
    """
    from datetime import datetime
    stem         = input_path.stem
    ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results_path = output_dir / f"{stem}_results_{ts}.csv"
    report_path  = output_dir / f"{stem}_log_{ts}.txt"

    # ── Ouvre le log (et optionnellement le miroir console) ───────────────────
    _original_stdout = sys.stdout
    tee              = _Tee(sys.stdout, str(report_path), mirror=not quiet)
    sys.stdout       = tee

    # Code de statut par défaut : ERR_UNKNOWN (remplacé par chaque chemin de code)
    status_code   = "ERR_UNKNOWN"
    status_detail = ""

    try:
        t_start = time.time()

        # ── En-tête du log ────────────────────────────────────────────────────
        print(f"\n{_SEP}")
        print(f"  Optimiseur de palettisation 3D — {input_path.name}")
        print(f"{_SEP}")
        print(f"  Entrée      : {input_path}")
        print(f"  Sortie      : {results_path}")
        print(f"  Horodatage  : {ts_display}")
        print(f"  --- Géométrie palette ---")
        print(f"  pallet_length              : {params.pallet_length} cm")
        print(f"  pallet_width               : {params.pallet_width} cm")
        print(f"  pallet_max_height          : {params.pallet_max_height} cm")
        print(f"  pallet_max_weight          : {params.pallet_max_weight} kg")
        print(f"  --- Physique / stabilité ---")
        print(f"  min_support_ratio          : {params.min_support_ratio}")
        print(f"  stability_ratio            : {params.stability_ratio}")
        print(f"  --- Ergonomie ---")
        print(f"  priority2_max_deposit_height: {params.priority2_max_deposit_height} cm")
        print(f"  --- Stratégie multi-client ---")
        print(f"  enable_multi_client        : {params.enable_multi_client}")
        print(f"  min_filling_ratio          : {params.min_filling_ratio}")
        print(f"  multi_client_minimum_ratio : {params.multi_client_minimum_ratio}")
        print(f"  multi_client_maximum_ratio : {params.multi_client_maximum_ratio}")
        print(f"  --- LNS mono-client ---")
        print(f"  lns_mono_time_per_pallet   : {params.lns_mono_time_per_pallet} s/palette")
        print(f"  lns_mono_small_box_volume  : {params.lns_mono_small_box_volume} cm³")
        print(f"  lns_mono_repair_top_k      : {params.lns_mono_repair_top_k}")
        print(f"  lns_mono_iter_per_pallet   : {params.lns_mono_iter_per_pallet} iters/palette")
        print(f"  lns_mono_random_seed       : {params.lns_mono_random_seed}")
        print(f"  --- LNS multi-client ---")
        print(f"  lns_multi_time_per_pallet  : {params.lns_multi_time_per_pallet} s/palette")
        print(f"  lns_multi_iter_per_pallet  : {params.lns_multi_iter_per_pallet} iters/palette")
        print(f"  lns_multi_destroy_ratio    : {params.lns_multi_destroy_ratio}")
        print(f"  lns_multi_repair_top_k     : {params.lns_multi_repair_top_k}")
        print(f"  lns_multi_random_seed      : {params.lns_multi_random_seed}")
        print(f"  --- Post-traitement ---")
        print(f"  enable_post_processing     : {params.enable_post_processing}")
        print(f"  pp_time_per_pallet         : {params.pp_time_per_pallet} s/palette")
        print(f"  pp_iter_per_pallet         : {params.pp_iter_per_pallet} iters/palette")
        print(f"  pp_top_k                   : {params.pp_top_k}")
        print(f"  pp_random_seed             : {params.pp_random_seed}")
        print(f"  pp_w_contact               : {params.pp_w_contact}")
        print(f"  pp_w_fill                  : {params.pp_w_fill}")
        print(f"  pp_w_p2                    : {params.pp_w_p2}")
        print(f"  pp_center_min_shift        : {params.pp_center_min_shift} cm")
        print(f"{_SEP}\n")

        # ── Phase 0 : validation CSV et chargement ─────────────────────────────
        _phase_header(0, "Contrôle du CSV d'entrée")
        print(f"  Fichier : {input_path.name}")

        # validate_csv retourne une liste vide si tout va bien
        errors = validate_csv(str(input_path), pallet_max_height=params.pallet_max_height)
        if errors:
            print(f"\n  VALIDATION CSV ÉCHOUÉE — {len(errors)} erreur(s) :")
            for err in errors:
                print(f"    [ERREUR] {err}")
            _phase_footer(0)
            print(f"\n[Abandonné] Corrigez le fichier d'entrée et relancez.")
            status_code   = "ERR_VALIDATION"
            status_detail = f"{len(errors)} erreur(s) de validation"
            return False, status_code, status_detail, [], None

        boxes = read_boxes_from_csv(str(input_path))
        if not boxes:
            print("  ERREUR : Aucune boîte chargée. Vérifiez le format CSV.")
            _phase_footer(0)
            status_code   = "ERR_EMPTY_INPUT"
            status_detail = "aucune boîte chargée depuis le CSV"
            return False, status_code, status_detail, [], None

        unique_clients = len({b.client_id for b in boxes})
        print(f"  Boîtes  : {len(boxes)}")
        print(f"  Clients : {unique_clients}")
        print(f"  Statut  : OK")
        _phase_footer(0)

        # ── Phases 1–4 : optimiseur (FFD + LNS mono + fusion + LNS multi) ──────
        pallets = optimize_palletization(boxes, params)

        # ── Phase 5 : post-traitement (contact P2, équilibre, centrage) ──────────
        _phase_header(5, "Post-traitement (répartition P2, fill, centrage)")
        if params.enable_post_processing:
            pallets = postprocess(pallets, boxes, params)
        else:
            print("  Sauté (enable_post_processing = False).")
        _phase_footer(5)

        # ── Phase 6 : vérification de sécurité (avant l'écriture) ────────────────
        # Le CSV résultats n'est écrit QUE si cette phase passe complètement.
        # Cela garantit que la présence du fichier résultats = succès total.
        _phase_header(6, "Vérification de sécurité — intégrité des boîtes")

        input_ids  = [b.id for b in boxes]
        input_set  = set(input_ids)
        output_ids = [pb.box_id for p in pallets for pb in p.boxes]
        output_set = set(output_ids)
        input_map: dict[str, object] = {b.id: b for b in boxes}

        check_ok        = True
        security_reason = ""

        # ── Vérification 1 : même nombre de boîtes ─────────────────────────────
        if len(output_ids) != len(input_ids):
            print(f"  [ÉCHEC] Écart de count : entrée={len(input_ids)}, sortie={len(output_ids)}")
            check_ok        = False
            security_reason = f"écart count entrée={len(input_ids)} sortie={len(output_ids)}"

        # ── Vérification 2 : aucune boîte perdue ───────────────────────────────
        missing = input_set - output_set
        if missing:
            print(f"  [ÉCHEC] {len(missing)} id(s) de l'entrée absents en sortie :")
            for bid in sorted(missing)[:10]:
                print(f"         - {bid}")
            if len(missing) > 10:
                print(f"         ... et {len(missing) - 10} de plus.")
            check_ok = False
            if not security_reason:
                security_reason = f"{len(missing)} boîte(s) absente(s) en sortie"

        # ── Vérification 3 : aucune boîte en trop ──────────────────────────────
        extra = output_set - input_set
        if extra:
            print(f"  [ÉCHEC] {len(extra)} id(s) en sortie absent(s) de l'entrée :")
            for bid in sorted(extra)[:10]:
                print(f"         - {bid}")
            check_ok = False
            if not security_reason:
                security_reason = f"{len(extra)} boîte(s) en trop en sortie"

        # ── Vérification 4 : numéros de séquence uniques par palette ──────────
        seq_errors: list[str] = []
        for p in pallets:
            seen_seqs: dict[int, list[str]] = {}
            for pb in p.boxes:
                seen_seqs.setdefault(pb.sequence, []).append(pb.box_id)
            for seq, box_ids in seen_seqs.items():
                if len(box_ids) > 1:
                    seq_errors.append(
                        f"palette {p.id}: séquence {seq} partagée par "
                        + ", ".join(box_ids[:5])
                        + (f" … (+{len(box_ids)-5} de plus)" if len(box_ids) > 5 else "")
                    )
        if seq_errors:
            print(f"  [ÉCHEC] Doublons de séquence ({len(seq_errors)} palette(s) affectée(s)) :")
            for msg in seq_errors:
                print(f"         - {msg}")
            check_ok = False
            if not security_reason:
                security_reason = f"doublons séquence dans {len(seq_errors)} palette(s)"

        # ── Vérification 5 : immutabilité des champs Box → PlacedBox ──────────
        # Pour chaque boîte placée, vérifie que les champs copiés depuis Box
        # n'ont pas été mutés : client_id, priority, weight, orientation (dans
        # la liste autorisée), et dimensions (cohérentes avec l'orientation).
        field_errors: list[str] = []
        for p in pallets:
            for pb in p.boxes:
                orig = input_map.get(pb.box_id)
                if orig is None:
                    continue   # id inconnu : déjà détecté dans la vérification extra

                violations: list[str] = []

                if pb.client_id != orig.client_id:
                    violations.append(
                        f"client_id: entrée={orig.client_id} → sortie={pb.client_id}"
                    )
                if pb.priority != orig.priority:
                    violations.append(
                        f"priority: entrée={orig.priority} → sortie={pb.priority}"
                    )
                if pb.weight != orig.weight:
                    violations.append(
                        f"weight: entrée={orig.weight} → sortie={pb.weight}"
                    )
                if pb.orientation not in orig.allowed_orientations:
                    allowed_str = ", ".join(o.value for o in orig.allowed_orientations)
                    violations.append(
                        f"orientation: placée={pb.orientation.value!r} non dans "
                        f"allowed=[{allowed_str}]"
                    )
                # Les dimensions placées doivent correspondre aux dimensions originales
                # recalculées avec l'orientation choisie.
                exp_l, exp_w, exp_h = orig.get_oriented_dims(pb.orientation)
                if pb.length != exp_l or pb.width != exp_w or pb.height != exp_h:
                    violations.append(
                        f"dims: placées=({pb.length}×{pb.width}×{pb.height})"
                        f" ≠ attendues=({exp_l}×{exp_w}×{exp_h})"
                        f" pour orientation={pb.orientation.value}"
                    )

                if violations:
                    field_errors.append(
                        f"box_id={pb.box_id!r} palette={p.id}: "
                        + " | ".join(violations)
                    )

        if field_errors:
            print(f"  [ÉCHEC] Mutations de champs Box détectées ({len(field_errors)} boîte(s)) :")
            for msg in field_errors[:10]:
                print(f"         - {msg}")
            if len(field_errors) > 10:
                print(f"         ... et {len(field_errors) - 10} de plus.")
            check_ok = False
            if not security_reason:
                security_reason = f"{len(field_errors)} boîte(s) avec champs mutés"

        if check_ok:
            print(f"  [OK] Toutes les {len(input_ids)} boîte(s) comptabilisées — entrée = sortie.")
            print(f"  [OK] Numéros de séquence uniques dans chaque palette.")
            print(f"  [OK] Intégrité des champs Box vérifiée (client, priority, weight, dims, orientation).")
        _phase_footer(6)

        # ── Écriture du CSV résultats — seulement si la phase 6 est OK ─────────
        kpi_rows = []
        if check_ok:
            write_results_to_csv(pallets, str(results_path))
            print(f"  Résultat sauvegardé : {results_path}")
            kpi_rows = compute_kpi_rows(pallets)
        else:
            print(f"  Résultat NON écrit ({results_path.name}) — vérification d'intégrité échouée.")

        print(f"\n{_SEP}")
        print(f"  Durée totale : {time.time() - t_start:.1f}s")
        if check_ok:
            print(f"  Sortie       : {results_path.name}")
        print(f"{_SEP}")

        if check_ok:
            status_code   = "OK"
            status_detail = ""
        else:
            status_code   = "ERR_SECURITY"
            status_detail = security_reason
        return check_ok, status_code, status_detail, kpi_rows, (results_path.name if check_ok else None)

    except Exception as e:
        # Capture toutes les exceptions non gérées (bug dans le pipeline)
        print(f"\n{_SEP}")
        print(f"  ERREUR INATTENDUE")
        print(f"{_SEP}")
        traceback.print_exc(file=sys.stdout)   # affiche la pile d'appels complète
        print(f"{_SEP}")
        print(f"\n[Abandonné] Traitement de {input_path.name} échoué.")
        status_code   = "ERR_EXCEPTION"
        status_detail = (str(e) or type(e).__name__)[:200]
        return False, status_code, status_detail, [], None

    finally:
        # Le bloc finally s'exécute toujours, même en cas d'exception.
        # On émet d'abord le marqueur BATCH-STATUS (capture dans le log via tee),
        # puis on restaure sys.stdout et ferme le fichier log.
        _emit_batch_status(stem, status_code, status_detail)
        sys.stdout = _original_stdout
        tee.close()
        print(f"[Log] Rapport d'exécution écrit dans : {report_path}")


def _write_execution_summary(
    output_dir: Path,
    input_dir: str,
    results: list,
    ts: str,
    total_time_s: float = 0.0,
) -> Path:
    """
    Écrit un résumé humainement lisible de toute la session batch dans
    `execution_summary_<ts>.txt`.

    Contenu :
        - En-tête : horodatage, dossiers, totaux globaux
        - Décompte des erreurs par type
        - Tableau par fichier avec statut et détail

    Paramètres :
        output_dir    : dossier où écrire le résumé
        input_dir     : dossier d'entrée (pour l'affichage)
        results       : liste de dicts {"name", "stem", "status_code", "status_detail"}
        ts            : horodatage pour le nom du fichier
        total_time_s  : durée totale de la session (secondes)

    Retourne le chemin du fichier résumé créé.
    """
    summary_path = output_dir / f"execution_summary_{ts}.txt"

    total = len(results)
    n_ok  = sum(1 for r in results if r["status_code"] == "OK")
    n_err = total - n_ok

    # Compte les échecs par type de code d'erreur
    err_counts = {}
    for r in results:
        code = r["status_code"]
        if code != "OK":
            err_counts[code] = err_counts.get(code, 0) + 1

    sep   = "=" * 62
    lines = []
    lines.append(sep)
    lines.append(f"  Résumé d'exécution — {ts}")
    lines.append(f"  Dossier d'entrée : {input_dir}")
    lines.append(f"  Dossier de sortie : {output_dir}")
    lines.append(sep)
    lines.append(f"  Fichiers total  : {total}")
    lines.append(f"  Succès          : {n_ok}")
    lines.append(f"  Échecs          : {n_err}")
    lines.append(f"  Durée totale    : {total_time_s:.1f}s")
    lines.append(sep)
    lines.append("")

    if err_counts:
        lines.append("Erreurs par type :")
        # Trie par count décroissant, puis par code croissant (déterministe)
        for code in sorted(err_counts, key=lambda c: (-err_counts[c], c)):
            lines.append(f"  {code:<16} : {err_counts[code]}")
        lines.append("")

    lines.append("Résultats par fichier :")
    code_width = max((len(r["status_code"]) for r in results), default=2) + 2
    for r in results:
        tag  = f"[{r['status_code']}]".ljust(code_width)
        line = f"  {tag} {r['name']}"
        if r["status_code"] != "OK" and r["status_detail"]:
            line += f"  — {r['status_detail']}"
        lines.append(line)

    summary_path.write_text("\n".join(lines) + "\n",
                            encoding="utf-8", errors="replace")
    return summary_path


def _write_manifest(output_dir: Path, results: list) -> None:
    """
    Met à jour output_dir/manifest.json avec les runs réussis de la session.

    Le manifest est lu par le visualizer Three.js pour lister les résultats
    disponibles sans scanner le dossier. Les entrées existantes sont conservées ;
    les nouvelles remplacent les éventuels doublons (même csv_name).
    """
    import json
    from datetime import datetime, timezone

    manifest_path = output_dir / "manifest.json"

    try:
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = {"schema_version": 1, "runs": []}
    except Exception:
        manifest = {"schema_version": 1, "runs": []}

    existing = {r["results_file"]: r for r in manifest.get("runs", []) if "results_file" in r}

    for result in results:
        if result["status_code"] != "OK" or not result.get("csv_name"):
            continue
        kpi_rows     = result.get("kpi_rows", [])
        pallet_count = len(kpi_rows)
        box_count    = sum(r["n_boxes"] for r in kpi_rows)
        avg_fill     = (round(sum(r["fill"] for r in kpi_rows) / pallet_count, 4)
                        if pallet_count else 0.0)
        existing[result["csv_name"]] = {
            "stem":           result["stem"],
            "results_file":   result["csv_name"],
            "timestamp":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status":         "OK",
            "pallet_count":   pallet_count,
            "box_count":      box_count,
            "avg_fill_ratio": avg_fill,
        }

    manifest["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest["runs"]         = list(existing.values())

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    n_new = sum(1 for r in results if r["status_code"] == "OK" and r.get("csv_name"))
    print(f"[Manifest] manifest.json mis à jour ({n_new} nouveau(x) run(s), "
          f"{len(manifest['runs'])} total).")


def main():
    """
    Fonction principale : parse les arguments, collecte les fichiers d'entrée,
    et traite chaque CSV (séquentiellement ou en parallèle).

    Mode séquentiel (max-workers = 1) :
        Traite les fichiers un par un dans l'ordre alphabétique.
        Les sorties console s'affichent en temps réel.

    Mode parallèle (max-workers > 1) :
        Utilise ProcessPoolExecutor pour traiter N fichiers simultanément.
        Chaque worker écrit dans son propre log (mirror=False = pas de console).
        N'active le mode parallèle qu'avec ≥ 4 fichiers (sinon retour séquentiel).

    Produit à la fin :
        - execution_summary_<ts>.txt : résumé humainement lisible de la session
        - KPI Excel (si visualization/view_kpi.py est disponible)
    """
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_files = _collect_inputs(args.input_dir)

    # Parse les surcharges JSON des paramètres (ex. '{"pallet_length": 120}')
    import json
    try:
        overrides = json.loads(args.params_json)
    except json.JSONDecodeError as e:
        print(f"ERREUR : --params-json invalide : {e}")
        sys.exit(1)
    params = OptimizationParameters(**overrides)

    max_workers = args.max_workers
    # Mode parallèle non utile avec peu de fichiers (overhead > gain)
    if max_workers > 1 and len(input_files) < 4:
        print(f"[Batch] Seulement {len(input_files)} fichier(s) — "
              f"mode parallèle nécessite ≥ 4, retour au mode séquentiel.")
        max_workers = 1
    print(f"[Batch] {len(input_files)} fichier(s) à traiter depuis '{args.input_dir}'"
          + (f" — {max_workers} worker(s) parallèles" if max_workers > 1 else ""))

    t_batch_start = time.time()
    failed  = 0
    results = []   # collecte les résultats par fichier pour le résumé

    if max_workers == 1:
        # ── Mode séquentiel ───────────────────────────────────────────────────
        for i, input_path in enumerate(input_files, start=1):
            print(f"\n[Batch] [{i}/{len(input_files)}] Traitement : {input_path.name}")
            ok, status_code, status_detail, kpi_rows, csv_name = _process_one(
                input_path, output_dir, params
            )
            if not ok:
                failed += 1
            results.append({
                "name":          input_path.name,
                "stem":          input_path.stem,
                "status_code":   status_code,
                "status_detail": status_detail,
                "kpi_rows":      kpi_rows,
                "csv_name":      csv_name,
            })
    else:
        # ── Mode parallèle avec ProcessPoolExecutor ───────────────────────────
        # ProcessPoolExecutor crée des PROCESSUS (pas des threads) pour contourner
        # le GIL (Global Interpreter Lock) de Python et utiliser tous les cœurs CPU.
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Soumet tous les fichiers d'un coup (en parallèle)
            future_to_path = {
                executor.submit(_process_one, p, output_dir, params, True): p
                for p in input_files
            }
            completed = 0
            # as_completed() retourne les futures au fur et à mesure qu'elles finissent
            for future in as_completed(future_to_path):
                path      = future_to_path[future]
                completed += 1
                try:
                    ok, status_code, status_detail, kpi_rows, csv_name = future.result()
                except Exception as e:
                    ok, status_code, status_detail, kpi_rows, csv_name = (
                        False, "ERR_EXCEPTION", str(e), [], None
                    )
                print(f"[Batch] [{completed}/{len(input_files)}] Terminé : {path.name} → {status_code}")
                if not ok:
                    failed += 1
                results.append({
                    "name":          path.name,
                    "stem":          path.stem,
                    "status_code":   status_code,
                    "status_detail": status_detail,
                    "kpi_rows":      kpi_rows,
                    "csv_name":      csv_name,
                })

    print(f"\n[Batch] {len(input_files)} fichier(s) traités — {failed} échec(s).")

    # ── Résumé d'exécution global ─────────────────────────────────────────────
    try:
        from datetime import datetime
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = _write_execution_summary(
            output_dir, args.input_dir, results, ts, time.time() - t_batch_start
        )
        print(f"[Résumé] Rapport global écrit dans : {summary_path}")
    except Exception as e:
        print(f"[Résumé] Avertissement : impossible d'écrire le résumé : {e}")

    # ── Cache KPI JSON + rapport Excel ────────────────────────────────────────
    new_kpi = {r["csv_name"]: r["kpi_rows"] for r in results if r.get("csv_name")}
    if new_kpi:
        try:
            from file_io.kpi_writer import load_kpi_cache, save_kpi_cache, write_excel
            cache = load_kpi_cache(output_dir)
            cache.update(new_kpi)
            save_kpi_cache(cache, output_dir)
            excel_path = write_excel(cache, output_dir)
            if excel_path:
                print(f"[Excel] Rapport KPI écrit dans : {excel_path}")
        except Exception as e:
            print(f"[Excel] Avertissement : {e}")

    # ── Manifest JSON (pour le futur visualizer Three.js) ─────────────────────
    try:
        _write_manifest(output_dir, results)
    except Exception as e:
        print(f"[Manifest] Avertissement : {e}")

    # Retourne un code de sortie non nul si au moins un fichier a échoué.
    # Utile pour les scripts d'automatisation (bash if, CI/CD, etc.).
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
