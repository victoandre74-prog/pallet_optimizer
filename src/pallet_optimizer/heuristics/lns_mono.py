"""
LNS — passe mono-client (Phase 2).

Qu'est-ce que le LNS (Large Neighbourhood Search) ?
    Le LNS est une méta-heuristique d'optimisation : une stratégie pour améliorer
    une solution existante de manière itérative.
    À chaque itération :
        1. DESTROY  : on « détruit » une partie de la solution (retire des boîtes)
        2. REPAIR   : on reconstruit cette partie différemment (replace les boîtes)
        3. ACCEPT   : si la nouvelle solution est meilleure → on la garde

    L'idée est d'explorer un large voisinage de la solution actuelle tout en
    guidant la recherche vers les meilleures zones de l'espace de solutions.

Fonction de coût (Phase 2) :
    coût = cost_mono_pallet_count × nombre_de_palettes
           + cost_mono_last_pallet_filling × fill_ratio_min

    Objectif principal  : minimiser le nombre de palettes.
    Objectif secondaire : minimiser le taux de remplissage de la palette la MOINS remplie.
                          Une palette peu remplie = bon candidat pour une fusion en Phase 3/4.

Stratégie Destroy (par itération) :
    1. Retire entièrement la palette la MOINS remplie (toutes ses boîtes → pool).
    2. Extrait aussi les petites boîtes (volume < lns_mono_small_box_volume) de
       toutes les palettes survivantes → donne plus de liberté à la réparation.
    3. Les palettes survivantes vidées par l'extraction de petites boîtes sont
       aussi traitées comme détruites.

Stratégie Repair :
    - Mélange aléatoirement le pool (perturbation de l'ordre).
    - Trie P1 avant P2 (contrainte obligatoire : les P1 doivent être posés en premier).
    - Place chaque boîte avec _find_placement_top_k : collecte toutes les positions
      valides, les trie par score, choisit aléatoirement parmi les top-k.
    - Cette perturbation contrôlée permet d'échapper aux optima locaux déterministes
      tout en restant guidée par le score géométrique.

Critère d'acceptation :
    On accepte la nouvelle solution si et seulement si :
        a) aucune boîte n'a été perdue (intégrité des données)
        b) le coût est strictement inférieur à la meilleure solution connue.
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

def compute_cost_mono(pallets: List[Pallet], params: OptimizationParameters) -> float:
    """
    Évalue la qualité d'une solution mono-client.

    Un coût plus faible = meilleure solution (convention : minimisation).

    Formule :
        coût = cost_mono_pallet_count        × nombre_de_palettes
               + cost_mono_last_pallet_filling × fill_ratio_minimal

    Explication des deux termes :
        Terme 1 : pénalise le nombre de palettes. Chaque palette en moins
                  économise du transport → c'est l'objectif principal.

        Terme 2 : pénalise un fort remplissage sur la palette la moins remplie.
                  Contre-intuitif au premier abord : on veut que la palette
                  la moins remplie soit LA PLUS VIDE POSSIBLE pour qu'elle
                  puisse facilement accueillir des boîtes d'un autre client
                  lors de la fusion (Phase 3/4).

    Retourne 0.0 si la liste de palettes est vide.
    """
    if not pallets:
        return 0.0

    pallet_count = len(pallets)
    # min() sur une expression génératrice : parcourt toutes les palettes
    # pour trouver celle avec le plus petit taux de remplissage
    min_fill = min(p.volumetric_fill_ratio for p in pallets)

    return (params.cost_mono_pallet_count * pallet_count
            + params.cost_mono_last_pallet_filling * min_fill)


# ── Alias des utilitaires partagés ────────────────────────────────────────────
# On les réexporte localement pour éviter les imports imbriqués dans les fonctions.
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
    Variante perturbée de find_best_placement : retourne une position choisie
    aléatoirement parmi les top-k meilleures positions valides.

    Différence avec find_best_placement :
        - find_best_placement : retourne TOUJOURS la position optimale (déterministe)
        - _find_placement_top_k : retourne UNE des top-k meilleures (aléatoire)
          → Introduit de la diversité dans les solutions explorées par le LNS.

    Quand top_k = 1 : identique à find_best_placement (même comportement).
    Quand top_k > 1 : peut choisir une position légèrement sous-optimale,
                       ce qui permet d'explorer des arrangements différents.

    Algorithme :
        1. Collecte toutes les combinaisons (point extrême × orientation) valides.
        2. Calcule le score de chaque combinaison (identique à find_best_placement).
        3. Trie par score croissant (du meilleur au moins bon).
        4. Choisit aléatoirement l'une des top-k premières.

    Retourne (x, y, z, orientation) ou None si aucune position valide.
    """
    from pallet_optimizer.models.orientation import get_oriented_dimensions

    candidates = []   # liste de (score, cx, cy, z, orientation)

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
        return None   # aucune position valide sur cette palette

    # Trie par score (le meilleur = plus petit score en premier)
    candidates.sort(key=lambda c: c[0])
    k      = min(top_k, len(candidates))        # ne dépasse pas le nombre de candidats
    chosen = rng.choice(candidates[:k])          # choix aléatoire parmi les k meilleurs
    _, cx, cy, z, orientation = chosen
    return cx, cy, z, orientation


def _repair_with_perturbation(
    pool_boxes: List[Box],
    surviving_pallets: List[Pallet],
    params: OptimizationParameters,
    rng: random.Random,
    next_pallet_id: int,
    allow_multi_client: bool,
) -> List[Pallet]:
    """
    Phase de réparation LNS : replace les boîtes du pool sur les palettes survivantes.

    Stratégie (First Fit + perturbation intra-palette) :
        Pour chaque boîte du pool :
            1. Essaie chaque palette existante dans l'ordre.
               Sur chaque palette, utilise _find_placement_top_k pour choisir
               aléatoirement parmi les top-k positions → perturbation contrôlée.
               Prend la PREMIÈRE palette qui accepte (First Fit).
            2. Si aucune palette ne convient, ouvre une nouvelle palette vide
               et y place la boîte de manière déterministe (meilleure position).
               (Perturber une palette vide n'a pas de sens : tous les EP
                convergent vers l'origine, donc toutes les positions top-k
                seraient identiques.)

    Paramètres :
        pool_boxes         : boîtes à replacer (objets Box reconstruits depuis PlacedBox)
        surviving_pallets  : palettes non détruites qui restent intactes
        params             : paramètres d'optimisation
        rng                : générateur aléatoire partagé (reproductible avec seed)
        next_pallet_id     : premier ID disponible pour une nouvelle palette
        allow_multi_client : si False, interdit de mélanger des clients

    Retourne la liste de palettes après réparation.
    """
    top_k   = params.lns_mono_repair_top_k
    pallets = list(surviving_pallets)   # copie locale de la liste
    counter = next_pallet_id

    for box in pool_boxes:
        placed = False

        for pallet in pallets:
            # Filtre multi-client si nécessaire
            if not allow_multi_client and pallet.boxes:
                if any(pb.client_id != box.client_id for pb in pallet.boxes):
                    continue

            result = _find_placement_top_k(box, pallet, params, rng, top_k)
            if result is not None:
                x, y, z, orientation = result
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = len(pallet.boxes) + 1
                pallet.boxes.append(pb)
                placed = True
                break   # First Fit : on arrête à la première palette qui accepte

        if not placed:
            # Ouvre une nouvelle palette vide
            new_pallet = Pallet(
                id=counter,
                length=params.pallet_length,
                width=params.pallet_width,
                max_height=params.pallet_max_height,
                max_weight=params.pallet_max_weight,
            )
            counter += 1
            result = find_best_placement(box, new_pallet, params)  # déterministe sur palette vide
            if result is not None:
                x, y, z, orientation = result
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = 1
                new_pallet.boxes.append(pb)
                pallets.append(new_pallet)
            else:
                print(f"[LNS-mono] AVERTISSEMENT : boîte {box.id!r} impossible à placer "
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
    allow_multi_client: bool,
    label: str,
    cost_fn: Callable,
) -> List[Pallet]:
    """
    Exécute une passe LNS complète sur les palettes données.

    Boucle principale (jusqu'au budget temps ou itérations épuisé) :
        1. Copie profonde de la meilleure solution connue.
        2. DESTROY :
              - Identifie la palette la moins remplie → pool.
              - Extrait les petites boîtes (volume < seuil) des survivantes → pool.
              - Les palettes vidées par l'extraction deviennent aussi détruites.
        3. Reconstruit les Box du pool depuis box_lookup.
        4. Mélange le pool (perturbation de l'ordre d'insertion).
        5. Trie P1 avant P2 (stable sort : préserve l'ordre aléatoire au sein du groupe).
        6. REPAIR : replace le pool sur les survivantes avec perturbation top-k.
        7. ACCEPT : conserve si aucune boîte perdue ET coût strictement inférieur.

    Paramètres :
        initial_pallets    : palettes initiales à optimiser
        box_lookup         : dict { box_id → Box original }
        params             : paramètres d'optimisation
        rng                : générateur aléatoire
        time_limit         : budget temps en secondes
        max_iterations     : nombre maximum d'itérations
        allow_multi_client : si False, empêche la création de palettes mixtes
        label              : préfixe pour les messages de log (ex. "[LNS-mono|client=1]")
        cost_fn            : fonction de coût (pallets, params) → float

    Retourne la meilleure liste de palettes trouvée dans le budget.
    """
    if not initial_pallets:
        print(f"{label} Aucune palette à optimiser — saut.")
        return initial_pallets

    # Initialise la meilleure solution connue avec la solution de départ
    best_pallets = copy.deepcopy(initial_pallets)
    best_cost    = cost_fn(best_pallets, params)

    start_time            = time.time()
    iteration             = 0
    improvement_count     = 0
    last_improvement_iter = 0

    print(f"{label} Démarrage. Coût : {best_cost:.2f}, palettes : {len(best_pallets)}")

    # Boucle principale : s'arrête quand le budget temps OU itérations est épuisé
    while (iteration < max_iterations and
           time.time() - start_time < time_limit):

        iteration += 1

        # ── DESTROY ─────────────────────────────────────────────────────────────
        # Travaille sur une copie profonde pour ne pas modifier best_pallets
        current = copy.deepcopy(best_pallets)

        # Trouve l'index de la palette la moins remplie
        least_idx = min(
            range(len(current)),
            key=lambda i: current[i].volumetric_fill_ratio,
        )

        pool_pbs: List[PlacedBox]       = []   # boîtes à replacer
        surviving_pallets: List[Pallet] = []   # palettes non détruites

        for i, pallet in enumerate(current):
            if i == least_idx:
                # Palette détruite : toutes ses boîtes vont dans le pool
                pool_pbs.extend(pallet.boxes)
                continue

            # Extrait les petites boîtes de cette palette survivante
            small = [pb for pb in pallet.boxes
                     if pb.volume < params.lns_mono_small_box_volume]
            if small:
                # Retire les petites boîtes et renumérote les survivantes
                pallet.boxes = [pb for pb in pallet.boxes
                                if pb.volume >= params.lns_mono_small_box_volume]
                for _seq_i, _pb in enumerate(pallet.boxes, 1):
                    _pb.sequence = _seq_i
                pool_pbs.extend(small)

            # Garde la palette seulement si elle n'est pas vide après extraction
            if not pallet.is_empty():
                surviving_pallets.append(pallet)
            else:
                # Palette vidée par l'extraction des petites boîtes → traitée comme détruite
                pool_pbs.extend(pallet.boxes)  # déjà vide ici, no-op mais explicite

        # ── Construction et mélange du pool ─────────────────────────────────────
        if not pool_pbs:
            continue   # pool vide → pas de réparation possible, itération suivante

        # Reconstruit les Box originales (dimensions non orientées + orientations complètes)
        pool_boxes = [_make_pool_box(pb, box_lookup) for pb in pool_pbs]

        # Mélange aléatoire = source de diversité du LNS
        rng.shuffle(pool_boxes)

        # Trie P1 avant P2 en conservant l'ordre aléatoire au sein de chaque groupe
        # (stable sort = sort() en Python garantit la stabilité)
        pool_boxes.sort(key=lambda b: b.priority)

        # ── REPAIR ───────────────────────────────────────────────────────────────
        next_id     = _get_next_pallet_id(surviving_pallets)
        new_pallets = _repair_with_perturbation(
            pool_boxes, surviving_pallets, params, rng,
            next_pallet_id=next_id,
            allow_multi_client=allow_multi_client,
        )

        # ── ACCEPT / REJECT ──────────────────────────────────────────────────────
        # Vérification de l'intégrité : aucune boîte ne doit avoir été perdue.
        # FFD ignore silencieusement les boîtes qu'il ne peut pas placer.
        # Accepter une telle solution signifierait perdre des colis réels → interdit.
        boxes_before = sum(len(p.boxes) for p in best_pallets)
        boxes_after  = sum(len(p.boxes) for p in new_pallets)
        if boxes_after < boxes_before:
            continue   # boîte perdue → rejette sans même calculer le coût

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

def lns_mono_client(
    pallets: List[Pallet],
    original_boxes: List[Box],
    params: OptimizationParameters,
) -> List[Pallet]:
    """
    Exécute le LNS indépendamment sur chaque groupe mono-client.

    Traitement par groupe :
        - Les palettes multi-client éventuellement présentes dans l'entrée
          sont passées sans modification (elles ne devraient pas exister en
          Phase 2, mais on les protège par précaution).
        - Les palettes mono-client sont regroupées par client_id.
        - Chaque groupe reçoit son propre LNS (isolation complète).
        - Les groupes d'une seule palette sont ignorés (pas d'optimisation possible
          sans au moins 2 palettes à compresser).

    Budgets :
        Temps    = taille_groupe × lns_mono_time_per_pallet
        Itérations = taille_groupe × lns_mono_iter_per_pallet

    Reproductibilité :
        Chaque groupe utilise une graine dérivée de la graine globale XOR client_id.
        Cela garantit que les résultats sont reproductibles mais différents par groupe
        (pas de contamination entre clients).

    Paramètres :
        pallets        : palettes actuelles (typiquement issues de la Phase 1 FFD)
        original_boxes : liste de toutes les Box originales (pour box_lookup)
        params         : paramètres d'optimisation

    Retourne :
        Palettes mono-client améliorées (tous groupes concaténés) +
        palettes multi-client inchangées.
    """
    # Construit le dictionnaire de recherche rapide { box_id → Box }
    box_lookup = {b.id: b for b in original_boxes}

    # Sépare les palettes mono et multi
    mono  = [p for p in pallets if not p.is_multi_client]
    multi = [p for p in pallets if p.is_multi_client]

    if not mono:
        print("[LNS-mono] Aucune palette mono-client — saut.")
        return pallets

    # Regroupe les palettes mono par client_id
    groups: dict = {}
    for p in mono:
        cid = next(iter(p.client_ids))   # récupère le seul client_id du set
        groups.setdefault(cid, []).append(p)

    improved_all: List[Pallet] = []

    print(f"[LNS-mono] {len(groups)} groupe(s) client, {len(mono)} palettes au total.")

    for cid, group in sorted(groups.items()):
        if len(group) <= 1:
            # Un seul pallet dans le groupe → rien à optimiser (FFD est déjà optimal)
            print(f"[LNS-mono|client={cid}] Palette unique — saut du LNS.")
            improved_all.extend(group)
            continue

        # Calcule le budget pour ce groupe (proportionnel à sa taille)
        time_budget = max(1.0, len(group) * params.lns_mono_time_per_pallet)
        iter_budget = max(1,   len(group) * params.lns_mono_iter_per_pallet)

        # Graine spécifique au client (XOR pour garantir l'unicité par client)
        seed = params.lns_mono_random_seed ^ cid
        rng  = random.Random(seed)

        improved = _lns_pass(
            group, box_lookup, params, rng,
            time_limit=time_budget,
            max_iterations=iter_budget,
            allow_multi_client=False,       # Phase 2 : interdit le mélange de clients
            label=f"[LNS-mono|client={cid}]",
            cost_fn=compute_cost_mono,
        )
        improved_all.extend(improved)

    result = improved_all + multi

    # Réattribue des IDs uniques et consécutifs.
    # Les passes LNS indépendantes par groupe peuvent créer des ID dupliqués
    # (chaque groupe ne connaît que ses propres palettes survivantes).
    for new_id, p in enumerate(result, 1):
        p.id = new_id

    return result
