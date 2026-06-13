"""
Détection de collisions 3D entre boîtes placées.

Ce module répond à la question fondamentale du rangement 3D :
    « Est-ce qu'une boîte qu'on veut placer à cette position EMPIÈTE sur
      une boîte déjà en place, ou sort-elle des limites de la palette ? »

Si la réponse est « oui » à l'une de ces deux questions, le placement est invalide.

Toutes les boîtes et la palette sont traitées comme des AABB (Axis-Aligned
Bounding Box) : des cuboïdes dont les faces sont parfaitement alignées sur
les axes X, Y, Z. Cela rend les calculs de collision très simples et rapides.

Vocabulaire important :
    - Collision : deux objets occupent le même espace → interdit
    - Contact (touching) : deux faces se touchent exactement sans se pénétrer → autorisé
"""

from typing import List

from pallet_optimizer.models.placed_box import PlacedBox
from pallet_optimizer.models.pallet import Pallet


def is_within_pallet(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    pallet: Pallet
) -> bool:
    """
    Vérifie que la boîte candidate tient entièrement dans les limites de la palette.

    Une boîte est définie par son coin bas-gauche-arrière (x, y, z) et ses
    dimensions (length, width, height). Elle doit satisfaire :
        - La coordonnée de départ est ≥ 0 (pas hors de la palette à gauche/derrière/bas)
        - La coordonnée de fin est ≤ la dimension maximale de la palette

    Conditions vérifiées :
        x ≥ 0  et  x + length  ≤ pallet.length   (ne dépasse pas à droite)
        y ≥ 0  et  y + width   ≤ pallet.width     (ne dépasse pas devant)
        z ≥ 0  et  z + height  ≤ pallet.max_height (ne dépasse pas la hauteur max)

    Paramètres :
        x, y, z             : coin bas-gauche-arrière de la boîte candidate (cm)
        length, width, height : dimensions de la boîte candidate (cm)
        pallet              : palette avec ses limites physiques
    """
    return (
        x >= 0 and x + length  <= pallet.length    and
        y >= 0 and y + width   <= pallet.width      and
        z >= 0 and z + height  <= pallet.max_height
    )


def collides_with_any(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox]
) -> bool:
    """
    Vérifie si la boîte candidate entre en collision avec l'une des boîtes
    déjà placées sur la palette.

    Utilise une intersection 3D stricte : deux boîtes qui se touchent sur
    une face seulement NE sont PAS considérées en collision.

    Note de performance :
        La vérification boxes_intersect_3d() est ici réécrite en ligne (inline)
        pour éviter l'overhead des appels de fonction Python. Avec des centaines
        de milliers d'appels dans une optimisation, cet overhead deviendrait
        significatif. pb.x_max / pb.y_max / pb.z_max sont des attributs
        pré-calculés sur PlacedBox (évite de recalculer x + length à chaque fois).

    Paramètres :
        x, y, z             : position de la boîte candidate (cm)
        length, width, height : dimensions de la boîte candidate (cm)
        placed_boxes        : liste des boîtes déjà sur la palette

    Retourne True si au moins une collision est détectée.
    """
    # Pré-calcule les coordonnées maximales de la boîte candidate
    x_max = x + length
    y_max = y + width
    z_max = z + height

    for pb in placed_boxes:
        # Intersection 3D inline : les 3 axes doivent se chevaucher simultanément.
        # « a < b_max and b < a_max » est la condition de chevauchement strict
        # (exclut le simple contact bord-à-bord).
        if (x  < pb.x_max and pb.x < x_max and
                y  < pb.y_max and pb.y < y_max and
                z  < pb.z_max and pb.z < z_max):
            return True   # collision trouvée → arrêt immédiat
    return False


def is_placement_geometrically_valid(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    pallet: Pallet
) -> bool:
    """
    Vérification géométrique combinée : la boîte candidate est-elle dans les
    limites de la palette ET sans collision avec les boîtes existantes ?

    C'est la première vérification effectuée lors d'un essai de placement
    (avant les vérifications plus coûteuses : poids, règles d'empilement,
    stabilité). Si cette vérification échoue, les suivantes ne sont pas exécutées.

    Paramètres :
        x, y, z             : position candidate (cm)
        length, width, height : dimensions de la boîte orientée (cm)
        pallet              : palette cible (limites + boîtes existantes)

    Retourne True si le placement est géométriquement valide.
    """
    # Étape 1 : la boîte tient-elle dans la palette ?
    if not is_within_pallet(x, y, z, length, width, height, pallet):
        return False

    # Étape 2 : la boîte entre-t-elle en collision avec une boîte existante ?
    if collides_with_any(x, y, z, length, width, height, pallet.boxes):
        return False

    return True
