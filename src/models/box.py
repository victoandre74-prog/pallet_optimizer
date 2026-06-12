"""
Modèle de données : Box (boîte non placée).

Une Box représente un colis physique à empiler sur une palette.
Elle contient ses dimensions physiques, son poids, son client d'appartenance
et les règles de manipulation qui lui sont propres.

Pourquoi séparer Box et PlacedBox ?
    - Box  : ce qu'on sait AVANT l'optimisation (dimensions originales, règles).
    - PlacedBox : le résultat APRÈS l'optimisation (position choisie, rotation appliquée).
    Ce découplage permet de relancer l'optimisation sans toucher aux données sources.
"""

from dataclasses import dataclass, field   # dataclass : génère automatiquement __init__, __repr__, etc.
from typing import List, Dict              # List, Dict : annotations de type (bonne pratique Python)

from models.orientation import Orientation, get_oriented_dimensions, ALL_ORIENTATIONS


@dataclass
class Box:
    """
    Représente une boîte rectangulaire à emballer sur une palette.

    C'est l'objet « source » — il décrit le colis tel qu'il est dans le monde réel,
    avant toute décision d'optimisation.

    Attributs principaux :
        id                   : identifiant unique de la boîte (chaîne de caractères)
        priority             : priorité de manipulation
                               1 = boîte lourde/encombrante, doit aller en bas
                               2 = boîte légère, peut aller plus haut (déposée à la main)
        length               : dimension selon X avant rotation (en cm)
        width                : dimension selon Y avant rotation (en cm)
        height               : dimension selon Z avant rotation (en cm)
        weight               : masse de la boîte (en kg)
        client_id            : identifiant du client auquel appartient cette boîte
                               Utilisé pour la stratégie mono-client (Phase 1/2)
        allowed_orientations : liste des orientations dans lesquelles la boîte
                               PEUT être placée (certains colis ont des contraintes,
                               ex. « ne pas mettre à l'envers »)
        stackable            : dictionnaire { orientation → bool }
                               True signifie qu'on PEUT poser d'autres boîtes
                               SUR CETTE boîte quand elle est dans cette orientation.
                               False = surface fragile, rien ne peut reposer dessus.
        designation          : libellé textuel du produit (optionnel, pour l'affichage)
        location             : emplacement d'origine dans l'entrepôt (optionnel)
    """

    # ── Champs obligatoires ────────────────────────────────────────────────────

    id: str             # identifiant unique, ex. "BOX-0042"
    priority: int       # 1 ou 2
    length: float       # en cm
    width: float        # en cm
    height: float       # en cm
    weight: float       # en kg
    client_id: int      # entier identifiant le client

    # ── Champs avec valeurs par défaut ─────────────────────────────────────────

    # Par défaut, toutes les orientations sont autorisées (la boîte peut être
    # tournée dans n'importe quelle direction).
    # field(default_factory=...) est nécessaire car les listes sont mutables :
    # Python interdit les listes directement comme valeur par défaut dans une dataclass.
    allowed_orientations: List[Orientation] = field(
        default_factory=lambda: list(ALL_ORIENTATIONS)
    )

    # Par défaut, la boîte est empilable dans toutes les orientations.
    # Le dictionnaire mappe chaque orientation sur True (empilable).
    stackable: Dict[Orientation, bool] = field(
        default_factory=lambda: {o: True for o in ALL_ORIENTATIONS}
    )

    designation: str = ""   # ex. "Boîte carton fragile"
    location: str = ""       # ex. "Allée A, Rayon 3"

    # ── Propriétés calculées ───────────────────────────────────────────────────

    @property
    def volume(self) -> float:
        """
        Retourne le volume de la boîte en cm³.

        Le volume est la même quelle que soit l'orientation : tourner une boîte
        ne change pas la quantité de matière qu'elle occupe.

        Exemple : boîte 10×20×5 → volume = 1000 cm³
        """
        return self.length * self.width * self.height

    def get_oriented_dims(self, orientation: Orientation):
        """
        Raccourci pour obtenir (placed_length, placed_width, placed_height)
        dans une orientation donnée.

        Délègue simplement au module orientation.py.
        Utile pour éviter d'importer get_oriented_dimensions partout.
        """
        return get_oriented_dimensions(
            self.length, self.width, self.height, orientation
        )

    def is_stackable_in(self, orientation: Orientation) -> bool:
        """
        Retourne True si d'autres boîtes peuvent être posées SUR CETTE boîte
        lorsqu'elle est placée dans l'orientation donnée.

        Le dictionnaire stackable peut être incomplet si la boîte a des
        orientations partiellement définies : .get() avec False en défaut
        est donc plus sûr qu'un accès direct par clé.

        Exemple d'usage :
            Si une bouteille ne peut pas supporter de poids quand elle est
            posée sur le côté (LHW), son dictionnaire contiendra
            { ..., Orientation.LHW: False, ... }
        """
        return self.stackable.get(orientation, False)

    def __repr__(self) -> str:
        """
        Représentation lisible de la boîte, affichée dans la console ou le débogueur.
        Le ! dans {self.id!r} force l'affichage avec les guillemets (repr).
        """
        return (
            f"Box(id={self.id!r}, priority={self.priority}, "
            f"dims={self.length}×{self.width}×{self.height}, "
            f"weight={self.weight}kg, client={self.client_id})"
        )
