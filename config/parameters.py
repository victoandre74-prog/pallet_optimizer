"""
Paramètres globaux de l'optimiseur de palettisation 3D.

Ce fichier centralise TOUS les paramètres réglables du système.
Modifier une valeur ici se répercute automatiquement dans tout l'algorithme
sans qu'il soit nécessaire de toucher au code de logique.

Organisation des paramètres :
    ── Géométrie de la palette (dimensions physiques)
    ── Physique / stabilité (règles de sécurité)
    ── Ergonomie (sécurité opérateur)
    ── Stratégie multi-client (quand et comment fusionner des palettes ?)
    ── LNS mono-client (Phase 2)
    ── LNS multi-client (Phase 4)
    ── Post-processing (Phase 5)

Pour un débutant — qu'est-ce qu'un @dataclass ?
    Un @dataclass est une classe Python pour laquelle Python génère
    automatiquement __init__, __repr__, etc. à partir des attributs déclarés.
    Ici, OptimizationParameters() crée un objet avec toutes les valeurs par défaut.
    On peut surcharger : OptimizationParameters(pallet_length=120.0).

PARAM_BOUNDS :
    Dictionnaire qui définit les plages valides pour chaque paramètre numérique.
    Permet à __post_init__ de valider les valeurs à la création de l'objet.
"""

from dataclasses import dataclass, fields   # fields() liste tous les champs d'une dataclass


# Plages valides pour chaque paramètre numérique.
# Format : nom_parametre → (valeur_minimale, valeur_maximale)
# Utilisé dans __post_init__ pour valider les paramètres à la construction.
PARAM_BOUNDS: dict[str, tuple] = {
    "pallet_length":                 (1,     300),
    "pallet_width":                  (1,     300),
    "pallet_max_height":             (1,     300),
    "pallet_max_weight":             (1,     1000),
    "min_support_ratio":             (0.2,   1.0),
    "stability_ratio":               (0.1,   20.0),
    "priority2_max_deposit_height":  (0,     300),
    "multi_client_minimum_ratio":    (0.0,   1.0),
    "multi_client_maximum_ratio":    (0.0,   1.0),
    "min_filling_ratio":             (0.0,   1.0),
    "cost_mono_pallet_count":        (0,     100_000),
    "cost_mono_last_pallet_filling": (0,     100_000),
    "cost_multi_pallet_count":       (0,     100_000),
    "lns_mono_small_box_volume":     (0,     100_000_000),
    "lns_mono_repair_top_k":         (1,     10),
    "lns_mono_iter_per_pallet":      (1,     200),
    "lns_mono_random_seed":          (0,     2**31),
    "lns_multi_iter_per_pallet":     (1,     200),
    "lns_multi_random_seed":         (0,     2**31),
    "lns_multi_destroy_ratio":       (0.01,  1.0),
    "lns_multi_repair_top_k":        (1,     10),
    "pp_iter_per_pallet":            (1,     200),
    "pp_top_k":                      (1,     10),
    "pp_random_seed":                (0,     2**31),
    "pp_w_contact":                  (0,     1_000_000),
    "pp_w_fill":                     (0,     1_000_000),
    "pp_w_p2":                       (0,     1_000_000),
    "pp_w_height":                   (0,     1_000_000),
    "pp_w_stability":                (0,     1_000_000),
    "pp_center_min_shift":           (0,     150),
}


@dataclass
class OptimizationParameters:
    """
    Tous les paramètres configurables de l'optimiseur de palettisation.

    Chaque attribut a une valeur par défaut raisonnable pour un usage standard.
    Surcharger un paramètre au moment de la création de l'objet :
        params = OptimizationParameters(pallet_length=120.0, stability_ratio=5.0)

    ────────────────────────────────────────────────────────────────────────────
    GÉOMÉTRIE DE LA PALETTE
    ────────────────────────────────────────────────────────────────────────────
        pallet_length       : longueur de la palette selon X (cm)
        pallet_width        : largeur de la palette selon Y (cm)
        pallet_max_height   : hauteur maximale d'empilement selon Z (cm)
        pallet_max_weight   : masse totale maximale par palette (kg)

    ────────────────────────────────────────────────────────────────────────────
    PHYSIQUE / STABILITÉ
    ────────────────────────────────────────────────────────────────────────────
        min_support_ratio   : fraction minimale de la base d'une boîte qui doit
                              reposer sur d'autres boîtes ou le sol (0.0 à 1.0).
                              Ex : 0.80 = au moins 80% de la surface doit être soutenue.

        stability_ratio     : ratio maximal autorisé entre la hauteur d'une pile
                              et sa dimension de base la plus étroite.
                              Formule : hauteur_pile / base_min < stability_ratio
                              Ex : 7.0 → une pile de 70 cm doit avoir une base ≥ 10 cm.

    ────────────────────────────────────────────────────────────────────────────
    ERGONOMIE
    ────────────────────────────────────────────────────────────────────────────
        priority2_max_deposit_height : altitude maximale (cm) de la base d'une boîte
                              de priorité 2. Les P2 sont posées à la main par un
                              opérateur — si la base est trop haute, le geste est
                              dangereux pour le dos. Valeur typique : 160 cm.

    ────────────────────────────────────────────────────────────────────────────
    STRATÉGIE MULTI-CLIENT (Phase 3)
    ────────────────────────────────────────────────────────────────────────────
    La Phase 3 fusionne des palettes sous-remplies de clients différents.
    Le comportement s'adapte automatiquement au nombre de palettes :

        enable_multi_client   : False = désactive Phase 3 et Phase 4 entièrement.
                                Utile pour garder chaque palette strictement mono-client.

        min_filling_ratio     : seuil de remplissage moyen pour le régime ≤10 palettes.
                                La fusion s'arrête quand l'average fill dépasse ce seuil.
                                Ex : 0.40 = arrêt quand la moyenne dépasse 40%.

        multi_client_minimum_ratio : borne inférieure souple pour le régime ≥11 palettes.
                                     La fusion s'arrête quand le ratio palettes_multi/total
                                     dépasse cette valeur ET que la palette mono la moins
                                     remplie dépasse min_filling_ratio.
                                     Ex : 0.12 = arrêt souple à 12% de palettes multi.

        multi_client_maximum_ratio : borne supérieure dure. La fusion s'arrête
                                     TOUJOURS quand ce ratio est atteint.
                                     Ex : 0.20 = jamais plus de 20% de palettes multi.

    Résumé des régimes (voir pallet_optimizer.py pour le détail complet) :
        1 client ou 1 palette    → pas de fusion
        2 palettes               → fusion si avg fill < min_filling_ratio
        3 à 10 palettes          → fusion des 2 moins remplies, puis boucle d'alimentation
        11 à 70 palettes         → boucle avec conditions d'arrêt min/max ratio
        > 70 palettes            → boucle par paires pour accélérer

    ────────────────────────────────────────────────────────────────────────────
    LNS MONO-CLIENT (Phase 2) — Large Neighbourhood Search
    ────────────────────────────────────────────────────────────────────────────
    Le LNS est une méta-heuristique d'optimisation : à chaque itération,
    on « détruit » une partie de la solution et on la « répare » différemment.
    Si la nouvelle solution est meilleure, on la conserve.

    Stratégie Destroy (Phase 2) :
        - Retire entièrement la palette la moins remplie (toutes ses boîtes dans le pool)
        - Retire aussi les petites boîtes (volume < lns_mono_small_box_volume) des
          palettes survivantes (pour donner plus de liberté au moteur de réparation)

    Stratégie Repair :
        - Mélange aléatoirement l'ordre du pool
        - Place chaque boîte avec une position tirée aléatoirement parmi les top-k meilleures
          (perturbation contrôlée — pas purement aléatoire, pas purement greedy)

        lns_mono_time_per_pallet  : budget temps par palette du groupe (secondes).
                                    Budget total = taille_groupe × cette_valeur.
        lns_mono_small_box_volume : volume (cm³) en dessous duquel une boîte est
                                    extraite des palettes survivantes à chaque itération.
        lns_mono_repair_top_k     : taille du bassin de sélection aléatoire (1 = déterministe).
        lns_mono_iter_per_pallet  : nombre d'itérations allouées par palette du groupe.
        lns_mono_random_seed      : graine aléatoire pour la reproductibilité.

    ────────────────────────────────────────────────────────────────────────────
    LNS MULTI-CLIENT (Phase 4)
    ────────────────────────────────────────────────────────────────────────────
    Même principe que le LNS mono, mais appliqué à un pool mixte (plusieurs clients).

    Stratégie Destroy (Phase 4) :
        - Retire les lns_multi_destroy_ratio × N palettes les moins remplies
          (au moins 2 sont toujours détruites pour forcer de vraies fusions)

        lns_multi_time_per_pallet  : budget temps par palette du pool (secondes)
        lns_multi_iter_per_pallet  : nombre d'itérations allouées par palette du pool
        lns_multi_random_seed      : graine aléatoire
        lns_multi_destroy_ratio    : fraction de palettes détruites à chaque itération
        lns_multi_repair_top_k     : taille du bassin de sélection aléatoire

    ────────────────────────────────────────────────────────────────────────────
    POST-PROCESSING LNS (Phase 5, préfixe pp_*)
    ────────────────────────────────────────────────────────────────────────────
    Phase d'amélioration finale qui optimise 5 objectifs simultanément :
        1. Contact P2→P1 : placer les boîtes manuelles contre les lourdes (stabilité)
        2. Équilibre de remplissage : remplissage similaire entre palettes du groupe
        3. Répartition des P2 : distribution équitable des boîtes manuelles
        4. Hauteur : minimiser la hauteur moyenne des palettes
        5. Stabilité : minimiser le ratio de stabilité le plus défavorable

    Chaque objectif a un poids qui détermine son importance relative dans
    la fonction de coût globale.

        pp_time_per_pallet   : budget temps par palette (secondes)
        pp_iter_per_pallet   : nombre d'itérations totales
        pp_top_k             : taille du bassin pour le placement P2 et la sélection
        pp_random_seed       : graine aléatoire

        pp_w_contact         : poids du contact P2→P1 (récompense)
        pp_w_fill            : poids de la variance de remplissage (pénalité)
        pp_w_p2              : poids de la variance du nombre de P2 (pénalité)
        pp_w_height          : poids de la hauteur moyenne normalisée (pénalité)
        pp_w_stability       : poids du pire ratio de stabilité (pénalité)

        pp_center_min_shift  : décalage minimal (cm) pour appliquer le centrage de charge
    """

    # ── Géométrie de la palette ────────────────────────────────────────────────
    pallet_length: float     = 130.0    # cm (palette standard 130 × 80)
    pallet_width: float      = 80.0     # cm
    pallet_max_height: float = 227.0   # cm (hauteur standard de transport)
    pallet_max_weight: float = 600.0   # kg (limite de charge standard)

    # ── Physique / stabilité ───────────────────────────────────────────────────
    min_support_ratio: float = 0.80    # 80% de la base doit être soutenue
    stability_ratio: float   = 7.0    # hauteur / base_min doit rester < 7

    # ── Ergonomie ─────────────────────────────────────────────────────────────
    priority2_max_deposit_height: float = 160.0  # cm — limite de dépôt manuel

    # ── Stratégie multi-client ─────────────────────────────────────────────────
    enable_multi_client: bool          = True   # mettre False pour garder palettes mono
    multi_client_minimum_ratio: float  = 0.12   # borne souple pour ≥11 palettes
    multi_client_maximum_ratio: float  = 0.20   # borne dure pour ≥11 palettes
    min_filling_ratio: float           = 0.40   # seuil de remplissage pour ≤10 palettes

    # ── Post-processing général ────────────────────────────────────────────────
    enable_post_processing: bool = True   # mettre False pour sauter la Phase 5

    # ── Fonction de coût — LNS mono ───────────────────────────────────────────
    # Objectif principal : réduire le nombre de palettes.
    # Objectif secondaire : garder la palette la moins remplie vraiment vide
    # (bon candidat pour la fusion Phase 3/4).
    cost_mono_pallet_count: float        = 500.0
    cost_mono_last_pallet_filling: float = 400.0   # pénalise un taux élevé sur la palette la moins remplie

    # ── Fonction de coût — LNS multi ──────────────────────────────────────────
    # Objectif unique : réduire le nombre de palettes.
    # La répartition P2 est gérée par post_processing.py.
    cost_multi_pallet_count: float = 10.0

    # ── LNS mono-client — budget et hyperparamètres ───────────────────────────
    lns_mono_time_per_pallet: float  = 0.7       # secondes par palette
    lns_mono_small_box_volume: float = 590000.0  # cm³ — seuil pour extraire les petites boîtes
    lns_mono_repair_top_k: int       = 3         # top-k pour la perturbation
    lns_mono_iter_per_pallet: int    = 30        # itérations par palette
    lns_mono_random_seed: int        = 42        # graine reproductible

    # ── LNS multi-client — budget et hyperparamètres ──────────────────────────
    lns_multi_time_per_pallet: float = 0.5    # secondes par palette
    lns_multi_iter_per_pallet: int   = 20     # itérations par palette
    lns_multi_random_seed: int       = 42     # graine reproductible
    lns_multi_destroy_ratio: float   = 0.33   # fraction de palettes détruites (au moins 2)
    lns_multi_repair_top_k: int      = 3      # top-k pour la perturbation

    # ── Post-processing — budget et hyperparamètres ───────────────────────────
    pp_time_per_pallet: float = 0.5    # secondes par palette
    pp_iter_per_pallet: int   = 20     # itérations totales (50% fill / 50% P2)
    pp_top_k: int             = 2      # bassin de candidats pour placement et sélection
    pp_random_seed: int       = 7      # graine reproductible

    # ── Post-processing — poids de la fonction de coût ────────────────────────
    pp_w_contact: float   = 10.0    # récompense par cm² de contact P2→P1
    pp_w_fill: float      = 5.0     # pénalité par unité de variance de remplissage
    pp_w_p2: float        = 5000.0  # pénalité par unité de variance du nombre de P2
    pp_w_height: float    = 5.0     # pénalité pour la hauteur moyenne normalisée
    pp_w_stability: float = 10.0    # pénalité pour le pire ratio de stabilité

    # ── Post-processing — centrage de la charge ────────────────────────────────
    pp_center_min_shift: float = 5.0    # décalage minimal (cm) pour activer le centrage

    def __post_init__(self) -> None:
        """
        Validation automatique des paramètres à la création de l'objet.

        __post_init__ est appelé automatiquement par la dataclass juste après
        __init__. On l'utilise ici pour vérifier que toutes les valeurs sont
        dans leurs plages valides et cohérentes entre elles.

        Si un paramètre est invalide, on lève une ValueError avec une liste
        de tous les problèmes trouvés (pas seulement le premier).
        """
        errors: list[str] = []

        # Vérifie que chaque paramètre numérique est dans sa plage autorisée
        for f in fields(self):   # fields() retourne la liste de tous les champs
            if f.name not in PARAM_BOUNDS:
                continue   # ce champ n'a pas de borne définie (ex. booléens)
            val = getattr(self, f.name)   # getattr = accès dynamique par nom
            lo, hi = PARAM_BOUNDS[f.name]
            if not (lo <= val <= hi):
                errors.append(f"{f.name}={val!r}  (plage autorisée : [{lo}, {hi}])")

        # Vérification spéciale : minimum doit être < maximum (cohérence)
        if self.multi_client_minimum_ratio >= self.multi_client_maximum_ratio:
            errors.append(
                "multi_client_minimum_ratio doit être strictement inférieur à "
                "multi_client_maximum_ratio"
            )

        # Si des erreurs ont été trouvées, les affiche toutes d'un coup
        if errors:
            raise ValueError(
                "Paramètres invalides :\n" + "\n".join(f"  • {e}" for e in errors)
            )
