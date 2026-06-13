"""
Vérifications de support et de stabilité pour les boîtes placées.

Ce module contient deux types de vérifications distinctes :

1. Ratio de support (check_support_ratio)
   Une boîte placée en hauteur (z > 0) doit avoir au moins X% de sa surface
   de base reposant sur d'autres boîtes. Sans support suffisant, la boîte
   « flotte dans le vide » → physiquement impossible.
   Exemple : si min_support_ratio = 0.80, alors 80% de la base doit être soutenue.

2. Stabilité de la pile (check_stack_stability)
   L'ensemble des boîtes superposées (une « colonne ») ne doit pas être trop
   haute par rapport à sa base. Une colonne haute et étroite risque de tomber.
   Condition : hauteur_colonne / base_min < stability_ratio
   Exemple : si stability_ratio = 7.0, une colonne de 70 cm de haut doit avoir
             une base d'au moins 10 cm dans sa direction la plus étroite.

Vocabulaire :
    - FLOAT_TOL : tolérance numérique. Deux valeurs distantes de moins de 1e-6
                  sont traitées comme égales (évite les erreurs d'arrondi flottant).
    - Support : surface de contact entre la boîte du dessus et celle du dessous.
    - Stack (colonne/pile) : ensemble de boîtes dont les empreintes XY se superposent.
"""

from typing import List

from pallet_optimizer.models.placed_box import PlacedBox
from pallet_optimizer.utils.geometry import xy_intersection_area, xy_overlap

FLOAT_TOL = 1e-6


# ── Ratio de support ───────────────────────────────────────────────────────────

def compute_support_area(
    x: float, y: float, z: float,
    length: float, width: float,
    placed_boxes: List[PlacedBox]
) -> float:
    """
    Calcule l'aire totale (en cm²) de la base de la boîte candidate qui est
    directement soutenue par des boîtes existantes.

    Principe :
        Pour chaque boîte déjà placée dont le sommet (z_max) se trouve exactement
        au niveau z (c'est-à-dire juste en dessous de la boîte candidate),
        on ajoute l'intersection de leurs empreintes XY.

    Paramètres :
        x, y, z        : position de la boîte candidate (cm)
        length, width  : dimensions XY de la boîte candidate (cm)
        placed_boxes   : liste des boîtes déjà sur la palette

    Retourne l'aire totale supportée (cm²). Peut être comparée à length × width
    pour calculer le ratio de support.
    """
    total_support = 0.0
    for pb in placed_boxes:
        # Vérifie que le sommet de pb est au même niveau que le bas de la boîte candidate
        # (tolérance pour éviter les problèmes d'arrondi flottant)
        if abs(pb.z_max - z) > FLOAT_TOL:
            continue   # pas en contact vertical → pas de support

        # Ajoute l'aire d'intersection XY entre la boîte candidate et pb
        # (= fraction de la base de la boîte candidate reposant sur pb)
        total_support += xy_intersection_area(
            x, y, x + length, y + width,           # empreinte de la boîte candidate
            pb.x, pb.y, pb.x_max, pb.y_max         # empreinte de pb (pré-calculée)
        )
    return total_support


def check_support_ratio(
    x: float, y: float, z: float,
    length: float, width: float,
    placed_boxes: List[PlacedBox],
    min_support_ratio: float
) -> bool:
    """
    Vérifie que la boîte candidate a un support suffisant.

    Règle :
        - Si la boîte est au sol (z ≈ 0), le sol de la palette la supporte
          entièrement → toujours valide.
        - Si elle est en hauteur (z > 0), au moins min_support_ratio de sa
          surface de base doit reposer sur d'autres boîtes.

    Paramètres :
        x, y, z            : position de la boîte candidate (cm)
        length, width      : dimensions XY de la boîte candidate (cm)
        placed_boxes       : boîtes déjà sur la palette
        min_support_ratio  : fraction minimale de la base qui doit être soutenue
                             (valeur typique : 0.80 = 80%)

    Retourne True si le support est suffisant, False sinon.
    """
    # Cas spécial : la boîte repose directement sur le sol → support garanti
    if z <= FLOAT_TOL:
        return True

    base_area = length * width
    if base_area <= 0:
        return False    # boîte dégénérée (dimension nulle) → rejeté

    # Calcule l'aire effectivement supportée et compare au minimum requis
    support_area  = compute_support_area(x, y, z, length, width, placed_boxes)
    support_ratio = support_area / base_area

    return support_ratio >= min_support_ratio


# ── Stabilité de la pile ───────────────────────────────────────────────────────

def _get_xy_connected_stack(
    new_box_x: float, new_box_y: float,
    new_box_x_max: float, new_box_y_max: float,
    placed_boxes: List[PlacedBox]
) -> List[PlacedBox]:
    """
    Retourne toutes les boîtes déjà placées dont l'empreinte XY chevauche
    celle de la boîte candidate.

    Ces boîtes, combinées avec la boîte candidate, forment la « pile » (stack)
    qui sera analysée pour la stabilité.

    Pourquoi l'empreinte XY suffit-elle ?
        En 3D, deux boîtes empilées verticalement ont obligatoirement leurs
        empreintes XY qui se chevauchent (au moins partiellement). Toutes les
        boîtes de la même colonne peuvent donc être identifiées par leur
        chevauchement XY avec la nouvelle boîte.
    """
    return [
        pb for pb in placed_boxes
        if xy_overlap(
            new_box_x, new_box_y, new_box_x_max, new_box_y_max,
            pb.x, pb.y, pb.x_max, pb.y_max
        )
    ]


def check_stack_stability(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox],
    stability_ratio: float
) -> bool:
    """
    Vérifie que la pile (colonne de boîtes) reste stable après l'ajout de
    la boîte candidate.

    Principe physique :
        Une pile est stable si elle n'est pas trop haute par rapport à sa base.
        Le critère utilisé est :
            hauteur_pile / min(largeur_base_X, largeur_base_Y) < stability_ratio

        En pratique, stability_ratio = 7.0 signifie qu'une pile de 70 cm de haut
        doit avoir une base d'au moins 10 cm dans sa direction la plus étroite.

    Méthode :
        1. Trouve toutes les boîtes dont l'empreinte XY chevauche la nouvelle boîte
           (= la pile qui inclura la nouvelle boîte).
        2. Calcule la boîte englobante XY de cette pile (pour avoir la largeur de base).
        3. Calcule la hauteur totale de la pile (du bas de la plus basse au sommet
           de la plus haute, en incluant la nouvelle boîte).
        4. Vérifie le ratio hauteur / base_min.

    Paramètres :
        x, y, z             : position de la boîte candidate (cm)
        length, width, height : dimensions de la boîte candidate (cm)
        placed_boxes        : boîtes déjà sur la palette
        stability_ratio     : ratio maximal autorisé (ex. 7.0)

    Retourne True si la pile reste stable, False si elle devient trop haute/étroite.

    Note : cette vérification n'est appliquée qu'aux boîtes de priorité 1
    (les P2 sont posées à la main par un opérateur, pas empilées automatiquement).
    """
    # Coordonnées maximales de la boîte candidate (pré-calculées une seule fois)
    x_max = x + length
    y_max = y + width

    # Collecte toutes les boîtes de la même « colonne » (chevauchement XY)
    stack = _get_xy_connected_stack(x, y, x_max, y_max, placed_boxes)

    # Rassemble tous les z de début et de fin, y compris la nouvelle boîte
    all_z_tops = [pb.z_max for pb in stack] + [z + height]
    all_z_bots = [pb.z for pb in stack]     + [z]

    # Hauteur de la pile = du point le plus bas au point le plus haut
    stack_height = max(all_z_tops) - min(all_z_bots)

    # Boîte englobante XY de toute la pile (union de toutes les empreintes)
    all_xs = ([pb.x for pb in stack] + [pb.x_max for pb in stack] +
              [x, x_max])
    all_ys = ([pb.y for pb in stack] + [pb.y_max for pb in stack] +
              [y, y_max])

    stack_base_x = max(all_xs) - min(all_xs)   # largeur de la base selon X
    stack_base_y = max(all_ys) - min(all_ys)   # largeur de la base selon Y

    # Évite la division par zéro pour les colonnes dégénérées (1 point)
    min_base = min(stack_base_x, stack_base_y)
    if min_base <= 0:
        return True     # colonne ponctuelle → toujours stable (cas théorique)

    # Critère de stabilité : ratio < seuil autorisé
    return (stack_height / min_base) < stability_ratio
