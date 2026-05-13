============================================================
  Rapport PFE - Taha Dazine - EMI / Departement MIS
  BMCE Capital - Salle des Marches
============================================================

COMPILATION
-----------
Ce rapport se compile avec XeLaTeX et Biber depuis le dossier latex/ :

  xelatex main.tex
  biber main
  xelatex main.tex
  xelatex main.tex

Ou avec latexmk :

  latexmk -xelatex main.tex

Dependances principales :
  fontspec, polyglossia, geometry, setspace, microtype,
  xcolor, graphicx, float, booktabs, tabularx, multirow,
  array, longtable, amsmath, amssymb, chngcntr, fancyhdr,
  titlesec, tocloft, listings, hyperref, biblatex.

POLICE ARABE
------------
La page molakhas.tex utilise Arial pour le texte arabe. Si Arial n'est pas
disponible, remplacer dans main.tex :

  \newfontfamily\arabicfont[...]{Arial}

par une police arabe installee, par exemple Amiri ou Scheherazade New.

STRUCTURE COMPILEE
------------------
main.tex                    -> fichier maitre
biblio.bib                  -> bibliographie et webographie
frontmatter/                -> pages preliminaires
chapters/
  intro.tex                 -> introduction generale
  ch1_contexte.tex          -> contexte, problematique, etat de l'art
  ch2_at.tex                -> analyse technique
  ch3_signaux.tex           -> Signal Engine A-G
  ch4_wfo.tex               -> moteur WFO
  ch5_architecture.tex      -> architecture applicative
  ch6_dashboard.tex         -> dashboard decisionnel
  ch7_analytics.tex         -> couche analytics
  conclusion.tex            -> conclusion et perspectives

Les anciens fichiers ch2_signaux.tex, ch3_wfo.tex, ch4_architecture.tex et
ch5_dashboard.tex sont des brouillons historiques non inclus par main.tex.

FIGURES
-------
Les figures utilisees par le rapport sont placees dans :

  figures/generated/

Elles peuvent etre regenerees avec :

  python scripts/generate_report_figures.py

Le script s'appuie sur les donnees locales disponibles dans le depot :
snapshots JSON du frontend, historique IAM local, documentation technique et
structure du code. Le PDF final genere est :

  main.pdf

SOURCES
-------
Les sources institutionnelles externes utilisees dans le rapport sont citees
dans biblio.bib : BANK OF AFRICA, BMCE Capital, Bourse de Casablanca et AMMC.
Les documents techniques locaux du dossier docs/ sont egalement references.
