# Revue de code & analyse de risques — Pallet Optimizer

> **Date** : 2026-06-10
> **Périmètre** : intégralité du code Python du dépôt (`~14 500` lignes, 8 packages).
> **Méthode** : lecture ciblée de chaque module + vérification manuelle des constats
> à fort enjeu (références `fichier:ligne` confirmées dans le code).
> **Nature** : analyse statique / revue humaine assistée — **aucune** exécution, aucun
> code modifié. Document purement consultatif.

---

## 1. Résumé exécutif

L'architecture est **propre et bien découpée** (couches `models` / `core` / `heuristics`
/ `optimizer` / `file_io` / `visualization`), la conservation des colis est protégée par
une vérification d'intégrité dédiée (Phase 6), et le parsing CSV est défensif
(orientations en liste blanche, pas d'`eval`, gestion du BOM). **Aucune vulnérabilité
d'exécution de code à distance n'a été trouvée** (voir l'annexe A pour les fausses
alertes écartées).

Les risques résiduels se concentrent sur **trois axes** :

1. **Sécurité de déploiement** — les apps Dash n'ont aucune authentification ; exposées
   sur le réseau (`PALLET_HOST=0.0.0.0`, mode Docker) elles permettent à un tiers de
   piloter des lectures/écritures de fichiers sur des chemins arbitraires et de
   consommer du CPU. *Risque documenté mais réel.*
2. **Robustesse des apps web** — sous-processus jamais nettoyés ni temporisés, état
   global mutable partagé sans verrou entre callbacks et threads.
3. **Cohérence E/S & défense en profondeur** — divergence entre la validation et la
   lecture du CSV ; la Phase 6 ne revérifie pas la validité *géométrique* de la
   solution finale.

### Tableau de synthèse

| ID | Sévérité | Domaine | Fichier:ligne | Résumé |
|----|----------|---------|---------------|--------|
| H1 | 🔴 Haute   | Sécurité    | app.py:1220-1230 ; visualizer.py:785-795 | Apps Dash sans authentification, exposables sur `0.0.0.0` |
| H2 | 🔴 Haute   | Sécurité    | app.py:960-974 ; visualizer.py:684-688,756-766 | Aucune restriction des chemins fournis par l'UI (read/write arbitraire) |
| M1 | 🟠 Moyenne | Correction  | csv_reader.py:159-170 vs 270-289 | CSV « valide » mais qui échoue au chargement (en-têtes non normalisés) |
| M2 | 🟠 Moyenne | Défense     | main.py:328-452 | Phase 6 ne revérifie pas collisions/poids/support de la solution finale |
| M3 | 🟠 Moyenne | Robustesse  | app.py:47,974,~1012 ; visualizer.py:688 | Sous-processus jamais terminés/purgés, polling sans timeout |
| M4 | 🟠 Moyenne | Concurrence | visualizer.py (`_state`, thread KPI) | État global mutable partagé sans verrou |
| M5 | 🟠 Moyenne | Correction  | post_processing.py:1326-1329 | Troncature silencieuse de palettes (atténuée par Phase 6) |
| L1 | 🟡 Basse   | Dépendances | kpi_writer.py:~20 | `numpy` importé en dur (alors qu'`openpyxl` est protégé) |
| L2 | 🟡 Basse   | Maintenance | placed_box.py / pallet.py (`__copy__`/`__deepcopy__`) | Copies manuelles fragiles à l'ajout de champs |
| L3 | 🟡 Basse   | Config      | parameters.py:~289 | Cohérence `min_ratio < max_ratio` validée tardivement, pas dans les bornes |
| L4 | 🟡 Basse   | Robustesse  | app.py:~87 (`_read_batch_status`) | `except Exception: return ""` masque les vraies erreurs |
| L5 | 🟡 Basse   | Robustesse  | app.py:~89-99 | Parsing fragile du marqueur `[BATCH-STATUS]` |
| L6 | 🟡 Basse   | Validation  | csv_reader.py:270-289 | `read_boxes_from_csv` ne revérifie pas (id vide possible si validation contournée) |
| I1 | ⚪ Info    | Structure   | post_processing.py (1350 lignes) | Module volumineux, fort recours à `deepcopy` → coût de maintenance |
| I2 | ⚪ Info    | Numérique   | core/* | Mélange comparaisons strictes / `FLOAT_TOL` selon les modules |
| I3 | ⚪ Info    | Performance | collision_detection.py | Collisions en O(n²), pas d'index spatial |
| I4 | ⚪ Info    | Sécurité    | app.py:1230 ; visualizer.py:795 | `debug=False` OK — garder `DASH_DEBUG` non défini en prod |

---

## 2. Risques HAUTS 🔴

### H1 — Apps Dash sans authentification, exposables sur le réseau
**Fichiers** : `app.py:1220-1230`, `visualization/visualizer.py:785-795` (+ les apps
secondaires `view_palette.py`, `view_kpi.py`).

Par défaut, les serveurs écoutent sur `127.0.0.1` (sûr). Mais via
`PALLET_HOST=0.0.0.0` (cas Docker/réseau, documenté §4.2 du README) ils deviennent
accessibles à **tout le réseau sans aucune authentification**. Un tiers peut alors :
lancer des optimisations, lire tous les résultats, déclencher des exports, et — combiné
à **H2** — provoquer des lectures/écritures de fichiers arbitraires et saturer le CPU.

- **Impact** : accès non autorisé aux données, déni de service, exfiltration.
- **Statut** : vérifié. Le README reconnaît explicitement l'absence d'auth (§5.2).
- **Recommandation** : ajouter une couche d'auth (HTTP Basic via middleware WSGI /
  reverse-proxy), **et/ou** documenter que le filtrage réseau (firewall, réseau Docker
  interne) est **obligatoire** dès que `PALLET_HOST=0.0.0.0`. Ne jamais exposer ces
  ports publiquement.

### H2 — Aucune restriction des chemins fournis par l'interface
**Fichiers** : `app.py:960-974` (sous-processus `main.py` avec `--input-dir` /
`--output-dir` issus des champs de l'UI), `visualization/visualizer.py:684-688`
(spawn `exporter.py` avec `csv_path`/`img_dir`) et routes Flask `:756-766`.

Les chemins de dossier/fichier saisis dans l'UI sont transmis tels quels au moteur,
sans validation de confinement (pas de `os.path.realpath` + `commonpath`). On peut
viser `/etc/...`, `../../...`, etc. : `main.py` lira/écrira là où le processus a les
droits.

- **Important — ce n'est PAS une injection de commande** : `subprocess.Popen` reçoit
  une **liste d'arguments** sans `shell=True` (`app.py:974`, `visualizer.py:688`). Un
  nom de fichier piégé (`"x; rm -rf /"`) est passé comme un seul `argv`, **non
  interprété par un shell**. Le risque est le **parcours/écriture de chemins
  arbitraires**, pas l'exécution de code.
- **Impact** : lecture/écriture de fichiers hors zone de travail ; en mode réseau (H1),
  exploitable à distance.
- **Statut** : vérifié.
- **Recommandation** : normaliser (`realpath`) et **confiner** input/output sous une
  base autorisée ; rejeter les chemins absolus hors base et ceux contenant `..`. Les
  routes Flask valident déjà `os.path.isfile` (`:756`,`:765`) mais sans contrôle de
  confinement — ajouter un test `commonpath`.

---

## 3. Risques MOYENS 🟠

### M1 — CSV « valide » mais qui échoue au chargement
**Fichiers** : `file_io/csv_reader.py`.

`validate_csv` normalise les en-têtes (`.strip().lower()`, ligne 159) **et** les clés de
ligne (ligne 170). Mais `read_boxes_from_csv` accède aux colonnes par clés **exactes**
sans normalisation (`row["allowed_orientations"]`, `row["id"]`, … lignes 273-289) via un
`DictReader` brut. Conséquence : un fichier avec un en-tête `Priority` ou ` priority`
(majuscule / espace) **passe la validation** puis lève une `KeyError → ValueError` à la
lecture.

- **Impact** : échec d'exécution déroutant sur un fichier déclaré valide ; contrat
  validation→lecture rompu.
- **Statut** : vérifié.
- **Recommandation** : normaliser les clés dans `read_boxes_from_csv` exactement comme
  `validate_csv` (ligne 170), ou factoriser une fonction de normalisation partagée.

~~### M2 — La Phase 6 ne revérifie pas la validité physique de la solution~~
~~**Fichier** : `main.py:328-452`.~~

~~La Phase 6 contrôle la **conservation** des colis (comptage, manquants, surnuméraires),~~
~~l'**unicité des séquences** et l'**immutabilité des champs** (client_id, priority,~~
~~weight, orientation ∈ autorisées, dims cohérentes avec l'orientation). Elle **ne~~
~~revérifie pas** que la disposition finale est physiquement valide : pas de re-contrôle~~
~~des collisions 3D, du budget de poids, du ratio de support ni de la stabilité.~~

~~- **Nuance importante** : ce n'est **pas** une contradiction avec le README — le tableau~~
~~  §6.7 ne promet que ces contrôles-là. C'est un **manque de défense en profondeur** : un~~
~~  bug introduit dans une phase 1-5 (chevauchement, dépassement de poids) passerait la~~
~~  Phase 6 et serait écrit puis visualisé.~~
~~- **Impact** : palettes physiquement invalides potentiellement livrées sans alerte.~~
~~- **Statut** : vérifié.~~
~~- **Recommandation** : ajouter un contrôle géométrique final optionnel (re-jouer~~
~~  `is_valid_placement` / détection de collisions par palette) avant écriture, au moins~~
~~  en mode strict / CI.~~

### M3 — Sous-processus : pas de nettoyage ni de timeout
**Fichiers** : `app.py` (`_runs`, `:47`,`:974`, callback de polling ~`:1012`),
`visualization/visualizer.py` (`_exports`, `:688`).

Les `Popen` (lancement de `main.py`, de `exporter.py`) sont stockés dans des dicts
globaux mais **jamais** `terminate()`/`wait()`/purgés. Le polling interroge `proc.poll()`
indéfiniment, **sans borne de temps**. Les dicts `_runs`/`_exports` croissent sans TTL.

- **Impact** : processus zombies/orphelins, fuite mémoire à long terme, UI bloquée en
  « en cours » si un sous-processus se fige (ex. blocage sur tampon stdout).
- **Statut** : vérifié (présence des `Popen`, absence de terminaison/cleanup).
- **Recommandation** : timeout mur (ex. tuer après N minutes sans progrès) ; purge des
  entrées terminées (TTL) ; `atexit` pour tuer les sous-processus restants à l'arrêt.

### M4 — État global mutable partagé sans verrou
**Fichier** : `visualization/visualizer.py` (dict global `_state`, thread KPI de fond).

`_state` est lu/écrit par plusieurs callbacks Dash (thread principal) **et** par un
thread de calcul KPI, sans `threading.Lock`. Écritures/lectures concurrentes sur les
mêmes clés (`kpi_ready`, `kpi_rows_by_file`, `df`, …).

- **Impact** : données obsolètes/corrompues affichées, plantage si un dict est modifié
  pendant son itération, drapeaux d'état perdus (polling qui ne se termine pas).
- **Statut** : constat plausible (revue) — à confirmer par test de charge.
- **Recommandation** : protéger les accès par un `Lock`, ou migrer l'état partagé vers
  des composants `dcc.Store` (thread-safe par conception).

### M5 — Troncature silencieuse de palettes en post-traitement
**Fichier** : `heuristics/post_processing.py:1326-1329`.

Si le post-traitement produit **plus** de palettes qu'en entrée, le code tronque :
`result = result[:n_pallets_in]` après un simple `print(...AVERTISSEMENT...)`. Cela peut
**supprimer des colis**.

- **Atténuation** : la Phase 6 (M2) détecterait alors la perte de colis et renverrait
  `ERR_SECURITY` → **aucun CSV corrompu n'est écrit**. Le défaut se manifeste donc comme
  un échec déroutant plutôt qu'une corruption silencieuse.
- **Impact** : exécution échouée masquant la cause réelle (explosion du nombre de
  palettes).
- **Statut** : vérifié.
- **Recommandation** : transformer la troncature en erreur explicite (lever une
  exception / code dédié) — cet état ne devrait jamais survenir et indique un bug amont.

---

## 4. Risques BAS 🟡

- **L1 — `numpy` en dépendance dure** (`file_io/kpi_writer.py`) : `openpyxl` est importé
  de façon protégée (try/except), mais `numpy` non. Tout chemin appelant le module
  échoue si `numpy` est absent. → Protéger l'import et message clair.
- **L2 — `__copy__`/`__deepcopy__` manuels fragiles** (`models/placed_box.py`,
  `models/pallet.py`) : corrects pour les champs actuels, mais l'ajout d'un futur champ
  scalaire à `Pallet`/`PlacedBox` ne serait **pas** copié → corruption d'état LNS
  silencieuse. → Commenter l'invariant (« champs scalaires immuables uniquement ») ou
  dériver les champs par introspection de dataclass. *(L'optimisation O(1) elle-même est
  justifiée et correcte.)*
- **L3 — Cohérence des ratios multi-client** (`config/parameters.py:~289`) :
  `minimum_ratio < maximum_ratio` n'est imposé qu'en `__post_init__`, pas via
  `PARAM_BOUNDS`. Des bornes individuelles valides peuvent former une combinaison
  dégénérée. → Documenter / valider explicitement la relation.
- **L4 — Capture trop large** (`app.py:~87`, `_read_batch_status`) :
  `except Exception: return ""` confond « fichier absent », « permission refusée » et
  « erreur d'E/S ». → Cibler `FileNotFoundError` vs autres.
- **L5 — Parsing fragile de `[BATCH-STATUS]`** (`app.py:~89-99`) : extraction par
  `find/split`. Un format inattendu renverrait `code=""` interprété comme « en cours »
  → polling sans fin. → Utiliser une regex `code=(\S+)` + validation contre la liste des
  codes connus.
- **L6 — Pas de re-validation à la lecture** (`csv_reader.py:270-289`) :
  `read_boxes_from_csv` suppose que `validate_csv` a été exécuté ; appelé seul sur un
  fichier à `id` vide, il crée un `Box` à id vide sans erveur. → Re-contrôle minimal
  défensif (id non vide, dims > 0).

---

## 5. Informations & pistes structurelles ⚪

- **I1 — `post_processing.py` (1350 lignes)** : module le plus complexe et le plus
  risqué (gap-repair, égalisation de remplissage, replacement P2, centrage), fort
  recours à `copy.deepcopy`. Candidat n°1 à un découpage en sous-modules + tests
  unitaires ciblés sur chaque sous-routine (`_gap_direction`, `_try_repack_signed`,
  `_targeted_gap_repair_1box`, `_place_p2_pool`).
- **I2 — Tolérance numérique hétérogène** : certains tests géométriques utilisent des
  inégalités strictes, d'autres `FLOAT_TOL`. Le placement au sol via `if z > FLOAT_TOL`
  (`placement_engine.py:217`) est *correct* (le sol supporte tout), mais l'absence de
  tolérance homogène sur les bornes de palette (`collision_detection.py`) peut, en
  théorie, rejeter/accepter à la marge sous accumulation d'erreurs flottantes. → Définir
  une politique epsilon unique et la documenter.
- **I3 — Collisions en O(n²)** (`collision_detection.py`) : balayage linéaire par
  candidat, sans index spatial (grille/quadtree). Acceptable aux volumes documentés
  (≤ quelques centaines de colis), à surveiller au-delà.
- **I4 — Mode debug** : `debug=False` est bien posé explicitement (`app.py:1230`,
  `visualizer.py:795`). Recommandation : garantir que `DASH_DEBUG` n'est jamais défini en
  production (sinon pages d'erreur interactives = fuite de code/données).

---

## 6. Points positifs (à préserver)

- ✅ **Conservation des colis** garantie par la Phase 6 (comptage + manquants +
  surnuméraires + immutabilité des champs) **avant** toute écriture — design solide.
- ✅ **Parsing CSV défensif** : orientations en liste blanche, pas d'`eval`, `stackable`
  contrôlé, gestion du BOM (`utf-8-sig`), détection des doublons d'`id`.
- ✅ **`subprocess` sans shell** : pas de `shell=True` → pas de surface d'injection de
  commande.
- ✅ **Dataclasses correctes** : `default_factory` pour les défauts mutables (pas de
  partage d'état entre instances `Box`).
- ✅ **Découpage en couches** clair et dépendances orientées (cf. `docs/code_map.html`).
- ✅ **Présence d'une suite de tests** (`tests/` : géométrie, collisions, stabilité,
  stacking, FFD, sorting, modèles…).

---

## Annexe A — Alertes investiguées puis écartées (faux positifs)

Plusieurs constats « critiques » remontés par l'analyse automatique ont été **vérifiés
dans le code et invalidés** :

1. **« RCE par injection dans `subprocess` »** → **Faux.** `Popen` reçoit une *liste*
   d'arguments, **sans `shell=True`** (`app.py:974`, `visualizer.py:688`). Aucune
   interprétation shell. (Le risque réel — chemins arbitraires — est traité en H2.)
2. **« Le `-residual` contredit la doc (minimise au lieu de maximiser) »** → **Faux.**
   `placement_engine.py:291-293` : le tri du tuple est *ascendant*, donc négativer la
   surface résiduelle (`-residual`) **maximise** bien l'aire résiduelle, conformément au
   docstring. Comportement correct.
3. **« Variable `iteration` non initialisée / `while…else` trompeur (régime >70) »** →
   **Faux.** `optimizer/pallet_optimizer.py:450-491` : `iteration` est incrémentée
   **avant** usage (ligne 483) et la clause `else` du `while` ne s'exécute que sans
   `break` — c'est-à-dire exactement « itérations max atteintes ». Logique correcte.
4. **« La Phase 6 contredit le README »** → **Nuancé.** Le README §6.7 ne promet pas la
   re-validation géométrique ; code et doc sont cohérents. Conservé uniquement comme
   *manque de défense en profondeur* (M2), pas comme contradiction.

---

## Annexe B — Plan d'action recommandé (par priorité)

1. **H1/H2** — Confiner les chemins (realpath + base autorisée) **avant** tout
   déploiement réseau ; ajouter auth ou exiger un firewall si `0.0.0.0`.
2. **M1** — Aligner la normalisation des en-têtes entre `validate_csv` et
   `read_boxes_from_csv` (correctif court, fort gain de fiabilité).
3. **M3/M4** — Timeouts + cleanup des sous-processus ; verrou sur `_state`.
4. **M2/M5** — Contrôle géométrique final optionnel + transformer la troncature
   post-traitement en erreur explicite.
5. **L1-L6 / I1** — Durcissements ciblés et découpage progressif de `post_processing.py`
   avec tests unitaires.
