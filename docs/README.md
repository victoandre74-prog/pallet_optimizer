# Carte interactive du code — `code_map.html`

Graphe interactif (React Flow) qui documente l'architecture de **Pallet Optimizer**
et répond visuellement à trois questions :

> **Quelles fonctions / quels modèles sont utilisés ? Pour quoi faire ? Dans quel fichier ?**

## Utilisation

Ouvrir le fichier dans un navigateur :

```bash
# depuis la racine du projet
xdg-open docs/code_map.html      # Linux
open docs/code_map.html          # macOS
start docs\code_map.html         # Windows
```

> Le graphe charge React, React Flow et htm depuis un CDN (esm.sh / jsDelivr).
> Une connexion internet est donc nécessaire au premier affichage. Aucune
> installation, aucun serveur : c'est une page HTML autonome.

## Trois vues

### 1. Flux / Étapes (par défaut)
Parcours pas-à-pas du pipeline d'optimisation (Phase 0 → Phase 6 → Sortie →
Visualisation). Utilisez **← Précédent / Suivant →** ou les pastilles numérotées.
Pour chaque phase, le panneau de droite liste les **modèles/modules utilisés**,
leur **fichier** et le **rôle** de chaque fonction. Les nœuds à droite du graphe
sont les fichiers mobilisés par l'étape courante.

### 2. Architecture
Graphe de dépendances complet : chaque nœud est un fichier Python, les flèches
sont les imports inter-modules. Filtrez par **couche** (models, core, heuristics,
visualization, …) et cliquez un nœud pour mettre en évidence ses dépendances et
afficher le détail de ses fonctions.

### 3. Documentation
Le `README.md` complet du projet, rendu dans la page avec un **sommaire interactif**
(navigation par section, surbrillance de la section courante au défilement, liens
internes fonctionnels). Le contenu est un **instantané** embarqué dans la page (pour
rester ouvrable en double-clic, sans serveur).

> **Resynchroniser après modification du `README.md`** :
> ```bash
> python docs/build_doc.py
> ```
> Le script réinjecte le texte du README entre les marqueurs `README:START/END`
> de `code_map.html`. Aucune autre partie de la page n'est touchée.

## Source des données

Le contenu (rôles des modules et des fonctions) est dérivé du `README.md` du
projet et d'une lecture du code source. Le fichier est **purement documentaire**
et ne modifie aucun code du projet.

Si la structure du code évolue, mettre à jour les objets `MODULES`, `DEPS` et
`PHASES` en tête du `<script type="module">` de `code_map.html`.
