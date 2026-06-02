"""
Règles d'empilement par priorité.

Ce module implémente les règles métier qui définissent QUELS types de boîtes
peuvent être posées SUR QUELS autres types.

Règles (issues du cahier des charges) :
    Boîte priorité 1 peut être posée sur :
        - Le sol de la palette (z == 0) → toujours autorisé
        - Une autre boîte de priorité 1 → toujours autorisé
        - N'importe quelle boîte dont la surface est marquée "stackable"
          (empilable) → autorisé

    Boîte priorité 2 peut être posée sur :
        - Une boîte de priorité 1 marquée "stackable" → autorisé
        - Une boîte de priorité 2 marquée "stackable" → autorisé
        - JAMAIS sur une boîte marquée non empilable (stackable = False)

    Dans tous les cas :
        « Posée sur » signifie que la face inférieure de la boîte du dessus
        est exactement en contact avec la face supérieure du support.

Distinction importante avec stability_check.py :
    Ce module vérifie les RÈGLES (qui peut aller sur qui ?).
    stability_check.py vérifie la PHYSIQUE (la surface de contact est-elle
    suffisante ? La colonne est-elle trop haute ?).

Tolerance flottante :
    FLOAT_TOL = 1e-6 cm. Deux coordonnées Z différant de moins de 1 nanomètre
    sont considérées comme identiques — nécessaire pour éviter les erreurs
    d'arrondi des calculs en virgule flottante.
"""

from typing import List

from models.placed_box import PlacedBox
from utils.geometry import xy_overlap

# Tolérance pour les comparaisons de coordonnées Z (en cm)
FLOAT_TOL = 1e-6


def _is_directly_below(candidate_z: float, pb: PlacedBox) -> bool:
    """
    Vérifie si le sommet de `pb` est exactement au niveau `candidate_z`.

    Si oui, `pb` est un support direct potentiel pour une boîte dont la base
    serait à l'altitude candidate_z.

    Paramètre candidate_z : altitude du bas de la boîte candidate (cm).
    """
    return abs(pb.z_max - candidate_z) <= FLOAT_TOL


def _xy_overlaps_with(
    x: float, y: float, length: float, width: float, pb: PlacedBox
) -> bool:
    """
    Vérifie si l'empreinte XY de la boîte candidate chevauche celle de `pb`.

    Utilise xy_overlap depuis utils/geometry.py (vérification stricte :
    le simple contact bord-à-bord ne constitue pas un chevauchement).
    """
    return xy_overlap(
        x, y, x + length, y + width,   # empreinte de la boîte candidate
        pb.x, pb.y, pb.x_max, pb.y_max  # empreinte pré-calculée de pb
    )


def get_supporting_boxes(
    x: float, y: float, z: float,
    length: float, width: float,
    placed_boxes: List[PlacedBox]
) -> List[PlacedBox]:
    """
    Retourne la liste de toutes les boîtes dont le sommet est exactement au
    niveau z ET dont l'empreinte XY chevauche celle de la boîte candidate.

    Ce sont les boîtes qui « porteraient physiquement » la boîte candidate
    si on la posait à cette position.

    Paramètres :
        x, y           : coin bas-gauche de la boîte candidate (cm)
        z              : altitude du bas de la boîte candidate (cm)
        length, width  : dimensions XY de la boîte candidate (cm)
        placed_boxes   : toutes les boîtes déjà sur la palette

    Retourne une liste (potentiellement vide si aucun support n'est trouvé).
    """
    return [
        pb for pb in placed_boxes
        if _is_directly_below(z, pb) and              # sommet de pb = bas de candidate
           _xy_overlaps_with(x, y, length, width, pb) # empreintes qui se chevauchent
    ]


def can_place_on_floor(priority: int) -> bool:
    """
    Toute boîte (priorité 1 ou 2) peut être posée directement sur le sol de la palette.

    Le sol est toujours stable et illimité en capacité de portance dans ce modèle.
    Cette fonction existe pour documenter explicitement cette décision métier.
    """
    return True   # aucune restriction pour le placement au sol


def check_stacking_rules(
    x: float, y: float, z: float,
    length: float, width: float,
    priority: int,
    placed_boxes: List[PlacedBox]
) -> bool:
    """
    Valide les règles d'empilement pour une boîte candidate.

    Retourne True si l'empilement est autorisé, False sinon.

    Logique complète :
        Si z == 0 (au sol) → toujours autorisé.

        Si z > 0 (en hauteur) → doit reposer sur au moins une boîte support.
            Pour priorité 1 :
                - Sur une autre P1 : toujours OK (P1 peut porter P1)
                - Sur une P2 stackable : OK
                - Sur une P2 non stackable : REFUSÉ
                → Toutes les boîtes supports dans l'empreinte doivent satisfaire
                  l'une de ces conditions.

            Pour priorité 2 :
                - Toutes les boîtes support doivent être stackable (peu importe P1 ou P2)
                - Si UNE SEULE n'est pas stackable → REFUSÉ

    Attention :
        Cette fonction vérifie uniquement la RÈGLE (qui peut aller sur qui).
        Elle ne vérifie PAS :
            - La surface de contact suffisante (→ check_support_ratio)
            - La stabilité de la colonne (→ check_stack_stability)
        Ces deux vérifications sont dans stability_check.py et appellées séparément.
    """
    # Cas au sol : toujours valide, aucun support requis
    if z <= FLOAT_TOL:
        return True

    # Trouve les boîtes qui supporteraient physiquement la boîte candidate
    supports = get_supporting_boxes(x, y, z, length, width, placed_boxes)

    # S'il n'y a aucun support et qu'on est en hauteur → physiquement impossible
    if not supports:
        return False

    if priority == 1:
        # Règle P1 : chaque boîte support doit être soit une P1, soit une P2 stackable.
        # Un seul support non stackable de type P2 invalide l'ensemble du placement.
        for sup in supports:
            if sup.priority == 1:
                continue            # P1 sur P1 : toujours permis → OK
            if sup.stackable:
                continue            # surface stackable : OK
            return False            # P2 non stackable : refus immédiat

        return True   # tous les supports sont valides

    elif priority == 2:
        # Règle P2 : CHAQUE boîte support doit être stackable (P1 ou P2 poco importe).
        # Un seul support non stackable → refus.
        for sup in supports:
            if not sup.stackable:
                return False   # surface fragile → refus immédiat

        return True   # tous les supports acceptent d'être empilés

    # Priorité inconnue (ne devrait pas arriver avec des données valides) → refus
    return False
