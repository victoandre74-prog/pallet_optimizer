"""
Fonctions géométriques bas niveau partagées dans tout le projet.

Ces fonctions travaillent uniquement sur des nombres (float), sans référence
aux objets métier (Box, Pallet, etc.). Cela les rend :
    - facilement testables (pas de dépendances à instancier)
    - réutilisables partout dans le code

Géométrie utilisée : AABB (Axis-Aligned Bounding Box)
    Toutes les boîtes et palettes sont des rectangles/cubes dont les côtés
    sont parfaitement alignés avec les axes X, Y, Z.
    Cela simplifie énormément les calculs de collision et d'intersection.

Vocabulaire pour un débutant :
    - Intervalle [a_min, a_max] : segment de droite entre deux points
    - Chevauchement (overlap) : deux intervalles se chevauchent si l'un empiète
      sur l'autre (ils ont des points en commun à l'intérieur)
    - Intersection : la zone commune à deux formes géométriques
"""


def intervals_overlap(a_min: float, a_max: float,
                      b_min: float, b_max: float) -> bool:
    """
    Vérifie si deux intervalles 1D se chevauchent (partagent un point intérieur).

    Les extrémités qui se touchent (contact bord-à-bord) NE sont PAS considérées
    comme un chevauchement. Cela correspond au comportement physique voulu :
    deux boîtes qui se touchent juste sur une face n'occupent pas le même espace.

    Paramètres :
        a_min, a_max : bornes de l'intervalle A (ex. x_début et x_fin d'une boîte)
        b_min, b_max : bornes de l'intervalle B

    Retourne True si les intervalles ont des points intérieurs communs.

    Exemples :
        [0, 5] et [5, 10] → False (contact bord-à-bord, pas de chevauchement)
        [0, 6] et [5, 10] → True  (ils partagent la zone [5, 6])
        [0, 3] et [7, 10] → False (séparés, aucun point commun)

    Astuce mathématique :
        Deux intervalles se chevauchent si et seulement si :
            a_min < b_max  ET  a_max > b_min
        C'est la condition complémentaire de « l'un est entièrement à gauche de l'autre ».
    """
    return a_min < b_max and a_max > b_min


def xy_overlap(
    x1: float, y1: float, x1_max: float, y1_max: float,
    x2: float, y2: float, x2_max: float, y2_max: float
) -> bool:
    """
    Vérifie si deux rectangles 2D (dans le plan XY) se chevauchent.

    Chaque rectangle est défini par son coin bas-gauche (x, y) et son coin
    haut-droit (x_max, y_max).

    Deux rectangles 2D se chevauchent si et seulement si leurs projections
    se chevauchent SIMULTANÉMENT selon X ET selon Y.
    (Si l'un dépasse l'autre dans un seul axe, ils ne se superposent pas.)

    Paramètres :
        x1, y1, x1_max, y1_max : bornes du rectangle 1
        x2, y2, x2_max, y2_max : bornes du rectangle 2

    Utilisation typique :
        Déterminer si deux empreintes au sol (footprints) de boîtes se superposent,
        pour décider si une boîte peut en supporter une autre ou si elles entrent
        en collision.
    """
    return (
        intervals_overlap(x1, x1_max, x2, x2_max) and   # chevauchement en X
        intervals_overlap(y1, y1_max, y2, y2_max)        # ET chevauchement en Y
    )


def xy_intersection_area(
    x1: float, y1: float, x1_max: float, y1_max: float,
    x2: float, y2: float, x2_max: float, y2_max: float
) -> float:
    """
    Calcule l'aire (en cm²) de l'intersection entre deux rectangles 2D.

    Retourne 0.0 s'ils ne se chevauchent pas.

    Principe :
        L'intersection de deux rectangles AABB est elle-même un rectangle.
        Sa largeur en X est le chevauchement des intervalles X.
        Sa hauteur en Y est le chevauchement des intervalles Y.
        L'aire = largeur × hauteur.

    Exemples d'utilisation :
        - Calculer quelle fraction de la base d'une boîte est supportée par
          des boîtes en dessous (ratio de support).
        - Calculer l'empreinte commune entre deux boîtes pour la stabilité.

    Astuce :
        max(0.0, ...) évite les valeurs négatives qui apparaissent quand
        les rectangles ne se chevauchent pas (min(...) < max(...) → négatif).
    """
    # Chevauchement selon X : max(0, min des max - max des min)
    overlap_x = max(0.0, min(x1_max, x2_max) - max(x1, x2))
    # Chevauchement selon Y
    overlap_y = max(0.0, min(y1_max, y2_max) - max(y1, y2))
    return overlap_x * overlap_y


def boxes_intersect_3d(
    x1: float, y1: float, z1: float,
    l1: float, w1: float, h1: float,
    x2: float, y2: float, z2: float,
    l2: float, w2: float, h2: float
) -> bool:
    """
    Vérifie si deux boîtes 3D (cuboïdes alignés sur les axes) se chevauchent.

    Chaque boîte est définie par son coin bas-gauche-arrière (x, y, z)
    et ses dimensions (longueur l, largeur w, hauteur h).

    Deux boîtes 3D se chevauchent si et seulement si leurs intervalles
    se chevauchent simultanément selon X, Y ET Z.

    Les boîtes qui partagent uniquement une face ou une arête (contact sans
    interpénétration) NE sont PAS considérées comme en intersection.

    Paramètres :
        x1, y1, z1, l1, w1, h1 : position et dimensions de la boîte 1
        x2, y2, z2, l2, w2, h2 : position et dimensions de la boîte 2

    Cette fonction est utilisée pour la détection de collision entre boîtes.
    En pratique, la vérification inline dans placement_engine.py est préférable
    pour la performance (évite l'overhead d'appel de fonction Python en boucle),
    mais cette version reste utile pour les tests et le code extérieur.
    """
    return (
        intervals_overlap(x1, x1 + l1, x2, x2 + l2) and   # collision en X
        intervals_overlap(y1, y1 + w1, y2, y2 + w2) and   # collision en Y
        intervals_overlap(z1, z1 + h1, z2, z2 + h2)        # collision en Z
    )


def clamp(value: float, lo: float, hi: float) -> float:
    """
    Limite (clamp) une valeur dans l'intervalle [lo, hi].

    Si value < lo  → retourne lo  (borne minimale)
    Si value > hi  → retourne hi  (borne maximale)
    Sinon          → retourne value telle quelle

    Exemple :
        clamp(3.0, 0.0, 1.0)  → 1.0  (trop grand, ramené à la borne max)
        clamp(-1.0, 0.0, 1.0) → 0.0  (trop petit, ramené à la borne min)
        clamp(0.5, 0.0, 1.0)  → 0.5  (dans l'intervalle, inchangé)
    """
    return max(lo, min(hi, value))
