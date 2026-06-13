"""
post_processing.py — Post-traitement LNS des résultats de palettisation.

Qu'est-ce que le post-traitement ?
    Après les Phases 1 à 4 (FFD + LNS mono/multi), on dispose d'une solution
    qui minimise le nombre de palettes. Le post-traitement (Phase 5) affine
    cette solution sur plusieurs critères de qualité secondaires, SANS augmenter
    le nombre de palettes.

Cinq objectifs optimisés conjointement par une fonction de coût :
    1. Contact P2→P1    : les boîtes manuelles (P2) devraient être placées
                          latéralement contre des boîtes lourdes (P1), pour
                          améliorer la stabilité mécanique lors du transport.
    2. Équilibre fill   : les palettes d'un même groupe devraient avoir des taux
                          de remplissage similaires (répartition équilibrée).
    3. Répartition P2   : le nombre de boîtes manuelles par palette devrait être
                          homogène entre palettes du groupe.
    4. Hauteur          : minimiser la hauteur moyenne des palettes
                          (compacité verticale).
    5. Stabilité        : minimiser le ratio de stabilité le plus défavorable.

Algorithme (par groupe de palettes) :
    Groupe d'une seule palette :
        Dépile toutes les P2, les replace une par une avec score de contact max.

    Groupe de plusieurs palettes :
        Étape 1 — Dépile toutes les P2 dans un pool.
        Étape 2 — Équilibrage du remplissage (si l'écart fill > 15%) :
                   Déplace 1 à 2 petites boîtes P1 de la plus remplie
                   vers la moins remplie, repacke les deux avec le moteur core.
                   Itère jusqu'à épuisement du budget ou équilibre atteint.
        Étape 3 — Placement LNS des P2 :
                   Mélange aléatoire du pool P2, assigne chaque P2 à une palette
                   avec un placement top-k maximisant le contact P2→P1.
                   Accepte si le coût global s'améliore.

    Après le LNS :
        - Réparation des vides (gap repair) : détecte les colonnes P1 avec des
          creux et tente de les combler en replaçant certaines boîtes.
        - Centrage de la charge : translate toutes les boîtes pour centrer
          la charge sur la palette (réduit le déport du centre de gravité).

Moteur de placement :
    Score P1 : (z, x, y)               — identique au moteur principal.
    Score P2 : (z, -contact_P1, x, y)  — maximise le contact vertical P2→P1.
    Top-k    : on collecte les k meilleures positions, on en tire une au hasard.

Groupes traités :
    • Un groupe par client mono-client.
    • Un groupe multi-client global (toutes les palettes multi).

Contraintes dures (toujours respectées) :
    • Le nombre de palettes ne peut pas augmenter.
    • Toutes les contraintes 3D (collision, empilement, support, poids, hauteur
      ergonomique) sont vérifiées par is_valid_placement à chaque placement.
"""

import copy
import random
import time
from dataclasses import replace as dc_replace
from typing import Dict, List, Optional, Tuple

from pallet_optimizer.models.box import Box
from pallet_optimizer.models.pallet import Pallet
from pallet_optimizer.models.placed_box import PlacedBox
from pallet_optimizer.models.orientation import Orientation, ALL_ORIENTATIONS, get_oriented_dimensions
from pallet_optimizer.config.parameters import OptimizationParameters
from pallet_optimizer.core.placement_engine import (
    generate_extreme_points,
    find_support_z,
    is_valid_placement,
    make_placed_box,
    find_best_placement as _core_find_best_placement,
)

FLOAT_TOL = 1e-6
# Seuil d'écart de remplissage (fill delta) au-delà duquel on lance
# la phase d'équilibrage des P1 : 15% d'écart = déséquilibre significatif.
_FILL_EQUALIZATION_THRESHOLD = 0.15


# ══════════════════════════════════════════════════════════════════════════════
# Utilitaires de reconstruction de Box
# ══════════════════════════════════════════════════════════════════════════════

def _reconstruct_box(pb: PlacedBox) -> Box:
    """
    Construit un Box de remplacement quand le box_id n'est pas trouvé dans box_lookup.

    Utilise les dimensions PLACÉES de PlacedBox comme dimensions canoniques.
    Cela peut être légèrement sous-optimal (orientations réduites) mais évite
    de perdre la boîte en cas d'incohérence des données.
    """
    return Box(
        id=pb.box_id, priority=pb.priority,
        length=pb.length, width=pb.width, height=pb.height,
        weight=pb.weight, client_id=pb.client_id,
        allowed_orientations=list(ALL_ORIENTATIONS),
        stackable={o: pb.stackable for o in ALL_ORIENTATIONS},
    )


def _get_box(pb: PlacedBox, box_lookup: Dict[str, Box]) -> Box:
    """
    Retourne le Box original depuis box_lookup, ou reconstruit depuis PlacedBox
    si introuvable (fallback sécurisé).
    """
    return box_lookup.get(pb.box_id) or _reconstruct_box(pb)


# ══════════════════════════════════════════════════════════════════════════════
# Fonction de coût du post-traitement
# ══════════════════════════════════════════════════════════════════════════════

def _vertical_contact_area(p2: PlacedBox, p1: PlacedBox) -> float:
    """
    Calcule l'aire de contact vertical (en cm²) entre une boîte P2 et une boîte P1.

    Contact vertical = deux boîtes se touchent sur une face latérale
    (perpendiculaire au plan XY, pas horizontale).

    Méthode :
        1. Calcule le chevauchement en Z (hauteur commune des deux boîtes).
           Si les boîtes ne se chevauchent pas en Z → contact nul.
        2. Vérifie si les boîtes sont en contact sur une face X (bord droit ou gauche).
           Si oui, calcule le chevauchement en Y × le chevauchement Z → aire de contact.
        3. Fait de même pour les faces Y (avant/arrière).

    La somme des contributions X et Y donne le contact vertical total.
    """
    total = 0.0

    # Chevauchement en Z (hauteur partagée par les deux boîtes)
    ov_z = max(0.0, min(p2.z_max, p1.z_max) - max(p2.z, p1.z))
    if ov_z <= FLOAT_TOL:
        return 0.0   # pas de chevauchement vertical → pas de contact

    # Contact sur les faces parallèles à YZ (faces gauche/droite en X)
    if abs(p2.x - p1.x_max) <= FLOAT_TOL or abs(p2.x_max - p1.x) <= FLOAT_TOL:
        ov_y   = max(0.0, min(p2.y_max, p1.y_max) - max(p2.y, p1.y))
        total += ov_y * ov_z

    # Contact sur les faces parallèles à XZ (faces avant/arrière en Y)
    if abs(p2.y - p1.y_max) <= FLOAT_TOL or abs(p2.y_max - p1.y) <= FLOAT_TOL:
        ov_x   = max(0.0, min(p2.x_max, p1.x_max) - max(p2.x, p1.x))
        total += ov_x * ov_z

    return total


def _p2_p1_contact_area(pallet: Pallet) -> float:
    """
    Calcule l'aire totale de contact vertical P2→P1 pour toute une palette (cm²).

    Parcourt chaque couple (boîte P2, boîte P1) et somme leurs contacts verticaux.
    Une valeur élevée signifie que les boîtes manuelles sont bien entourées
    de boîtes lourdes → meilleure stabilité lors du transport.
    """
    total    = 0.0
    p1_boxes = [pb for pb in pallet.boxes if pb.priority == 1]
    for pb in pallet.boxes:
        if pb.priority != 2:
            continue
        for p1 in p1_boxes:
            total += _vertical_contact_area(pb, p1)
    return total


def compute_pp_cost(pallets: List[Pallet], params: OptimizationParameters) -> float:
    """
    Calcule le coût global d'une solution post-traitée.

    Un coût plus faible = meilleure solution.

    Formule :
        coût = - w_contact   × Σ(contact P2→P1 par palette)    [maximiser → signe négatif]
               + w_fill      × Variance(taux de remplissage)
               + w_p2        × Variance(nombre de P2 par palette)
               + w_height    × moyenne(hauteur_actuelle / hauteur_max)
               + w_stability × max(ratio_stabilité_pire)

    Les termes avec « + » sont des pénalités (on veut les minimiser).
    Le terme contact est négatif car on veut le MAXIMISER (plus de contact = meilleur).

    Variance d'une liste [x1, x2, ...] :
        mean = (x1 + x2 + ...) / N
        variance = Σ(xi - mean)² / N
    Une variance nulle = toutes les palettes identiques (idéal pour fill et P2).
    """
    if not pallets:
        return 0.0

    # ── Contact P2→P1 (récompense → négatif dans la somme) ──────────────────
    contact_cost = -sum(_p2_p1_contact_area(p) for p in pallets)

    # ── Variance du remplissage volumétrique ─────────────────────────────────
    fills     = [p.volumetric_fill_ratio for p in pallets]
    fill_mean = sum(fills) / len(fills)
    fill_var  = sum((f - fill_mean) ** 2 for f in fills) / len(fills)

    # ── Variance du nombre de boîtes P2 par palette ───────────────────────────
    p2c    = [sum(1 for pb in p.boxes if pb.priority == 2) for p in pallets]
    p2m    = sum(p2c) / len(p2c)
    p2_var = sum((c - p2m) ** 2 for c in p2c) / len(p2c)

    # ── Terme de hauteur : moyenne de (hauteur_courante / hauteur_max) ────────
    heights = [(p.current_height / p.max_height) if p.max_height > 0 else 0.0
               for p in pallets]
    height_term = sum(heights) / len(heights)

    # ── Terme de stabilité : pire ratio de stabilité P1 dans le groupe ────────
    stab_ratios    = [p.worst_stability_ratio for p in pallets if p.boxes]
    stability_term = max(stab_ratios) if stab_ratios else 0.0

    return (params.pp_w_contact   * contact_cost
            + params.pp_w_fill    * fill_var
            + params.pp_w_p2      * p2_var
            + params.pp_w_height  * height_term
            + params.pp_w_stability * stability_term)


# ══════════════════════════════════════════════════════════════════════════════
# Fonctions de placement spécialisées
# ══════════════════════════════════════════════════════════════════════════════

def _p2_contact_with_p1(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox],
) -> float:
    """
    Calcule l'aire de contact vertical (cm²) entre une boîte P2 CANDIDATE
    (pas encore placée) et toutes les boîtes P1 déjà sur la palette.

    Utilisé pour scorer les positions candidates lors du placement P2 :
    on préfère les positions qui maximisent ce contact (→ meilleure stabilité).

    Paramètres :
        x, y, z             : position candidate de la boîte P2
        length, width, height : dimensions de la boîte P2 dans son orientation
        placed_boxes        : boîtes déjà sur la palette
    """
    total  = 0.0
    x_max  = x + length
    y_max  = y + width
    z_max  = z + height

    for pb in placed_boxes:
        if pb.priority != 1:
            continue   # on ne considère que les P1 comme partenaires de contact

        ov_z = max(0.0, min(z_max, pb.z_max) - max(z, pb.z))
        if ov_z <= FLOAT_TOL:
            continue   # pas de chevauchement vertical → pas de contact

        # Face gauche ou droite (selon X)
        if abs(x - pb.x_max) <= FLOAT_TOL or abs(x_max - pb.x) <= FLOAT_TOL:
            ov_y   = max(0.0, min(y_max, pb.y_max) - max(y, pb.y))
            total += ov_y * ov_z

        # Face avant ou arrière (selon Y)
        if abs(y - pb.y_max) <= FLOAT_TOL or abs(y_max - pb.y) <= FLOAT_TOL:
            ov_x   = max(0.0, min(x_max, pb.x_max) - max(x, pb.x))
            total += ov_x * ov_z

    return total


def _find_best_p2_placement(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
) -> Optional[Tuple[float, float, float, Orientation]]:
    """
    Trouve la meilleure position pour une boîte P2 en maximisant le contact P2→P1.

    Score : (z, -contact/aire_base, x, y)
        → Préfère les positions basses (z faible), puis celles avec le plus de
          contact avec les P1, puis les plus à gauche/arrière.

    Retourne (x, y, z, orientation) ou None si aucune position valide.
    """
    best       = None
    best_score = None

    for orientation in box.allowed_orientations:
        L, W, H = get_oriented_dimensions(box.length, box.width, box.height, orientation)

        for cx, cy in generate_extreme_points(pallet):
            z = find_support_z(cx, cy, L, W, H, pallet.boxes)

            if not is_valid_placement(box, cx, cy, z, orientation, L, W, H, pallet, params):
                continue

            contact = _p2_contact_with_p1(cx, cy, z, L, W, H, pallet.boxes)
            score   = (z, -contact, cx, cy)   # -contact car on veut maximiser

            if best_score is None or score < best_score:
                best_score = score
                best       = (cx, cy, z, orientation)

    return best


def _find_top_k_p2_placements(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
    k: int,
) -> List[Tuple[float, float, float, Orientation]]:
    """
    Retourne jusqu'à k meilleures positions P2 valides, triées par score croissant.

    Score : (z, -contact/aire_base, x, y) — identique à _find_best_p2_placement.
    Utilisé par _place_p2_pool pour le tirage aléatoire parmi les top-k.

    Paramètre k : taille du bassin de sélection (params.pp_top_k).
    """
    candidates: List[Tuple[Tuple, Tuple]] = []

    for orientation in box.allowed_orientations:
        L, W, H = get_oriented_dimensions(box.length, box.width, box.height, orientation)

        for cx, cy in generate_extreme_points(pallet):
            z = find_support_z(cx, cy, L, W, H, pallet.boxes)

            if not is_valid_placement(box, cx, cy, z, orientation, L, W, H, pallet, params):
                continue

            contact = _p2_contact_with_p1(cx, cy, z, L, W, H, pallet.boxes)
            score   = (z, -contact, cx, cy)
            candidates.append((score, (cx, cy, z, orientation)))

    candidates.sort(key=lambda c: c[0])
    return [c[1] for c in candidates[:k]]


def _pack_p1_only(
    p1_boxes: List[Box],
    template: Pallet,
    params: OptimizationParameters,
) -> Optional[Pallet]:
    """
    Repacke uniquement les boîtes P1 sur une nouvelle palette vide.

    Trie les P1 par volume décroissant puis poids décroissant (les plus grosses
    et lourdes en premier pour une meilleure densité).

    Utilise le moteur de placement core (scores déterministes : z, x, y, residual).

    Retourne None si une boîte P1 ne peut pas être placée (repacking impossible).
    Cette situation déclenche le rejet de l'itération courante dans l'équilibrage.
    """
    pallet = Pallet(id=template.id, length=template.length,
                    width=template.width, max_height=template.max_height,
                    max_weight=template.max_weight)

    # Tri : volumes décroissants (grandes boîtes en premier)
    ordered = sorted(p1_boxes, key=lambda b: (-b.volume, -b.weight))

    for box in ordered:
        result = _core_find_best_placement(box, pallet, params)
        if result is None:
            return None   # échec → rejette l'itération entière

        x, y, z, orientation = result
        pb          = make_placed_box(box, x, y, z, orientation)
        pb.sequence = len(pallet.boxes) + 1
        pallet.boxes.append(pb)

    return pallet


def _place_p2_pool(
    p2_pool: List[Box],
    pallets: List[Pallet],
    params: OptimizationParameters,
    rng: random.Random,
) -> bool:
    """
    Distribue toutes les boîtes P2 du pool sur les palettes (mute les palettes).

    Pour chaque boîte P2 :
        - Mélange aléatoirement l'ordre des palettes candidates.
        - Sur chaque palette, collecte les top-k positions P2 par score de contact.
        - Choisit aléatoirement l'une des top-k.
        - Passe à la palette suivante si la courante n'a aucune position valide.

    Retourne True si TOUTES les P2 ont été placées avec succès.
    Retourne False si au moins une P2 ne trouve pas de place (solution rejetée).
    """
    N = len(pallets)
    for box in p2_pool:
        order  = list(range(N))
        rng.shuffle(order)   # ordre aléatoire des palettes
        placed = False

        for i in order:
            tops = _find_top_k_p2_placements(box, pallets[i], params, params.pp_top_k)
            if tops:
                x, y, z, orientation = rng.choice(tops)  # tirage dans le top-k
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = len(pallets[i].boxes) + 1
                pallets[i].boxes.append(pb)
                placed = True
                break

        if not placed:
            return False   # une P2 n'a pas pu être placée → échec

    return True


# ══════════════════════════════════════════════════════════════════════════════
# LNS unifié (mono et multi)
# ══════════════════════════════════════════════════════════════════════════════

def _lns_group(
    pallets: List[Pallet],
    box_lookup: Dict[str, Box],
    params: OptimizationParameters,
    rng: random.Random,
    label: str,
    time_budget: float = None,
    iter_budget: int   = None,
) -> List[Pallet]:
    """
    LNS unifié de post-traitement pour un groupe de palettes (mono ou multi).

    Étapes :
        1. Dépile toutes les P2 dans un pool (les palettes ne gardent que les P1).
        2. Si une seule palette : place les P2 directement avec top-k contact.
        3. Si plusieurs palettes ET écart fill > 15% : phase d'équilibrage P1.
        4. Phase P2 : itère en mélangeant et replaçant les P2, accepte si coût baisse.

    Note sur le coût de référence :
        Le coût de départ (original_cost) est calculé sur la solution INITIALE
        avec les P2 en place. Les itérations P2 essaient de battre ce coût.
        Même si aucune amélioration n'est trouvée, on retourne la solution originale
        (jamais pire que l'entrée).

    Paramètres :
        pallets     : palettes du groupe à optimiser
        box_lookup  : dict { box_id → Box original }
        params      : paramètres d'optimisation
        rng         : générateur aléatoire
        label       : préfixe de log
        time_budget : budget temps (calculé automatiquement si None)
        iter_budget : budget itérations (calculé automatiquement si None)

    Retourne la liste améliorée de palettes du groupe.
    """
    if not pallets:
        return pallets

    if time_budget is None:
        time_budget = max(1.0, len(pallets) * params.pp_time_per_pallet)
    if iter_budget is None:
        iter_budget = max(1, len(pallets) * params.pp_iter_per_pallet)

    N        = len(pallets)
    original = copy.deepcopy(pallets)   # sauvegarde de sécurité (retournée si aucune amélioration)
    best     = copy.deepcopy(pallets)

    # ── Étape 1 : dépile toutes les P2 → pool ────────────────────────────────
    p2_pool: List[Box] = []
    for p in best:
        p2_pbs = [pb for pb in p.boxes if pb.priority == 2]
        for pb in p2_pbs:
            p2_pool.append(_get_box(pb, box_lookup))
        p.boxes = [pb for pb in p.boxes if pb.priority == 1]   # garde uniquement les P1
    rng.shuffle(p2_pool)   # mélange initial du pool

    original_cost = compute_pp_cost(original, params)

    print(f"{label} début — {N} palette(s), {len(p2_pool)} P2 dépilées")
    _log_group_stats(label, original)

    # ── Étape 3 : équilibrage du remplissage P1 (si delta > seuil) ───────────
    fills = [p.volumetric_fill_ratio for p in best]
    delta = max(fills) - min(fills)   # écart entre la plus et la moins remplie

    start    = time.time()
    improved = 0
    skipped  = 0
    fill_last_improvement_iter = 0
    fill_iters_run             = 0

    if delta > _FILL_EQUALIZATION_THRESHOLD:
        # Utilise la moitié du budget d'itérations pour l'équilibrage
        fill_iters = iter_budget // 2
        fill_cost  = compute_pp_cost(best, params)

        print(f"{label} delta fill {delta:.1%} > {_FILL_EQUALIZATION_THRESHOLD:.0%}"
              f" — équilibrage ({fill_iters} iters max)")

        for iteration in range(1, fill_iters + 1):
            if time.time() - start > time_budget / 2:
                break

            current    = copy.deepcopy(best)
            fills_cur  = [p.volumetric_fill_ratio for p in current]
            i_donor    = fills_cur.index(max(fills_cur))   # palette la plus remplie
            i_receiver = fills_cur.index(min(fills_cur))   # palette la moins remplie

            if i_donor == i_receiver:
                break   # toutes les palettes ont le même remplissage → équilibré

            # Sélectionne 1 ou 2 petites P1 à déplacer de donor vers receiver
            donor_p1 = [(pb, _get_box(pb, box_lookup))
                        for pb in current[i_donor].boxes if pb.priority == 1]
            if not donor_p1:
                skipped += 1
                continue   # la palette donneuse n'a plus de P1 à déplacer

            donor_p1.sort(key=lambda t: t[1].volume)   # trie par volume croissant
            k        = rng.randint(1, min(2, len(donor_p1)))   # 1 ou 2 boîtes
            move     = donor_p1[:k]
            move_ids = {pb.box_id for pb, _ in move}
            move_boxes = [b for _, b in move]

            # Recalcule les P1 de chaque palette après le déplacement
            donor_remaining = [_get_box(pb, box_lookup)
                               for pb in current[i_donor].boxes
                               if pb.priority == 1 and pb.box_id not in move_ids]
            receiver_p1 = [_get_box(pb, box_lookup)
                           for pb in current[i_receiver].boxes
                           if pb.priority == 1] + move_boxes

            # Repacke les P1 des deux palettes avec le moteur de placement core
            new_donor = _pack_p1_only(donor_remaining, current[i_donor], params) \
                        if donor_remaining else \
                        Pallet(id=current[i_donor].id,
                               length=current[i_donor].length,
                               width=current[i_donor].width,
                               max_height=current[i_donor].max_height,
                               max_weight=current[i_donor].max_weight)
            new_receiver = _pack_p1_only(receiver_p1, current[i_receiver], params)

            if new_donor is None or new_receiver is None:
                skipped += 1
                continue   # une boîte ne rentre pas → rejette ce déplacement

            current[i_donor]    = new_donor
            current[i_receiver] = new_receiver

            new_cost = compute_pp_cost(current, params)
            if new_cost < fill_cost:
                d         = fill_cost - new_cost
                fill_cost = new_cost
                best      = current
                improved += 1
                fill_last_improvement_iter = iteration
                new_fills = [p.volumetric_fill_ratio for p in best]
                print(f"{label} fill iter {iteration:4d}: "
                      f"coût {new_cost:.4f} (Δ={d:.4f})  "
                      f"déplacé {k} P1  fills=[{', '.join(f'{f:.1%}' for f in new_fills)}]")

            fill_iters_run = iteration

        elapsed_fill  = time.time() - start
        fill_stag     = fill_iters_run - fill_last_improvement_iter
        fill_stag_pct = fill_stag / max(1, fill_iters_run) * 100
        print(
            f"{label} équilibrage terminé — {improved} amélioration(s) "
            f"({skipped} sautées) en {elapsed_fill:.1f}s | "
            f"stagnation: {fill_stag} iter ({fill_stag_pct:.0f}%)"
        )

    # ── Étape 4 : placement LNS des P2 ───────────────────────────────────────
    # Sauvegarde l'état P1-only optimisé (sert de base pour chaque essai P2)
    p1_snapshot = copy.deepcopy(best)
    best_cost   = original_cost     # baseline = solution originale complète
    best        = original          # si aucune amélioration → retourne l'original

    p2_improved              = 0
    p2_skipped               = 0
    p2_last_improvement_iter = 0
    p2_iters_run             = 0
    p2_start                 = time.time()

    for iteration in range(1, iter_budget + 1):
        if time.time() - p2_start > time_budget:
            break

        trial = copy.deepcopy(p1_snapshot)   # copie de l'état P1-only
        rng.shuffle(p2_pool)                  # nouvel ordre aléatoire des P2

        if not _place_p2_pool(p2_pool, trial, params, rng):
            p2_skipped  += 1
            p2_iters_run = iteration
            continue   # au moins une P2 n'a pas pu être placée → rejette

        new_cost = compute_pp_cost(trial, params)
        if new_cost < best_cost:
            d         = best_cost - new_cost
            best_cost = new_cost
            best      = trial
            p2_improved += 1
            p2_last_improvement_iter = iteration
            if p2_improved <= 10 or p2_improved % 50 == 0:
                print(f"{label} P2 iter {iteration:4d}: "
                      f"coût {new_cost:.4f} (Δ={d:.4f})")

        p2_iters_run = iteration

    elapsed_p2  = time.time() - p2_start
    p2_stag     = p2_iters_run - p2_last_improvement_iter
    p2_stag_pct = p2_stag / max(1, p2_iters_run) * 100
    if p2_improved == 0:
        print(
            f"{label} P2 terminé — aucune amélioration, conservation de l'original. "
            f"({p2_skipped} sautées) en {elapsed_p2:.1f}s | "
            f"stagnation: {p2_stag} iter ({p2_stag_pct:.0f}%)"
        )
    else:
        print(
            f"{label} P2 terminé — {p2_improved} amélioration(s) "
            f"({p2_skipped} sautées) en {elapsed_p2:.1f}s | "
            f"stagnation: {p2_stag} iter ({p2_stag_pct:.0f}%) | "
            f"Coût final={best_cost:.2f}"
        )

    # ── Vérification de sécurité : aucune boîte perdue ───────────────────────
    original_ids = {pb.box_id for p in original for pb in p.boxes}
    best_ids     = {pb.box_id for p in best for pb in p.boxes}
    if best_ids != original_ids:
        lost   = original_ids - best_ids
        gained = best_ids - original_ids
        print(f"{label} AVERTISSEMENT : décalage de boîtes — perdues={len(lost)} gagnées={len(gained)}. "
              f"Retour à l'original.")
        best = original

    _log_group_stats(label, best)
    return best


# ══════════════════════════════════════════════════════════════════════════════
# Utilitaires de journalisation
# ══════════════════════════════════════════════════════════════════════════════

def _log_group_stats(label: str, pallets: List[Pallet]) -> None:
    """Affiche des statistiques détaillées sur un groupe de palettes."""
    if not pallets:
        return
    fills    = [p.volumetric_fill_ratio for p in pallets]
    p2s      = [sum(1 for pb in p.boxes if pb.priority == 2) for p in pallets]
    contacts = [_p2_p1_contact_area(p) for p in pallets]
    heights  = [p.current_height for p in pallets]
    stab     = [p.worst_stability_ratio for p in pallets if p.boxes]
    avg_fill = sum(fills) / len(fills)
    fill_var = sum((f - avg_fill) ** 2 for f in fills) / len(fills)
    fills_fmt = "  ".join(f"{f:.1%}" for f in fills)
    print(f"  {label}")
    print(f"    fill/palette   : [{fills_fmt}]")
    print(f"    variance fill  : {fill_var:.6f}  (plus faible = plus équilibré)")
    print(f"    P2/palette     : {p2s}")
    print(f"    contact P2→P1 : {[f'{c:.0f}cm²' for c in contacts]}")
    print(f"    hauteur/palette: {[f'{h:.0f}cm' for h in heights]}")
    print(f"    stabilité      : {[f'{s:.2f}' for s in stab]}")


# ══════════════════════════════════════════════════════════════════════════════
# Détection et réparation des vides (water-fill gap)
# ══════════════════════════════════════════════════════════════════════════════

def _water_fill_gap(
    pallet: Pallet,
    a_attr: str,
    a_len_attr: str,
    b_attr: str,
    b_len_attr: str,
    scale: float = 1.0,
) -> float:
    """
    Détecte et mesure les « vides piégés » dans le profil de hauteur P1 selon
    une projection donnée (XZ ou YZ).

    Principe — analogie de l'eau :
        Imaginez que vous remplissez d'eau l'espace entre les boîtes P1.
        L'eau est piégée dans les creux entourés de boîtes plus hautes à gauche
        ET à droite. La surface totale de l'eau piégée = l'aire des vides.

    Méthode :
        1. Construit le profil de hauteur H[a] = hauteur maximale des P1 en
           chaque position a (discrétisé par `scale`).
        2. Calcule max_left[a] = maximum de H de la gauche jusqu'à a.
        3. Calcule max_right[a] = maximum de H de la droite jusqu'à a.
        4. L'eau piégée en a = max(0, min(max_left[a], max_right[a]) - H[a]).
        5. Somme sur tous les a → aire totale des vides (cm²).

    Paramètres :
        a_attr, a_len_attr : attributs de la coordonnée « horizontale » (ex. 'x', 'length')
        b_attr, b_len_attr : attributs de la coordonnée « verticale » (ex. 'z', 'height')
        scale              : résolution de la grille de discrétisation (cm)

    Retourne l'aire des vides piégés (cm²). 0.0 = profil sans vide.
    """
    p1_boxes = [pb for pb in pallet.boxes if pb.priority == 1]
    if not p1_boxes:
        return 0.0

    # Largeur maximale selon l'axe a
    a_max = max(getattr(pb, a_attr) + getattr(pb, a_len_attr) for pb in p1_boxes)
    n     = int(a_max / scale) + 2
    H     = [0.0] * n   # profil de hauteur discrétisé

    # Construction du profil : pour chaque boîte, met à jour H aux positions couvertes
    for pb in p1_boxes:
        a0 = getattr(pb, a_attr)
        a1 = a0 + getattr(pb, a_len_attr)
        b1 = getattr(pb, b_attr) + getattr(pb, b_len_attr)  # sommet de la boîte
        for ga in range(int(a0 / scale), min(int(a1 / scale) + 1, n)):
            if H[ga] < b1:
                H[ga] = b1

    occupied = [gx for gx in range(n) if H[gx] > 0]
    if not occupied:
        return 0.0
    x0, x1 = min(occupied), max(occupied) + 1

    # Calcule max depuis la gauche et depuis la droite
    max_left  = [0.0] * n
    ml = 0.0
    for gx in range(x0, x1):
        ml = max(ml, H[gx])
        max_left[gx] = ml

    max_right = [0.0] * n
    mr = 0.0
    for gx in range(x1 - 1, x0 - 1, -1):
        mr = max(mr, H[gx])
        max_right[gx] = mr

    # Somme des surfaces d'eau piégée
    gap = sum(
        max(0.0, min(max_left[gx], max_right[gx]) - H[gx]) * scale
        for gx in range(x0, x1)
    )
    return gap


def _detect_gap_pallets(pallets: List[Pallet]) -> List[Tuple[Pallet, float, float]]:
    """
    Identifie les palettes qui ont des vides dans leur profil P1 (XZ ou YZ).

    Retourne la liste des palettes avec vide, triées par aire de vide décroissante
    (les plus problématiques d'abord).

    Chaque entrée de la liste est (pallet, gap_XZ, gap_YZ).
    """
    flagged = []
    for pallet in pallets:
        xz = _water_fill_gap(pallet, 'x', 'length', 'z', 'height')
        yz = _water_fill_gap(pallet, 'y', 'width',  'z', 'height')
        if xz > 0.0 or yz > 0.0:
            flagged.append((pallet, xz, yz))

    # Trie par maximum de XZ et YZ décroissant (les pires en premier)
    flagged.sort(key=lambda t: max(t[1], t[2]), reverse=True)
    return flagged


# ══════════════════════════════════════════════════════════════════════════════
# Réparation des vides
# ══════════════════════════════════════════════════════════════════════════════

# Les 4 combinaisons de signes pour les placements « signés » :
# (sx, sy) = (+1, +1) → position naturelle (coin bas-gauche-arrière au EP)
# (sx, sy) = (-1, +1) → coin droit au EP (boîte à gauche du EP)
# etc.
_SIGNS = [(1, 1), (-1, 1), (1, -1), (-1, -1)]


def _gap_direction(pallet: Pallet, scale: float = 1.0) -> str:
    """
    Détermine de quel côté (gauche ou droite) se trouve la colonne P1 la plus haute,
    c'est-à-dire le côté vers lequel il faut pousser les boîtes pour combler le vide.

    Retourne 'right' si la colonne haute est à droite du vide,
             'left'  si elle est à gauche.

    Utilisé pour guider x_gravity dans _find_best_placement_signed.
    """
    p1_boxes = [pb for pb in pallet.boxes if pb.priority == 1]
    if not p1_boxes:
        return 'right'

    a_max = max(pb.x + pb.length for pb in p1_boxes)
    n     = int(a_max / scale) + 2
    H     = [0.0] * n

    for pb in p1_boxes:
        a0, a1 = pb.x, pb.x + pb.length
        b1     = pb.z + pb.height
        for ga in range(int(a0 / scale), min(int(a1 / scale) + 1, n)):
            if H[ga] < b1:
                H[ga] = b1

    occupied = [gx for gx in range(n) if H[gx] > 0]
    if not occupied:
        return 'right'
    x0, x1 = min(occupied), max(occupied) + 1

    max_left  = [0.0] * n
    ml = 0.0
    for gx in range(x0, x1):
        ml = max(ml, H[gx])
        max_left[gx] = ml

    max_right = [0.0] * n
    mr = 0.0
    for gx in range(x1 - 1, x0 - 1, -1):
        mr = max(mr, H[gx])
        max_right[gx] = mr

    right_sum = left_sum = 0.0
    for gx in range(x0, x1):
        water = min(max_left[gx], max_right[gx]) - H[gx]
        if water > 0:
            right_sum += max_right[gx]
            left_sum  += max_left[gx]

    return 'right' if right_sum >= left_sum else 'left'


def _xz_gap_with_box(
    placed_p1_xzlh: List[Tuple[float, float, float, float]],
    ax: float, z: float, bL: float, bH: float,
    scale: float = 1.0,
) -> float:
    """
    Calcule le vide XZ d'un profil P1 si on y ajoute une boîte candidate.

    Plus léger que de créer un objet Pallet complet pour chaque candidat.
    Utilisé dans _find_best_placement_signed pour choisir la position qui
    minimise le vide résiduel après placement.

    Paramètres :
        placed_p1_xzlh : liste de (x, z, length, height) pour les P1 déjà placées
        ax, z          : position candidate de la nouvelle boîte
        bL, bH         : length et height de la nouvelle boîte

    Retourne l'aire de vide XZ (cm²) avec la boîte candidate incluse.
    """
    items = placed_p1_xzlh + [(ax, z, bL, bH)]
    a_max = max(x + l for x, _, l, _ in items)
    n     = int(a_max / scale) + 2
    H_arr = [0.0] * n

    for x, bz, l, h in items:
        b1 = bz + h
        for ga in range(int(x / scale), min(int((x + l) / scale) + 1, n)):
            if H_arr[ga] < b1:
                H_arr[ga] = b1

    occupied = [gx for gx in range(n) if H_arr[gx] > 0]
    if not occupied:
        return 0.0
    x0, x1 = min(occupied), max(occupied) + 1

    ml = mr = 0.0
    max_left  = [0.0] * n
    max_right = [0.0] * n
    for gx in range(x0, x1):
        ml = max(ml, H_arr[gx]); max_left[gx] = ml
    for gx in range(x1 - 1, x0 - 1, -1):
        mr = max(mr, H_arr[gx]); max_right[gx] = mr

    return sum(
        max(0.0, min(max_left[gx], max_right[gx]) - H_arr[gx]) * scale
        for gx in range(x0, x1)
    )


def _find_best_placement_signed(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
    x_gravity: int,
) -> Optional[Tuple[float, float, float, Orientation]]:
    """
    Placement signé : teste 4 orientations de position à chaque point extrême
    pour trouver la position qui minimise le vide XZ.

    Paramètre x_gravity :
        -1 → préfère les x élevés (pousse vers la droite, vers la colonne haute)
        +1 → préfère les x faibles (pousse vers la gauche, vers la colonne haute)
         0 → aucune préférence directionnelle (utilisé dans la réparation 1-boîte)

    Score : (z, gap_xz_après_placement, x_gravity × ax, ay)
        Le gap XZ après placement est le critère secondaire principal :
        une position qui ferme le vide est toujours préférée à une qui le laisse
        ouvert, même si elle satisfait moins bien x_gravity.

    Les 4 signes (sx, sy) permettent de placer la boîte en décalant depuis le
    point extrême dans différentes directions (pas seulement coin bas-gauche-arrière).
    """
    best       = None
    best_score = None

    # Instantané des P1 pour le calcul de gap sans créer de Pallet
    placed_p1 = [(pb.x, pb.z, pb.length, pb.height)
                 for pb in pallet.boxes if pb.priority == 1]

    for orientation in box.allowed_orientations:
        bL, bW, bH = get_oriented_dimensions(box.length, box.width, box.height, orientation)

        for cx, cy in generate_extreme_points(pallet):
            for sx, sy in _SIGNS:
                # Calcule la position réelle selon le signe
                ax = cx if sx > 0 else cx - bL
                ay = cy if sy > 0 else cy - bW

                if ax < -FLOAT_TOL or ay < -FLOAT_TOL:
                    continue   # position hors palette
                if ax + bL > pallet.length + FLOAT_TOL or ay + bW > pallet.width + FLOAT_TOL:
                    continue

                ax = max(0.0, ax)
                ay = max(0.0, ay)

                z = find_support_z(ax, ay, bL, bW, bH, pallet.boxes)

                if not is_valid_placement(box, ax, ay, z, orientation, bL, bW, bH, pallet, params):
                    continue

                # Calcule le vide XZ si on place la boîte ici
                gap   = _xz_gap_with_box(placed_p1, ax, z, bL, bH)
                score = (z, gap, x_gravity * ax, ay)
                if best_score is None or score < best_score:
                    best_score = score
                    best       = (ax, ay, z, orientation)

    return best


def _try_repack_signed(
    pallet: Pallet,
    p1_boxes: List[Box],
    p2_boxes: List[Box],
    x_gravity: int,
    params: OptimizationParameters,
) -> Optional[Pallet]:
    """
    Tente un repack complet (P1 + P2) de la palette avec x_gravity donné.

    Ordre : P1 en premier (grandes en premier), puis P2.
    Retourne la nouvelle palette si tout a été placé, None si une boîte échoue.
    """
    new_pallet = Pallet(id=pallet.id, length=pallet.length,
                        width=pallet.width, max_height=pallet.max_height,
                        max_weight=pallet.max_weight)

    ordered_p1 = sorted(p1_boxes, key=lambda b: (-b.volume, -b.weight))
    for box in ordered_p1:
        result = _find_best_placement_signed(box, new_pallet, params, x_gravity)
        if result is None:
            return None   # échec : une P1 ne peut pas être placée
        x, y, z, orientation = result
        pb          = make_placed_box(box, x, y, z, orientation)
        pb.sequence = len(new_pallet.boxes) + 1
        new_pallet.boxes.append(pb)

    ordered_p2 = sorted(p2_boxes, key=lambda b: (-b.volume, -b.weight))
    for box in ordered_p2:
        result = _find_best_p2_placement(box, new_pallet, params)
        if result is None:
            return None   # échec : une P2 ne peut pas être placée
        x, y, z, orientation = result
        pb          = make_placed_box(box, x, y, z, orientation)
        pb.sequence = len(new_pallet.boxes) + 1
        new_pallet.boxes.append(pb)

    return new_pallet


def _leaf_p1_boxes(pallet: Pallet) -> List[PlacedBox]:
    """
    Retourne les boîtes P1 « feuilles » : celles sur lesquelles aucune autre boîte
    ne repose directement.

    Une boîte B repose sur A si B.z ≈ A.z_max ET leurs empreintes XY se chevauchent.
    Les boîtes feuilles peuvent être retirées en toute sécurité (aucune autre boîte
    ne sera mise en l'air si on les enlève).

    Utilisé dans _targeted_gap_repair_1box pour choisir quelles boîtes déplacer.
    """
    p1_boxes      = [pb for pb in pallet.boxes if pb.priority == 1]
    supported_ids: set = set()   # IDs des boîtes qui portent quelque chose

    for a in p1_boxes:
        a_top = a.z + a.height
        for b in pallet.boxes:
            if b.box_id == a.box_id:
                continue
            if abs(b.z - a_top) > FLOAT_TOL:
                continue   # b n'est pas directement au-dessus de a
            ov_x = max(0.0, min(b.x + b.length, a.x + a.length) - max(b.x, a.x))
            ov_y = max(0.0, min(b.y + b.width,  a.y + a.width)  - max(b.y, a.y))
            if ov_x > FLOAT_TOL and ov_y > FLOAT_TOL:
                supported_ids.add(a.box_id)  # a porte b → a n'est pas feuille
                break

    # Retourne les P1 qui ne portent rien (= feuilles)
    return [pb for pb in p1_boxes if pb.box_id not in supported_ids]


def _targeted_gap_repair_1box(
    pallet: Pallet,
    box_lookup: Dict[str, Box],
    params: OptimizationParameters,
) -> Pallet:
    """
    Réparation locale 1-boîte : essaie de déplacer chaque boîte P1 feuille
    vers une position qui réduit le vide XZ.

    Stratégie greedy :
        Pour chaque boîte feuille (dans l'ordre original) :
            1. La retire de la palette.
            2. Cherche la position qui minimise le vide XZ (sans biais x_gravity).
            3. Accepte si le nouveau vide XZ est strictement inférieur.
            4. Continue avec les feuilles restantes sur la palette améliorée.

    Les moves sont appliqués au fil de l'eau : chaque move accepté modifie
    la palette de travail pour les moves suivants.

    Retourne la palette améliorée, ou la palette d'origine si aucun move n'aide.
    """
    current_gap  = _water_fill_gap(pallet, 'x', 'length', 'z', 'height')
    best_pallet  = pallet
    best_gap     = current_gap

    for leaf_pb in _leaf_p1_boxes(pallet):
        box = box_lookup.get(leaf_pb.box_id)
        if box is None:
            continue

        # Palette réduite : meilleur layout actuel sans la boîte feuille
        reduced = Pallet(
            id=best_pallet.id, length=best_pallet.length,
            width=best_pallet.width, max_height=best_pallet.max_height,
            max_weight=best_pallet.max_weight,
        )
        reduced.boxes = [pb for pb in best_pallet.boxes
                         if pb.box_id != leaf_pb.box_id]

        # Cherche la position qui minimise le vide (x_gravity=0 = sans biais)
        result = _find_best_placement_signed(box, reduced, params, x_gravity=0)
        if result is None:
            continue   # ne peut pas replacer cette boîte → skip

        ax, ay, z, orientation = result
        new_pb          = make_placed_box(box, ax, ay, z, orientation)
        new_pb.sequence = leaf_pb.sequence   # conserve le slot de séquence

        # Évalue la palette candidate
        candidate       = Pallet(
            id=best_pallet.id, length=best_pallet.length,
            width=best_pallet.width, max_height=best_pallet.max_height,
            max_weight=best_pallet.max_weight,
        )
        candidate.boxes = reduced.boxes + [new_pb]

        new_gap = _water_fill_gap(candidate, 'x', 'length', 'z', 'height')
        if new_gap < best_gap - FLOAT_TOL:
            best_gap    = new_gap
            best_pallet = candidate
            if new_gap < FLOAT_TOL:
                break   # vide entièrement comblé → inutile de continuer

    return best_pallet


def _repack_gap_pallet(
    pallet: Pallet,
    box_lookup: Dict[str, Box],
    params: OptimizationParameters,
) -> Pallet:
    """
    Tente de réparer le vide d'une palette en deux stratégies :

    Stratégie A — Repack complet (les deux directions x_gravity) :
        1. Détecte de quel côté se trouve la colonne haute (_gap_direction).
        2. Tente le repack dans les DEUX directions (pas seulement la détectée).
           Raison : _gap_direction peut se tromper quand les deux côtés sont hauts.
        3. Accepte si toutes les boîtes sont placées ET le vide XZ diminue.

    Stratégie B — Réparation 1-boîte (repli) :
        Si A n'améliore pas, essaie _targeted_gap_repair_1box.

    Retourne la palette améliorée, ou l'originale si aucune amélioration.
    """
    old_gap   = _water_fill_gap(pallet, 'x', 'length', 'z', 'height')
    direction = _gap_direction(pallet)
    x_gravity_hint = -1 if direction == 'right' else 1

    all_boxes = [(pb, box_lookup.get(pb.box_id)) for pb in pallet.boxes]
    if any(b is None for _, b in all_boxes):
        return pallet   # données manquantes → skip

    p1_boxes = [b for pb, b in all_boxes if pb.priority == 1]
    p2_boxes = [b for pb, b in all_boxes if pb.priority == 2]

    best_pallet = pallet
    best_gap    = old_gap

    # ── Stratégie A : repack complet dans les deux directions ────────────────
    for x_grav in (x_gravity_hint, -x_gravity_hint):
        candidate = _try_repack_signed(pallet, p1_boxes, p2_boxes, x_grav, params)
        if candidate is None:
            continue
        new_gap = _water_fill_gap(candidate, 'x', 'length', 'z', 'height')
        if new_gap < best_gap - FLOAT_TOL:
            best_gap    = new_gap
            best_pallet = candidate

    if best_pallet is not pallet:
        print(f"    Palette {pallet.id:3d}: vide {old_gap:.0f} → {best_gap:.0f} cm²  "
              f"[hint: {direction}]  ACCEPTÉ (repack complet)")
        return best_pallet

    # ── Stratégie B : réparation locale 1-boîte ──────────────────────────────
    targeted = _targeted_gap_repair_1box(pallet, box_lookup, params)
    if targeted is not pallet:
        new_gap = _water_fill_gap(targeted, 'x', 'length', 'z', 'height')
        print(f"    Palette {pallet.id:3d}: vide {old_gap:.0f} → {new_gap:.0f} cm²  "
              f"[hint: {direction}]  ACCEPTÉ (réparation 1-boîte)")
        return targeted

    print(f"    Palette {pallet.id:3d}: vide {old_gap:.0f} — aucune amélioration  "
          f"[hint: {direction}]  IGNORÉ")
    return pallet


# ══════════════════════════════════════════════════════════════════════════════
# Renumérotation et centrage
# ══════════════════════════════════════════════════════════════════════════════

def _center_boxes(pallet: Pallet, min_shift: float = 1.0) -> Pallet:
    """
    Centre la charge sur la palette en translateant toutes les boîtes.

    Calcule l'espace libre restant en X et en Y (après la boîte la plus à droite
    et la plus en avant) et décale toutes les boîtes de la moitié de cet espace.

    But : centrer le centre de gravité de la charge sur la palette réduit
          les risques de basculement lors du transport.

    Le centrage est appliqué uniquement si le décalage dans au moins un axe
    dépasse min_shift (cm) — évite des microdécalages sans intérêt.

    Utilise dataclasses.replace pour créer de nouvelles PlacedBox avec les
    coordonnées mises à jour (les objets originaux sont immuables dans ce contexte).
    """
    if not pallet.boxes:
        return pallet

    max_x = max(pb.x + pb.length for pb in pallet.boxes)
    max_y = max(pb.y + pb.width  for pb in pallet.boxes)

    shift_x = (pallet.length - max_x) / 2.0
    shift_y = (pallet.width  - max_y) / 2.0

    # N'applique que si le décalage est suffisamment grand pour valoir le coup
    if abs(shift_x) < min_shift and abs(shift_y) < min_shift:
        return pallet

    # Crée de nouvelles PlacedBox avec les coordonnées décalées
    new_boxes = [
        dc_replace(pb, x=pb.x + shift_x, y=pb.y + shift_y)
        for pb in pallet.boxes
    ]
    return dc_replace(pallet, boxes=new_boxes)


def _renumber(pallets: List[Pallet]) -> List[Pallet]:
    """
    Renumérotation finale : les palettes mono-client en premier (triées par client_id),
    les palettes multi-client à la fin.
    """
    mono  = sorted([p for p in pallets if not p.is_multi_client],
                   key=lambda p: min(p.client_ids) if p.client_ids else 0)
    multi = [p for p in pallets if p.is_multi_client]
    ordered = mono + multi
    for new_id, p in enumerate(ordered, 1):
        p.id = new_id
    return ordered


# ══════════════════════════════════════════════════════════════════════════════
# Point d'entrée public
# ══════════════════════════════════════════════════════════════════════════════

def postprocess(
    pallets: List[Pallet],
    boxes:   List[Box],
    params:  Optional[OptimizationParameters] = None,
) -> List[Pallet]:
    """
    Lance le pipeline complet de post-traitement Phase 5.

    Étapes du pipeline :
        1. Corrige les flags stackable depuis les Box d'origine (cohérence).
        2. Regroupe les palettes en groupes : un groupe mono par client,
           un groupe multi-client global.
        3. Exécute _lns_group sur chaque groupe mono-client.
        4. Exécute _lns_group sur le groupe multi-client.
        5. Réparation des vides P1 (gap repair) sur toutes les palettes.
        6. Centre la charge sur chaque palette.
        7. Vérifications de sécurité (palettes multi non créées, count stable).
        8. Renumérotation finale.

    Paramètres :
        pallets : résultat de l'optimiseur (Phases 1-4)
        boxes   : catalogue de Box originales (pour les flags d'orientation)
        params  : paramètres d'optimisation (valeurs par défaut si None)

    Retourne la liste de palettes post-traitée.
    """
    if params is None:
        params = OptimizationParameters()

    print(f"\n{'='*60}")
    print(f"  Post-traitement  (LNS)")
    print(f"{'='*60}")
    print(f"  Budget   : {params.pp_time_per_pallet}s/palette × {params.pp_iter_per_pallet} iters/palette  top-k={params.pp_top_k}")
    print(f"  Poids    : contact={params.pp_w_contact}  fill={params.pp_w_fill}  "
          f"P2={params.pp_w_p2}  hauteur={params.pp_w_height}  "
          f"stabilité={params.pp_w_stability}\n")

    # ── Prépare le dictionnaire de recherche et corrige les flags stackable ───
    box_lookup = {b.id: b for b in boxes}
    for pallet in pallets:
        for pb in pallet.boxes:
            orig = box_lookup.get(pb.box_id)
            if orig:
                # Assure que le flag stackable correspond à l'orientation RÉELLE choisie
                pb.stackable = orig.is_stackable_in(pb.orientation)

    n_pallets_in = len(pallets)
    n_multi_in   = sum(1 for p in pallets if p.is_multi_client)

    print(f"  Chargé {n_pallets_in} palettes  "
          f"({n_multi_in} multi-client, {n_pallets_in - n_multi_in} mono-client)\n")

    # ── Regroupe les palettes ──────────────────────────────────────────────────
    mono_groups: Dict[int, List[Pallet]] = {}
    multi_group: List[Pallet]            = []

    for p in pallets:
        if p.is_multi_client:
            multi_group.append(p)
        else:
            cid = next(iter(p.client_ids)) if p.client_ids else 0
            mono_groups.setdefault(cid, []).append(p)

    result: List[Pallet] = []
    rng = random.Random(params.pp_random_seed)

    # ── LNS par groupe mono-client ─────────────────────────────────────────────
    for cid in sorted(mono_groups.keys()):
        group    = mono_groups[cid]
        print(f"\n[Post] ── Groupe mono-client : client {cid}  ({len(group)} palette(s)) ──")
        t_budget = max(1.0, len(group) * params.pp_time_per_pallet)
        i_budget = max(1,   len(group) * params.pp_iter_per_pallet)
        improved = _lns_group(
            group, box_lookup, params,
            rng=random.Random(rng.randint(0, 2**31)),   # graine indépendante par groupe
            label=f"[LNS|cid={cid}]",
            time_budget=t_budget,
            iter_budget=i_budget,
        )
        result.extend(improved)

    # ── LNS pour le groupe multi-client ────────────────────────────────────────
    if multi_group:
        print(f"\n[Post] ── Groupe multi-client  ({len(multi_group)} palette(s)) ──")
        t_budget = max(1.0, len(multi_group) * params.pp_time_per_pallet)
        i_budget = max(1,   len(multi_group) * params.pp_iter_per_pallet)
        improved_multi = _lns_group(
            multi_group, box_lookup, params,
            rng=random.Random(rng.randint(0, 2**31)),
            label="[LNS|multi]",
            time_budget=t_budget,
            iter_budget=i_budget,
        )
        result.extend(improved_multi)

    # ── Réparation des vides (gap repair) ─────────────────────────────────────
    gap_pallets = _detect_gap_pallets(result)
    if gap_pallets:
        print(f"\n[Post] Réparation des vides — {len(gap_pallets)} palette(s) avec vides P1 :")
        result_by_id = {p.id: i for i, p in enumerate(result)}
        for pallet, xz, yz in gap_pallets:
            dominant = "XZ" if xz >= yz else "YZ"
            print(f"  Palette {pallet.id:3d}: XZ={xz:6.0f} cm²  YZ={yz:6.0f} cm²  "
                  f"[dominant: {dominant}]")
            repacked                          = _repack_gap_pallet(pallet, box_lookup, params)
            result[result_by_id[pallet.id]]  = repacked
    else:
        print("\n[Post] Réparation des vides — aucun vide P1 détecté.")

    # ── Centrage de la charge sur chaque palette ──────────────────────────────
    print("\n[Post] Centrage des boîtes sur chaque palette...")
    result = [_center_boxes(p, min_shift=params.pp_center_min_shift) for p in result]

    # ── Vérifications de sécurité ─────────────────────────────────────────────
    n_multi_out = sum(1 for p in result if p.is_multi_client)
    if n_multi_out > n_multi_in:
        # Le post-traitement ne doit pas CRÉER de nouvelles palettes multi-client
        print(f"\n[Post] AVERTISSEMENT : palettes multi {n_multi_in} → {n_multi_out}. "
              f"Rétablissement des palettes affectées.")
        orig_by_id       = {p.id: p for p in pallets}
        orig_multi_ids   = {p.id for p in pallets if p.is_multi_client}
        for i, p in enumerate(result):
            if p.id in orig_multi_ids:
                orig = orig_by_id.get(p.id)
                if orig:
                    result[i] = orig
    elif n_multi_out < n_multi_in:
        print(f"\n[Post] INFO : palettes multi {n_multi_in} → {n_multi_out} "
              f"(meilleure séparation clients — amélioration conservée).")

    if len(result) > n_pallets_in:
        print(f"\n[Post] AVERTISSEMENT : nb palettes {n_pallets_in} → {len(result)}. "
              f"Troncature.")
        result = result[:n_pallets_in]

    # ── Renumérotation finale ─────────────────────────────────────────────────
    result = _renumber(result)

    n_multi_final = sum(1 for p in result if p.is_multi_client)
    all_fills     = [p.volumetric_fill_ratio for p in result if p.boxes]
    avg_fill      = sum(all_fills) / len(all_fills) if all_fills else 0.0
    total_contact = sum(_p2_p1_contact_area(p) for p in result if p.boxes)
    max_stab      = max((p.worst_stability_ratio for p in result if p.boxes), default=0.0)
    avg_height    = (sum(p.current_height for p in result if p.boxes)
                     / len(all_fills)) if all_fills else 0.0

    print(f"\n[Post] ══ Solution finale ══")
    print(f"  Palettes         : {len(result)}  (était {n_pallets_in})")
    print(f"  Multi-client     : {n_multi_final}  (était {n_multi_in})")
    print(f"  Remplissage moy. : {avg_fill:.1%}")
    print(f"  Contact P2→P1   : {total_contact:.0f} cm² total")
    print(f"  Hauteur moy.     : {avg_height:.0f} cm")
    print(f"  Pire stabilité   : {max_stab:.2f}")

    return result
