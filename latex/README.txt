============================================================
  Rapport PFE — Taha Dazine — EMI / Département MIS
  BMCE Capital — Salle des Marchés
============================================================

COMPILATION
-----------
Ce rapport nécessite XeLaTeX (pour le support Unicode, le texte arabe et fontspec).

Commandes de compilation (depuis le dossier latex/) :
  xelatex main.tex
  biber main
  xelatex main.tex
  xelatex main.tex

Ou avec latexmk (recommandé) :
  latexmk -xelatex main.tex

Distribution LaTeX recommandée : MiKTeX (Windows) ou TeX Live.
Assurez-vous que les paquets suivants sont installés :
  fontspec, polyglossia, geometry, setspace, microtype,
  xcolor, graphicx, float, caption, subcaption,
  booktabs, tabularx, multirow, array, longtable,
  amsmath, amssymb, chngcntr, fancyhdr, titlesec,
  tocloft, listings, hyperref, biblatex

POLICE ARABE
------------
La page ملخص (molakhas.tex) utilise la police Arial pour le texte arabe.
Si Arial n'est pas disponible, remplacez dans main.tex :
  \newfontfamily\arabicfont[...]{Arial}
par une police arabe installée :
  \newfontfamily\arabicfont[...]{Amiri}       % à installer depuis CTAN
  ou
  \newfontfamily\arabicfont[...]{Scheherazade New}

STRUCTURE
---------
main.tex                    → Fichier maître (preamble + structure)
biblio.bib                  → Bibliographie BibTeX
frontmatter/
  garde.tex                 → Page de garde
  dedicace.tex              → Dédicace
  remerciements.tex         → Remerciements
  resume.tex                → Résumé français
  abstract.tex              → Abstract anglais
  molakhas.tex              → ملخص arabe
  abreviations.tex          → Liste des abréviations
chapters/
  intro.tex                 → Introduction générale
  ch1_contexte.tex          → Chapitre 1 — Contexte, Problématique, État de l'art
  ch2_signaux.tex           → Chapitre 2 — Moteur de Signaux (A→G)
  ch3_wfo.tex               → Chapitre 3 — Moteur de Backtest WFO
  ch4_architecture.tex      → Chapitre 4 — Architecture de la plateforme
  ch5_dashboard.tex         → Chapitre 5 — Dashboard (livrable final)
  conclusion.tex            → Conclusion et Perspectives
figures/
  placeholder.txt           → Convention de nommage des figures (voir ce fichier)
  [vos figures ici]

FIGURES À INSÉRER
-----------------
Toutes les figures sont des placeholders \placeholder{...} dans le code.
Pour insérer une figure réelle, remplacez :
  \placeholder{Description}
par :
  \includegraphics[width=0.8\linewidth]{figures/ch_X_fig_Y.png}

Voir figures/placeholder.txt pour la convention de nommage complète.

PAGES DE GARDE
--------------
Remplacez figures/logo_emi.png et figures/logo_bmce.png par les logos officiels.
Complétez les noms du jury dans frontmatter/garde.tex.

SOUTENANCE
----------
Rappel règle EMI : transmettre le rapport au jury au moins 1 semaine
avant la soutenance.
