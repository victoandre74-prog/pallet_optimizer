"""
Algorithme First Fit Decreasing (FFD) pour la palettisation 3D.

Qu'est-ce que FFD ?
    FFD est un algorithme glouton (greedy) classique du problème de bin packing.
    « First Fit » = on place chaque boîte sur la PREMIÈRE palette qui l'accepte.
    « Decreasing » = les boîtes sont triées par taille décroissante avant.

Algorithme simplifié :
    Pour chaque boîte (dans l'ordre trié grande → petite) :
        1. Essaie chaque palette existante dans l'ordre.
        2. Si la palette accepte la boîte (position valide trouvée) :
               → Place la boîte et passe à la suivante.
        3. Si aucune palette ne convient :
               → Ouvre une nouvelle palette vide et y place la boîte.

Pourquoi les grandes boîtes en premier ?
    Les grandes boîtes sont les plus difficiles à placer car elles ont moins de
    positions valides. En les plaçant tôt (palettes encore vides), elles trouvent
    toujours de la place. Les petites boîtes remplissent ensuite les espaces
    résiduels comme des « bouchons ».

Versatilité :
    Cette fonction est appelée dans deux contextes :
    - Phase 1 : liste mono-client (une seule entreprise par appel)
    - Phase 3 (repacking) : liste multi-client pour remplir des espaces libres
      sur des palettes existantes (initial_pallets non vide)
"""

from typing import List, Optional, Tuple

from pallet_optimizer.models.box import Box
from pallet_optimizer.models.pallet import Pallet
from pallet_optimizer.config.parameters import OptimizationParameters
from pallet_optimizer.core.placement_engine import find_best_placement, make_placed_box


def _make_new_pallet(pallet_id: int, params: OptimizationParameters) -> Pallet:
    """
    Crée une nouvelle palette vide avec les dimensions standard.

    Paramètres :
        pallet_id : identifiant unique attribué à cette palette
        params    : paramètres de l'optimiseur (dimensions physiques de la palette)

    Retourne une Pallet vide avec id=pallet_id et les dimensions de params.
    """
    return Pallet(
        id=pallet_id,
        length=params.pallet_length,
        width=params.pallet_width,
        max_height=params.pallet_max_height,
        max_weight=params.pallet_max_weight,
    )


def pack_boxes_ffd(
    boxes: List[Box],
    params: OptimizationParameters,
    initial_pallets: Optional[List[Pallet]] = None,
    next_pallet_id: int = 1,
    allow_multi_client: bool = True,
) -> List[Pallet]:
    """
    Emballe une liste de boîtes pré-triées sur des palettes avec FFD.

    Paramètres :
        boxes              : liste de boîtes à emballer (doit être pré-triée par
                             sort_boxes_for_packing() avant cet appel)
        params             : paramètres de l'optimiseur
        initial_pallets    : si fourni, tente d'abord de placer sur ces palettes
                             existantes (utile pour la Phase 3 de repacking)
        next_pallet_id     : ID à attribuer à la prochaine palette créée
        allow_multi_client : si False, interdit de mélanger les clients sur une palette.
                             Une boîte de client A ne sera jamais placée sur une palette
                             contenant déjà des boîtes du client B.

    Retourne :
        Liste de toutes les palettes (existantes + nouvelles) avec les boîtes placées.
        Les boîtes qui n'ont pu être placées nulle part sont ignorées (cas très rare —
        signifie une boîte plus grande que la palette elle-même).

    Déroulement détaillé pour chaque boîte :
        Étape 1 : cherche la première palette existante qui accepte la boîte.
                  « Accepte » = find_best_placement() retourne une position valide.
                  Si allow_multi_client=False, saute les palettes qui créeraient un mélange.

        Étape 2 : si aucune palette existante ne convient, crée une nouvelle palette
                  vide et tente d'y placer la boîte.
                  Si même la palette vide ne convient pas (boîte trop grande/lourde),
                  affiche un avertissement et ignore la boîte.
    """
    # Démarre avec les palettes éventuellement fournies (pour le repacking)
    pallets: List[Pallet] = list(initial_pallets) if initial_pallets else []
    pallet_counter = next_pallet_id

    unplaced: List[Box] = []   # boîtes impossibles à placer (très rare)

    for box in boxes:
        placed = False

        # ── Étape 1 : essaie chaque palette existante ────────────────────────
        best_pallet: Optional[Pallet] = None
        best_result: Optional[Tuple]  = None

        for pallet in pallets:
            # Filtre : si on interdit le multi-client et que la palette n'est
            # pas vide, on vérifie que tous ses colis appartiennent au même client.
            if not allow_multi_client and pallet.boxes:
                if any(pb.client_id != box.client_id for pb in pallet.boxes):
                    continue   # palette déjà occupée par un autre client → saute

            # Cherche la meilleure position sur cette palette
            result = find_best_placement(box, pallet, params)
            if result is None:
                continue    # aucune position valide sur cette palette → essaie la suivante

            # First Fit : on prend la PREMIÈRE palette qui accepte (pas la meilleure)
            best_result = result
            best_pallet = pallet
            break   # inutile de chercher plus loin

        if best_pallet is not None:
            # Place la boîte sur la palette trouvée
            x, y, z, orientation = best_result
            placed_box = make_placed_box(box, x, y, z, orientation)
            # Numéro de séquence = combien de boîtes étaient déjà là + 1
            placed_box.sequence = len(best_pallet.boxes) + 1
            best_pallet.boxes.append(placed_box)
            placed = True

        # ── Étape 2 : ouvre une nouvelle palette si aucune n'a convenu ─────
        if not placed:
            new_pallet = _make_new_pallet(pallet_counter, params)
            pallet_counter += 1

            result = find_best_placement(box, new_pallet, params)
            if result is not None:
                x, y, z, orientation = result
                placed_box = make_placed_box(box, x, y, z, orientation)
                placed_box.sequence = 1   # première boîte sur cette palette
                new_pallet.boxes.append(placed_box)
                pallets.append(new_pallet)
            else:
                # Cas exceptionnel : la boîte ne rentre même pas sur une palette vide
                # (dimensions ou poids incompatibles avec les paramètres configurés)
                unplaced.append(box)
                print(
                    f"[FFD] AVERTISSEMENT : boîte {box.id!r} impossible à placer "
                    f"(dims {box.length}×{box.width}×{box.height}, "
                    f"poids {box.weight}kg). Ignorée."
                )

    return pallets
