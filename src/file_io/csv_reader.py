"""
Lecteur CSV pour les données d'entrée des boîtes.

Ce module gère la lecture et la validation du fichier CSV qui décrit les
colis à emballer sur les palettes.

Format attendu : CSV délimité par des points-virgules (;)

Colonnes requises :
    id                   — identifiant unique de la boîte (chaîne de caractères)
    priority             — 1 ou 2
    length               — longueur en cm (réel > 0)
    width                — largeur en cm (réel > 0)
    height               — hauteur en cm (réel > 0)
    weight               — poids en kg (réel > 0)
    client_id            — identifiant client (entier)
    allowed_orientations — orientations autorisées : noms séparés par des virgules
                           ou "all" pour toutes.
                           Exemple : "LWH,WLH,HLW"  ou  "all"
    stackable            — "true" ou "false" (d'autres variantes acceptées :
                           "1", "0", "yes", "no")

Colonnes optionnelles (ignorées si absentes) :
    designation          — libellé du produit
    location             — emplacement dans l'entrepôt

Bonne pratique : appelez d'abord validate_csv() pour obtenir une liste complète
des erreurs AVANT d'appeler read_boxes_from_csv(). Cela affiche tous les problèmes
en une seule passe au lieu de planter à la première erreur.
"""

import csv
from pathlib import Path        # Path : manipulation de chemins de fichiers (plus sûr que os.path)
from typing import List, Tuple

from models.box import Box
from models.orientation import Orientation, ALL_ORIENTATIONS

# Ensemble des colonnes obligatoires (pour la vérification d'en-tête)
REQUIRED_COLUMNS = {
    "id", "priority", "length", "width", "height",
    "weight", "client_id", "allowed_orientations", "stackable",
}
# Noms valides d'orientations (pour la vérification des valeurs)
VALID_ORIENTATIONS = {o.name for o in ALL_ORIENTATIONS}


# ── Parseurs internes ──────────────────────────────────────────────────────────

def _parse_orientations(value: str) -> List[Orientation]:
    """
    Convertit une chaîne d'orientations CSV en liste d'objets Orientation.

    Formats acceptés :
        "all"              → toutes les orientations (liste complète)
        "LWH,WLH,HLW"     → liste des orientations nommées
        " LWH , WLH "     → les espaces sont ignorés (strip)

    Lève une ValueError si un nom d'orientation est inconnu.
    """
    value = value.strip()
    if value.lower() == "all":
        return list(ALL_ORIENTATIONS)   # raccourci pour « toutes »

    orientations = []
    for name in value.split(","):
        name = name.strip().upper()   # normalise la casse
        try:
            orientations.append(Orientation[name])   # accès par nom dans l'enum
        except KeyError:
            raise ValueError(
                f"Orientation inconnue : {name!r}. "
                f"Valeurs valides : {sorted(VALID_ORIENTATIONS)}"
            )
    return orientations


def _parse_stackable(value: str, orientations: List[Orientation]) -> dict:
    """
    Convertit la valeur texte 'stackable' en dictionnaire { Orientation → bool }.

    Le flag s'applique uniformément à TOUTES les orientations autorisées.
    Si l'on veut des flags différents par orientation, il faudrait étendre le CSV
    (non supporté actuellement).

    Valeurs acceptées :
        True  → "true", "1", "yes" (insensible à la casse)
        False → tout le reste (ex. "false", "0", "no")
    """
    flag = value.strip().lower() in ("true", "1", "yes")
    return {o: flag for o in orientations}   # même flag pour toutes les orientations


# ── Validation du CSV ──────────────────────────────────────────────────────────

def validate_csv(filepath: str, pallet_max_height: float = None) -> List[str]:
    """
    Valide la structure et le contenu d'un CSV d'entrée de boîtes.

    Cette fonction est conçue pour être appelée AVANT read_boxes_from_csv().
    Elle parcourt tout le fichier et collecte TOUTES les erreurs en une seule
    passe, plutôt que de s'arrêter à la première.

    Vérifications effectuées :
        - Le fichier existe et est lisible.
        - Le délimiteur est bien le point-virgule (;).
          Détecte les fichiers comma-delimited (erreur courante sous Excel).
        - Toutes les colonnes requises sont présentes.
        - Pas de doublons d'identifiant (id) dans le fichier.
        - priority est 1 ou 2.
        - length, width, height, weight sont des réels > 0.
        - (si pallet_max_height fourni) aucune dimension ne dépasse la hauteur palette.
        - client_id est un entier.
        - allowed_orientations ne contient que des noms valides (ou "all").
        - stackable est une valeur booléenne reconnue.

    Paramètres :
        filepath         : chemin vers le fichier CSV
        pallet_max_height : hauteur maximale de palette (cm). Si fournie, valide
                           que les dimensions des boîtes ne la dépassent pas.

    Retourne :
        Une liste de chaînes d'erreur. Liste vide = fichier valide.
        Ne lève pas d'exception.
    """
    errors: List[str] = []
    path = Path(filepath)

    # Vérifie l'existence du fichier
    if not path.exists():
        return [f"Fichier introuvable : {filepath}"]

    # ── Lecture brute du contenu ───────────────────────────────────────────────
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        # utf-8-sig : ignore automatiquement le BOM (Byte Order Mark)
        # ajouté par Excel lors de l'enregistrement en UTF-8.
    except Exception as e:
        return [f"Impossible de lire le fichier : {e}"]

    if not raw.strip():
        return ["Le fichier est vide."]

    # ── Détection du délimiteur ────────────────────────────────────────────────
    first_line = raw.splitlines()[0]
    if ";" not in first_line and "," in first_line:
        errors.append(
            "Mauvais délimiteur : le fichier semble utiliser la virgule (,) au lieu "
            "du point-virgule (;). Merci d'enregistrer le CSV avec ; comme séparateur."
        )
        return errors   # inutile de continuer si le délimiteur est faux

    # ── Vérification des colonnes ──────────────────────────────────────────────
    reader = csv.DictReader(raw.splitlines(), delimiter=";")
    if reader.fieldnames is None:
        return ["Impossible de lire l'en-tête du fichier."]

    # Normalise les noms de colonnes (minuscules, sans espaces)
    actual_cols = {c.strip().lower() for c in reader.fieldnames if c}
    missing     = REQUIRED_COLUMNS - actual_cols
    if missing:
        errors.append(f"Colonnes manquantes : {sorted(missing)}")
        return errors   # impossible de valider les lignes sans les colonnes

    # ── Validation ligne par ligne ─────────────────────────────────────────────
    seen_ids: set = set()   # pour détecter les doublons d'ID

    for row_num, row in enumerate(reader, start=2):   # start=2 : ligne 1 = en-tête
        # Normalise les clés : strip + lower (même traitement que la vérif. des colonnes
        # ligne 159, pour couvrir les espaces et majuscules parasites, ex. " Priority")
        row    = {k.strip().lower(): v.strip() if v else "" for k, v in row.items() if k}
        prefix = f"Ligne {row_num}"

        # ── Colonne 'id' ──────────────────────────────────────────────────────
        box_id = row.get("id", "").strip()
        if not box_id:
            errors.append(f"{prefix}: 'id' est vide.")
        elif box_id in seen_ids:
            errors.append(f"{prefix}: id {box_id!r} en doublon.")
        else:
            seen_ids.add(box_id)

        # ── Colonne 'priority' ────────────────────────────────────────────────
        try:
            p = int(row.get("priority", ""))
            if p not in (1, 2):
                errors.append(f"{prefix} (id={box_id!r}): 'priority' doit être 1 ou 2, obtenu {p}.")
        except ValueError:
            errors.append(f"{prefix} (id={box_id!r}): 'priority' n'est pas un entier ({row.get('priority')!r}).")

        # ── Colonnes numériques positives + vérification dimensions ──────────
        dims: dict = {}
        for field in ("length", "width", "height", "weight"):
            try:
                v = float(row.get(field, ""))
                if v <= 0:
                    errors.append(f"{prefix} (id={box_id!r}): '{field}' doit être > 0, obtenu {v}.")
                else:
                    dims[field] = v
            except ValueError:
                errors.append(f"{prefix} (id={box_id!r}): '{field}' n'est pas un nombre ({row.get(field)!r}).")

        # Vérifie qu'aucune dimension ne dépasse la hauteur maximale de la palette
        if pallet_max_height is not None and dims:
            for field in ("length", "width", "height"):
                v = dims.get(field)
                if v is not None and v > pallet_max_height:
                    errors.append(
                        f"{prefix} (id={box_id!r}): '{field}' ({v} cm) dépasse "
                        f"pallet_max_height ({pallet_max_height} cm)."
                    )

        # ── Colonne 'client_id' ───────────────────────────────────────────────
        try:
            int(row.get("client_id", ""))
        except ValueError:
            errors.append(f"{prefix} (id={box_id!r}): 'client_id' n'est pas un entier ({row.get('client_id')!r}).")

        # ── Colonne 'allowed_orientations' ────────────────────────────────────
        ao = row.get("allowed_orientations", "").strip()
        if ao.lower() != "all":
            for name in ao.split(","):
                name = name.strip().upper()
                if name not in VALID_ORIENTATIONS:
                    errors.append(
                        f"{prefix} (id={box_id!r}): orientation inconnue {name!r}. "
                        f"Valeurs valides : {sorted(VALID_ORIENTATIONS)} ou 'all'."
                    )

        # ── Colonne 'stackable' ───────────────────────────────────────────────
        st = row.get("stackable", "").strip().lower()
        if st not in ("true", "false", "1", "0", "yes", "no"):
            errors.append(
                f"{prefix} (id={box_id!r}): 'stackable' doit être true/false, obtenu {st!r}."
            )

    return errors


# ── Chargement des boîtes ──────────────────────────────────────────────────────

def read_boxes_from_csv(filepath: str) -> List[Box]:
    """
    Lit et retourne la liste des Box depuis un fichier CSV.

    Suppose que le fichier a DÉJÀ été validé avec validate_csv().
    Si des erreurs inattendues surviennent, lève FileNotFoundError ou ValueError.

    Paramètre :
        filepath : chemin vers le fichier CSV valide

    Retourne :
        Liste d'objets Box dans l'ordre du fichier.

    Exemple d'utilisation typique :
        errors = validate_csv("input/commande.csv")
        if errors:
            for e in errors: print(e)
        else:
            boxes = read_boxes_from_csv("input/commande.csv")
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier d'entrée introuvable : {filepath}")

    boxes: List[Box] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        # DictReader : chaque ligne du CSV devient un dictionnaire { colonne → valeur }
        reader = csv.DictReader(f, delimiter=";")
        for row_num, row in enumerate(reader, start=2):
            try:
                # Normalise les clés : strip + lower (aligne sur validate_csv ligne 170)
                row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items() if k}
                # Convertit les orientations texte → liste d'objets Orientation
                allowed   = _parse_orientations(row["allowed_orientations"])
                # Convertit le flag texte → dictionnaire { Orientation → bool }
                stackable = _parse_stackable(row["stackable"], allowed)

                box = Box(
                    id=row["id"].strip(),
                    priority=int(row["priority"]),
                    length=float(row["length"]),
                    width=float(row["width"]),
                    height=float(row["height"]),
                    weight=float(row["weight"]),
                    client_id=int(row["client_id"]),
                    allowed_orientations=allowed,
                    stackable=stackable,
                    # .get() avec "" par défaut : la colonne est optionnelle
                    designation=row.get("designation", "").strip(),
                    location=row.get("location", "").strip(),
                )
                boxes.append(box)

            except (KeyError, ValueError) as exc:
                # KeyError   : colonne manquante (ne devrait pas arriver après validate_csv)
                # ValueError : conversion numérique échouée
                raise ValueError(
                    f"Erreur à la ligne {row_num} de {filepath} : {exc}\n"
                    f"Contenu de la ligne : {dict(row)}"
                ) from exc

    print(f"[Lecteur CSV] {len(boxes)} boîtes chargées depuis {filepath}")
    return boxes
