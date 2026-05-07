# Rapport PFE MIS (LaTeX) - Scope Signaux Legacy

Ce dossier contient une implementation du memoire orientee sur le perimetre:
page legacy originale des signaux + methodologie de detection + restitution
dashboard.

## Structure

- `main.tex`: point d'entree du memoire
- `frontmatter/`: page de garde, dedicace, resumes, abreviations
- `chapters/`: chapitres 1 a 7 (jusqu'a la partie signaux/dashboard)
- `references.bib`: bibliographie BibTeX (style IEEE)

## Compilation locale (optionnelle)

Utiliser pdfLaTeX :

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

## Overleaf

1. Creer un projet vide.
2. Uploader tout le contenu de `report-pfe-mis/`.
3. Choisir le compilateur `pdfLaTeX`.
4. Compiler.

## Notes

- Les marges sont fixees a 2.5 cm.
- La pagination est en chiffres romains dans les preliminaires, puis en arabe
  a partir de l'introduction.
- Bibliographie et webographie sont separees.
