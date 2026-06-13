"""
Heuristiques de tri des boîtes avant placement.

Pourquoi trier avant de placer ?
    L'algorithme FFD (First Fit Decreasing) doit recevoir les boîtes dans un
    ordre judicieux. En général, les objets les plus difficiles à caser doivent
    être traités en premier, quand les palettes sont encore vides et offrent
    le plus de liberté.

Ordre de tri appliqué (du plus prioritaire au moins prioritaire) :
    1. Priorité  — croissante  : P1 avant P2
       → Les boîtes lourdes/encombrantes doivent toujours être posées en premier
         (les P2 reposent parfois dessus, donc elles ne peuvent pas arriver avant)
    2. Volume    — décroissant : grandes boîtes en premier
       → Plus une boîte est grande, plus elle est difficile à caser.
         L'insérer en premier garantit qu'elle trouvera de la place.
    3. Poids     — décroissant : boîtes lourdes en premier (parmi les mêmes volumes)
       → Les boîtes lourdes doivent aller en bas (stabilité). En les plaçant
         tôt, le moteur les posera naturellement au bas de la palette.

Concept Python clé — tri multi-critère avec une clé lambda :
    sorted(items, key=lambda b: (b.priority, -b.volume, -b.weight))
    Python trie d'abord par priority (croissant), puis par -volume (donc
    volume décroissant), puis par -weight (poids décroissant).
    Le signe moins (-) inverse l'ordre naturel (croissant → décroissant).
"""

from typing import List

from pallet_optimizer.models.box import Box


def sort_boxes_for_packing(boxes: List[Box]) -> List[Box]:
    """
    Retourne une nouvelle liste triée selon l'heuristique de placement.

    Critères de tri (du plus au moins prioritaire) :
        1. priorité croissante  (P1 avant P2)
        2. volume décroissant   (grandes boîtes d'abord)
        3. poids décroissant    (boîtes lourdes d'abord à volumes égaux)

    La liste originale n'est PAS modifiée (sorted() retourne une nouvelle liste).

    Paramètre :
        boxes : liste de Box à trier (peut contenir plusieurs clients)

    Retourne une nouvelle liste triée.
    """
    return sorted(
        boxes,
        key=lambda b: (b.priority, -b.volume, -b.weight)
        # b.priority   : tri croissant (1 avant 2)
        # -b.volume    : tri décroissant (grand avant petit)
        # -b.weight    : tri décroissant (lourd avant léger)
    )


def sort_boxes_by_client(boxes: List[Box]) -> dict:
    """
    Regroupe les boîtes par client_id et trie chaque groupe.

    Retourne un dictionnaire : { client_id → [Box trié, ...] }

    Chaque liste de boîtes par client est triée selon sort_boxes_for_packing.
    Ce regroupement est utilisé en Phase 1 (packing mono-client) : chaque client
    est traité indépendamment sur son propre ensemble de palettes.

    Paramètre :
        boxes : liste de toutes les boîtes (tous clients confondus)

    Retourne :
        dict { client_id (int) → list[Box] trié }

    Exemple :
        Si boxes contient des boîtes pour les clients 1 et 3, le résultat sera :
        { 1: [boîtes_client1_triées], 3: [boîtes_client3_triées] }

    Concept Python — setdefault :
        groups.setdefault(key, []).append(val)
        Crée une liste vide si la clé n'existe pas encore, puis ajoute val.
        Équivalent à :
            if key not in groups: groups[key] = []
            groups[key].append(val)
    """
    groups: dict = {}
    for box in boxes:
        # Ajoute la boîte dans le groupe de son client
        groups.setdefault(box.client_id, []).append(box)

    # Trie chaque groupe indépendamment avec l'heuristique de placement
    return {
        cid: sort_boxes_for_packing(group)
        for cid, group in groups.items()
        # dict comprehension : crée un nouveau dict avec les groupes triés
    }
