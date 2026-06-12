"""
Écrivain CSV pour les résultats de palettisation.

Ce module génère le fichier de sortie à partir des palettes optimisées.
Le CSV produit est consommé par le tableau de bord Dash (visualization/).

Format de sortie : CSV délimité par des points-virgules (;)
Une ligne par boîte placée.

Colonnes de sortie :
    pallet_id              — identifiant de la palette (entier)
    sequence               — ordre de placement dans la palette (1 = première posée)
    box_id                 — identifiant d'origine de la boîte
    client_id              — identifiant client
    priority               — 1 ou 2
    x, y, z               — position du coin bas-gauche-arrière (cm)
    orientation            — nom de l'orientation (ex. "LWH")
    length, width, height  — dimensions placées (après rotation) en cm
    weight                 — poids de la boîte (kg)
    pallet_length          — longueur de la palette (cm)   ← pour le dashboard
    pallet_width           — largeur de la palette (cm)    ← pour le dashboard
    pallet_height          — hauteur max de la palette (cm) ← pour le dashboard
    multi_client           — "yes" si la palette est multi-client, "no" sinon
    volumetric_fill_ratio  — volume utilisé / volume total palette (0.0–1.0)
    worst_stability_ratio  — pire ratio de stabilité P1 (plus élevé = moins stable)
    designation            — libellé du produit (peut être vide)
    location               — emplacement entrepôt (peut être vide)
"""

import csv
from pathlib import Path    # Path : manipulation de chemins multi-OS (Windows/Linux)
from typing import List

from models.pallet import Pallet


# Liste ordonnée des colonnes de sortie.
# Cet ordre définit l'ordre des colonnes dans le fichier CSV produit.
RESULT_COLUMNS = [
    "pallet_id",
    "sequence",
    "box_id",
    "client_id",
    "priority",
    "x", "y", "z",
    "orientation",
    "length", "width", "height",
    "weight",
    "pallet_length",
    "pallet_width",
    "pallet_height",
    "multi_client",
    "volumetric_fill_ratio",
    "worst_stability_ratio",
    "designation",
    "location",
]


def write_results_to_csv(pallets: List[Pallet], filepath: str) -> None:
    """
    Écrit le résultat complet de la palettisation dans un fichier CSV.

    Pour chaque palette, itère sur ses boîtes placées dans l'ordre de placement
    (ordre naturel de pallet.boxes) et écrit une ligne par boîte.

    Les informations répétées par palette (dimensions, fill, stability) sont
    dupliquées sur chaque ligne pour faciliter le chargement dans le dashboard
    sans jointure supplémentaire.

    Paramètres :
        pallets  : liste de palettes optimisées (sortie de l'optimiseur)
        filepath : chemin du fichier CSV à créer ou écraser

    Fonctionnement :
        - Crée automatiquement les répertoires parents s'ils n'existent pas
          (Path.mkdir(parents=True, exist_ok=True)).
        - Les valeurs numériques sont arrondies à 4 décimales pour éviter
          les nombres en notation scientifique (ex. 1.234567890123e-12).
        - worst_stability_ratio est calculé une fois par palette et répété
          sur chaque ligne (c'est un attribut de la palette, pas de la boîte).

    Affiche un résumé en console à la fin.
    """
    path = Path(filepath)
    # Crée le dossier parent si nécessaire (ex. output/ n'existe pas encore)
    path.parent.mkdir(parents=True, exist_ok=True)

    row_count = 0   # compteur de lignes écrites

    with open(path, "w", newline="", encoding="utf-8") as f:
        # DictWriter : écrit chaque ligne à partir d'un dictionnaire { colonne → valeur }
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, delimiter=";")
        writer.writeheader()   # écrit l'en-tête (noms des colonnes)

        for pallet in pallets:
            # Calcule worst_stability_ratio une seule fois pour toute la palette
            # (appel coûteux — O(n²) sur les boîtes P1)
            stability = pallet.worst_stability_ratio

            for pb in pallet.boxes:
                writer.writerow({
                    # ── Identifiants ─────────────────────────────────────────
                    "pallet_id":    pallet.id,
                    "sequence":     pb.sequence,
                    "box_id":       pb.box_id,
                    "client_id":    pb.client_id,
                    "priority":     pb.priority,

                    # ── Position 3D (arrondies à 4 décimales) ───────────────
                    "x":            round(pb.x,      4),
                    "y":            round(pb.y,      4),
                    "z":            round(pb.z,      4),

                    # ── Orientation et dimensions placées ────────────────────
                    "orientation":  pb.orientation.value,   # ex. "LWH"
                    "length":       round(pb.length, 4),
                    "width":        round(pb.width,  4),
                    "height":       round(pb.height, 4),
                    "weight":       round(pb.weight, 4),

                    # ── Dimensions de la palette (pour le dashboard) ─────────
                    "pallet_length": pallet.length,
                    "pallet_width":  pallet.width,
                    "pallet_height": pallet.max_height,

                    # ── Statistiques palette répétées par boîte ──────────────
                    "multi_client":           "yes" if pallet.is_multi_client else "no",
                    "volumetric_fill_ratio":  round(pallet.volumetric_fill_ratio, 4),
                    "worst_stability_ratio":  stability,

                    # ── Métadonnées optionnelles ─────────────────────────────
                    "designation": pb.designation,
                    "location":    pb.location,
                })
                row_count += 1

    print(
        f"[Écrivain CSV] Résultats écrits dans {filepath} "
        f"({len(pallets)} palettes, {row_count} boîtes placées)."
    )
