#!/usr/bin/env python3
"""Réinjecte le contenu de README.md dans docs/code_map.html (onglet Documentation).

La page embarque un *instantané* du README pour rester autonome (ouverture par
simple double-clic, sans serveur). Relancer ce script après chaque modification
du README pour resynchroniser :

    python docs/build_doc.py

Le contenu est inséré tel quel dans une balise <script type="text/markdown">
entre les marqueurs README:START / README:END, puis rendu côté navigateur par
marked.js. Aucune autre partie de la page n'est modifiée.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
PAGE = ROOT / "docs" / "code_map.html"

START = "<!-- README:START"
END = "<!-- README:END -->"


def main() -> int:
    readme = README.read_text(encoding="utf-8")

    # Une balise <script> ne peut pas contenir la séquence "</script" : elle
    # fermerait prématurément le bloc. On refuse plutôt que de corrompre le texte.
    if "</script" in readme.lower():
        print("ERREUR : README.md contient '</script' — embarquement impossible.", file=sys.stderr)
        return 1

    page = PAGE.read_text(encoding="utf-8")

    block = (
        '<!-- README:START — contenu injecté depuis README.md par docs/build_doc.py '
        '(ne pas éditer à la main) -->\n'
        '<script type="text/markdown" id="readme-src">' + readme + "</script>\n"
        + END
    )

    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(page):
        print("ERREUR : marqueurs README:START/END introuvables dans code_map.html.", file=sys.stderr)
        return 1

    PAGE.write_text(pattern.sub(lambda _m: block, page, count=1), encoding="utf-8")
    print(f"OK : {len(readme)} caractères de README.md injectés dans {PAGE.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
