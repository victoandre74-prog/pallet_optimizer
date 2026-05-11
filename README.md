# Documentation Technique / Read me — Pallet Optimizer

> **Version** : 1.2  
> **Date** : Mai 2026  
> **Langue** : Français

---

## Table des matières

1. [Introduction](#1-introduction)
2. [Présentation du système](#2-présentation-du-système)
3. [Guide d'installation](#3-guide-dinstallation)
4. [Guide de configuration](#4-guide-de-configuration)
5. [Guide d'utilisation](#5-guide-dutilisation)
6. [Pipeline d'optimisation](#6-pipeline-doptimisation)
7. [Formats de données](#7-formats-de-données)
8. [Modèles de données](#8-modèles-de-données)
9. [Essais et validation](#9-essais-et-validation)
10. [Déploiement](#10-déploiement)
11. [Assistance et maintenance](#11-assistance-et-maintenance)
12. [Journal des modifications](#12-journal-des-modifications)
13. [Glossaire](#13-glossaire)

---

## 1. Introduction

### 1.1 But

**Pallet Optimizer** est un système d'optimisation 3D de palettisation conçu pour résoudre le problème d'emballage en bac tridimensionnel (*3D bin packing*). Son objectif est de maximiser la densité de chargement des palettes tout en respectant un ensemble de contraintes physiques, ergonomiques et logistiques :

- Respecter les contraintes de dimensions et de poids par palette
- Empiler les colis en respectant les règles de priorité (meubles P1 en bas, colis P2 au-dessus)
- Garantir la stabilité mécanique des empilements
- Minimiser le nombre de palettes utilisées
- Optimiser la répartition des colis P2 au contact des meubles P1
- Gérer les palettes multi-clients (colis de plusieurs clients sur une même palette)

### 1.2 Portée

Le système couvre l'intégralité du flux de palettisation :

- **Lecture et validation** des données d'entrée (CSV)
- **Optimisation** en 5 phases successives (FFD → LNS mono → fusion multi-client adaptative → LNS multi → post-traitement)
- **Vérification d'intégrité** automatique après chaque optimisation (Phase 6)
- **Visualisation interactive** 3D des résultats
- **Export** des résultats en CSV, PNG ou HTML
- **Interface utilisateur** web paramétrable sans connaissance en programmation

Il ne couvre pas : la gestion des stocks, la communication avec des ERP/WMS, le calcul de routes de livraison.

### 1.3 Public

Ce document est destiné aux profils suivants :

| Profil | Sections prioritaires |
|---|---|
| Développeur / intégrateur | 2, 3, 6, 7, 8 |
| Utilisateur métier | 4, 5, 11 |
| Administrateur système | 3, 4, 10 |
| Testeur / QA | 9 |

---

## 2. Présentation du système

### 2.1 Architecture

Le système est organisé en modules Python indépendants, communicant via des objets de données partagés.

```
pallet_optimizer/
├── app.py                           ← Interface utilisateur Dash (lancement + visualisation + export + KPI)
├── main.py                          ← Point d'entrée CLI (traitement par lot)
│
├── config/
│   └── parameters.py                ← Tous les paramètres configurables (dataclass)
│
├── models/
│   ├── box.py                       ← Colis non placé
│   ├── placed_box.py                ← Colis positionné (coordonnées + dimensions orientées)
│   ├── pallet.py                    ← Palette (conteneur + métriques)
│   └── orientation.py               ← 6 orientations possibles d'un colis
│
├── core/
│   ├── placement_engine.py          ← Heuristique Extreme Points + validation contraintes
│   ├── collision_detection.py       ← Vérification géométrique 3D
│   ├── stability_check.py           ← Ratio de support + stabilité des piles
│   └── stacking_rules.py            ← Règles d'empilement basées sur la priorité
│
├── heuristics/
│   ├── first_fit_decreasing.py      ← Phase 1 : FFD initial
│   ├── lns_mono.py                  ← Phase 2 : LNS mono-client
│   ├── lns_multi.py                 ← Phase 4 : LNS multi-client
│   ├── lns_utils.py                 ← Utilitaires LNS partagés
│   ├── sorting.py                   ← Tri des colis
│   └── post_processing.py           ← Phase 5 : LNS post-traitement (en mémoire)
│
├── optimizer/
│   └── pallet_optimizer.py          ← Orchestrateur des phases 1 à 4
│
├── file_io/
│   ├── csv_reader.py                ← Lecture et validation du CSV d'entrée
│   └── csv_writer.py                ← Écriture du CSV de résultats
│
├── visualization/
│   ├── pallet_visualizer.py         ← Rendu 3D Plotly
│   ├── pallet_dashboard.py          ← Dashboard 3D (2 pages : Slots / Zoom)
│   ├── export_pallet_images.py      ← Export PNG (par palette ou par séquence)
│   └── kpi_report.py                ← Rapport KPI multi-fichiers (Excel + Dash)
│
└── utils/
    └── geometry.py                  ← Utilitaires géométriques (chevauchements, intersections)
```

**Flux de données principal :**

```
CSV entrée → csv_reader → [Box] → phases 1–4 → [Pallet] → post_processing (en mémoire) → Phase 6 → csv_writer → CSV sortie
                                                                                                                ↓
                                                                                        pallet_dashboard / kpi_report / app.py
```

Le pipeline est entièrement en mémoire entre les phases 1 et 5 : aucun aller-retour CSV entre l'optimiseur et le post-traitement. La Phase 6 vérifie l'intégrité en mémoire ; l'écriture `write_results_to_csv` n'est effectuée qu'après une Phase 6 réussie.

### 2.2 Technologies utilisées

| Composant | Technologie | Version minimale |
|---|---|---|
| Langage | Python | 3.8 |
| Interface utilisateur | Dash (Plotly) | 2.14.0 |
| Visualisation 3D | Plotly | 5.17.0 |
| Manipulation de données | Pandas | 2.0.0 |
| Calcul numérique | NumPy | 1.24.0 |
| Export image | Kaleido | 0.2.1 |
| Export Excel | openpyxl | 3.1.0 |

### 2.3 Dépendances

**Fichier `requirements.txt` :**

```
dash>=2.14.0
plotly>=5.17.0
pandas>=2.0.0
numpy>=1.24.0
kaleido>=0.2.1
openpyxl>=3.1.0
```

**Bibliothèques standard Python utilisées** (incluses dans toute installation Python) :

- `dataclasses`, `copy`, `csv`, `os`, `sys`, `random`, `time`, `json`
- `argparse`, `pathlib`, `threading`, `socket`, `base64`

---

## 3. Guide d'installation

### 3.1 Conditions préalables

- Python 3.8 ou supérieur installé et accessible via `python` ou `python3`
- `pip` disponible
- Accès en lecture/écriture aux dossiers d'entrée et de sortie
- Navigateur web moderne (Chrome, Firefox, Edge) pour l'interface Dash

### 3.2 Configuration système requise

| Composant | Minimum | Recommandé |
|---|---|---|
| CPU | 2 cœurs | 4 cœurs ou plus |
| RAM | 2 Go | 8 Go |
| Disque | 500 Mo | 2 Go |
| OS | Windows 10 / Linux / macOS | Windows 11 / Ubuntu 22.04 |

> **Note :** Les temps de calcul dépendent fortement du nombre de colis. Pour des lots de plus de 500 colis, la configuration recommandée est conseillée.

### 3.3 Étapes d'installation

**1. Cloner ou décompresser le projet**

```bash
# Si via Git
git clone <url-du-depot>
cd pallet_optimizer

# Ou décompresser l'archive ZIP dans un dossier dédié
```

**2. Créer un environnement virtuel (recommandé)**

```bash
python -m venv venv

# Activer l'environnement
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate
```

**3. Installer les dépendances**

```bash
pip install -r pallet_optimizer/requirements.txt
```

**4. Vérifier l'installation**

```bash
cd pallet_optimizer/pallet_optimizer
python -c "import dash, plotly, pandas, numpy; print('Installation OK')"
```

**5. Lancer l'interface (test rapide)**

```bash
python app.py
# Ouvrir http://localhost:8050 dans le navigateur
```

---

## 4. Guide de configuration

### 4.1 Paramètres de configuration

Tous les paramètres sont centralisés dans `config/parameters.py` via la classe `OptimizationParameters`. L'interface Dash permet de les modifier sans toucher au code.

#### Géométrie de la palette

| Paramètre | Défaut | Unité | Description |
|---|---|---|---|
| `pallet_length` | 130.0 | cm | Dimension X de la palette |
| `pallet_width` | 80.0 | cm | Dimension Y de la palette |
| `pallet_max_height` | 226.0 | cm | Hauteur maximale d'empilement |
| `pallet_max_weight` | 600.0 | kg | Charge maximale |

#### Contraintes physiques et stabilité

| Paramètre | Défaut | Description |
|---|---|---|
| `min_support_ratio` | 0.80 | Fraction de la base d'un colis devant reposer sur un support (80 %) |
| `stability_ratio` | 7.0 | Rapport max hauteur de pile / dimension minimale de la base |

> **Interprétation :** `min_support_ratio = 0.80` signifie qu'au moins 80 % de la surface inférieure d'un colis doit être supportée. `stability_ratio = 7.0` empêche les tours trop minces.

#### Contrainte ergonomique

| Paramètre | Défaut | Unité | Description |
|---|---|---|---|
| `priority2_max_deposit_height` | 160.0 | cm | Hauteur maximale du bas d'un colis P2 (déposé manuellement) |

#### Stratégie multi-client (Phase 3)

| Paramètre | Défaut | Description |
|---|---|---|
| `enable_multi_client` | True | Activer la fusion multi-client (Phases 3 et 4). Mettre à `False` pour conserver toutes les palettes mono-client. |
| `multi_client_minimum_ratio` | 0.13 | **Seuil d'arrêt doux** pour le régime ≥ 11 palettes : la boucle peut s'arrêter quand multi/total > ce seuil ET que la palette mono la moins remplie est déjà bien remplie. |
| `multi_client_maximum_ratio` | 0.17 | **Seuil d'arrêt forcé** pour le régime ≥ 11 palettes : arrêt immédiat dès que multi/total > ce seuil, quelles que soient les conditions. |
| `min_filling_ratio` | 0.35 | Seuil de remplissage moyen pour le régime ≤ 10 palettes. La fusion continue tant que le remplissage projeté reste sous ce seuil. |
| `enable_post_processing` | True | Activer la phase 5 (LNS post-traitement + gap repair + centrage) |

> **Condition d'arrêt composée (régime ≥ 11 palettes) :**  
> Arrêt si `(multi/total > minimum_ratio ET fill(mono la moins remplie) > min_filling_ratio)`  
> **OU** si `multi/total > maximum_ratio`  
> La première condition est un arrêt *doux* (les palettes mono restantes sont déjà bien remplies, pas de gain à fusionner davantage). La seconde est un arrêt *forcé* (plafond absolu).

#### LNS mono-client (Phase 2)

| Paramètre | Défaut | Description |
|---|---|---|
| `lns_mono_time_limit` | 100.0 s | Budget temps |
| `lns_mono_max_iterations` | 500 | Plafond d'itérations |
| `lns_mono_small_box_volume` | 408 000 cm³ | Colis en dessous de ce volume extraits des palettes survivantes à chaque itération |
| `lns_mono_repair_top_k` | 3 | Taille du pool de positions candidates |
| `lns_mono_random_seed` | 42 | Graine aléatoire (reproductibilité) |
| `cost_mono_pallet_count` | 500.0 | Poids du nombre de palettes dans la fonction de coût |
| `cost_mono_last_pallet_filling` | 400.0 | Pénalité sur le taux de remplissage de la palette la moins chargée |

#### LNS multi-client (Phase 4)

| Paramètre | Défaut | Description |
|---|---|---|
| `lns_multi_time_limit` | 40.0 s | Budget temps |
| `lns_multi_max_iterations` | 300 | Plafond d'itérations |
| `lns_multi_destroy_ratio` | 0.33 | Fraction des palettes les moins remplies détruites par itération (minimum 2) |
| `lns_multi_repair_top_k` | 3 | Taille du pool de positions candidates |
| `lns_multi_random_seed` | 42 | Graine aléatoire |
| `cost_multi_pallet_count` | 10.0 | Poids du nombre de palettes |

#### Post-traitement (Phase 5)

| Paramètre | Défaut | Description |
|---|---|---|
| `pp_time_limit` | 20.0 s | Budget temps par groupe |
| `pp_max_iterations` | 250 | Plafond d'itérations par groupe |
| `pp_top_k` | 2 | Taille du pool de placements candidats |
| `pp_random_seed` | 7 | Graine aléatoire |
| `pp_w_contact` | 10.0 | Récompense par cm² de contact vertical P2→P1 |
| `pp_w_fill` | 5.0 | Pénalité sur la variance du taux de remplissage |
| `pp_w_p2` | 5000.0 | Pénalité sur la variance du nombre de P2 entre palettes |
| `pp_w_height` | 5.0 | Pénalité sur le ratio hauteur/hauteur max moyen |
| `pp_w_stability` | 10.0 | Pénalité sur le pire ratio de stabilité |
| `pp_center_min_shift` | 5.0 cm | Décalage minimum pour appliquer le centrage de charge |

### 4.2 Configuration de l'environnement

**Variables d'environnement** (optionnelles, non requises par défaut) :

Aucune variable d'environnement n'est obligatoire. Le système utilise des chemins relatifs depuis le répertoire de travail.

**Structure des dossiers attendue :**

```
<dossier-de-travail>/
├── input/          ← CSV d'entrée (un fichier par commande/lot)
└── output/         ← CSV de résultats, rapports, images
```

Les dossiers `input/` et `output/` sont créés automatiquement si absents.

### 4.3 Intégration des services externes

Le système est **entièrement autonome** (standalone). Il ne communique avec aucun service externe, API, ou base de données. Toutes les données transitent via des fichiers CSV locaux.

Pour une intégration dans un flux SI existant :
- **Entrée** : déposer les fichiers CSV d'entrée dans le dossier `input/`
- **Sortie** : récupérer les fichiers CSV de résultats depuis le dossier `output/`
- **Automatisation** : utiliser `main.py` en ligne de commande (scriptable, sans interface graphique)

---

## 5. Guide d'utilisation

### 5.1 Présentation de l'interface utilisateur

L'interface principale (`app.py`) est une application web Dash organisée en **4 sections** accessibles sans authentification :

```
┌─────────────────────────────────────────────────┐
│  Logo          Pallet Optimizer          Logo   │
├─────────────────────────────────────────────────┤
│  ▼  1 — Paramétrage et Exécution                │
│     [Dossier entrée] [Dossier sortie]           │
│     [Toggles multi-client / post-traitement]    │
│     [Grille de paramètres pliable]              │
│     [▶ Lancer l'exécution]  [Console batch]     │
├─────────────────────────────────────────────────┤
│  ▼  2 — Visualisation                           │
│     [Sélecteur CSV résultats]                   │
│     [Ouvrir le Dashboard 3D]                    │
├─────────────────────────────────────────────────┤
│  ▼  3 — Export images                           │
│     [Sélecteur CSV] [Portée] [▶ Exporter]       │
├─────────────────────────────────────────────────┤
│  ▼  4 — Rapport KPI                             │
│     [Dossier analysé] [📊 Ouvrir le rapport]    │
└─────────────────────────────────────────────────┘
```

Le **dashboard 3D** (`visualization/pallet_dashboard.py`) s'ouvre dans un onglet navigateur indépendant et propose 2 pages :
- **Page 1 — Vue Slots Palettes** (`/`) : grille 2 colonnes, plusieurs palettes par page, vues 3D interactives
- **Page 2 — Vue Zoom Palette** (`/zoom`) : vue agrandie d'une seule palette avec slider de séquence de placement

Le **rapport KPI** (`visualization/kpi_report.py`) est un module indépendant : il scanne le dossier de sortie, produit un fichier Excel `kpi_report_{ts}.xlsx` agrégeant tous les résultats et affiche une vue Dash (accordéon par fichier).

### 5.2 Authentification de l'utilisateur

Le système ne dispose pas de mécanisme d'authentification. L'accès est limité par réseau (le serveur Dash écoute sur `localhost` uniquement par défaut). Pour un déploiement multi-utilisateurs, la configuration du serveur réseau est à la charge de l'administrateur.

### 5.3 Fonctionnalité de base

#### Lancer une optimisation

1. Ouvrir l'interface : `python app.py` → navigateur à `http://localhost:8050`
2. Dans la section **Paramétrage & Exécution** :
   - Sélectionner le dossier contenant le(s) CSV d'entrée
   - Sélectionner le dossier de sortie
   - Ajuster les paramètres si nécessaire (ou garder les valeurs par défaut)
3. Cliquer sur **▶ Lancer l'exécution**
4. Suivre la progression dans la console en temps réel
5. À la fin, le dashboard s'ouvre automatiquement

#### Utilisation en ligne de commande

```bash
cd pallet_optimizer/pallet_optimizer

# Traitement standard (toutes les phases activées)
python main.py

# Avec dossiers personnalisés
python main.py --input-dir /chemin/vers/input --output-dir /chemin/vers/output

# Override de paramètres via JSON (ex. désactiver le post-traitement)
python main.py --params-json '{"enable_post_processing": false}'
```

Les trois arguments supportés par `main.py` sont :

| Argument | Défaut | Description |
|---|---|---|
| `--input-dir` | `input/` | Dossier contenant les CSV d'entrée |
| `--output-dir` | `output/` | Dossier de sortie |
| `--params-json` | `{}` | Chaîne JSON d'overrides transmise à `OptimizationParameters(**overrides)` |

#### Visualiser les résultats

```bash
# Ouvrir le dashboard sur un fichier de résultats existant
python visualization/pallet_dashboard.py output/ma_commande_results_20260420_143022.csv

# Générer le rapport KPI Excel sur un dossier de sortie
python visualization/kpi_report.py output/
```

### 5.4 Fonctionnalités avancées

#### Réglage fin des poids de la fonction de coût (post-traitement)

La fonction de coût du post-traitement combine 5 objectifs :

```
Coût = - w_contact   × Σ(contact P2→P1)     ← maximiser le contact
       + w_fill      × Var(taux remplissage) ← équilibrer les palettes
       + w_p2        × Var(nombre de P2)     ← répartir les P2
       + w_height    × hauteur_moyenne/max   ← minimiser la hauteur
       + w_stability × pire_ratio_stabilité  ← améliorer la stabilité
```

**Conseils de réglage :**

| Objectif prioritaire | Action sur les poids |
|---|---|
| Maximiser le contact P2/P1 | Augmenter `pp_w_contact` (ex : 20–50) |
| Équilibrer le remplissage | Augmenter `pp_w_fill` (ex : 20–100) |
| Répartir P2 uniformément | Augmenter `pp_w_p2` (ex : 10 000–50 000) |
| Minimiser la hauteur | Augmenter `pp_w_height` (ex : 10–30) |
| Améliorer la stabilité | Augmenter `pp_w_stability` (ex : 20–50) |

#### Contrôle de la reproductibilité

Chaque phase LNS possède sa propre graine aléatoire :
- `lns_mono_random_seed` (défaut : 42)
- `lns_multi_random_seed` (défaut : 42)
- `pp_random_seed` (défaut : 7)

Fixer ces graines garantit des résultats identiques à chaque exécution avec les mêmes données.

#### Désactiver la fusion multi-client

Mettre `enable_multi_client = False` (ou décocher dans l'interface) pour conserver toutes les palettes mono-client. Utile pour des contraintes logistiques strictes (séparation par client obligatoire).

#### Réparation des espaces libres (gap repair)

Après le post-traitement LNS, un algorithme de détection d'espaces libres est appliqué automatiquement sur les palettes présentant un « vide en L » entre colonnes P1 :

1. **Détection** : projection XZ avec algorithme de remplissage d'eau (*water fill*)
2. **Direction** : comparaison des hauteurs gauche/droite pour déterminer le sens de déplacement
3. **Réparation** : replacement P1 avec orientations négatives (coin droit/avant à l'EP), puis P2 contact

### 5.5 Dépannage

Voir la section [11.1 Guide de dépannage](#111-guide-de-dépannage).

---

## 6. Pipeline d'optimisation

### 6.1 Vue d'ensemble

```
CSV entrée
    │
    ▼
[Phase 0] Validation CSV
    │
    ▼
[Phase 1] FFD Initial (mono-client)
          First Fit Decreasing
          Tri : priorité ↑, volume ↓, poids ↓
    │
    ▼
[Phase 2] LNS Mono-client
          Objectif : réduire le nombre de palettes
          Coût = 500×n_palettes + 400×min_fill
    │
    ▼
[Phase 3] Fusion Multi-client adaptative
          ≤1 client ou ≤1 palette  → ignoré
          2 palettes               → fusionner si fill moy. < min_filling_ratio
          3..10 palettes           → boucle fill-driven
          11..70 palettes          → boucle avec condition d'arrêt composée
          >70 palettes             → boucle paire-fusion + même condition
    │
    ▼
[Phase 4] LNS Multi-client
          Objectif : réduire le nombre de palettes total
          Coût = 10×n_palettes
    │
    ▼
[Phase 5] Post-traitement LNS
          Objectifs : contact P2/P1, équilibre fill,
                      répartition P2, hauteur, stabilité
          + Gap repair + centrage de charge
    │
    ▼
[Phase 6] Vérification sécurité
          - Comptage colis entrée == sortie
          - Unicité des séquences de placement par palette
    │
    ▼
CSV résultats + rapport d'exécution
```

### 6.2 Phase 1 — First Fit Decreasing (FFD)

**Module :** `heuristics/first_fit_decreasing.py`

**Algorithme :**
1. Regrouper les colis par `client_id`
2. Pour chaque client, trier : priorité ↑ (P1 avant P2), volume ↓, poids ↓
3. Pour chaque colis, essayer chaque palette existante (premier qui accepte)
4. Si aucune palette n'accepte, ouvrir une nouvelle palette
5. Placement : minimiser (z, x, y) via heuristique Extreme Points

**Heuristique Extreme Points :**

Un *extreme point* (EP) est une position (x, y) candidate générée par les coins existants :
- Origine (0, 0)
- (x + longueur, y) pour chaque colis déjà placé
- (x, y + largeur) pour chaque colis déjà placé

Pour chaque EP, le z est calculé par projection vers le bas (`find_support_z`).

**Score de placement P1 :**
```
score = (z, cx, cy, height_score, -residual_area)
```
où `residual_area` estime la surface libre restante après placement.

### 6.3 Phase 2 — LNS Mono-client

**Module :** `heuristics/lns_mono.py`

**Cycle d'une itération :**

```
Détruire
  └── Extraire la palette la moins remplie (tous ses colis)
  └── Extraire les petits colis (< lns_mono_small_box_volume) des palettes survivantes
        → Renuméroter les séquences des colis restants (fermeture des trous)
  └── Supprimer les palettes devenues vides

Réparer
  └── Mélanger le pool aléatoirement
  └── Trier P1 avant P2
  └── Pour chaque colis :
        Générer tous les placements valides (EP × orientation)
        Tirer aléatoirement parmi les top-k
        Placer ou ouvrir une nouvelle palette

Évaluer
  └── coût = 500×n_palettes + 400×min_fill_ratio
  └── Accepter si coût < meilleur coût précédent
```

> **Note technique :** l'extraction des petits colis crée des trous dans la numérotation des séquences des palettes survivantes. Ces séquences sont immédiatement renumérotées de manière compacte (1, 2, 3 …) après extraction afin que la réinsertion via `len(pallet.boxes) + 1` produise toujours un numéro unique.

### 6.4 Phase 3 — Fusion Multi-client adaptative

**Module :** `optimizer/pallet_optimizer.py`

La stratégie est déterminée une seule fois, avant le début de la boucle, en fonction du nombre de palettes `n` après la Phase 2.

#### Régimes

| Régime | Condition | Stratégie |
|---|---|---|
| **Ignoré** | ≤ 1 client **ou** ≤ 1 palette | Phase 3 et 4 sautées |
| **2 palettes** | n = 2 | Fusionner les deux si leur fill moyen < `min_filling_ratio` |
| **3..10 palettes** | 3 ≤ n ≤ 10 | Fusion initiale des 2 moins remplies si fill moyen < seuil, puis boucle *fill-driven* |
| **11..70 palettes** | 11 ≤ n ≤ 70 | Fusion initiale des 2 moins remplies, puis boucle : ajouter la palette mono la moins remplie au pool multi, une par une |
| **> 70 palettes** | n > 70 | Boucle : fusionner les 2 palettes les moins remplies dans le pool multi à chaque itération |

#### Condition d'arrêt des régimes 3..10

La boucle s'arrête si :
- Le fill combiné `(fill_mono + fill_avg_multi) / 2 ≥ min_filling_ratio`, **ou**
- Le nombre de palettes n'a pas diminué (aucun gain), **ou**
- Plus aucune palette mono disponible.

#### Condition d'arrêt composée (régimes 11..70 et > 70)

À chaque itération, on calcule `multi_ratio = multi_count / total_count`.

**Arrêt forcé (plafond absolu) :**
```
multi_ratio > multi_client_maximum_ratio   (défaut : 0.17)
```

**Arrêt doux (gain marginal nul) :**
```
multi_ratio > multi_client_minimum_ratio   (défaut : 0.13)
ET fill(palette mono la moins remplie) > min_filling_ratio  (défaut : 0.35)
```

L'arrêt doux signifie que le seuil minimum est atteint ET que les palettes mono restantes sont déjà bien remplies — les fusionner apporterait peu.

#### Gestion des palettes restantes (Phase 4)

Après la Phase 3, l'orchestrateur identifie les palettes mono *nouvellement créées* par un repack (par opposition aux palettes mono originales intactes) en comparant les identités Python (`id()`) aux objets pré-Phase 3. Ces palettes sont passées à la Phase 4 comme `extra_mono` pour leur donner une seconde chance de fusion.

### 6.5 Phase 4 — LNS Multi-client

**Module :** `heuristics/lns_multi.py`

Identique à la Phase 2 mais opère sur les palettes multi-client (et les `extra_mono` identifiés en Phase 3). Le critère de destruction est le ratio `lns_multi_destroy_ratio` (33 % des palettes les moins remplies, minimum 2). Les palettes mono originales intactes sont retournées sans modification.

### 6.6 Phase 5 — Post-traitement

**Module :** `heuristics/post_processing.py`

**Signature publique :** `postprocess(pallets: List[Pallet], boxes: List[Box], params: OptimizationParameters) -> List[Pallet]`

La phase 5 fonctionne entièrement en mémoire : elle reçoit directement les objets `Pallet` produits par les phases 1–4, applique l'algorithme décrit ci-dessous, et retourne une nouvelle liste de `Pallet`.

**Algorithme par groupe (mono ou multi) :**

```
1. Dépalettiser tous les P2 → pool (mélangé aléatoirement)

2. Si 1 seule palette :
     Replacer P2 avec top-k (z, -contact/aire, x, y)

3. Si N > 1 palettes et delta_fill > 15 % :
     Phase égalisation fill (itérations) :
       Donneur = palette la plus remplie
       Receveur = palette la moins remplie
       Déplacer 1-2 plus petits P1 (volume) de donneur → receveur
       Repalettiser P1 des deux avec scoring core : (z, cx, cy, height_score, -residual)
       Accepter si coût améliore

4. Phase placement P2 (itérations) :
     Mélanger le pool
     Pour chaque P2, choisir une palette aléatoirement
     Top-k placement par contact (z, -contact, x, y)
     Accepter si coût améliore
     Si aucune amélioration : conserver l'état original

5. Gap repair (sur palettes flagguées) :
     Détection espace libre (water fill XZ)
     Direction (comparer hauteurs gauche/droite)
     Replacement P1 avec orientations signées (±X, ±Y)
     Replacement P2 contact
     Accepter si gap diminue

6. Centrage de charge :
     Décaler tous les colis de shift_x = (pallet_length - max_x) / 2
     Décaler tous les colis de shift_y = (pallet_width  - max_y) / 2
     Appliquer seulement si décalage > pp_center_min_shift
```

**Contraintes de sécurité :**
- Si un P2 ne peut être placé nulle part : itération abandonnée
- Si le nombre de colis varie en sortie : revert à l'état original

### 6.7 Phase 6 — Vérification d'intégrité

**Module :** `main.py`

La Phase 6 s'exécute en mémoire, **avant** toute écriture CSV. Le fichier résultat n'est créé que si tous les contrôles passent. Un fichier résultat existant garantit donc une exécution intègre de bout en bout.

**Contrôles effectués :**

| Contrôle | Code erreur | Description |
|---|---|---|
| Comptage de colis | `ERR_SECURITY` | `len(output_ids) == len(input_ids)` — aucun colis perdu ni dupliqué |
| Colis manquants | `ERR_SECURITY` | Tous les `box_id` d'entrée sont présents en sortie |
| Colis supplémentaires | `ERR_SECURITY` | Aucun `box_id` en sortie qui n'existait pas en entrée |
| Unicité des séquences | `ERR_SECURITY` | Au sein de chaque palette, tous les numéros de séquence (`PlacedBox.sequence`) sont distincts |

> **Codes statut dans le log :**  
> `OK` — intégrité vérifiée, résultat écrit.  
> `ERR_SECURITY` — échec d'un ou plusieurs contrôles, résultat non écrit.  
> `ERR_VALIDATION` — CSV d'entrée invalide (Phase 0).  
> `ERR_EMPTY_INPUT` — CSV parsé mais aucun colis.  
> `ERR_EXCEPTION` — exception non gérée.

### 6.8 Contraintes de placement

Toutes les contraintes sont vérifiées dans `core/placement_engine.py:is_valid_placement()` dans l'ordre suivant :

1. **Géométrie** : le colis tient dans les dimensions de la palette, pas de collision 3D
2. **Poids** : `pallet.total_weight + box.weight ≤ pallet.max_weight`
3. **Ergonomie** : pour P2 uniquement — `z ≤ priority2_max_deposit_height`
4. **Stacking** : P1 ne peut reposer que sur P1 ou surfaces `stackable=True` ; P2 idem
5. **Support** : si z > 0, au moins `min_support_ratio` de la base supportée
6. **Stabilité** : pour P1 uniquement — `stack_height / min_base_dim < stability_ratio`

---

## 7. Formats de données

### 7.1 Format CSV d'entrée

**Séparateur :** point-virgule (`;`)  
**Encodage :** UTF-8 (avec ou sans BOM)  
**Emplacement par défaut :** `input/`

#### Colonnes requises

| Colonne | Type | Contraintes | Exemple |
|---|---|---|---|
| `id` | chaîne | Unique dans le fichier | `BOX-001` |
| `priority` | entier | 1 (meuble) ou 2 (colis manuel) | `1` |
| `length` | flottant | > 0, ≤ `pallet_max_height` (cm) | `47.9` |
| `width` | flottant | > 0, ≤ `pallet_max_height` (cm) | `26.8` |
| `height` | flottant | > 0, ≤ `pallet_max_height` (cm) | `17.8` |
| `weight` | flottant | > 0 (kg) | `26.1` |
| `client_id` | entier | Identifiant du client | `2` |
| `allowed_orientations` | chaîne | `all` ou liste séparée par virgules | `LWH,WLH` |
| `stackable` | chaîne | `true` ou `false` | `true` |

#### Colonnes optionnelles

Ces colonnes sont ignorées par le moteur d'optimisation : l'algorithme tourne sans (les valeurs par défaut sont des chaînes vides). Elles sont lues par `file_io/csv_reader.py` via `row.get(col, "")` puis propagées dans les objets `Box` / `PlacedBox` et dans le CSV de sortie. Elles enrichissent uniquement les visualisations (infobulles du dashboard 3D, rapport KPI Excel). Si absentes du CSV d'entrée, ces informations ne seront simplement pas affichées.

| Colonne | Type | Description | Exemple |
|---|---|---|---|
| `designation` | chaîne | Libellé ou désignation produit du colis | `Carton A4 ramettes` |
| `location` | chaîne | Emplacement / référence logistique (zone, allée, casier...) | `Zone B - Allée 12` |

#### Valeurs d'orientation acceptées

| Valeur | Dimensions placées (L×l×H) | Description |
|---|---|---|
| `LWH` | longueur × largeur × hauteur | Orientation originale |
| `WLH` | largeur × longueur × hauteur | Rotation 90° axe Z |
| `LHW` | longueur × hauteur × largeur | Rotation 90° axe X |
| `WHL` | largeur × hauteur × longueur | Combinaison |
| `HLW` | hauteur × longueur × largeur | Combinaison |
| `HWL` | hauteur × largeur × longueur | Combinaison |
| `all` | — | Toutes les 6 orientations |

#### Exemple de fichier d'entrée

```csv
id;priority;length;width;height;weight;client_id;allowed_orientations;stackable
BOX-001;1;47.9;26.8;17.8;26.1;2;all;true
BOX-002;1;27.9;45.7;16.6;7.8;1;all;true
BOX-003;2;50.0;49.5;26.0;35.6;3;LWH,WLH;false
BOX-004;2;32.5;28.0;21.5;12.0;2;all;true
```

### 7.2 Format CSV de sortie

**Séparateur :** point-virgule (`;`)  
**Encodage :** UTF-8  
**Nommage :** `{nom_entrée}_results_{AAAAMMJJ_HHMMSS}.csv`  
**Contenu :** un unique CSV final est produit par exécution. Il intègre, lorsque `enable_post_processing = True`, le résultat de la phase 5. L'écriture n'a lieu que si la Phase 6 (vérification d'intégrité) passe sans erreur.

| Colonne | Type | Description |
|---|---|---|
| `pallet_id` | entier | Numéro de palette (base 1) |
| `sequence` | entier | Ordre de placement dans la palette (base 1, unique par palette) |
| `box_id` | chaîne | Identifiant du colis (depuis l'entrée) |
| `client_id` | entier | Identifiant client |
| `priority` | entier | 1 ou 2 |
| `x` | flottant | Position coin inférieur-gauche-arrière — axe X (cm) |
| `y` | flottant | Position coin inférieur-gauche-arrière — axe Y (cm) |
| `z` | flottant | Position coin inférieur-gauche-arrière — axe Z (cm, 0 = plancher) |
| `orientation` | chaîne | Orientation retenue (ex. `LWH`) |
| `length` | flottant | Dimension X placée (cm, après rotation) |
| `width` | flottant | Dimension Y placée (cm, après rotation) |
| `height` | flottant | Dimension Z placée (cm, après rotation) |
| `weight` | flottant | Poids du colis (kg) |
| `pallet_length` | flottant | Dimension X de la palette (cm) |
| `pallet_width` | flottant | Dimension Y de la palette (cm) |
| `pallet_height` | flottant | Hauteur max de la palette (cm) |
| `multi_client` | chaîne | `yes` / `no` |
| `volumetric_fill_ratio` | flottant | 0.0–1.0 (volume utilisé / volume total palette) |
| `worst_stability_ratio` | flottant | Pire ratio hauteur/base d'empilement (indicatif) |

### 7.3 Fichiers générés automatiquement

Le suffixe `{ts}` vaut `AAAAMMJJ_HHMMSS` (horodatage d'exécution).

| Fichier | Description |
|---|---|
| `output/{stem}_results_{ts}.csv` | Résultat final — écrit **uniquement si la Phase 6 passe** |
| `output/{stem}_log_{ts}.txt` | Journal complet d'exécution (copie de la sortie console) |
| `output/execution_summary_{ts}.txt` | Récapitulatif par lot : OK / ERR_SECURITY / ERR_EXCEPTION par fichier |
| `output/kpi_report_{ts}.xlsx` | Rapport KPI Excel agrégé (tous fichiers du dossier) — généré en fin de lot |
| `intermediate/{stem}_phase*.csv` | Snapshots par phase (dossier purgé au début de chaque lot) |

---

## 8. Modèles de données

### 8.1 Box (colis non placé)

```python
@dataclass
class Box:
    id: str                                      # identifiant unique
    priority: int                                # 1 = meuble, 2 = colis manuel
    length: float                                # dimension originale X (cm)
    width: float                                 # dimension originale Y (cm)
    height: float                                # dimension originale Z (cm)
    weight: float                                # poids (kg)
    client_id: int                               # identifiant client
    allowed_orientations: List[Orientation]      # orientations autorisées
    stackable: Dict[Orientation, bool]           # peut-on poser quelque chose dessus ?
```

**Propriétés :**
- `volume` : longueur × largeur × hauteur (cm³)
- `get_oriented_dims(orientation)` : tuple (L, l, H) dans l'orientation donnée
- `is_stackable_in(orientation)` : bool

### 8.2 PlacedBox (colis positionné)

```python
@dataclass
class PlacedBox:
    box_id: str          # référence à Box.id
    x: float             # coin inférieur-gauche-arrière — X (cm)
    y: float             # coin inférieur-gauche-arrière — Y (cm)
    z: float             # coin inférieur-gauche-arrière — Z (cm)
    orientation: Orientation
    length: float        # dimension X placée (cm, déjà orientée)
    width: float         # dimension Y placée (cm, déjà orientée)
    height: float        # dimension Z placée (cm, déjà orientée)
    priority: int
    weight: float
    client_id: int
    stackable: bool      # peut-on poser quelque chose sur ce colis dans cette orientation
    designation: str = ""
    location: str = ""
    sequence: int = 0    # ordre de placement (1-based, unique par palette)
```

**Propriétés géométriques :**
- `x_max`, `y_max`, `z_max` : coins opposés
- `base_area` : surface inférieure (length × width)
- `volume` : volume placé
- `bounds()` : tuple (x_min, x_max, y_min, y_max, z_min, z_max)

### 8.3 Pallet (palette)

```python
@dataclass
class Pallet:
    id: int
    length: float         # dimension X (cm)
    width: float          # dimension Y (cm)
    max_height: float     # hauteur max (cm)
    max_weight: float     # poids max (kg)
    boxes: List[PlacedBox]  # colis placés
```

**Propriétés :**
- `total_weight` : poids total des colis (kg)
- `remaining_weight` : capacité restante (kg)
- `pallet_volume` : volume total (cm³)
- `used_volume` : somme des volumes des colis (cm³)
- `volumetric_fill_ratio` : taux de remplissage volumétrique (0.0–1.0)
- `current_height` : hauteur actuelle (cm)
- `client_ids` : ensemble des `client_id` présents
- `is_multi_client` : True si plus d'un client
- `priority1_count`, `priority2_count` : comptages
- `worst_stability_ratio` : pire ratio hauteur/base d'une sous-colonne P1 (indicatif)

### 8.4 Orientation

```
┌──────────┬──────────────┬──────────────┐
│ Enum     │ Dim X placée │ Dim Z placée │
├──────────┼──────────────┼──────────────┤
│ LWH      │ length       │ height       │
│ WLH      │ width        │ height       │
│ LHW      │ length       │ width        │
│ WHL      │ width        │ length       │
│ HLW      │ height       │ width        │
│ HWL      │ height       │ length       │
└──────────┴──────────────┴──────────────┘
```

**Système de coordonnées :**
- Axe X : profondeur de la palette (longueur)
- Axe Y : largeur de la palette
- Axe Z : hauteur (vertical, 0 = plancher)
- Origine (0, 0, 0) : coin inférieur-gauche-arrière de la palette

---

## 9. Essais et validation

### 9.1 Plan d'essai

Les tests à réaliser pour valider une livraison :

| Type | Objectif | Méthode |
|---|---|---|
| Validation entrée | Rejeter les CSV malformés | Tester csv_reader avec fichiers invalides |
| Contraintes physiques | Aucun colis hors palette ni en collision | Vérifier `is_valid_placement` sur résultats |
| Contrainte poids | Respect de `pallet_max_weight` | Sommer les poids par palette |
| Contrainte ergonomique | P2 avec z ≤ 160 cm | Vérifier z de chaque P2 |
| Conservation des colis | Aucun colis perdu ni dupliqué | Compter et comparer les IDs (Phase 6) |
| Unicité des séquences | Pas de doublon de séquence par palette | Phase 6 — contrôle automatique |
| Multi-client | Chaque palette multi-client a ≥ 2 clients | Vérifier `client_ids` |
| Reproductibilité | Même graine → même résultat | Exécuter 2 fois avec mêmes paramètres |

### 9.2 Cas de tests

**Test 1 : Fichier vide**
```csv
id;priority;length;width;height;weight;client_id;allowed_orientations;stackable
```
→ Résultat attendu : erreur de validation, 0 palettes générées

**Test 2 : Colis plus grand que la palette**
```csv
id;priority;length;width;height;weight;client_id;allowed_orientations;stackable
XXL-001;1;200.0;200.0;300.0;100.0;1;all;true
```
→ Résultat attendu : erreur de validation (hauteur 300 > `pallet_max_height` 226)

**Test 3 : Colis P2 trop haut**
```csv
id;priority;length;width;height;weight;client_id;allowed_orientations;stackable
P2-001;2;50.0;50.0;50.0;10.0;1;all;true
```
→ Résultat attendu : placé avec z ≤ 160 (si physiquement possible)

**Test 4 : Un seul colis**
→ Résultat attendu : 1 palette avec 1 colis à (0, 0, 0)

**Test 5 : Reproductibilité**
→ Exécuter 2 fois avec `lns_mono_random_seed=42`, `lns_multi_random_seed=42`, `pp_random_seed=7`  
→ Résultat attendu : CSV de sortie bit-à-bit identiques

**Test 6 : Unicité des séquences après fusion multi-client**
→ Exécuter avec `enable_multi_client=True` sur un lot de 20+ palettes  
→ Résultat attendu : Phase 6 `OK` — aucun doublon de séquence détecté sur les palettes produites par le repack

### 9.3 Résultats des tests

Les vérifications automatiques suivantes sont appliquées à chaque exécution (`main.py`, Phase 6) :

- **Conservation des colis** : compte de colis en entrée == compte en sortie
- **Absence de colis fantômes** : chaque `box_id` de sortie existe en entrée
- **Absence de pertes** : chaque `box_id` d'entrée est présent en sortie
- **Unicité des séquences** : pour chaque palette, tous les numéros `sequence` sont distincts
- **Aucune collision** : vérifiée implicitement par `is_valid_placement` lors du placement
- **Contrainte ergonomique** : vérifiée par `is_valid_placement` pour P2

---

## 10. Déploiement

### 10.1 Processus de déploiement

**Déploiement local (usage standard) :**

```bash
# 1. Installer les dépendances
pip install -r pallet_optimizer/requirements.txt

# 2. Lancer l'interface
cd pallet_optimizer/pallet_optimizer
python app.py
# → Ouvre http://localhost:8050
```

**Déploiement sur serveur partagé (multi-utilisateurs) :**

Pour exposer l'interface sur un réseau local :

```python
# Modifier dans app.py, ligne de démarrage du serveur :
app.run(host="0.0.0.0", port=8050, debug=False)
```

> Sans mécanisme d'authentification, l'accès est public sur le réseau concerné. À réserver aux réseaux d'entreprise sécurisés.

**Déploiement Docker (intégré) :**

Le projet fournit à la racine un pipeline Docker complet :

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image `python:3.11-slim`, installe `requirements.txt`, copie le package `pallet_optimizer/`, expose le port `8050`. Point d'entrée par défaut : `python app.py`. Variables `PALLET_HOST=0.0.0.0` et `PALLET_PORT=8050` (surchargeables avec `-e`). |
| `docker-compose.yml` | Deux services partageant la même image : `dashboard` (long-running, port 8050) et `optimizer` (profil `optimizer`, exécution batch ponctuelle). |
| `.dockerignore` | Exclut `venv/`, caches Python, `input/`, `output/`, `intermediate/`, docs et `.git`. |

**Service `dashboard` — interface Dash en continu :**

```bash
docker compose up -d dashboard
# Accès navigateur : http://localhost:8050
```

**Service `optimizer` — traitement batch ponctuel :**

```bash
docker compose run --rm optimizer
# Les résultats apparaissent dans ./output/ côté hôte
```

**Override de paramètres en Docker :**

```bash
docker compose run --rm optimizer \
  python main.py --input-dir /app/input --output-dir /app/output \
  --params-json '{"enable_post_processing": false}'
```

### 10.2 Notes de version

| Version | Date | Résumé |
|---|---|---|
| 1.0 | Avril 2026 | Version initiale — 5 phases, interface Dash, dashboard 3 pages |
| 1.1 | Avril 2026 | Réorganisation modulaire, pipeline Phase 5 en mémoire, CLI `--params-json`, KPI Excel |
| 1.2 | Mai 2026 | Nouvelle stratégie Phase 3 (régimes 11..70 / >70, condition d'arrêt composée, paramètre `multi_client_maximum_ratio`) ; contrôle d'unicité des séquences en Phase 6 ; correction bug séquences LNS-mono |

### 10.3 Problèmes connus et limites

| Problème | Contexte | Contournement |
|---|---|---|
| Temps de calcul élevé | > 300 colis P1 avec LNS mono time_limit = 100s | Réduire `lns_mono_time_limit` ou `lns_mono_max_iterations` |
| Colis P2 non placés | Palettes très remplies, z disponible > 160 cm | Vérifier `priority2_max_deposit_height`, ou distribuer différemment les P1 |
| Port 8050 occupé | Si une instance précédente est encore active | Le système choisit automatiquement un port libre |
| Export PNG lent | Kaleido crée un sous-processus à la première utilisation | Normal, délai uniquement au premier export |
| Gap repair sans amélioration | Gap vertical entre colonnes — non amélioré par la direction X | Limitation connue : le gap vertical nécessite une stratégie spécifique |

---

## 11. Assistance et maintenance

### 11.1 Guide de dépannage

#### Le bouton "Lancer" est grisé

**Cause :** Les champs dossier d'entrée ou de sortie sont vides ou invalides.  
**Solution :** Vérifier que les deux champs sont remplis et que les dossiers existent.

#### Aucun fichier CSV trouvé dans le dossier d'entrée

**Cause :** Le dossier sélectionné ne contient pas de fichiers `.csv`.  
**Solution :** Déplacer les fichiers d'entrée dans le bon dossier ou sélectionner le bon chemin.

#### Erreur de validation CSV à l'exécution

**Message type :** `[Validation] Erreur dans fichier X : colonne 'id' manquante`  
**Solution :** Vérifier le séparateur (doit être `;`), les noms de colonnes exacts, et l'encodage (UTF-8).

#### ERR_SECURITY — sequence duplicates

**Symptôme :** Le fichier de résultats n'est pas produit ; le log indique `sequence duplicates in N pallet(s)`.  
**Cause :** Deux colis sur la même palette partagent le même numéro de séquence de placement. Ce cas ne devrait plus se produire depuis la v1.2 (correction du bug LNS-mono). S'il persiste, vérifier que la version du code est bien à jour.

#### ERR_SECURITY — box count / missing / extra

**Symptôme :** Le log indique `count mismatch` ou `box(es) missing/extra`.  
**Cause :** Un colis n'a pas pu être placé (dimensions dépassant les limites de la palette, ou contrainte de poids trop restrictive).  
**Solution :** Vérifier les dimensions des colis problématiques dans le log d'exécution.

#### Le dashboard ne s'ouvre pas automatiquement

**Solution :** Ouvrir manuellement un navigateur à `http://localhost:{port}` (le port est affiché dans la console).

#### Consommation mémoire élevée

**Cause :** Beaucoup de colis et/ou temps LNS long avec nombreuses itérations.  
**Solution :** Réduire `lns_mono_max_iterations`, `lns_mono_time_limit`, ou `pp_max_iterations`.

#### Résultats différents d'une exécution à l'autre

**Cause :** Graines aléatoires non fixées (ou système d'exploitation différent).  
**Solution :** Fixer `lns_mono_random_seed`, `lns_multi_random_seed`, `pp_random_seed` à des valeurs constantes.

### 11.2 Foire aux questions (FAQ)

**Q : Peut-on traiter plusieurs fichiers CSV en une seule exécution ?**  
R : Oui. Le système traite tous les fichiers `.csv` présents dans le dossier d'entrée en séquence.

**Q : Pourquoi un fichier de résultats n'est-il pas toujours produit ?**  
R : L'écriture du CSV résultat est conditionnée au succès de la Phase 6 (vérification d'intégrité). Si la Phase 6 échoue (code `ERR_SECURITY`), le fichier n'est pas créé afin de garantir qu'un fichier résultat existant est toujours valide. Le log d'exécution détaille la raison de l'échec.

**Q : Pourquoi certains P2 sont-ils sur la même palette que des colis d'un client différent ?**  
R : Seuls les P1 (meubles) sont soumis à la contrainte mono/multi-client dans les phases 3 et 4. Les P2 sont répartis librement par le post-traitement pour maximiser le contact avec les P1.

**Q : Le ratio de stabilité affiché dans le dashboard est-il une contrainte ou un indicateur ?**  
R : C'est un **indicateur post-hoc**. La contrainte réelle de stabilité (appliquée pendant le placement) est `stability_ratio` dans les paramètres. Le `worst_stability_ratio` affiché est une analyse après placement.

**Q : Comment accélérer les calculs ?**  
R : Réduire par ordre d'impact : `lns_mono_time_limit` → `lns_mono_max_iterations` → `lns_multi_time_limit` → `pp_time_limit`.

**Q : Quelle est la différence entre `multi_client_minimum_ratio` et `multi_client_maximum_ratio` ?**  
R : Le minimum (0.13 par défaut) est un seuil *doux* : la boucle peut s'arrêter si ce seuil est dépassé ET que les palettes mono restantes sont déjà bien remplies. Le maximum (0.17 par défaut) est un plafond *forcé* : la boucle s'arrête dès que ce seuil est dépassé, quelles que soient les conditions.

**Q : L'orientation `all` autorise-t-elle vraiment les 6 rotations pour tous les colis ?**  
R : Oui, mais la contrainte `stackable` s'applique aussi. Un colis avec `stackable=false` ne peut recevoir aucun autre colis dessus, quelle que soit l'orientation.

### 11.3 Coordonnées

| Rôle | Contact |
|---|---|
| Développement | victo.andre74@gmail.com |

---

## 12. Journal des modifications

### 12.1 Historique des versions

| Version | Date | Auteur | Type |
|---|---|---|---|
| 1.0.0 | Avril 2026 | V. André | Version initiale |
| 1.1.0 | Avril 2026 | V. André | Réorganisation modulaire + pipeline en mémoire |
| 1.2.0 | Mai 2026 | V. André | Nouvelle stratégie Phase 3 + intégrité Phase 6 + correction LNS-mono |

### 12.2 Résumé des modifications

**Version 1.0.0 (Avril 2026)**

- Pipeline d'optimisation 5 phases complet (FFD + LNS mono + fusion + LNS multi + post-traitement)
- Interface utilisateur Dash avec paramètres configurables
- Dashboard 3 pages (Pallets Slots View / Pallet Zoom View / Report)
- Algorithme de détection et réparation des espaces libres (water fill + gap repair)
- Fonction de coût post-traitement à 5 objectifs (contact, fill, P2, hauteur, stabilité)
- Export PNG et HTML
- Centrage automatique de la charge sur chaque palette

**Version 1.1.0 (Avril 2026)**

- `post_processing.py` déplacé dans `heuristics/`
- `pallet_dashboard.py`, `export_pallet_images.py`, nouveau `kpi_report.py` regroupés dans `visualization/`
- Fichier racine `_runner.py` supprimé — logique fusionnée dans `main.py`
- Pipeline phases 1–5 entièrement en mémoire (plus de round-trip CSV entre l'optimiseur et le post-traitement). Unique écriture CSV après la phase 5
- Nouveau paramètre `enable_post_processing` (remplace le drapeau CLI `--no-post-pro`)
- Argument CLI `--params-json` : override JSON de n'importe quel paramètre sans toucher `parameters.py`
- Interface Dash enrichie d'une section 4 — **Rapport KPI** (export Excel via `openpyxl`)
- Dashboard 3D réduit à 2 pages (Vue Slots + Vue Zoom)
- Fichier de log renommé `{stem}_log_{ts}.txt`
- Ajout de la dépendance `openpyxl>=3.1.0`

**Version 1.2.0 (Mai 2026)**

- **Phase 3 — Nouvelle stratégie adaptative :**
  - Nouveaux régimes : 11..70 palettes (anciennement 11..100) et > 70 (anciennement > 100)
  - Nouveau paramètre `multi_client_maximum_ratio` (défaut : 0.17) — plafond forcé de fusion
  - Condition d'arrêt composée pour les régimes ≥ 11 palettes : arrêt doux quand `multi/total > minimum AND fill(mono) > min_fill`, arrêt forcé quand `multi/total > maximum`
  - Interface Dash : nouveau champ "Seuil d'arrêt multi-client (max)" avec activation/désactivation conditionnelle
- **Phase 6 — Vérification d'unicité des séquences :**
  - Nouveau contrôle : au sein de chaque palette, tous les numéros `sequence` doivent être distincts
  - Code erreur `ERR_SECURITY` avec message `sequence duplicates in N pallet(s)` si violation
  - Le fichier résultat n'est écrit que si ce contrôle passe (comportement identique aux autres contrôles Phase 6)
- **Correction — LNS-mono (`heuristics/lns_mono.py`) :**
  - Bug : après extraction des petits colis d'une palette survivante, les séquences restantes créaient des trous (ex : 1, 3, 5). La réinsertion via `len(pallet.boxes) + 1` pouvait produire un numéro déjà utilisé (ex : 4 OK, puis 5 → collision avec l'existant 5)
  - Fix : renumérotation compacte (1, 2, 3 …) des séquences restantes immédiatement après l'extraction, avant la réparation

---

## 13. Glossaire

### 13.1 Termes et définitions

| Terme | Définition |
|---|---|
| **Bin packing 3D** | Problème d'optimisation combinatoire : placer des boîtes rectangulaires dans des conteneurs en minimisant l'espace perdu |
| **Colis P1** | Colis de priorité 1 (meubles). Placés en premier, occupent le bas de la palette, ne peuvent être empilés que sur des surfaces appropriées |
| **Colis P2** | Colis de priorité 2 (petits colis, déposés manuellement). Placés après les P1, soumis à une contrainte ergonomique de hauteur |
| **Condition d'arrêt composée** | Critère d'arrêt de la Phase 3 (régimes ≥ 11 palettes) combinant un seuil doux (`minimum_ratio` + `min_filling_ratio`) et un seuil forcé (`maximum_ratio`) |
| **Contact P2→P1** | Surface verticale de contact entre un colis P2 et un colis P1 sur une face latérale partagée. Objectif à maximiser pour la stabilité physique |
| **Extreme Point (EP)** | Position (x, y) candidate générée par les coins des colis déjà placés. Fondement de l'heuristique de placement |
| **FFD** | First Fit Decreasing — heuristique d'emballage : les boîtes sont triées par taille décroissante et placées sur la première palette qui les accepte |
| **Fill ratio** | Taux de remplissage volumétrique d'une palette : volume utilisé / volume total × 100 % |
| **Gap** | Espace libre enfermé entre deux colonnes de colis P1 — détecté par l'algorithme water fill |
| **Gap repair** | Algorithme de post-traitement qui repositionne les colis P1 pour combler les espaces libres en L |
| **LNS** | Large Neighbourhood Search — métaheuristique d'optimisation : détruire une partie de la solution, puis la reconstruire de manière guidée |
| **Multi-client** | Palette contenant des colis appartenant à au moins deux clients différents |
| **Orientation** | L'une des 6 rotations possibles d'un colis rectangulaire dans l'espace 3D |
| **Palette EUR** | Palette europalette standard : 130 × 80 cm, hauteur max 226 cm (valeurs par défaut du système) |
| **Post-traitement** | Phase 5 de l'optimisation : raffinement des positions P2, équilibrage des palettes, centrage de charge |
| **Ratio de support** | Fraction de la surface inférieure d'un colis reposant sur un support. Contrainte min : 80 % par défaut |
| **Ratio de stabilité** | Rapport hauteur d'empilement / dimension minimale de la base. Contrainte max : 7.0 par défaut |
| **Séquence de placement** | Ordre dans lequel les colis ont été placés sur une palette. Unique par palette et par colis. Utilisé par le mode Zoom View avec slider et vérifié en Phase 6 |
| **Signed placement** | Extension de l'heuristique EP qui teste les 4 positions (±X, ±Y) à chaque extreme point pour remplir les vides en L |
| **Stackable** | Propriété d'un colis indiquant si d'autres colis peuvent être posés dessus dans cette orientation |
| **Top-k** | Mécanisme d'exploration : parmi les k meilleurs placements valides, un est choisi aléatoirement. Contrôle le compromis exploration/exploitation |
| **Taux de remplissage volumétrique** | Voir *fill ratio* |
| **Water fill** | Algorithme de détection d'espaces libres : simule le remplissage d'eau dans le profil de hauteur XZ pour quantifier les vides en L |
| **Worst stability ratio** | Indicateur post-hoc du pire ratio de stabilité sur la palette. Affiché dans le dashboard, ne bloque pas le placement |
