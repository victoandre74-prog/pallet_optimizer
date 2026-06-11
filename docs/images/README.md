# Images d'illustration de la documentation

Déposez ici les captures d'écran référencées par `README.md` (et rendues dans
l'onglet **Documentation** de `docs/code_map.html`).

## Convention de chemin

Dans `README.md`, référencez les images avec le préfixe `docs/` :

```markdown
![App 1 — Paramétrage & Exécution](docs/images/app1.png)
*App 1 — Paramétrage & Exécution (port 8050)*
```

- Sur **GitHub**, le chemin `docs/images/app1.png` est correct (README à la racine).
- Dans la **page HTML** (qui vit déjà dans `docs/`), `DocView` retire le préfixe
  `docs/` automatiquement → `images/app1.png`. Les deux contextes fonctionnent.

## Fichiers attendus (exemples)

| Fichier | Illustration |
|---|---|
| `app1.png` | App 1 — Paramétrage & Exécution (port 8050) |
| `app2.png` | App 2 — Visualiseur unifié (port 8053) |

Format conseillé : PNG, largeur ~1200–1600 px.

## Après ajout / mise à jour d'une image

Rien à faire pour les images elles-mêmes. Si vous avez aussi modifié le **texte**
du `README.md`, resynchronisez la page :

```bash
python docs/build_doc.py
```
