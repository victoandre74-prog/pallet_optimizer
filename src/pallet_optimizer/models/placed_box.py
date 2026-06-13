"""
Modèle de données : PlacedBox (boîte placée sur une palette).

Une PlacedBox est le résultat de la décision de l'optimiseur :
« cette boîte sera posée à cette position, dans cette orientation ».

Elle contient TOUTES les informations nécessaires pour la vérification des
contraintes (collisions, stabilité, poids) et pour la visualisation,
sans qu'on ait besoin de re-consulter la Box d'origine à chaque fois.

Relation avec Box :
    Box       →  données originales (dimensions non orientées, règles)
    PlacedBox →  résultat final (position 3D, dimensions après rotation, métadonnées copiées)

Le coin de référence (x, y, z) est le coin bas-gauche-arrière de la boîte,
ce qui correspond au coin (0, 0, 0) de la palette pour la première boîte posée au sol.
"""

from dataclasses import dataclass, field   # field : gère les valeurs calculées après __init__

from pallet_optimizer.models.orientation import Orientation


@dataclass
class PlacedBox:
    """
    Une boîte positionnée et orientée sur une palette.

    Système de coordonnées :
        (0, 0, 0) = coin bas-gauche-arrière de la palette
        x croissant → vers la droite (axe X = longueur palette)
        y croissant → vers l'avant   (axe Y = largeur  palette)
        z croissant → vers le haut   (axe Z = vertical)

    Les attributs (x, y, z) désignent le coin BAS-GAUCHE-ARRIÈRE de la boîte.
    Les attributs x_max, y_max, z_max sont automatiquement calculés.

    Attributs :
        box_id      : référence à l'identifiant de la Box d'origine
        x, y, z     : position du coin bas-gauche-arrière (en cm)
        orientation : orientation choisie par l'optimiseur
        length      : dimension occupée selon X après rotation (en cm)
        width       : dimension occupée selon Y après rotation (en cm)
        height      : dimension occupée selon Z après rotation (en cm)
        priority    : copié depuis Box pour accéder rapidement aux règles d'empilement
        weight      : poids en kg (copié depuis Box)
        client_id   : identifiant client (copié depuis Box, pour les stats et couleurs)
        stackable   : True si d'autres boîtes peuvent reposer sur celle-ci
                      dans l'orientation choisie
        sequence    : ordre de placement sur la palette (1 = première posée)
        x_max       : x + length (calculé automatiquement, jamais réassigné)
        y_max       : y + width  (calculé automatiquement)
        z_max       : z + height (calculé automatiquement)
    """

    # ── Identité et position ───────────────────────────────────────────────────
    box_id: str           # ex. "BOX-0042"
    x: float              # coin gauche en X (cm)
    y: float              # coin arrière en Y (cm)
    z: float              # coin bas en Z (cm)
    orientation: Orientation

    # ── Dimensions après rotation ──────────────────────────────────────────────
    # Ces valeurs sont déjà calculées à la création (via make_placed_box).
    # Les stocker ici évite de recalculer get_oriented_dimensions à chaque
    # vérification de collision — gain de performance important dans les boucles.
    length: float         # espace occupé en X (cm)
    width: float          # espace occupé en Y (cm)
    height: float         # espace occupé en Z (cm)

    # ── Métadonnées copiées depuis Box ─────────────────────────────────────────
    # On les copie ici pour ne pas avoir à parcourir une liste de Box originales
    # à chaque vérification de contrainte.
    priority: int         # 1 ou 2
    weight: float         # kg
    client_id: int        # entier client
    stackable: bool       # True → d'autres boîtes peuvent reposer dessus

    designation: str = ""   # libellé produit (optionnel)
    location: str = ""       # emplacement entrepôt (optionnel)

    # Ordre de placement dans la palette (1 = première boîte posée).
    # Initialisé à 0, assigné par le moteur de placement après création.
    sequence: int = 0

    # ── Coordonnées maximales pré-calculées ────────────────────────────────────
    # field(init=False) : ces attributs ne sont PAS passés au constructeur,
    # ils sont calculés automatiquement dans __post_init__ juste après.
    # Cela évite de les recalculer (x + length, etc.) à chaque vérification.
    x_max: float = field(init=False)
    y_max: float = field(init=False)
    z_max: float = field(init=False)

    def __post_init__(self):
        """
        Appelé automatiquement par la dataclass juste après __init__.
        Calcule les coordonnées maximales une seule fois.

        x_max = x + length  (bord droit de la boîte selon X)
        y_max = y + width   (bord avant de la boîte selon Y)
        z_max = z + height  (sommet de la boîte selon Z)
        """
        self.x_max = self.x + self.length
        self.y_max = self.y + self.width
        self.z_max = self.z + self.height

    # ── Propriétés géométriques ────────────────────────────────────────────────

    @property
    def base_area(self) -> float:
        """
        Aire de l'empreinte au sol de la boîte (en cm²).
        Utilisée pour calculer les ratios de support (combien de surface repose
        sur d'autres boîtes).
        """
        return self.length * self.width

    @property
    def volume(self) -> float:
        """Volume occupé par la boîte une fois placée (en cm³)."""
        return self.length * self.width * self.height

    def bounds(self):
        """
        Retourne la boîte englobante (Axis-Aligned Bounding Box) sous la forme :
            (x_min, x_max, y_min, y_max, z_min, z_max)

        Utile pour les tests d'intersection géométrique : deux boîtes se
        chevauchent si et seulement si leurs AABB se chevauchent dans les 3 axes.
        """
        return (
            self.x, self.x_max,
            self.y, self.y_max,
            self.z, self.z_max,
        )

    # ── Copie rapide ────────────────────────────────────────────────────────────

    def __copy__(self):
        """
        Copie superficielle optimisée pour le LNS.

        Tous les champs de PlacedBox sont des types immuables en Python :
            float, int, str, bool, Orientation (enum = singleton immuable).
        Une copie superficielle (shallow copy) est donc sémantiquement identique
        à une copie profonde (deep copy), sans le coût de récursion.

        x_max / y_max / z_max sont déjà présents dans __dict__ et copiés
        directement, sans repasser par __post_init__.

        Pourquoi est-ce important ?
            Le LNS réalise des milliers de copies de palettes par seconde.
            copy.copy() est ~100× plus rapide que copy.deepcopy() sur cet objet.
        """
        new = object.__new__(PlacedBox)    # crée l'objet sans appeler __init__
        new.__dict__.update(self.__dict__)  # copie tous les champs d'un coup
        return new

    def __deepcopy__(self, memo):
        """
        Copie profonde déléguée à __copy__ : aucun champ n'est un conteneur
        mutable, donc la copie superficielle est déjà une vraie copie indépendante.

        memo : dictionnaire interne de copy.deepcopy() pour gérer les références
               circulaires — on y enregistre le nouvel objet pour éviter les boucles.
        """
        new = self.__copy__()
        memo[id(self)] = new
        return new

    def __repr__(self) -> str:
        """Représentation lisible pour la console et le débogueur."""
        return (
            f"PlacedBox(id={self.box_id!r}, "
            f"pos=({self.x},{self.y},{self.z}), "
            f"dims={self.length}×{self.width}×{self.height}, "
            f"orient={self.orientation.value})"
        )
