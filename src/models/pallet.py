"""
Modèle de données : Pallet (palette).

Une palette est une surface de transport sur laquelle on empile des boîtes.
Ce fichier contient :
    - La classe Pallet : conteneur principal avec statistiques utiles
    - Des fonctions d'analyse de stabilité (niveau module) utilisées par Pallet

Notions clés pour un débutant :
    - Pallet.volumetric_fill_ratio : quel pourcentage du volume disponible est utilisé ?
      Plus ce ratio est proche de 1.0 (= 100%), plus la palette est bien remplie.
    - Pallet.worst_stability_ratio : indicateur de stabilité des piles de boîtes P1.
      Un ratio élevé indique une pile haute et étroite (risque de renversement).
"""

import copy
from dataclasses import dataclass, field
from typing import List, Set

from models.placed_box import PlacedBox

# Tolérance flottante : deux coordonnées séparées de moins d'1 nanomètre
# sont considérées comme égales. Évite les erreurs d'arrondi flottant.
FLOAT_TOL = 1e-6


@dataclass
class Pallet:
    """
    Palette de livraison avec toutes ses boîtes empilées.

    Attributs :
        id           : numéro unique de la palette
        length       : dimension de la palette selon X (en cm)
        width        : dimension de la palette selon Y (en cm)
        max_height   : hauteur maximale d'empilement autorisée (en cm)
        max_weight   : masse totale maximale autorisée (en kg)
        boxes        : liste des boîtes actuellement placées sur cette palette
    """

    id: int
    length: float       # cm, axe X
    width: float        # cm, axe Y
    max_height: float   # cm, limite verticale
    max_weight: float   # kg, limite de poids
    boxes: List[PlacedBox] = field(default_factory=list)   # vide par défaut

    # ── Poids ──────────────────────────────────────────────────────────────────

    @property
    def total_weight(self) -> float:
        """
        Somme des poids de toutes les boîtes placées (en kg).

        Utilise une expression génératrice (generator expression) :
            sum(pb.weight for pb in self.boxes)
        C'est l'équivalent pythonique de :
            total = 0
            for pb in self.boxes: total += pb.weight
        """
        return sum(pb.weight for pb in self.boxes)

    @property
    def remaining_weight(self) -> float:
        """Capacité de poids restante (en kg) avant d'atteindre la limite."""
        return self.max_weight - self.total_weight

    # ── Géométrie ──────────────────────────────────────────────────────────────

    @property
    def pallet_volume(self) -> float:
        """Volume utilisable total de la palette (en cm³)."""
        return self.length * self.width * self.max_height

    @property
    def used_volume(self) -> float:
        """Volume total occupé par les boîtes placées (en cm³)."""
        return sum(pb.volume for pb in self.boxes)

    @property
    def volumetric_fill_ratio(self) -> float:
        """
        Taux de remplissage volumétrique de la palette (entre 0.0 et 1.0).

        Formule : volume_utilisé / volume_total_palette

        Exemple : 0.72 signifie que 72% du volume de la palette est occupé.
        Un taux de 1.0 (100%) est impossible en pratique à cause des espaces
        résiduels entre les boîtes de formes différentes.

        Retourne 0.0 si la palette a un volume nul (palette invalide).
        """
        if self.pallet_volume == 0:
            return 0.0
        return self.used_volume / self.pallet_volume

    @property
    def current_height(self) -> float:
        """
        Hauteur actuelle de la palette : z_max de la boîte la plus haute.
        Retourne 0.0 si la palette est vide.

        Utilise max() avec une expression génératrice pour trouver le sommet
        le plus haut parmi toutes les boîtes (pb.z_max = z + height).
        """
        if not self.boxes:
            return 0.0
        return max(pb.z_max for pb in self.boxes)

    # ── Informations client ─────────────────────────────────────────────────────

    @property
    def client_ids(self) -> Set[int]:
        """
        Ensemble (set) des identifiants clients présents sur cette palette.

        Un set ne contient pas de doublons : si 10 boîtes appartiennent au
        client 3, le set contiendra juste {3}.
        """
        return {pb.client_id for pb in self.boxes}

    @property
    def is_multi_client(self) -> bool:
        """
        True si la palette contient des boîtes de plusieurs clients différents.

        Palette multi-client = les boîtes seront livrées à plusieurs destinataires
        depuis la même palette, ce qui peut compliquer la livraison.
        """
        return len(self.client_ids) > 1

    # ── Comptages par priorité ─────────────────────────────────────────────────

    @property
    def priority1_count(self) -> int:
        """Nombre de boîtes de priorité 1 (lourdes, placées en bas)."""
        return sum(1 for pb in self.boxes if pb.priority == 1)

    @property
    def priority2_count(self) -> int:
        """Nombre de boîtes de priorité 2 (légères, déposées à la main en haut)."""
        return sum(1 for pb in self.boxes if pb.priority == 2)

    # ── Indicateur de stabilité (analyse post-placement, pas une contrainte) ───

    @property
    def worst_stability_ratio(self) -> float:
        """
        Ratio de stabilité le plus défavorable parmi toutes les sous-colonnes P1.

        Plus cette valeur est élevée, moins la pile est stable.
        C'est un indicateur visuel/analytique, pas une contrainte de placement
        (les contraintes sont dans stability_check.py).

        Le calcul complet est délégué à _compute_worst_stability_ratio
        (définie en bas de ce fichier) pour ne pas encombrer la classe.

        Référence : une pile de livres posée debout a un ratio élevé
                    (hauteur >> largeur de la base → instable).
                    Une caisse basse et large a un ratio faible → stable.
        """
        return _compute_worst_stability_ratio(self.boxes)

    # ── Utilitaires ─────────────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        """Retourne True si la palette ne contient aucune boîte."""
        return len(self.boxes) == 0

    # ── Copie profonde optimisée ─────────────────────────────────────────────────

    def __deepcopy__(self, memo):
        """
        Copie profonde optimisée pour le LNS (Large Neighbourhood Search).

        Dans le LNS, on copie des centaines de palettes par seconde pour tester
        des solutions candidates. La copie générique de Python (copy.deepcopy)
        traverse récursivement tout le graphe d'objets — très lent.

        Optimisation appliquée ici :
            - Les champs scalaires (id, length, width, …) sont immuables en Python :
              les entiers et flottants ne peuvent pas être modifiés, donc les partager
              par référence est sans danger.
            - Seule la liste `boxes` est réellement dupliquée.
            - Chaque PlacedBox est copiée avec copy.copy() (appelle PlacedBox.__copy__),
              qui est ~100× plus rapide que copy.deepcopy() sur cet objet.

        memo : dictionnaire interne de deepcopy() pour éviter les copies infinies
               en cas de références circulaires.
        """
        new = object.__new__(Pallet)     # crée la Pallet sans appeler __init__
        memo[id(self)] = new             # enregistre dans memo pour les références circulaires
        new.id         = self.id
        new.length     = self.length
        new.width      = self.width
        new.max_height = self.max_height
        new.max_weight = self.max_weight
        # Duplique la liste ET chaque PlacedBox (copy.copy utilise PlacedBox.__copy__)
        new.boxes      = [copy.copy(pb) for pb in self.boxes]
        return new

    def __repr__(self) -> str:
        """Représentation lisible pour la console et le débogueur."""
        return (
            f"Pallet(id={self.id}, boxes={len(self.boxes)}, "
            f"fill={self.volumetric_fill_ratio:.1%}, "
            f"weight={self.total_weight:.1f}kg, "
            f"clients={self.client_ids})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Fonctions d'analyse de stabilité (niveau module)
# Utilisées par Pallet.worst_stability_ratio
# ══════════════════════════════════════════════════════════════════════════════

# Ratio de support minimal utilisé pour connecter deux boîtes dans la même pile.
# La valeur est la même que dans OptimizationParameters (cohérence par défaut).
_MIN_SUPPORT_RATIO = 0.75


def _support_ratio(upper: PlacedBox, lower: PlacedBox) -> float:
    """
    Calcule la fraction de la base de `upper` qui repose directement sur `lower`.

    Retourne un nombre entre 0.0 (pas de contact) et 1.0 (support complet).

    Vérifie d'abord que le sommet de `lower` est bien au niveau du bas de `upper`
    (à la tolérance flottante près). Si oui, calcule l'intersection XY des deux
    empreintes au sol et la divise par la surface de la base de `upper`.
    """
    # Vérifie que les boîtes sont en contact vertical (lower est juste en dessous)
    if abs(upper.z - lower.z_max) > FLOAT_TOL:
        return 0.0   # pas de contact vertical → pas de support

    # Calcule le chevauchement en X et en Y des deux empreintes
    x_ov = max(0.0, min(upper.x_max, lower.x_max) - max(upper.x, lower.x))
    y_ov = max(0.0, min(upper.y_max, lower.y_max) - max(upper.y, lower.y))

    base = upper.length * upper.width
    if base <= 0:
        return 0.0   # boîte dégénérée (surface nulle)

    # Ratio = aire d'intersection / aire totale de la base de upper
    return (x_ov * y_ov) / base


def _build_support_stacks(p1_boxes: List[PlacedBox]) -> List[List[PlacedBox]]:
    """
    Regroupe les boîtes P1 en piles physiquement connectées.

    Deux boîtes P1 sont « connectées dans une pile » si l'une repose sur l'autre
    avec un ratio de support ≥ _MIN_SUPPORT_RATIO.
    La fermeture transitive de ces relations donne des composantes connexes :
    ce sont les piles physiques réelles.

    Algorithme :
        1. Construire un graphe d'adjacence : arête entre i et j si i repose sur j.
        2. Parcours BFS (Breadth-First Search) pour trouver les composantes connexes.
           BFS = exploration en largeur, niveau par niveau (comme les ronds dans l'eau).

    Retourne une liste de listes : chaque sous-liste est une pile physique.
    """
    n = len(p1_boxes)
    # adj[i] = ensemble des indices j de boîtes connectées à i
    adj: List[Set[int]] = [set() for _ in range(n)]

    # Construction du graphe d'adjacence (paires de boîtes en contact)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = p1_boxes[i], p1_boxes[j]
            # Connexion si l'une repose sur l'autre (dans un sens ou dans l'autre)
            if (_support_ratio(b, a) >= _MIN_SUPPORT_RATIO
                    or _support_ratio(a, b) >= _MIN_SUPPORT_RATIO):
                adj[i].add(j)
                adj[j].add(i)

    # BFS pour trouver les composantes connexes (= piles physiques)
    visited = [False] * n
    stacks: List[List[PlacedBox]] = []

    for start in range(n):
        if visited[start]:
            continue   # boîte déjà assignée à une pile

        # Parcours BFS depuis cette boîte non visitée
        component: List[int] = []
        queue = [start]
        visited[start] = True

        while queue:
            node = queue.pop(0)     # prend le premier élément de la file
            component.append(node)
            for nb in adj[node]:   # visite les voisins non encore visités
                if not visited[nb]:
                    visited[nb] = True
                    queue.append(nb)

        stacks.append([p1_boxes[i] for i in component])

    return stacks


def _lateral_braced_height(
    bb_x: float, bb_y: float, bb_x_max: float, bb_y_max: float,
    bb_z: float, bb_z_max: float,
    exclude_ids: set,
    all_boxes: List[PlacedBox],
    axis: str,
) -> float:
    """
    Calcule la hauteur Z couverte par des boîtes P1 extérieures qui « étayent »
    (bracing) la boîte englobante selon l'axe donné.

    Quand une boîte P1 est en contact latéral avec une pile, elle la stabilise
    mécaniquement sur une partie de sa hauteur. Cette fonction mesure la hauteur
    effective de cet étaiement pour la soustraire du ratio de stabilité.

    Paramètres :
        bb_x, bb_y, bb_x_max, bb_y_max : boîte englobante de la pile (XY)
        bb_z, bb_z_max                  : hauteur de la pile (Z)
        exclude_ids                      : IDs Python des boîtes de la pile
                                           (on cherche des boîtes EXTÉRIEURES)
        all_boxes                        : toutes les boîtes de la palette
        axis                             : 'x' ou 'y', axe selon lequel on
                                           cherche le contact latéral

    Retourne la hauteur totale étayée (union des intervalles Z en contact).
    """
    intervals = []

    for pb in all_boxes:
        # On ne considère que les boîtes P1 extérieures à la pile
        if pb.priority != 1 or id(pb) in exclude_ids:
            continue

        touching = False
        if axis == "x":
            # Contact sur la face gauche ou droite de la boîte englobante
            if abs(pb.x_max - bb_x) <= FLOAT_TOL or abs(bb_x_max - pb.x) <= FLOAT_TOL:
                if min(bb_y_max, pb.y_max) - max(bb_y, pb.y) > FLOAT_TOL:
                    touching = True
        else:
            # Contact sur la face avant ou arrière
            if abs(pb.y_max - bb_y) <= FLOAT_TOL or abs(bb_y_max - pb.y) <= FLOAT_TOL:
                if min(bb_x_max, pb.x_max) - max(bb_x, pb.x) > FLOAT_TOL:
                    touching = True

        if touching:
            # Intersection de hauteur Z entre la boîte d'étayement et la pile
            oz_lo = max(bb_z, pb.z)
            oz_hi = min(bb_z_max, pb.z_max)
            if oz_hi > oz_lo + FLOAT_TOL:
                intervals.append((oz_lo, oz_hi))

    if not intervals:
        return 0.0

    # Fusionne les intervalles qui se chevauchent pour éviter de compter deux fois
    intervals.sort()
    merged = [list(intervals[0])]
    for lo, hi in intervals[1:]:
        if lo <= merged[-1][1] + FLOAT_TOL:
            merged[-1][1] = max(merged[-1][1], hi)   # étend le dernier intervalle
        else:
            merged.append([lo, hi])

    # Somme des longueurs des intervalles fusionnés = hauteur totale étayée
    return sum(hi - lo for lo, hi in merged)


def _effective_ratio(
    col_height: float, narrow_dim: float, narrow_axis: str,
    bb_x: float, bb_y: float, bb_x_max: float, bb_y_max: float,
    bb_z: float, bb_z_max: float,
    exclude_ids: set, all_boxes: List[PlacedBox],
) -> float:
    """
    Calcule le ratio de stabilité effectif après soustraction de l'étaiement latéral.

    Formule :
        ratio_effectif = (hauteur_pile - hauteur_étayée) / dimension_étroite

    Plus ce ratio est petit, plus la pile est stable.
    Si narrow_dim <= 0 ou col_height <= 0, retourne 0.0 (cas dégénéré).
    """
    if narrow_dim <= 0 or col_height <= 0:
        return 0.0

    # Hauteur de la pile étayée par des boîtes voisines
    braced = _lateral_braced_height(
        bb_x, bb_y, bb_x_max, bb_y_max, bb_z, bb_z_max,
        exclude_ids, all_boxes, narrow_axis,
    )

    # Hauteur effective = hauteur totale moins la partie supportée latéralement
    effective = col_height - braced
    return max(0.0, effective / narrow_dim)


def _compute_worst_stability_ratio(placed_boxes: List[PlacedBox]) -> float:
    """
    Retourne le ratio de stabilité le plus défavorable parmi toutes les piles P1
    de la palette.

    Méthode :
        1. Ne considère que les boîtes de priorité 1.
        2. Regroupe ces boîtes en piles physiques connectées par support.
        3. Pour chaque pile, calcule plusieurs ratios candidats :
           a. Ratio de la boîte englobante complète (selon X et selon Y).
           b. Ratio de chaque sous-colonne : en partant d'une boîte anchor,
              on ne garde que les boîtes au-dessus qui ne sont pas plus larges.
        4. Soustrait l'étaiement latéral de boîtes voisines.
        5. Retourne le maximum de tous ces ratios.

    Un ratio élevé → pile haute et étroite → moins stable (risque de chute).
    Un ratio faible → pile large ou basse → stable.
    """
    # On ne s'intéresse qu'aux boîtes P1 (les P2 sont déposées à la main)
    p1_boxes = [pb for pb in placed_boxes if pb.priority == 1]
    if not p1_boxes:
        return 0.0   # pas de boîte P1 → pas de pile à analyser

    # Regroupe les boîtes en piles physiques
    stacks = _build_support_stacks(p1_boxes)
    worst = 0.0

    for stack in stacks:
        # ── Ratio de la boîte englobante de toute la pile ──────────────────
        z_tops = [pb.z_max for pb in stack]
        z_bots = [pb.z for pb in stack]
        stack_z_min, stack_z_max = min(z_bots), max(z_tops)
        stack_height = stack_z_max - stack_z_min   # hauteur totale de la pile

        # Boîte englobante en XY de toute la pile
        all_xs = [pb.x for pb in stack] + [pb.x_max for pb in stack]
        all_ys = [pb.y for pb in stack] + [pb.y_max for pb in stack]
        bb_x, bb_x_max = min(all_xs), max(all_xs)
        bb_y, bb_y_max = min(all_ys), max(all_ys)
        base_x = bb_x_max - bb_x   # largeur de la base selon X
        base_y = bb_y_max - bb_y   # largeur de la base selon Y

        stack_ids = {id(pb) for pb in stack}   # IDs Python pour exclure ces boîtes

        # Vérifie le ratio selon chaque axe horizontale indépendamment
        for axis, dim in (("x", base_x), ("y", base_y)):
            if dim <= 0:
                continue
            r = _effective_ratio(
                stack_height, dim, axis,
                bb_x, bb_y, bb_x_max, bb_y_max,
                stack_z_min, stack_z_max,
                stack_ids, placed_boxes,
            )
            worst = max(worst, r)

        # ── Ratio de chaque sous-colonne (depuis chaque boîte anchor) ─────
        # Une sous-colonne = ensemble des boîtes qui reposent sur `anchor`
        # et qui ne sont pas plus larges qu'elle (colonne cohérente).
        for anchor in stack:
            sub = [anchor]
            sub_ids = {id(anchor)}

            for pb in stack:
                if pb is anchor:
                    continue
                # Exclut les boîtes en dessous de l'ancre
                if pb.z < anchor.z - FLOAT_TOL:
                    continue
                # Garde les boîtes pas plus larges que l'ancre selon les deux axes
                if (pb.x_max - pb.x) <= anchor.length + FLOAT_TOL and \
                   (pb.y_max - pb.y) <= anchor.width  + FLOAT_TOL:
                    sub.append(pb)
                    sub_ids.add(id(pb))

            sub_z_top  = max(pb.z_max for pb in sub)
            sub_height = sub_z_top - anchor.z   # hauteur de la sous-colonne

            sub_xs = [pb.x for pb in sub] + [pb.x_max for pb in sub]
            sub_ys = [pb.y for pb in sub] + [pb.y_max for pb in sub]
            sub_bb_x, sub_bb_x_max = min(sub_xs), max(sub_xs)
            sub_bb_y, sub_bb_y_max = min(sub_ys), max(sub_ys)

            # Vérifie les deux axes de la sous-colonne
            for axis, dim in (("x", anchor.length), ("y", anchor.width)):
                if dim <= 0:
                    continue
                r = _effective_ratio(
                    sub_height, dim, axis,
                    sub_bb_x, sub_bb_y, sub_bb_x_max, sub_bb_y_max,
                    anchor.z, sub_z_top,
                    sub_ids, placed_boxes,
                )
                worst = max(worst, r)

    # Arrondi à 4 décimales pour un affichage lisible
    return round(worst, 4)
