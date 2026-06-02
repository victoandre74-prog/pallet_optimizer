"""
Utilitaires partagés entre les passes LNS mono-client et multi-client.

Ce module contient deux fonctions auxiliaires utilisées dans lns_mono.py
et lns_multi.py, pour éviter la duplication de code.

Concept clé — Pool de boîtes :
    Dans le LNS, on « détruit » des palettes en retirant des boîtes placées
    (PlacedBox) pour les remettre dans un « pool ». Mais le moteur de placement
    travaille avec des objets Box (non placés). Il faut donc reconstruire des
    Box à partir des PlacedBox du pool — c'est le rôle de make_pool_box().
"""

from typing import List

from models.box import Box
from models.placed_box import PlacedBox
from models.pallet import Pallet


def make_pool_box(pb: PlacedBox, box_lookup: dict) -> Box:
    """
    Reconstruit un objet Box à partir d'un objet PlacedBox.

    Pourquoi est-ce nécessaire ?
        Le moteur de placement (find_best_placement, find_support_z, etc.) travaille
        avec des objets Box (dimensions non orientées, liste d'orientations autorisées).
        Mais après une destruction LNS, on n'a que des PlacedBox (position, orientation
        choisie, dimensions DÉJÀ orientées).
        → On doit reconstituer le Box d'origine pour que le moteur puisse choisir
          librement la meilleure orientation lors de la réparation.

    Stratégie :
        On utilise box_lookup (dict { box_id → Box original }) pour retrouver
        toutes les propriétés d'origine (dimensions non orientées, orientations
        autorisées, stackable par orientation).
        Si le Box original est introuvable (cas exceptionnel), on utilise les
        dimensions de la PlacedBox comme dimensions canoniques avec toutes les
        orientations.

    Paramètres :
        pb         : boîte placée extraite d'une palette détruite
        box_lookup : dictionnaire { box_id → Box original }

    Retourne un objet Box prêt à être replacé par le moteur de placement.

    Note sur la randomisation :
        La perturbation vient du mélange de l'ordre du pool (rng.shuffle),
        PAS de la restriction des orientations. Restreindre les orientations
        pourrait rendre certaines boîtes impossibles à placer (si leur seule
        orientation forcée dépasse les limites de la palette).
    """
    from models.orientation import ALL_ORIENTATIONS

    original = box_lookup.get(pb.box_id)   # cherche dans le dictionnaire d'origine

    if original is not None:
        # Cas normal : reconstruit depuis les données d'origine
        return Box(
            id=original.id,
            priority=original.priority,
            length=original.length,          # dimensions NON orientées (originales)
            width=original.width,
            height=original.height,
            weight=original.weight,
            client_id=original.client_id,
            allowed_orientations=list(original.allowed_orientations),  # copie de la liste
            stackable=dict(original.stackable),                        # copie du dict
        )
    else:
        # Cas exceptionnel : box_id pas trouvé dans le dictionnaire
        # (ne devrait pas arriver en usage normal — données cohérentes)
        # On utilise les dimensions placées (déjà orientées) comme dimensions canoniques
        return Box(
            id=pb.box_id,
            priority=pb.priority,
            length=pb.length,
            width=pb.width,
            height=pb.height,
            weight=pb.weight,
            client_id=pb.client_id,
            allowed_orientations=list(ALL_ORIENTATIONS),  # toutes orientations par défaut
            stackable={o: pb.stackable for o in ALL_ORIENTATIONS},
        )


def get_next_pallet_id(pallets: List[Pallet]) -> int:
    """
    Retourne le prochain ID de palette disponible.

    Formule : max(IDs existants) + 1.
    Si la liste est vide, retourne 1 (premier ID).

    Pourquoi est-ce utile ?
        Dans le LNS, on crée de nouvelles palettes pendant la réparation.
        Il faut leur attribuer des IDs uniques qui ne rentrent pas en conflit
        avec les palettes survivantes. Cette fonction garantit l'unicité.

    Paramètre :
        pallets : liste des palettes dont on veut éviter les IDs

    Retourne un entier, toujours ≥ 1.
    """
    if not pallets:
        return 1   # liste vide → commence à 1
    return max(p.id for p in pallets) + 1   # +1 pour être au-dessus du max existant
