"""
Définit les 6 orientations possibles d'une boîte rectangulaire en 3D.

Une boîte est définie à l'origine par ses dimensions (L, W, H) :
    - L = longueur (length) → axe X de la palette
    - W = largeur  (width)  → axe Y de la palette
    - H = hauteur  (height) → axe Z, vertical

Quand on « tourne » une boîte, on permute ces trois axes.
Avec 3 axes, il existe exactement 3! = 6 permutations possibles.
Chaque permutation correspond à une orientation physique distincte
(par ex. poser la boîte sur sa tranche, sur sa face, etc.).

Système de coordonnées de la palette :
    axe X → longueur de la palette (de gauche à droite)
    axe Y → largeur  de la palette (de l'avant vers l'arrière)
    axe Z → vertical (du bas vers le haut)
"""

from enum import Enum        # Enum : type spécial pour lister des constantes nommées
from typing import Tuple     # Tuple : type d'annotation pour une valeur (a, b, c)


class Orientation(Enum):
    """
    Énumération des 6 orientations physiques d'une boîte.

    Chaque valeur est composée de 3 lettres qui indiquent QUELLE dimension
    originale de la boîte occupe chaque axe placé (longueur / largeur / hauteur).

    Convention de nommage — les 3 lettres signifient :
        1ère lettre → dimension originale qui devient la longueur placée (axe X)
        2ème lettre → dimension originale qui devient la largeur  placée (axe Y)
        3ème lettre → dimension originale qui devient la hauteur  placée (axe Z)

    Exemple concret :
        Orientation WLH :
            placed_length = original W  (la largeur d'origine occupe l'axe X)
            placed_width  = original L  (la longueur d'origine occupe l'axe Y)
            placed_height = original H  (la hauteur d'origine reste verticale)

        Intuition physique : la boîte a été tournée de 90° autour de l'axe Z,
        donc ce qui était sa longueur pointe maintenant vers l'axe Y de la palette.
    """

    LWH = "LWH"   # Pas de rotation : (L, W, H) → position naturelle
    LHW = "LHW"   # Rotation 90° autour de X : la boîte est couchée sur le côté
    WLH = "WLH"   # Rotation 90° autour de Z : la boîte est pivotée à plat
    WHL = "WHL"   # Combinaison : la largeur d'origine devient la longueur
    HLW = "HLW"   # Combinaison : la hauteur d'origine devient la longueur
    HWL = "HWL"   # Combinaison : la hauteur d'origine devient la longueur (autre axe)


# Liste pratique de toutes les orientations possibles, utilisée comme valeur
# par défaut dans Box (toutes orientations autorisées si rien n'est précisé).
ALL_ORIENTATIONS: list = list(Orientation)


def get_oriented_dimensions(
    length: float,
    width: float,
    height: float,
    orientation: Orientation
) -> Tuple[float, float, float]:
    """
    Calcule les dimensions réelles d'une boîte une fois placée dans
    une orientation donnée.

    Entrées :
        length      : dimension originale de la boîte selon X (avant rotation), en cm
        width       : dimension originale de la boîte selon Y (avant rotation), en cm
        height      : dimension originale de la boîte selon Z (avant rotation), en cm
        orientation : l'orientation choisie (une valeur de l'enum Orientation)

    Sortie :
        Un tuple (placed_length, placed_width, placed_height) en cm.
        Ces valeurs représentent l'espace réellement occupé sur la palette
        une fois la boîte posée dans cette orientation.

    Exemple :
        Boîte de dimensions L=100, W=50, H=30.
        En orientation HLW : placed_length=30, placed_width=100, placed_height=50.
        La boîte est posée « debout sur sa tranche » et occupe 30 cm en X,
        100 cm en Y et 50 cm en hauteur.
    """
    # Dictionnaire : orientation → (placed_length, placed_width, placed_height)
    # Chaque ligne relit la permutation des axes selon la convention de nommage.
    mapping = {
        Orientation.LWH: (length, width,  height),   # naturel
        Orientation.LHW: (length, height, width),    # H et W échangés
        Orientation.WLH: (width,  length, height),   # L et W échangés
        Orientation.WHL: (width,  height, length),   # permutation cyclique
        Orientation.HLW: (height, length, width),    # permutation cyclique
        Orientation.HWL: (height, width,  length),   # H devient longueur
    }
    return mapping[orientation]
