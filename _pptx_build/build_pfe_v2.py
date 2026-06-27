"""Build Final_PFE_BMCE_v2.pptx — academic redesign with storytelling, navy palette,
real rdtalpha.xyz screenshots, and programmatic diagrams."""
from __future__ import annotations
import sys
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor

from theme import (
    NAVY, BLUE, MID_BLUE, LIGHT_BLUE, TEAL, SOFT_BLUE, WHITE, NEAR_BLACK,
    GRAY, LIGHT_GRAY, PALE_BLUE, ACCENT_OR,
    GRADE_A, GRADE_B, GRADE_C, GRADE_D, GRADE_F,
    FONT, SLIDE_W, SLIDE_H,
    add_filled_shape, add_textbox, add_label, add_multiline,
    page_chrome, set_text, clear_animations,
)

ROOT = Path(__file__).resolve().parents[1]
FIGS = ROOT / "latex" / "figures" / "generated"
SHOTS = Path(__file__).resolve().parent / "shots"
SRC  = Path(r"C:/Users/taha/Downloads/Final_PFE_BMCE_blue_logo.pptx")
DST  = Path(r"C:/Users/taha/Downloads/Final_PFE_BMCE_v2_FINAL.pptx")


# ── helpers ──────────────────────────────────────────────────────────────────

def _new_blank_slide(prs: Presentation):
    blank = None
    for layout in prs.slide_layouts:
        if len(layout.placeholders) == 0:
            blank = layout
            break
    return prs.slides.add_slide(blank or prs.slide_layouts[-1])


def _embed_img(slide, path: str | Path, x, y, w=None, h=None):
    kw = {}
    if w is not None: kw["width"]  = Inches(w)
    if h is not None: kw["height"] = Inches(h)
    return slide.shapes.add_picture(str(path), Inches(x), Inches(y), **kw)


def _bridge(slide, text, y=0.75):
    """Italic narrative bridge line below the title band."""
    add_textbox(slide, 0.50, y, 9.00, 0.30, text,
                font_size=11, bold=False, color=GRAY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def _caption(slide, text, y=4.85):
    add_textbox(slide, 0.50, y, 9.00, 0.28, text,
                font_size=8, bold=False, color=GRAY,
                align=PP_ALIGN.CENTER)


def _section_chip(slide, x, y, w, h, text, *, fill=NAVY, color=WHITE,
                  font_size=11, bold=True):
    """A small pill/chip used as a section heading."""
    sh = add_filled_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=fill)
    add_label(sh, text, font_size=font_size, bold=bold, color=color)
    return sh


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 9 — PROBLÉMATIQUE  (storytelling: avant / écart / cible)
# ─────────────────────────────────────────────────────────────────────────────
def build_problematique(prs: Presentation, page_num: int = 9) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Problématique",
                subtitle="Du risque de marché à la décision robuste")

    _bridge(s, "Face au risque de marché, le Desk Actions doit suivre 73 valeurs quotidiennement — comment décider vite et juste ?")

    # ── Two-column layout: Avant | Cible ──
    col_w = 4.05
    col_h = 2.85
    col_y = 1.20
    lx = 0.55
    rx = SLIDE_W - col_w - 0.55

    # Left column header
    _section_chip(s, lx, col_y, col_w, 0.45,
                  "PROCESSUS ACTUEL", fill=NAVY, font_size=12)
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     lx, col_y + 0.50, col_w, col_h - 0.50,
                     fill=PALE_BLUE, line=LIGHT_BLUE, line_width=0.75)

    left_items = [
        ("Manuel",         "Analyse titre par titre, indicateur par indicateur"),
        ("Subjectif",      "Choix dépendant du trader et de l'humeur du jour"),
        ("Partiel",        "Couverture limitée : focus sur les valeurs liquides"),
        ("Non validé",     "Aucune mesure de robustesse hors-échantillon"),
    ]
    iy = col_y + 0.66
    for tag, desc in left_items:
        dot = add_filled_shape(s, MSO_SHAPE.OVAL, lx + 0.18, iy + 0.08, 0.16, 0.16,
                               fill=NAVY)
        add_textbox(s, lx + 0.42, iy, 1.20, 0.30, tag,
                    font_size=11, bold=True, color=NAVY,
                    anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, lx + 1.55, iy, col_w - 1.65, 0.30, desc,
                    font_size=9, bold=False, color=NEAR_BLACK,
                    anchor=MSO_ANCHOR.MIDDLE)
        iy += 0.55

    # Right column header
    _section_chip(s, rx, col_y, col_w, 0.45,
                  "APPROCHE CIBLE", fill=TEAL, font_size=12)
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     rx, col_y + 0.50, col_w, col_h - 0.50,
                     fill=PALE_BLUE, line=TEAL, line_width=0.75)

    right_items = [
        ("Automatisé",   "Pipeline reproductible sur les 73 titres du MASI"),
        ("Objectif",     "Règles paramétrées, traçables, expliquables"),
        ("Exhaustif",    "Couverture systématique de tout l'univers"),
        ("Statistique",  "Validation Walk-Forward, grade de robustesse"),
    ]
    iy = col_y + 0.66
    for tag, desc in right_items:
        dot = add_filled_shape(s, MSO_SHAPE.OVAL, rx + 0.18, iy + 0.08, 0.16, 0.16,
                               fill=TEAL)
        add_textbox(s, rx + 0.42, iy, 1.20, 0.30, tag,
                    font_size=11, bold=True, color=TEAL,
                    anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, rx + 1.55, iy, col_w - 1.65, 0.30, desc,
                    font_size=9, bold=False, color=NEAR_BLACK,
                    anchor=MSO_ANCHOR.MIDDLE)
        iy += 0.55

    # Central bridging arrow between columns
    bx = lx + col_w + 0.04
    bw = rx - bx - 0.04
    add_filled_shape(s, MSO_SHAPE.RIGHT_ARROW,
                     bx, col_y + col_h / 2 - 0.18, bw, 0.36, fill=LIGHT_BLUE)
    add_textbox(s, bx, col_y + col_h / 2 - 0.50, bw, 0.30,
                "Écart à combler",
                font_size=9, bold=True, color=NAVY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    # Bottom band: research question
    band_y = col_y + col_h + 0.20
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 0.55, band_y, SLIDE_W - 1.10, 0.55,
                     fill=NAVY)
    add_textbox(s, 0.65, band_y + 0.03, SLIDE_W - 1.30, 0.50,
                "Comment construire une plateforme qui automatise, optimise et valide statistiquement la lecture technique du MASI ?",
                font_size=12, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 10 — DÉMARCHE GLOBALE  (NEW: 5-step methodology roadmap)
# ─────────────────────────────────────────────────────────────────────────────
def build_demarche(prs: Presentation, page_num: int = 10) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Démarche Globale",
                subtitle="Cinq étapes, de la donnée brute à la décision")

    _bridge(s, "Pour répondre à la problématique, j'ai construit un pipeline en cinq étapes — chaque étape sera détaillée dans la suite.")

    # 5 horizontal step nodes
    steps = [
        ("1", "Données",          "OHLCV journalières\n73 titres MASI",      NAVY),
        ("2", "Indicateurs",      "20 indicateurs\n4 familles",                BLUE),
        ("3", "Signal Engine",    "Agrégation\nScore [-100, +100]",            MID_BLUE),
        ("4", "Validation WFO",   "10 plis IS/OOS\nGrade A–F",                 TEAL),
        ("5", "Décision",         "Direction technique\nNiveaux & blotter",    SOFT_BLUE),
    ]

    n = len(steps)
    margin = 0.50
    gap = 0.12
    box_w = (SLIDE_W - 2 * margin - (n - 1) * gap) / n
    box_h = 1.85
    by = 1.40

    for i, (num, title, body, color) in enumerate(steps):
        bx = margin + i * (box_w + gap)
        # Card body
        add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                         bx, by, box_w, box_h, fill=color)
        # Number badge (top)
        badge = add_filled_shape(s, MSO_SHAPE.OVAL,
                                 bx + box_w / 2 - 0.22, by - 0.22, 0.44, 0.44,
                                 fill=WHITE, line=color, line_width=1.5)
        add_label(badge, num, font_size=14, bold=True, color=color)
        # Title
        add_textbox(s, bx + 0.10, by + 0.35, box_w - 0.20, 0.40, title,
                    font_size=13, bold=True, color=WHITE,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # Body (two lines)
        add_textbox(s, bx + 0.10, by + 0.85, box_w - 0.20, box_h - 0.90, body,
                    font_size=9, bold=False, color=WHITE,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)
        # Arrow between cards
        if i < n - 1:
            ax = bx + box_w + 0.005
            add_filled_shape(s, MSO_SHAPE.RIGHT_TRIANGLE,
                             ax, by + box_h / 2 - 0.08,
                             gap - 0.01, 0.16, fill=NAVY)

    # Bottom legend bar - lifecycle
    leg_y = by + box_h + 0.50
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     0.55, leg_y, SLIDE_W - 1.10, 0.50, fill=PALE_BLUE)
    add_textbox(s, 0.65, leg_y + 0.03, SLIDE_W - 1.30, 0.46,
                "Production : pipeline ré-exécuté chaque jour à la clôture — résultats visibles sur la plateforme rdtalpha.xyz",
                font_size=10, bold=True, color=NAVY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 11 — ANALYSE TECHNIQUE  (4 familles × 5 indicateurs, navy palette)
# ─────────────────────────────────────────────────────────────────────────────
def build_analyse_technique(prs: Presentation, page_num: int = 11) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Analyse Technique",
                subtitle="La matière première : 20 indicateurs · 4 familles orthogonales")

    _bridge(s, "Étape 1 — Chaque famille capte une dimension différente du prix : direction, accélération, retournement, conviction.")

    families = [
        ("TENDANCE",   "Direction & structure",      ["SMA", "EMA", "EMA Cross", "Ichimoku", "PSAR"], NAVY),
        ("MOMENTUM",   "Accélération du mouvement",  ["MACD", "ROC", "TRIX", "ADX", "TSI"],            BLUE),
        ("OSCILLATION","Sur-achat / sur-vente",      ["RSI", "Stochastique", "CCI", "MFI", "Ultimate"],MID_BLUE),
        ("VOLUME",     "Conviction des flux",        ["OBV", "CMF", "A/D Line", "VWAP", "Force Idx"],   TEAL),
    ]

    n = len(families)
    margin = 0.45
    gap = 0.18
    col_w = (SLIDE_W - 2 * margin - (n - 1) * gap) / n
    col_y = 1.20
    col_h = 3.30

    for i, (fam, sub, indicators, color) in enumerate(families):
        cx = margin + i * (col_w + gap)
        # Header pill
        hdr = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                               cx, col_y, col_w, 0.55, fill=color)
        add_label(hdr, fam, font_size=13, bold=True, color=WHITE)
        # Sub-title
        add_textbox(s, cx, col_y + 0.58, col_w, 0.28, sub,
                    font_size=9, bold=False, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # Indicator chips
        chip_y = col_y + 0.95
        chip_h = 0.42
        chip_gap = 0.06
        for j, ind in enumerate(indicators):
            cy = chip_y + j * (chip_h + chip_gap)
            chip = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                    cx + 0.10, cy, col_w - 0.20, chip_h,
                                    fill=WHITE, line=color, line_width=1.25)
            add_label(chip, ind, font_size=11, bold=True, color=color)

    # Bottom band — why orthogonal
    leg_y = col_y + col_h + 0.20
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     0.55, leg_y, SLIDE_W - 1.10, 0.40, fill=PALE_BLUE)
    add_textbox(s, 0.65, leg_y, SLIDE_W - 1.30, 0.40,
                "Le choix orthogonal réduit la redondance — chaque famille apporte une information décorrélée des autres.",
                font_size=10, bold=True, color=NAVY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 12 — SIGNAL ENGINE  (7-step internal pipeline, navy)
# ─────────────────────────────────────────────────────────────────────────────
def build_signal_engine(prs: Presentation, page_num: int = 12) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Signal Engine",
                subtitle="Du vote individuel au score unifié [-100, +100]")

    _bridge(s, "Étape 2 — Chaque indicateur produit un vote ; le Signal Engine les filtre, pondère et synthétise.")

    # Vertical timeline with 7 steps (A→G), letter badges + title + 1-liner
    steps = [
        ("A", "Générer les candidats",     "Familles × variantes paramétriques → signaux élémentaires"),
        ("B", "Tester la stabilité",        "Score sur plusieurs sous-périodes historiques"),
        ("C", "Calculer la robustesse",     "Performance · régularité · risque · cohérence"),
        ("D", "Conserver les survivants",   "Seuil minimal + classement relatif par famille"),
        ("E", "Réduire la redondance",      "Regroupement statistique des signaux proches"),
        ("F", "Lire le dernier jour",       "Variantes survivantes → vote { Vente / Neutre / Achat }"),
        ("G", "Agréger le score technique", "Sortie unifiée [-100, +100] + contributions par famille"),
    ]

    sx = 0.80     # left margin for badges
    sy = 1.15
    row_h = 0.45
    gap = 0.05

    for i, (letter, title, desc) in enumerate(steps):
        ry = sy + i * (row_h + gap)
        # Letter badge
        color = NAVY if i < 6 else TEAL  # final step highlighted
        badge = add_filled_shape(s, MSO_SHAPE.OVAL, sx, ry, 0.42, 0.42, fill=color)
        add_label(badge, letter, font_size=14, bold=True, color=WHITE)
        # Row bar
        bar = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                               sx + 0.55, ry, SLIDE_W - sx - 1.40, row_h,
                               fill=PALE_BLUE if i < 6 else LIGHT_BLUE,
                               line=color, line_width=0.6)
        add_textbox(s, sx + 0.70, ry + 0.03, 2.30, row_h - 0.06, title,
                    font_size=11, bold=True, color=NAVY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, sx + 3.05, ry + 0.03, SLIDE_W - sx - 3.95, row_h - 0.06, desc,
                    font_size=9, bold=False, color=NEAR_BLACK,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

    # Output illustration on the far right of the last row (a "score chip")
    last_ry = sy + (len(steps) - 1) * (row_h + gap)
    chip = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                            SLIDE_W - 1.30, last_ry - 0.05, 0.80, row_h + 0.10,
                            fill=NAVY)
    add_label(chip, "-66.7", font_size=14, bold=True, color=WHITE)

    # Bottom interpretation legend
    leg_y = sy + len(steps) * (row_h + gap) + 0.05
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     0.55, leg_y, SLIDE_W - 1.10, 0.42, fill=NAVY)
    add_textbox(s, 0.65, leg_y, SLIDE_W - 1.30, 0.42,
                "Lecture : -100 = Vente forte    |   0 = Neutre    |   +100 = Achat fort     (ex. ATW = -66.7 → Vente forte)",
                font_size=10, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 13 — WALK-FORWARD OPTIMIZATION  (programmatic timeline, navy)
# ─────────────────────────────────────────────────────────────────────────────
def build_wfo(prs: Presentation, page_num: int = 13) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Walk-Forward Optimization",
                subtitle="Validation hors-échantillon · fenêtres glissantes")

    _bridge(s, "Étape 3 — Un score n'a de valeur que s'il généralise : on optimise In-Sample, on teste Out-of-Sample, on roule.")

    # ── Timeline axis ── (9 ticks so all 5 folds fit: IS=4t + 4 rolls + 1 OOS = 9)
    axis_y = 1.30
    axis_x0 = 0.95
    axis_x1 = SLIDE_W - 0.50
    add_filled_shape(s, MSO_SHAPE.RECTANGLE,
                     axis_x0, axis_y, axis_x1 - axis_x0, 0.02, fill=NEAR_BLACK)
    years = ["t₀", "t₁", "t₂", "t₃", "t₄", "t₅", "t₆", "t₇", "t₈", "t₉"]
    n_t = len(years)
    for i, yr in enumerate(years):
        tx = axis_x0 + i * (axis_x1 - axis_x0) / (n_t - 1)
        add_filled_shape(s, MSO_SHAPE.RECTANGLE,
                         tx - 0.005, axis_y - 0.08, 0.01, 0.16, fill=NEAR_BLACK)
        add_textbox(s, tx - 0.30, axis_y - 0.35, 0.60, 0.22, yr,
                    font_size=9, bold=False, color=GRAY, align=PP_ALIGN.CENTER)

    # ── 5 rolling folds: IS spans 4 ticks, OOS = 1 tick, rolls 1 tick per fold ──
    n_folds = 5
    fold_y0 = axis_y + 0.25
    fold_h = 0.35
    fold_gap = 0.08
    tick_w = (axis_x1 - axis_x0) / (n_t - 1)
    for i in range(n_folds):
        ry = fold_y0 + i * (fold_h + fold_gap)
        is_x = axis_x0 + i * tick_w
        is_w = 4 * tick_w
        oos_x = is_x + is_w
        oos_w = tick_w
        add_textbox(s, 0.20, ry, 0.70, fold_h, f"Pli {i+1}",
                    font_size=10, bold=True, color=NAVY,
                    align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        is_bar = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                  is_x, ry, is_w, fold_h, fill=NAVY)
        add_label(is_bar, "In-Sample  ·  optimisation", font_size=9, bold=True, color=WHITE)
        oos_bar = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                   oos_x, ry, oos_w, fold_h, fill=TEAL)
        add_label(oos_bar, "OOS", font_size=9, bold=True, color=WHITE)

    # ── Legend ──
    leg_y = fold_y0 + n_folds * (fold_h + fold_gap) + 0.05
    # Legend dots
    lx = 0.80
    add_filled_shape(s, MSO_SHAPE.OVAL, lx, leg_y + 0.07, 0.15, 0.15, fill=NAVY)
    add_textbox(s, lx + 0.20, leg_y, 2.20, 0.28,
                "IS — sélection par PROM",
                font_size=10, bold=True, color=NAVY,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
    add_filled_shape(s, MSO_SHAPE.OVAL, lx + 2.60, leg_y + 0.07, 0.15, 0.15, fill=TEAL)
    add_textbox(s, lx + 2.80, leg_y, 2.20, 0.28,
                "OOS — vérification du score",
                font_size=10, bold=True, color=TEAL,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
    add_filled_shape(s, MSO_SHAPE.RIGHT_ARROW, lx + 5.20, leg_y + 0.05, 0.40, 0.20,
                     fill=LIGHT_BLUE)
    add_textbox(s, lx + 5.65, leg_y, 2.20, 0.28,
                "pas rolling = longueur OOS",
                font_size=10, bold=True, color=NAVY,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

    # Bottom band — outcome
    band_y = leg_y + 0.50
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     0.55, band_y, SLIDE_W - 1.10, 0.45, fill=PALE_BLUE)
    add_textbox(s, 0.65, band_y, SLIDE_W - 1.30, 0.45,
                "À chaque pli : on optimise sur IS, on teste sur OOS → on compte si le retour OOS est positif (pli rentable)",
                font_size=10, bold=True, color=NAVY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 14 — PROM & WFE  (formula chain + grade table)
# ─────────────────────────────────────────────────────────────────────────────
def build_prom_wfe(prs: Presentation, page_num: int = 14) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Robustesse WFO",
                subtitle="Régularité du signal hors-échantillon")

    _bridge(s, "Étape 4 — On compte la part des fenêtres OOS où la stratégie est rentable.")

    # ── Left column: formula chain ──
    lx = 0.55
    cw = 4.30
    cy = 1.20
    cy_step = 0.78

    # B1: per-fold
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, lx, cy, cw, 0.55, fill=NAVY)
    add_label(s.shapes[-1], "Pli i :   retour OOS_i  →  rentable ou non",
              font_size=11, bold=False, color=WHITE)
    add_filled_shape(s, MSO_SHAPE.DOWN_ARROW, lx + cw/2 - 0.10, cy + 0.58, 0.20, 0.18,
                     fill=LIGHT_BLUE)

    # B2: Robustesse formula
    cy2 = cy + cy_step
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, lx, cy2, cw, 0.55, fill=BLUE)
    add_label(s.shapes[-1], "Robustesse  =  N(plis rentables)  /  N(plis OOS)",
              font_size=11, bold=True, color=WHITE)
    add_filled_shape(s, MSO_SHAPE.DOWN_ARROW, lx + cw/2 - 0.10, cy2 + 0.58, 0.20, 0.18,
                     fill=LIGHT_BLUE)

    # B3: numerical example
    cy3 = cy2 + cy_step
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, lx, cy3, cw, 0.55, fill=MID_BLUE)
    add_label(s.shapes[-1], "Exemple :   4 / 6   =   0,67",
              font_size=13, bold=True, color=WHITE)
    add_filled_shape(s, MSO_SHAPE.DOWN_ARROW, lx + cw/2 - 0.10, cy3 + 0.58, 0.20, 0.18,
                     fill=LIGHT_BLUE)

    # B4: interpretation
    cy4 = cy3 + cy_step
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, lx, cy4, cw, 0.55, fill=TEAL)
    add_label(s.shapes[-1], "Lecture :  profitable dans 67 % des fenêtres test",
              font_size=11, bold=True, color=WHITE)

    # ── Right column: grade table ──
    rx = lx + cw + 0.40
    rw = SLIDE_W - rx - 0.55

    # Header bar
    add_filled_shape(s, MSO_SHAPE.RECTANGLE, rx, cy, rw, 0.42, fill=NAVY)
    add_textbox(s, rx + 0.10, cy + 0.02, 0.70, 0.38, "Grade",
                font_size=10, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    add_textbox(s, rx + 0.80, cy + 0.02, 1.50, 0.38, "Seuil Robustesse",
                font_size=10, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    add_textbox(s, rx + 2.35, cy + 0.02, rw - 2.45, 0.38, "Interprétation",
                font_size=10, bold=True, color=WHITE,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

    grades = [
        ("A", "≥ 0,80",    "Excellent — très régulier",        GRADE_A),
        ("B", "0,60–0,79", "Bon — généralisable",               GRADE_B),
        ("C", "0,40–0,59", "Mitigé — à surveiller",             GRADE_C),
        ("D", "0,20–0,39", "Faible — peu régulier",             GRADE_D),
        ("F", "< 0,20",    "Rejeté — non généralisable",        GRADE_F),
    ]
    row_h = 0.50
    for i, (g, seuil, interp, color) in enumerate(grades):
        ry = cy + 0.45 + i * (row_h + 0.03)
        # Row background
        rbg = add_filled_shape(s, MSO_SHAPE.RECTANGLE, rx, ry, rw, row_h,
                               fill=WHITE if i % 2 else LIGHT_GRAY,
                               line=LIGHT_GRAY, line_width=0.5)
        # Grade badge
        gbadge = add_filled_shape(s, MSO_SHAPE.RECTANGLE, rx + 0.08, ry + 0.05,
                                  0.55, row_h - 0.10, fill=color)
        add_label(gbadge, g, font_size=18, bold=True, color=WHITE)
        # Seuil
        add_textbox(s, rx + 0.70, ry, 1.55, row_h, seuil,
                    font_size=11, bold=True, color=NEAR_BLACK,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # Interpretation
        add_textbox(s, rx + 2.30, ry, rw - 2.40, row_h, interp,
                    font_size=10, bold=False, color=NEAR_BLACK,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 15 — ARCHITECTURE TECHNIQUE  (layered stack, navy)
# ─────────────────────────────────────────────────────────────────────────────
def build_architecture(prs: Presentation, page_num: int = 15) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Architecture technique",
                subtitle="Stack de production déployé sur rdtalpha.xyz")

    _bridge(s, "Étape 5 — Le pipeline tourne dans une stack micro-services orchestrée, mise à jour à chaque clôture de séance.")

    # 4 horizontal layers + a vertical "compute" lane on right
    layers = [
        ("PRÉSENTATION",   "Next.js 14 · React · Tailwind",        "Vues : Tableau de Bord · Data · Signaux",       LIGHT_BLUE, NAVY),
        ("API",            "FastAPI · Pydantic · OpenAPI",         "Routeurs : runs · datasets · signals · ops",     SOFT_BLUE, NAVY),
        ("CALCUL",         "Redis · RQ workers · quant_core",      "Tâches : ingestion · backtests · WFO · scores",  MID_BLUE, WHITE),
        ("PERSISTANCE",    "PostgreSQL · MinIO (S3)",              "Metadata · datasets · artefacts · résultats",     NAVY,     WHITE),
    ]

    lx = 0.55
    lw = 6.50
    ly = 1.20
    lh = 0.78
    lgap = 0.10

    for i, (name, tech, desc, fill, color) in enumerate(layers):
        y = ly + i * (lh + lgap)
        add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, lx, y, lw, lh, fill=fill)
        # Layer name (left)
        add_textbox(s, lx + 0.15, y, 1.60, lh, name,
                    font_size=12, bold=True, color=color,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        # Tech stack (middle)
        add_textbox(s, lx + 1.85, y + 0.07, 2.20, lh - 0.14, tech,
                    font_size=10, bold=True, color=color,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        # Description (right)
        add_textbox(s, lx + 4.05, y + 0.07, lw - 4.15, lh - 0.14, desc,
                    font_size=9, bold=False, color=color,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        # Vertical connector arrow (between layers)
        if i < len(layers) - 1:
            ax = lx + lw / 2 - 0.10
            ay = y + lh + 0.01
            add_filled_shape(s, MSO_SHAPE.DOWN_ARROW, ax, ay, 0.20, lgap - 0.02,
                             fill=NAVY)

    # Right side: deployment box
    rx = lx + lw + 0.30
    rw = SLIDE_W - rx - 0.55
    rh = 4 * lh + 3 * lgap
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, rx, ly, rw, rh, fill=PALE_BLUE,
                     line=NAVY, line_width=1.0)
    add_textbox(s, rx + 0.10, ly + 0.10, rw - 0.20, 0.35, "DÉPLOIEMENT",
                font_size=11, bold=True, color=NAVY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    deploy_items = [
        ("Caddy",      "reverse-proxy TLS"),
        ("Docker",     "compose multi-services"),
        ("GCP VM",     "rdtalpha.xyz"),
        ("Cron daily", "ingestion · scoring"),
    ]
    dy = ly + 0.55
    for tag, desc in deploy_items:
        add_textbox(s, rx + 0.12, dy, rw - 0.24, 0.30, tag,
                    font_size=10, bold=True, color=NAVY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, rx + 0.12, dy + 0.30, rw - 0.24, 0.30, desc,
                    font_size=8, bold=False, color=GRAY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        dy += 0.72


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 16 — PLATEFORME : TABLEAU DE BORD  (real screenshot)
# ─────────────────────────────────────────────────────────────────────────────
def build_dashboard_view(prs: Presentation, page_num: int = 16) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Plateforme — Tableau de Bord",
                subtitle="Priorisation des opportunités sur les 73 titres MASI")

    _bridge(s, "Résultat — Le trader voit, chaque matin, le classement des titres par score WFO et grade de robustesse.")

    # Real screenshot (left ≈ 70%) + annotation panel (right)
    _embed_img(s, SHOTS / "dashboard.png", x=0.30, y=1.10, w=6.80)

    # Right annotation column
    rx = 7.25
    rw = SLIDE_W - rx - 0.45
    ry = 1.10
    _section_chip(s, rx, ry, rw, 0.40, "CE QUE LE TRADER VOIT",
                  fill=NAVY, font_size=10)

    callouts = [
        ("Univers actif",     "20 titres après filtres"),
        ("Edge éligibles",    "9 long · 11 short"),
        ("Action requise",    "E[R] médian = 0.45 %"),
        ("Classement",        "Trié par score WFO décroissant"),
        ("Suivi par titre",   "Méthode auto, retour attendu, succès, edge"),
    ]
    cy = ry + 0.55
    for tag, desc in callouts:
        add_filled_shape(s, MSO_SHAPE.OVAL, rx + 0.05, cy + 0.10, 0.12, 0.12, fill=TEAL)
        add_textbox(s, rx + 0.25, cy, rw - 0.30, 0.22, tag,
                    font_size=10, bold=True, color=NAVY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
        add_textbox(s, rx + 0.25, cy + 0.22, rw - 0.30, 0.30, desc,
                    font_size=8, bold=False, color=GRAY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
        cy += 0.60

    _caption(s, "Capture en direct : rdtalpha.xyz/dashboard — données MASI mises à jour le 2026-05-15")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 17 — PLATEFORME : ANALYSE D'UN TITRE  (real screenshot)
# ─────────────────────────────────────────────────────────────────────────────
def build_signal_view(prs: Presentation, page_num: int = 17) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Plateforme — Analyse titre",
                subtitle="Décomposition du score par famille · ex. ATW")

    _bridge(s, "Drill-down — Pour chaque titre, le détail des familles et variantes qui forment le score.")

    # Real screenshot (full width)
    _embed_img(s, SHOTS / "signals_atw_indicateurs.png", x=0.30, y=1.10, w=6.80)

    # Right annotation column
    rx = 7.25
    rw = SLIDE_W - rx - 0.45
    ry = 1.10
    _section_chip(s, rx, ry, rw, 0.40, "EXEMPLE : ATW",
                  fill=GRADE_F, font_size=10)

    callouts = [
        ("Score global",      "-66.7 %  →  Vente forte"),
        ("Tendance",          "-20 %  ·  contre-tendance"),
        ("Momentum",          "-80 %  ·  fort baissier"),
        ("Cohérence familles","3 / 4 familles alignées"),
        ("Lecture",           "Repli technique confirmé"),
    ]
    cy = ry + 0.55
    for tag, desc in callouts:
        add_filled_shape(s, MSO_SHAPE.OVAL, rx + 0.05, cy + 0.10, 0.12, 0.12, fill=GRADE_F)
        add_textbox(s, rx + 0.25, cy, rw - 0.30, 0.22, tag,
                    font_size=10, bold=True, color=NAVY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
        add_textbox(s, rx + 0.25, cy + 0.22, rw - 0.30, 0.30, desc,
                    font_size=8, bold=False, color=GRAY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
        cy += 0.60

    _caption(s, "Capture en direct : rdtalpha.xyz/signals — Attijariwafa Bank, mode Expanded Pure TA")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 18 — VALIDATION STATISTIQUE
# ─────────────────────────────────────────────────────────────────────────────
def build_validation(prs: Presentation, page_num: int = 18) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Validation statistique",
                subtitle="Stabilité temporelle · sur-apprentissage écarté")

    _bridge(s, "Pour conclure la méthodologie : trois garanties statistiques contre le sur-apprentissage.")

    # 3 horizontal claims with metric badges
    claims = [
        ("ANTI-OVERFITTING", "Robustesse",
         "Mesure sur fenêtres OOS jamais vues pendant l'optimisation",
         "N(plis rentables) / N(plis OOS)", NAVY),
        ("STABILITÉ TEMPORELLE", "6 sous-périodes",
         "Score testé sur 2018→2025 par fenêtres glissantes",
         "Variance des grades", BLUE),
        ("SIGNIFIANCE", "Walk-Forward × 10",
         "Indépendance des plis → test de régularité répété",
         "Robustesse ≥ 0,60 (grade A/B)", TEAL),
    ]

    n = len(claims)
    margin = 0.55
    gap = 0.20
    cw = (SLIDE_W - 2 * margin - (n - 1) * gap) / n
    cy = 1.20
    ch_box = 2.85

    for i, (name, metric, body, formula, color) in enumerate(claims):
        cx = margin + i * (cw + gap)
        # Card body
        add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                         cx, cy, cw, ch_box, fill=PALE_BLUE,
                         line=color, line_width=1.5)
        # Header pill
        _section_chip(s, cx + 0.10, cy + 0.10, cw - 0.20, 0.42,
                      name, fill=color, font_size=10)
        # Metric badge
        add_textbox(s, cx + 0.10, cy + 0.65, cw - 0.20, 0.45, metric,
                    font_size=16, bold=True, color=color,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # Body
        add_textbox(s, cx + 0.15, cy + 1.20, cw - 0.30, 0.95, body,
                    font_size=10, bold=False, color=NEAR_BLACK,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)
        # Formula (bottom strip)
        add_filled_shape(s, MSO_SHAPE.RECTANGLE, cx + 0.10, cy + ch_box - 0.40,
                         cw - 0.20, 0.30, fill=color)
        add_textbox(s, cx + 0.15, cy + ch_box - 0.40, cw - 0.30, 0.30, formula,
                    font_size=10, bold=True, color=WHITE,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    # Bottom band — synthesis
    band_y = cy + ch_box + 0.20
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     0.55, band_y, SLIDE_W - 1.10, 0.50, fill=NAVY)
    add_textbox(s, 0.65, band_y, SLIDE_W - 1.30, 0.50,
                "Garantie : seules les variantes de grade A ou B sont retenues — la décision technique est statistiquement défendable.",
                font_size=11, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 19 — CONCLUSION & PERSPECTIVES
# ─────────────────────────────────────────────────────────────────────────────
def build_conclusion(prs: Presentation, page_num: int = 19) -> None:
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Conclusion & Perspectives",
                subtitle="Contributions livrées et évolutions envisagées")

    _bridge(s, "En synthèse — cinq apports concrets et trois axes d'évolution pour le Desk Actions.")

    # ── Top row: 5 contribution circles ──
    contributions = [
        (NAVY,      "Signal Engine",        "20 indicateurs · 4 familles · score [-100, +100]"),
        (BLUE,      "Walk-Forward",         "10 plis OOS · sélection par PROM · grade WFE"),
        (MID_BLUE,  "Plateforme",           "Tableau de Bord · Data · Signaux · drill-down"),
        (TEAL,      "Stack de prod.",       "Next.js · FastAPI · Redis · PG · MinIO"),
        (SOFT_BLUE, "Déploiement",          "rdtalpha.xyz · 73 titres · cron quotidien"),
    ]
    n = len(contributions)
    margin = 0.40
    cw = (SLIDE_W - 2 * margin) / n
    cy = 1.50
    r = 0.42

    for i, (color, ctitle, body) in enumerate(contributions):
        cx = margin + cw * i + cw / 2
        circle = add_filled_shape(s, MSO_SHAPE.OVAL,
                                  cx - r, cy - r, 2 * r, 2 * r, fill=color)
        add_label(circle, str(i + 1), font_size=20, bold=True, color=WHITE)
        add_textbox(s, cx - cw / 2 + 0.05, cy + r + 0.10, cw - 0.10, 0.30, ctitle,
                    font_size=11, bold=True, color=color,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, cx - cw / 2 + 0.05, cy + r + 0.42, cw - 0.10, 0.60, body,
                    font_size=9, bold=False, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)

    # ── Perspectives band ──
    band_y = 3.45
    add_textbox(s, 0.55, band_y, SLIDE_W - 1.10, 0.30,
                "PERSPECTIVES",
                font_size=11, bold=True, color=NAVY,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

    perspectives = [
        ("Intégration Bloomberg",   "factor data temps-réel"),
        ("Alertes Slack / mail",    "déclenchement sur grade A"),
        ("Extension Obligataire",   "courbe taux + signaux dérivés"),
    ]
    py = 3.80
    pgap = 0.10
    pw = (SLIDE_W - 1.10 - 2 * pgap) / 3
    for i, (tag, desc) in enumerate(perspectives):
        px = 0.55 + i * (pw + pgap)
        add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, px, py, pw, 0.65,
                         fill=PALE_BLUE, line=NAVY, line_width=0.75)
        add_textbox(s, px + 0.15, py + 0.04, pw - 0.30, 0.28, tag,
                    font_size=11, bold=True, color=NAVY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, px + 0.15, py + 0.32, pw - 0.30, 0.28, desc,
                    font_size=9, bold=False, color=GRAY,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

    # ── Thank-you ribbon ──
    ty = 4.60
    add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                     0.55, ty, SLIDE_W - 1.10, 0.45, fill=NAVY)
    add_textbox(s, 0.65, ty, SLIDE_W - 1.30, 0.45,
                "Merci de votre attention   —   questions ?",
                font_size=13, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ── MAIN ──────────────────────────────────────────────────────────────────────

PIPELINE = [
    (9,  build_problematique),
    (10, build_demarche),
    (11, build_analyse_technique),
    (12, build_signal_engine),
    (13, build_wfo),
    (14, build_prom_wfe),
    (15, build_architecture),
    (16, build_dashboard_view),
    (17, build_signal_view),
    (18, build_validation),
    (19, build_conclusion),
]


def main():
    prs = Presentation(str(SRC))
    print(f"Template: {len(prs.slides)} slides")

    for page_num, fn in PIPELINE:
        fn(prs, page_num=page_num)
        print(f"  OK Slide {page_num:>2}  {fn.__name__.replace('build_','')}")

    # Try saving to v2; fall back if locked
    for path in [DST,
                 Path(str(DST).replace('.pptx', '_v3.pptx')),
                 Path(str(DST).replace('.pptx', '_v4.pptx'))]:
        try:
            prs.save(str(path))
            print(f"\nSaved -> {path}  |  total {len(prs.slides)} slides")
            return
        except PermissionError:
            print(f"  (locked: {path})")
            continue
    raise RuntimeError("All target paths locked")


if __name__ == "__main__":
    main()
