"""
Moteur de placement — trouve les positions valides pour une boîte sur une palette.

Algorithme principal : Extreme-Point (EP)
─────────────────────────────────────────
L'heuristique des points extrêmes maintient un ensemble de positions candidates
(x, y) dérivées des coins des boîtes déjà placées. Pour chaque candidat,
la hauteur z réelle est trouvée en « projetant » la boîte vers le bas jusqu'à
ce qu'elle repose sur une surface de support.

Comment sont générés les points extrêmes ?
    Après chaque placement, deux nouveaux points sont ajoutés :
        Bord droit  : (x + length, y)   → à droite de la boîte placée
        Bord avant  : (x, y + width)    → devant la boîte placée
    Et l'origine (0, 0) est toujours dans la liste.

Stratégie de sélection (bottom-left-back) :
    Parmi tous les placements valides, on choisit celui qui minimise :
        (z, x, y)  en ordre de priorité croissante
    Ce qui signifie : le plus bas possible, puis le plus à gauche, puis le plus
    en arrière. Cette stratégie tend à produire des palettes denses et stables.

Pourquoi cette heuristique ?
    L'espace de recherche exact (toutes les positions possibles) est infini.
    Les points extrêmes réduisent cet espace à un ensemble fini de candidats
    « naturellement bons » — les coins formés par les boîtes existantes —
    tout en garantissant que la solution optimale pour les premières boîtes
    est toujours atteinte.
"""

from typing import List, Optional, Tuple

from pallet_optimizer.models.box import Box
from pallet_optimizer.models.placed_box import PlacedBox
from pallet_optimizer.models.pallet import Pallet
from pallet_optimizer.models.orientation import Orientation, get_oriented_dimensions
from pallet_optimizer.config.parameters import OptimizationParameters
from pallet_optimizer.core.collision_detection import is_placement_geometrically_valid
from pallet_optimizer.core.stacking_rules import check_stacking_rules
from pallet_optimizer.core.stability_check import check_support_ratio, check_stack_stability
from pallet_optimizer.utils.geometry import xy_overlap, boxes_intersect_3d  # disponibles pour les appelants

# Tolérance numérique pour les comparaisons de coordonnées (en cm)
FLOAT_TOL = 1e-6


# ── Calcul de l'aire résiduelle ────────────────────────────────────────────────

def _compute_residual_area(
    cx: float, cy: float,
    length: float, width: float,
    pallet: Pallet,
) -> float:
    """
    Estime la plus grande zone rectangulaire libre restante après avoir placé
    une boîte à la position (cx, cy) avec l'empreinte (length × width).

    Pourquoi est-ce utile ?
        Deux placements peuvent avoir le même (z, x, y) mais laisser des
        zones très différentes pour les boîtes suivantes. Ce score permet de
        préférer le placement qui fragmente le moins l'espace restant.

    Méthode (approximation rapide) :
        On utilise les deux nouveaux points extrêmes que ce placement générerait
        comme approximation de l'espace libre résiduel :
            Point droit  : (cx + length, cy)    → espace à droite de la boîte
            Point avant  : (cx, cy + width)      → espace devant la boîte
        Pour chaque point extrême EP (ex, ey), l'espace approximé est :
            (pallet.length - ex) × (pallet.width - ey)
        On retourne le maximum des deux (meilleure zone résiduelle).

    Une valeur élevée → le placement laisse plus d'espace continu → préférable.
    """
    best = 0.0
    for (ex, ey) in ((cx + length, cy), (cx, cy + width)):
        free_x = pallet.length - ex
        free_y = pallet.width  - ey
        if free_x > 0 and free_y > 0:
            best = max(best, free_x * free_y)
    return best


# ── Gestion des points extrêmes ────────────────────────────────────────────────

def generate_extreme_points(pallet: Pallet) -> List[Tuple[float, float]]:
    """
    Génère la liste dédupliquée des points candidats (x, y) pour le placement.

    Sources des candidats :
        (0, 0)                       : origine de la palette (toujours présente)
        (pb.x + pb.length, pb.y)     : bord droit de chaque boîte placée
        (pb.x, pb.y + pb.width)      : bord avant de chaque boîte placée

    Ces points correspondent aux « coins » formés par les boîtes déjà en place.
    Ce sont naturellement les meilleurs endroits pour poser de nouvelles boîtes
    car ils permettent de remplir les espaces résiduels.

    Utilise un set Python pour la déduplication automatique (pas de doublon).
    """
    points = {(0.0, 0.0)}   # l'origine est toujours candidate
    for pb in pallet.boxes:
        points.add((pb.x + pb.length, pb.y))  # coin droit de pb
        points.add((pb.x, pb.y + pb.width))   # coin avant de pb
    return list(points)


def find_support_z(
    cx: float, cy: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox]
) -> float:
    """
    Trouve l'altitude z minimale à laquelle une boîte peut reposer à (cx, cy)
    sans entrer en collision avec aucune boîte déjà placée.

    Principe du « largage » (projection vers le bas) :
        On imagine qu'on lâche la boîte en (cx, cy) depuis le haut.
        Elle descend jusqu'à atterrir sur la surface la plus haute qui la supporte.
        Les surfaces candidates sont : le sol (z=0) et le sommet de chaque boîte
        dont l'empreinte XY chevauche celle de la nouvelle boîte.

    Algorithme :
        1. Collecte tous les z candidats : z=0 (sol) + z_max de chaque boîte
           dont l'empreinte XY chevauche la boîte candidate.
        2. Trie ces z du plus bas au plus haut.
        3. Pour chaque z candidat (du bas vers le haut), vérifie qu'aucune boîte
           existante ne serait percutée si on place la boîte à cet z.
        4. Retourne le premier z valide (le plus bas possible).

    Tester du bas vers le haut préserve les espaces sous les boîtes en
    porte-à-faux : une boîte peut atterrir sur le sol même si une autre boîte
    la surplombe partiellement, tant que les hauteurs ne se chevauchent pas.

    Note de performance :
        Les appels à xy_overlap() et boxes_intersect_3d() sont réécrits en ligne
        (inline) ici pour éliminer l'overhead des appels de fonction Python dans
        les boucles critiques. pb.x_max / pb.y_max / pb.z_max sont des attributs
        pré-calculés sur PlacedBox.
    """
    cx_max = cx + length
    cy_max = cy + width

    # ── Passe 1 : collecte les z candidats depuis les boîtes qui chevauchent en XY ──
    # xy_overlap inliné : utilise pb.x_max / pb.y_max déjà calculés
    candidate_zs = {0.0}   # le sol est toujours candidat
    for pb in placed_boxes:
        if cx < pb.x_max and pb.x < cx_max and cy < pb.y_max and pb.y < cy_max:
            candidate_zs.add(pb.z_max)   # sommet de pb = z d'atterrissage potentiel

    # ── Passe 2 : teste chaque z candidat (du plus bas au plus haut) ─────────
    # boxes_intersect_3d inliné pour éviter l'overhead d'appel de fonction
    for z in sorted(candidate_zs):
        z_max_new = z + height
        for pb in placed_boxes:
            # Test d'intersection 3D : collision si les 3 axes se chevauchent
            if (cx < pb.x_max and pb.x < cx_max and
                    cy < pb.y_max and pb.y < cy_max and
                    z  < pb.z_max and pb.z < z_max_new):
                break   # collision à ce z → essaie le z suivant
        else:
            return z    # aucune collision trouvée → c'est le bon z

    # Fallback : ne devrait jamais être atteint si les paramètres sont valides
    return 0.0


# ── Validation complète des contraintes ───────────────────────────────────────

def is_valid_placement(
    box: Box,
    x: float, y: float, z: float,
    orientation: Orientation,
    length: float, width: float, height: float,
    pallet: Pallet,
    params: OptimizationParameters
) -> bool:
    """
    Effectue la vérification complète de toutes les contraintes pour placer
    `box` à la position (x, y, z) avec les dimensions orientées données.

    Vérifications effectuées dans l'ordre croissant de coût de calcul
    (les moins chères d'abord pour court-circuiter rapidement) :

        1. Géométrie : dans les limites + pas de collision   (collision_detection)
        2. Poids : le poids total de la palette ne dépasse pas le maximum
        3. Hauteur ergonomique pour les boîtes P2 (déposées à la main)
           La base d'une P2 ne peut pas être trop haute (risque lombaire)
        4. Règles d'empilement : qui peut aller sur qui ?    (stacking_rules)
        5. Ratio de support : assez de surface soutenue ?    (stability_check)
        6. Stabilité de la colonne : pas trop haute/étroite ? (stability_check)
           (uniquement pour P1 — les P2 sont placées manuellement)

    Retourne True si TOUTES les contraintes sont satisfaites.
    """
    placed = pallet.boxes

    # ── Contrainte 1 : géométrie (rapide — vérifié en premier) ───────────────
    if not is_placement_geometrically_valid(x, y, z, length, width, height, pallet):
        return False

    # ── Contrainte 2 : budget de poids ─────────────────────────────────────────
    if pallet.total_weight + box.weight > pallet.max_weight:
        return False

    # ── Contrainte 3 : hauteur ergonomique (boîtes priorité 2 uniquement) ─────
    # Une P2 est déposée à la main par un opérateur. Si sa base est trop haute,
    # le geste est dangereux pour le dos → on impose un plafond.
    if box.priority == 2 and z > params.priority2_max_deposit_height:
        return False

    # ── Contrainte 4 : règles d'empilement (qui peut reposer sur qui ?) ────────
    if not check_stacking_rules(x, y, z, length, width, box.priority, placed):
        return False

    # ── Contrainte 5 : ratio de support (surface soutenue suffisante ?) ────────
    # Seulement pour les boîtes au-dessus du sol (le sol supporte tout).
    if z > FLOAT_TOL:
        if not check_support_ratio(
            x, y, z, length, width, placed, params.min_support_ratio
        ):
            return False

    # ── Contrainte 6 : stabilité de la colonne (P1 seulement) ─────────────────
    if box.priority == 1:
        if not check_stack_stability(
            x, y, z, length, width, height, placed, params.stability_ratio
        ):
            return False

    return True   # toutes les contraintes sont satisfaites


# ── Recherche du meilleur placement ───────────────────────────────────────────

def find_best_placement(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters
) -> Optional[Tuple[float, float, float, Orientation]]:
    """
    Trouve le meilleur placement valide pour `box` sur `pallet`.

    Retourne (x, y, z, orientation) du meilleur placement trouvé,
    ou None si la boîte ne peut pas être placée sur cette palette.

    Stratégie de sélection (critères en ordre de priorité) :
        1. Minimiser z              (le plus bas possible → densité verticale)
        2. Minimiser x              (le plus à gauche)
        3. Minimiser y              (le plus en arrière)
        4. Minimiser z + height     (si la boîte est empilable → préserve la hauteur)
           (neutralisé si la boîte n'est pas empilable : rien ne montera dessus)
        5. Maximiser l'aire résiduelle (moins de fragmentation de l'espace restant)

    La combinaison de ces critères produit un remplissage « bottom-left-back »
    (bas-gauche-arrière) qui tend à créer des palettes denses et stables.

    Processus :
        Pour chaque orientation autorisée de la boîte :
            Pour chaque point extrême (cx, cy) de la palette :
                - Projette la boîte vers le bas pour trouver z
                - Vérifie toutes les contraintes
                - Conserve la meilleure position trouvée jusqu'ici
    """
    best: Optional[Tuple] = None
    best_score: Optional[Tuple] = None

    # Génère les candidats (x, y) à partir des coins des boîtes existantes
    ep_candidates = generate_extreme_points(pallet)

    for orientation in box.allowed_orientations:
        # Calcule les dimensions réelles dans cette orientation
        length, width, height = get_oriented_dimensions(
            box.length, box.width, box.height, orientation
        )

        for (cx, cy) in ep_candidates:
            # Trouve l'altitude z réelle par projection vers le bas
            z = find_support_z(cx, cy, length, width, height, pallet.boxes)

            # Vérifie toutes les contraintes physiques et métier
            if is_valid_placement(
                box, cx, cy, z, orientation,
                length, width, height, pallet, params
            ):
                # Calcule le score de ce placement (critères multi-niveaux)
                stackable    = box.is_stackable_in(orientation)
                # Si la boîte est empilable, préférer les positions qui laissent
                # le moins de hauteur non utilisée au-dessus.
                # Si elle n'est pas empilable, ce critère est neutralisé (0.0).
                height_score = (z + height) if stackable else 0.0
                # Aire résiduelle : plus grande est mieux → on la négative pour min
                residual     = _compute_residual_area(cx, cy, length, width, pallet)
                score = (z, cx, cy, height_score, -residual)

                # Conserve le placement si son score est meilleur (plus petit)
                if best_score is None or score < best_score:
                    best_score = score
                    best = (cx, cy, z, orientation)

    return best   # None si aucune position valide n'a été trouvée


def make_placed_box(
    box: Box,
    x: float, y: float, z: float,
    orientation: Orientation
) -> PlacedBox:
    """
    Crée un objet PlacedBox à partir d'une Box et de sa position confirmée.

    Cette fonction est le « point de création » officiel d'une PlacedBox.
    Elle pré-calcule les dimensions orientées et copie les métadonnées de Box
    pour que PlacedBox soit autonome lors des vérifications ultérieures.

    Paramètres :
        box         : la boîte originale (avec ses dimensions non orientées)
        x, y, z     : position choisie (retournée par find_best_placement)
        orientation : orientation choisie (retournée par find_best_placement)

    Retourne un PlacedBox prêt à être ajouté à pallet.boxes.
    """
    # Calcule les dimensions réelles dans l'orientation choisie
    length, width, height = get_oriented_dimensions(
        box.length, box.width, box.height, orientation
    )
    return PlacedBox(
        box_id=box.id,
        x=x, y=y, z=z,
        orientation=orientation,
        length=length,
        width=width,
        height=height,
        priority=box.priority,
        weight=box.weight,
        client_id=box.client_id,
        stackable=box.is_stackable_in(orientation),   # flag pour l'orientation choisie
        designation=box.designation,
        location=box.location,
    )
