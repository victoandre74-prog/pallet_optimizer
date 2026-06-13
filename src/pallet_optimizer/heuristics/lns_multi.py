"""
LNS — passe multi-client (Phase 4).

Objectif : améliorer un pool de palettes mélangeant plusieurs clients en
réduisant le nombre total de palettes.

Différences avec la passe mono (lns_mono.py) :
    1. La fonction de coût est plus simple : uniquement le nombre de palettes.
       La répartition P2 et l'équilibre de remplissage sont gérés par post_processing.py.
    2. La stratégie de destruction est différente :
       → On détruit les N MOINS REMPLIES (fraction lns_multi_destroy_ratio),
         avec un minimum forcé de 2 palettes détruites.
       → Forcer 2 destructions minimum évite un problème : avec seulement 1 palette
         détruite, les palettes survivantes sont figées et FFD ne peut qu'empiler
         par-dessus. Avec 2+ destructions, les boîtes des deux palettes se mélangent,
         ce qui permet de vrais réarrangements (ex. interleaver des couches).
    3. Il n'y a pas de restriction sur le mélange de clients (c'est le but même
       de la Phase 4 : optimiser les palettes multi-client).

Fonction de coût (Phase 4) :
    coût = cost_multi_pallet_count × nombre_de_palettes

Stratégie Destroy :
    Trie toutes les palettes du pool par taux de remplissage croissant.
    Sélectionne les max(2, int(N × destroy_ratio)) moins remplies → pool.
    Les palettes non sélectionnées sont « survivantes » (inchangées).

Stratégie Repair :
    Identique à la passe mono : mélange aléatoire + top-k perturbé.
    Pas de restriction sur le mélange de clients pendant la réparation.
"""

import copy
import random
import time
from typing import Callable, List, Optional, Tuple

from pallet_optimizer.models.box import Box
from pallet_optimizer.models.placed_box import PlacedBox
from pallet_optimizer.models.pallet import Pallet
from pallet_optimizer.config.parameters import OptimizationParameters
from pallet_optimizer.core.placement_engine import (
    find_best_placement, make_placed_box,
    generate_extreme_points, find_support_z, is_valid_placement,
    _compute_residual_area,
)
from pallet_optimizer.heuristics.lns_utils import make_pool_box, get_next_pallet_id


# ── Fonction de coût ───────────────────────────────────────────────────────────

def compute_cost_multi(pallets: List[Pallet], params: OptimizationParameters) -> float:
    """
    Évalue la qualité d'une solution multi-client.

    Formule :
        coût = cost_multi_pallet_count × nombre_de_palettes

    Un coût plus faible = meilleure solution (moins de palettes = moins de transport).
    La répartition des boîtes P2 est intentionnellement ignorée ici : elle sera
    optimisée séparément dans post_processing.py (Phase 5).

    Retourne 0.0 si la liste de palettes est vide.
    """
    if not pallets:
        return 0.0

    return params.cost_multi_pallet_count * len(pallets)


# ── Alias des utilitaires partagés ────────────────────────────────────────────
_make_pool_box      = make_pool_box
_get_next_pallet_id = get_next_pallet_id


# ── Placement avec perturbation (top-k) ───────────────────────────────────────

def _find_placement_top_k(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
    rng: random.Random,
    top_k: int,
) -> Optional[Tuple[float, float, float, object]]:
    """
    Variante perturbée de find_best_placement : retourne une position tirée
    aléatoirement parmi les top-k meilleures positions valides.

    Identique à la version dans lns_mono.py mais sans la restriction
    multi-client (toutes les palettes peuvent recevoir n'importe quel client).

    Paramètres :
        box    : boîte à placer
        pallet : palette cible
        params : paramètres d'optimisation
        rng    : générateur aléatoire (pour le tirage dans le top-k)
        top_k  : taille du bassin de sélection (1 = déterministe, comme find_best_placement)

    Retourne (x, y, z, orientation) ou None si aucune position valide.
    """
    from pallet_optimizer.models.orientation import get_oriented_dimensions

    candidates = []
    ep_candidates = generate_extreme_points(pallet)

    for orientation in box.allowed_orientations:
        length, width, height = get_oriented_dimensions(
            box.length, box.width, box.height, orientation
        )
        for (cx, cy) in ep_candidates:
            z = find_support_z(cx, cy, length, width, height, pallet.boxes)
            if is_valid_placement(box, cx, cy, z, orientation,
                                  length, width, height, pallet, params):
                stackable    = box.is_stackable_in(orientation)
                height_score = (z + height) if stackable else 0.0
                residual     = _compute_residual_area(cx, cy, length, width, pallet)
                score        = (z, cx, cy, height_score, -residual)
                candidates.append((score, cx, cy, z, orientation))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0])
    k      = min(top_k, len(candidates))
    chosen = rng.choice(candidates[:k])
    _, cx, cy, z, orientation = chosen
    return cx, cy, z, orientation


def _repair_with_perturbation(
    pool_boxes: List[Box],
    surviving_pallets: List[Pallet],
    params: OptimizationParameters,
    rng: random.Random,
    next_pallet_id: int,
) -> List[Pallet]:
    """
    Phase de réparation pour le LNS multi-client.

    Identique à la version mono sauf qu'il n'y a PAS de restriction sur le
    mélange de clients (c'est justement le but de la Phase 4 d'optimiser
    des palettes multi-client).

    Pour chaque boîte du pool :
        1. Essaie chaque palette existante avec un placement top-k perturbé.
           Prend la première qui accepte (First Fit).
        2. Si aucune palette ne convient, ouvre une nouvelle palette et y
           place la boîte de façon déterministe.

    Paramètres :
        pool_boxes        : boîtes à replacer (Box reconstruites depuis PlacedBox)
        surviving_pallets : palettes non détruites (conservées intactes)
        params            : paramètres d'optimisation
        rng               : générateur aléatoire partagé
        next_pallet_id    : premier ID disponible pour une nouvelle palette

    Retourne la liste de palettes après réparation.
    """
    top_k   = params.lns_multi_repair_top_k
    pallets = list(surviving_pallets)
    counter = next_pallet_id

    for box in pool_boxes:
        placed = False

        for pallet in pallets:
            result = _find_placement_top_k(box, pallet, params, rng, top_k)
            if result is not None:
                x, y, z, orientation = result
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = len(pallet.boxes) + 1
                pallet.boxes.append(pb)
                placed = True
                break

        if not placed:
            new_pallet = Pallet(
                id=counter,
                length=params.pallet_length,
                width=params.pallet_width,
                max_height=params.pallet_max_height,
                max_weight=params.pallet_max_weight,
            )
            counter += 1
            result = find_best_placement(box, new_pallet, params)
            if result is not None:
                x, y, z, orientation = result
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = 1
                new_pallet.boxes.append(pb)
                pallets.append(new_pallet)
            else:
                print(f"[LNS-multi] AVERTISSEMENT : boîte {box.id!r} impossible à placer "
                      f"(dims {box.length}×{box.width}×{box.height}). Ignorée.")

    return pallets


# ── Passe LNS principale ───────────────────────────────────────────────────────

def _lns_pass(
    initial_pallets: List[Pallet],
    box_lookup: dict,
    params: OptimizationParameters,
    rng: random.Random,
    time_limit: float,
    max_iterations: int,
    label: str,
    cost_fn: Callable,
) -> List[Pallet]:
    """
    Exécute une passe LNS multi-client sur les palettes données.

    Différence principale avec _lns_pass de lns_mono :
        Stratégie de destruction multi-palette :
            - Trie toutes les palettes par remplissage croissant.
            - Sélectionne les max(2, floor(N × destroy_ratio)) moins remplies.
            - Force minimum 2 palettes détruites pour permettre de vraies fusions
              (avec 1 seule palette détruite, les survivantes sont figées et seul
               du remplissage vertical additionnel est possible, pas de réarrangement).

    Boucle principale identique à lns_mono :
        DESTROY → RANDOMISE → REPAIR → ACCEPT

    Paramètres :
        initial_pallets  : palettes à optimiser
        box_lookup       : dict { box_id → Box original }
        params           : paramètres d'optimisation
        rng              : générateur aléatoire
        time_limit       : budget temps (secondes)
        max_iterations   : nombre maximum d'itérations
        label            : préfixe pour les messages de log
        cost_fn          : fonction de coût (pallets, params) → float

    Retourne la meilleure liste de palettes trouvée.
    """
    if not initial_pallets:
        print(f"{label} Aucune palette à optimiser — saut.")
        return initial_pallets

    best_pallets = copy.deepcopy(initial_pallets)
    best_cost    = cost_fn(best_pallets, params)

    start_time            = time.time()
    iteration             = 0
    improvement_count     = 0
    last_improvement_iter = 0

    print(f"{label} Démarrage. Coût : {best_cost:.2f}, palettes : {len(best_pallets)}")

    while (iteration < max_iterations and
           time.time() - start_time < time_limit):

        iteration += 1

        # ── DESTROY ─────────────────────────────────────────────────────────────
        current = copy.deepcopy(best_pallets)

        # Nombre de palettes à détruire : au moins 2 pour forcer de vraies fusions
        n_destroy = max(2, int(len(current) * params.lns_multi_destroy_ratio))
        # Trie les palettes par taux de remplissage croissant
        sorted_by_fill = sorted(range(len(current)),
                                key=lambda i: current[i].volumetric_fill_ratio)
        # Sélectionne les n_destroy moins remplies comme ensemble à détruire
        destroy_indices = set(sorted_by_fill[:n_destroy])

        pool_pbs: List[PlacedBox]       = []
        surviving_pallets: List[Pallet] = []

        for i, pallet in enumerate(current):
            if i in destroy_indices:
                pool_pbs.extend(pallet.boxes)  # toutes les boîtes dans le pool
                continue
            surviving_pallets.append(pallet)   # palette survivante : inchangée

        # ── Construction et mélange du pool ─────────────────────────────────────
        if not pool_pbs:
            continue

        pool_boxes = [_make_pool_box(pb, box_lookup) for pb in pool_pbs]
        rng.shuffle(pool_boxes)                          # mélange aléatoire
        pool_boxes.sort(key=lambda b: b.priority)        # P1 avant P2

        # ── REPAIR ───────────────────────────────────────────────────────────────
        next_id     = _get_next_pallet_id(surviving_pallets)
        new_pallets = _repair_with_perturbation(
            pool_boxes, surviving_pallets, params, rng,
            next_pallet_id=next_id,
        )

        # ── ACCEPT / REJECT ──────────────────────────────────────────────────────
        boxes_before = sum(len(p.boxes) for p in best_pallets)
        boxes_after  = sum(len(p.boxes) for p in new_pallets)
        if boxes_after < boxes_before:
            continue   # boîte perdue → rejet immédiat

        new_cost = cost_fn(new_pallets, params)
        if new_cost < best_cost:
            best_cost             = new_cost
            best_pallets          = copy.deepcopy(new_pallets)
            improvement_count    += 1
            last_improvement_iter = iteration
            print(f"{label} iter {iteration:4d}: coût amélioré → {best_cost:.2f}, "
                  f"palettes : {len(best_pallets)}")

    elapsed    = time.time() - start_time
    stagnation = iteration - last_improvement_iter
    stag_pct   = stagnation / max(1, iteration) * 100
    print(
        f"{label} Terminé. {iteration} iter en {elapsed:.1f}s | "
        f"améliorations: {improvement_count} | "
        f"stagnation: {stagnation} iter ({stag_pct:.0f}%) | "
        f"palettes: {len(initial_pallets)}→{len(best_pallets)}"
    )

    return best_pallets


# ── Point d'entrée public ──────────────────────────────────────────────────────

def lns_multi_client(
    pallets: List[Pallet],
    original_boxes: List[Box],
    params: OptimizationParameters,
    extra_mono: List[Pallet] = None,
) -> List[Pallet]:
    """
    Exécute le LNS sur les palettes multi-client, plus d'éventuelles palettes
    mono-client « restantes » (leftovers) de la Phase 3.

    Qu'est-ce qu'un leftover Phase 3 ?
        Lors du repacking Phase 3, FFD peut créer de nouvelles palettes
        mono-client : des boîtes d'un seul client que FFD n'a pas réussi à
        intégrer dans le pool multi-client. Ces palettes passent souvent mieux
        si on les soumet au LNS multi-client (destroy + repair avec perturbation),
        qui peut trouver un arrangement que FFD greedy a raté.

    Identification des leftovers :
        Les leftovers sont identifiés par identité d'objet Python (id(p)).
        L'appelant passe les VRAIS objets Pallet présents dans `pallets`, pas des copies.
        Tout mono dont l'id() Python n'est pas dans extra_mono est laissé intact.

    Paramètres :
        pallets        : liste complète des palettes (multi + mono)
        original_boxes : toutes les Box originales
        params         : paramètres d'optimisation
        extra_mono     : palettes mono-client à inclure dans le pool LNS
                         (None ou liste vide = comportement classique multi-only)

    Retourne :
        Palettes mono intactes (hors extra_mono) + pool amélioré (multi + extra_mono).
    """
    rng        = random.Random(params.lns_multi_random_seed)
    box_lookup = {b.id: b for b in original_boxes}

    # Identifie les objets extra_mono par leur adresse Python pour éviter les copies
    extra_ids      = {id(p) for p in (extra_mono or [])}
    # Pool = palettes multi-client + leftovers mono explicitement fournis
    pool           = [p for p in pallets if p.is_multi_client or id(p) in extra_ids]
    # Palettes mono non touchées : passent directement en sortie
    untouched_mono = [p for p in pallets if not p.is_multi_client and id(p) not in extra_ids]

    if len(pool) <= 1:
        if not pool:
            print("[LNS-multi] Aucune palette multi-client — saut.")
        else:
            print(f"[LNS-multi] Pool trop petit ({len(pool)} palette) — saut.")
        return pallets

    if extra_ids:
        print(f"[LNS-multi] Pool : {len(pool)} palette(s) "
              f"({len(pool) - len(extra_ids)} multi + {len(extra_ids)} leftover(s) Phase-3).")

    # Calcule le budget proportionnellement à la taille du pool
    pool_size   = len(pool)
    time_budget = max(1.0, pool_size * params.lns_multi_time_per_pallet)
    iter_budget = max(1,   pool_size * params.lns_multi_iter_per_pallet)
    print(f"[LNS-multi] Budget : {pool_size} palettes × "
          f"{params.lns_multi_time_per_pallet}s = {time_budget:.1f}s / {iter_budget} iters")

    improved_pool = _lns_pass(
        pool, box_lookup, params, rng,
        time_limit=time_budget,
        max_iterations=iter_budget,
        label="[LNS-multi]",
        cost_fn=compute_cost_multi,
    )

    return untouched_mono + improved_pool
