"""
Orchestrateur principal — coordonne les 4 phases de la palettisation.

Ce fichier est le « chef d'orchestre » : il ne contient pas d'algorithme
de placement (c'est le rôle de core/ et heuristics/) mais appelle les bonnes
fonctions dans le bon ordre avec les bons paramètres.

Vue d'ensemble des 4 phases :

Phase 1 — Packing mono-client (FFD)
    Chaque client est traité indépendamment. Ses boîtes sont triées et
    emballées sur ses propres palettes avec First Fit Decreasing.
    Résultat : palettes entièrement mono-client, souvent sous-remplies.

Phase 2 — LNS mono-client
    Améliore les palettes de la Phase 1 par Large Neighbourhood Search.
    Interdit de mélanger les clients. Objectif : réduire le nombre de palettes
    ET rendre la palette la moins remplie la plus vide possible (candidat fusion).

Phase 3 — Fusion multi-client adaptative
    Reppack les palettes sous-remplies ensemble, mélangeant les clients.
    Le comportement s'adapte automatiquement au nombre de palettes :
        1 client ou 1 palette  → saut (pas de fusion possible)
        2 palettes             → fusion si avg fill < min_filling_ratio
        3..10 palettes         → fusion des 2 moins remplies, puis boucle d'alimentation
                                  (condition : fill moyen projeté < seuil ET amélioration réelle)
        11..70 palettes        → fusion initiale + alimentation une par une ;
                                  arrêt : ratio multi/total > minimum_ratio ET
                                          fill_mono_min > min_filling_ratio
                                  OU : ratio > maximum_ratio (borne dure)
        >70 palettes           → fusion par paires (2 à la fois) pour aller plus vite

Phase 4 — LNS multi-client
    Améliore le pool de palettes multi-client issu de la Phase 3.
    Les palettes mono « leftover » (créées par FFD lors du repacking Phase 3
    et non intégrées au pool multi) sont aussi incluses dans le LNS pour leur
    donner une seconde chance de fusion.

Détection des leftovers Phase 3 :
    Les leftovers sont identifiés par identité d'objet Python (id()).
    Avant la Phase 3, on prend un snapshot de la liste courante.
    Après la Phase 3, tout objet mono dont l'id() n'est PAS dans ce snapshot
    est nécessairement un nouvel objet créé par _repack_pallets → leftover.
"""

from typing import List

from models.box import Box
from models.pallet import Pallet
from config.parameters import OptimizationParameters
from heuristics.sorting import sort_boxes_for_packing, sort_boxes_by_client
from heuristics.first_fit_decreasing import pack_boxes_ffd
from heuristics.lns_mono import lns_mono_client
from heuristics.lns_multi import lns_multi_client

# Séparateur visuel pour les logs de progression
_SEP = "=" * 55


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


def _next_id(pallets: List[Pallet]) -> int:
    """
    Retourne le plus petit entier non encore utilisé comme ID de palette.
    Si la liste est vide, retourne 1.
    """
    if not pallets:
        return 1
    return max(p.id for p in pallets) + 1


# ── Phase 1 : packing mono-client ─────────────────────────────────────────────

def pack_mono_client(
    boxes: List[Box],
    params: OptimizationParameters
) -> List[Pallet]:
    """
    Emballe les boîtes indépendamment par client (Phase 1).

    Chaque client reçoit ses propres palettes — les clients ne se mélangent pas.
    Les boîtes de chaque client sont triées (P1 avant P2, grandes en premier)
    puis emballées avec FFD sur un ensemble de palettes vierges.

    Paramètres :
        boxes  : toutes les boîtes à emballer (tous clients confondus)
        params : paramètres de l'optimiseur

    Retourne la liste plate de toutes les palettes produites (tous clients).
    """
    client_groups = sort_boxes_by_client(boxes)   # { client_id → [Box trié] }
    all_pallets: List[Pallet] = []

    for client_id, client_boxes in sorted(client_groups.items()):
        print(f"[Phase 1] Emballage client {client_id} "
              f"({len(client_boxes)} boîtes)…")
        client_pallets = pack_boxes_ffd(
            client_boxes, params,
            next_pallet_id=_next_id(all_pallets)   # IDs uniques et consécutifs
        )
        all_pallets.extend(client_pallets)
        print(f"[Phase 1] Client {client_id} : {len(client_pallets)} palette(s).")

    return all_pallets


# ── Phase 3 : utilitaires de fusion ───────────────────────────────────────────

def _extract_boxes(pallets: List[Pallet], box_lookup: dict) -> List[Box]:
    """
    Récupère les Box originales correspondant à toutes les PlacedBox d'une liste
    de palettes.

    Utilisé avant un repacking : on « décharge » les palettes en récupérant
    les Box d'origine (non orientées) pour les redonner à FFD.

    Paramètres :
        pallets    : palettes à décharger
        box_lookup : dict { box_id → Box original }

    Retourne la liste de Box originales (dans l'ordre de parcours).
    """
    boxes: List[Box] = []
    for pallet in pallets:
        for pb in pallet.boxes:
            original = box_lookup.get(pb.box_id)
            if original:
                boxes.append(original)
    return boxes


def _repack_pallets(
    pallets_to_repack: List[Pallet],
    well_filled: List[Pallet],
    box_lookup: dict,
    params: OptimizationParameters,
    iteration: int,
    label: str = "",
) -> List[Pallet]:
    """
    Démantèle les palettes à repackager et les réemballe avec FFD.

    Les palettes « well_filled » (bien remplies) sont conservées intactes et
    ajoutées au résultat après le repacking.

    Processus :
        1. Extrait toutes les Box originales de pallets_to_repack.
        2. Les trie avec sort_boxes_for_packing.
        3. Les réemballe avec pack_boxes_ffd sur de nouvelles palettes vides.
        4. Retourne well_filled + nouvelles_palettes.

    Paramètres :
        pallets_to_repack : palettes à démonter et réemballer
        well_filled       : palettes à conserver sans modification
        box_lookup        : dict { box_id → Box original }
        params            : paramètres d'optimisation
        iteration         : numéro d'itération (pour le log)
        label             : description optionnelle (pour le log)

    Retourne la liste combinée des palettes après repacking.
    """
    boxes_to_repack = _extract_boxes(pallets_to_repack, box_lookup)

    print(
        f"[Phase 3 | iter {iteration}] Repacking {len(boxes_to_repack)} boîtes "
        f"depuis {len(pallets_to_repack)} palette(s){label}…"
    )

    sorted_repack = sort_boxes_for_packing(boxes_to_repack)
    new_pallets   = pack_boxes_ffd(
        sorted_repack, params,
        next_pallet_id=_next_id(well_filled),   # IDs uniques
    )
    result_pallets = well_filled + new_pallets

    new_multi = sum(1 for p in new_pallets if p.is_multi_client)
    print(
        f"[Phase 3 | iter {iteration}] Créé {len(new_pallets)} palette(s) "
        f"({new_multi} multi-client). Total : {len(result_pallets)}."
    )
    return result_pallets


# ── Renumérotation ─────────────────────────────────────────────────────────────

def _renumber_pallets(pallets: List[Pallet]) -> List[Pallet]:
    """
    Renumérotation des palettes selon la convention de sortie :
        - Palettes mono-client en premier, triées par client_id croissant.
        - Palettes multi-client à la fin.
        - IDs réattribués de 1 à N (consécutifs, sans trous).

    Paramètre :
        pallets : liste de palettes dans un ordre quelconque

    Retourne la liste réordonnée et renumérotée.
    """
    mono  = sorted(
        [p for p in pallets if not p.is_multi_client],
        key=lambda p: min(p.client_ids) if p.client_ids else 0,
    )
    multi = [p for p in pallets if p.is_multi_client]

    ordered = mono + multi
    for new_id, pallet in enumerate(ordered, start=1):
        pallet.id = new_id

    return ordered


# ── API publique ───────────────────────────────────────────────────────────────

def optimize_palletization(
    boxes: List[Box],
    parameters: OptimizationParameters,
) -> List[Pallet]:
    """
    Point d'entrée principal de l'optimiseur de palettisation.

    Exécute les 4 phases dans l'ordre et retourne la solution optimisée.

    Paramètres :
        boxes      : toutes les boîtes à emballer (issues de la lecture CSV)
        parameters : paramètres de tuning de l'algorithme

    Retourne :
        Liste optimisée de palettes avec leurs boîtes placées.
        Toutes les boîtes d'entrée sont garanties présentes en sortie
        (la Phase 6 dans main.py vérifie cette intégrité).
    """
    if not boxes:
        print("[Optimiseur] Aucune boîte à emballer.")
        return []

    print(f"[Optimiseur] {len(boxes)} boîtes à optimiser pour "
          f"{len({b.client_id for b in boxes})} client(s).")

    # ── Phase 1 : FFD mono-client ─────────────────────────────────────────────
    _phase_header(1, "Packing mono-client")
    pallets = pack_mono_client(boxes, parameters)
    phase1_pallet_count = len(pallets)
    print(f"  Résultat : {phase1_pallet_count} palette(s)")
    _phase_footer(1)

    # ── Phase 2 : LNS mono-client ─────────────────────────────────────────────
    _phase_header(2, "LNS amélioration (mono-client)")
    if parameters.lns_mono_iter_per_pallet > 0 and len(pallets) > 1:
        pallets = lns_mono_client(pallets, boxes, parameters)
    else:
        print("  Sauté (palette unique ou iter_per_pallet=0).")
    print(f"  Résultat : {len(pallets)} palette(s)")
    _phase_footer(2)

    # ── Phase 3 : fusion multi-client adaptative ──────────────────────────────
    unique_clients = {b.client_id for b in boxes}
    n_pallets      = len(pallets)

    _phase_header(3, "Fusion multi-client adaptative")

    # Fonction interne pour sauter les Phases 3 et 4 proprement
    def _skip_phase3_and_4(reason: str):
        """Saute les Phases 3 et 4 avec un message et une renumérotation."""
        print(f"  Sauté ({reason}).")
        nonlocal pallets
        pallets = _renumber_pallets(pallets)
        _phase_footer(3)
        _phase_header(4, "LNS amélioration (multi-client, passe unique)")
        print(f"  Sauté ({reason}).")
        _phase_footer(4)
        multi = sum(1 for p in pallets if p.is_multi_client)
        print(
            f"\n[Optimiseur] ══ Solution brute ══\n"
            f"  Palettes utilisées : {len(pallets)}\n"
            f"  Multi-client       : {multi}\n"
        )

    # ── Conditions de saut de Phase 3 et 4 ─────────────────────────────────
    if not parameters.enable_multi_client:
        _skip_phase3_and_4("enable_multi_client=False")
        return pallets

    if len(unique_clients) <= 1:
        _skip_phase3_and_4("client unique")
        return pallets

    if n_pallets <= 1:
        _skip_phase3_and_4("palette unique")
        return pallets

    box_lookup = {b.id: b for b in boxes}
    iteration  = 0

    # Snapshot avant Phase 3 : sert à identifier les leftovers après Phase 3.
    # Tout objet mono dont id() n'est pas dans ce snapshot est un leftover FFD.
    phase3_initial_state = pallets[:]

    def _avg_fill(pool):
        """Retourne le taux de remplissage moyen d'une liste de palettes."""
        return (sum(p.volumetric_fill_ratio for p in pool) / len(pool)) if pool else 0.0

    min_fill = parameters.min_filling_ratio

    # ── Régime : exactement 2 palettes ─────────────────────────────────────
    if n_pallets == 2:
        avg_fill = _avg_fill(pallets)
        if avg_fill < min_fill:
            iteration = 1
            print(f"  2 palettes, remplissage moy. {avg_fill:.1%} < {min_fill:.0%} → fusion.")
            pallets = _repack_pallets(
                pallets, [], box_lookup, parameters, iteration,
                label=" (2 palettes ensemble)",
            )
        else:
            print(f"  2 palettes, remplissage moy. {avg_fill:.1%} ≥ {min_fill:.0%} → pas de fusion.")

    # ── Régime : 3..10 palettes — boucle d'alimentation fill-driven ────────
    elif n_pallets <= 10:
        # Fusion initiale des 2 moins remplies seulement si leur avg fill est sous le seuil
        sorted_by_fill = sorted(pallets, key=lambda p: p.volumetric_fill_ratio)
        two_least      = sorted_by_fill[:2]
        well_filled    = sorted_by_fill[2:]
        init_avg       = _avg_fill(two_least)

        if init_avg >= min_fill:
            print(f"  ≤10 palettes : avg des 2 moins remplies {init_avg:.1%} ≥ "
                  f"{min_fill:.0%} → pas de fusion initiale.")
        else:
            iteration = 1
            print(f"  ≤10 palettes : fusion initiale des 2 moins remplies "
                  f"(avg {init_avg:.1%} < {min_fill:.0%}).")
            repack_pool = _repack_pallets(
                two_least, [], box_lookup, parameters, iteration,
                label=" (2 moins remplies, initiale)",
            )
            pallets = well_filled + repack_pool

            # Boucle : alimente la moins remplie du pool mono dans le pool multi
            # tant que l'avg projeté est sous le seuil ET qu'on améliore le count.
            max_iterations = phase1_pallet_count
            while iteration < max_iterations:
                if not well_filled:
                    print("  Plus de palettes mono à alimenter. Arrêt de la boucle.")
                    break

                well_filled_sorted = sorted(well_filled,
                                            key=lambda p: p.volumetric_fill_ratio)
                candidate  = well_filled_sorted[0]
                cand_fill  = candidate.volumetric_fill_ratio
                multi_avg  = _avg_fill(repack_pool)
                projected  = (cand_fill + multi_avg) / 2.0

                if projected >= min_fill:
                    print(f"  Avg combiné ({cand_fill:.1%} + {multi_avg:.1%})/2 = "
                          f"{projected:.1%} ≥ {min_fill:.0%}. Arrêt de la boucle.")
                    break

                iteration += 1
                prev_total = len(pallets)

                mono_to_add       = [candidate]
                well_filled       = well_filled_sorted[1:]
                pallets_to_repack = repack_pool + mono_to_add
                repack_pool       = _repack_pallets(
                    pallets_to_repack, [], box_lookup, parameters, iteration,
                    label=f" ({len(mono_to_add)} mono + {len(repack_pool)} pool repack)",
                )
                pallets = well_filled + repack_pool

                # Si la fusion n'a pas réduit le nombre total → inutile de continuer
                if len(pallets) >= prev_total:
                    print(f"  Aucune amélioration du count "
                          f"({prev_total} → {len(pallets)}). Arrêt.")
                    break
            else:
                print(f"  Iterations maximales atteintes ({max_iterations}). Arrêt.")

    # ── Régime : 11..70 palettes — boucle ratio multi-client ───────────────
    elif n_pallets <= 70:
        iteration      = 1
        sorted_by_fill = sorted(pallets, key=lambda p: p.volumetric_fill_ratio)
        two_least      = sorted_by_fill[:2]
        well_filled    = sorted_by_fill[2:]
        print(f"  11..70 palettes — fusion initiale des 2 moins remplies.")
        repack_pool = _repack_pallets(
            two_least, [], box_lookup, parameters, iteration,
            label=" (2 moins remplies, initiale)",
        )
        pallets = well_filled + repack_pool

        max_iterations = phase1_pallet_count
        while iteration < max_iterations:
            iteration  += 1
            total_count = len(pallets)
            multi_count = sum(1 for p in pallets if p.is_multi_client)
            multi_ratio = multi_count / total_count if total_count > 0 else 0.0

            # Borne dure : arrêt immédiat si le ratio dépasse le maximum
            if multi_ratio > parameters.multi_client_maximum_ratio:
                print(f"  Borne dure : {multi_count}/{total_count} "
                      f"({multi_ratio:.1%}) > "
                      f"{parameters.multi_client_maximum_ratio:.0%}. Arrêt.")
                break

            # Borne souple : arrêt si ratio > minimum ET la moins remplie des mono est bien remplie
            if multi_ratio > parameters.multi_client_minimum_ratio and well_filled:
                least_mono_fill = min(p.volumetric_fill_ratio for p in well_filled)
                if least_mono_fill > parameters.min_filling_ratio:
                    print(f"  Borne souple : {multi_ratio:.1%} > ratio min et "
                          f"fill mono min {least_mono_fill:.1%} > "
                          f"{parameters.min_filling_ratio:.0%}. Arrêt.")
                    break

            if not well_filled:
                print("  Plus de palettes mono à alimenter. Arrêt.")
                break

            # Alimente la moins remplie des mono une par une
            well_filled_sorted = sorted(well_filled,
                                        key=lambda p: p.volumetric_fill_ratio)
            mono_to_add        = well_filled_sorted[:1]
            well_filled        = well_filled_sorted[1:]
            pallets_to_repack  = repack_pool + mono_to_add
            repack_pool        = _repack_pallets(
                pallets_to_repack, [], box_lookup, parameters, iteration,
                label=f" ({len(mono_to_add)} mono + {len(repack_pool)} pool)",
            )
            pallets = well_filled + repack_pool
        else:
            print(f"  Iterations maximales ({max_iterations}). Arrêt.")

    # ── Régime : >70 palettes — fusion par paires pour accélérer ──────────
    # Deux moins remplies sont fusionnées à chaque itération (vs une à la fois
    # pour le régime 11..70), ce qui permet d'atteindre le ratio cible plus vite
    # sur de très grandes batches (centaines de palettes).
    else:
        repack_pool    = []
        max_iterations = phase1_pallet_count
        while iteration < max_iterations:
            total_count = len(pallets)
            multi_count = sum(1 for p in pallets if p.is_multi_client)
            multi_ratio = multi_count / total_count if total_count > 0 else 0.0

            if multi_ratio > parameters.multi_client_maximum_ratio:
                print(f"  Borne dure : {multi_count}/{total_count} "
                      f"({multi_ratio:.1%}) > "
                      f"{parameters.multi_client_maximum_ratio:.0%}. Arrêt.")
                break

            # well_filled = toutes les palettes qui ne sont PAS dans le pool repack
            repack_ids  = {id(p) for p in repack_pool}
            well_filled = [p for p in pallets if id(p) not in repack_ids]

            if multi_ratio > parameters.multi_client_minimum_ratio and well_filled:
                least_mono_fill = min(p.volumetric_fill_ratio for p in well_filled)
                if least_mono_fill > parameters.min_filling_ratio:
                    print(f"  Borne souple : {multi_ratio:.1%} > ratio min et "
                          f"fill mono min {least_mono_fill:.1%} > "
                          f"{parameters.min_filling_ratio:.0%}. Arrêt.")
                    break

            if len(well_filled) < 2:
                print("  Moins de 2 palettes mono restantes. Arrêt.")
                break

            # Prend les 2 moins remplies des palettes hors pool
            well_filled_sorted = sorted(well_filled,
                                        key=lambda p: p.volumetric_fill_ratio)
            two_least  = well_filled_sorted[:2]
            remaining  = well_filled_sorted[2:]

            iteration += 1
            pallets_to_repack = repack_pool + two_least
            repack_pool       = _repack_pallets(
                pallets_to_repack, [], box_lookup, parameters, iteration,
                label=f" (2 mono + {len(repack_pool)} pool repack)",
            )
            pallets = remaining + repack_pool
        else:
            print(f"  Iterations maximales ({max_iterations}). Arrêt.")

    multi_end3 = sum(1 for p in pallets if p.is_multi_client)
    print(f"  Résultat : {len(pallets)} palette(s) ({multi_end3} multi-client)"
          + (f" après {iteration} itération(s)" if iteration > 0 else ""))
    _phase_footer(3)

    # ── Phase 4 : LNS multi-client ──────────────────────────────────────────────
    # Identifie les leftovers : palettes mono créées PENDANT la Phase 3 par FFD.
    # Ces objets n'existaient pas avant → leur id() Python n'est pas dans le snapshot.
    _phase_header(4, "LNS amélioration (multi-client, passe unique)")
    original_ids         = {id(p) for p in phase3_initial_state}
    phase3_leftover_mono = [
        p for p in pallets
        if not p.is_multi_client and id(p) not in original_ids
    ]
    multi_count = sum(1 for p in pallets if p.is_multi_client)
    pool_size   = multi_count + len(phase3_leftover_mono)

    if parameters.lns_multi_iter_per_pallet > 0 and pool_size > 1:
        if phase3_leftover_mono:
            print(f"  Inclusion de {len(phase3_leftover_mono)} leftover(s) "
                  f"Phase-3 dans le pool LNS.")
        pallets = lns_multi_client(pallets, boxes, parameters,
                                   extra_mono=phase3_leftover_mono)
    else:
        print(f"  Sauté (pool size {pool_size} ≤ 1 ou iter_per_pallet=0).")

    pallets   = _renumber_pallets(pallets)
    multi_p4  = sum(1 for p in pallets if p.is_multi_client)
    print(f"  Résultat : {len(pallets)} palette(s) ({multi_p4} multi-client)")
    _phase_footer(4)

    multi = sum(1 for p in pallets if p.is_multi_client)
    print(
        f"\n[Optimiseur] ══ Solution brute ══\n"
        f"  Palettes utilisées : {len(pallets)}\n"
        f"  Multi-client       : {multi}\n"
    )

    return pallets
