"""Build Stratégie + Backtest (Edge) side slides for BMCE_Final_Khadija_v2.pptx.

User copies these slides into v2 manually (v2 is open in PowerPoint).
"""
from __future__ import annotations
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

from theme import (
    NAVY, BLUE, MID_BLUE, LIGHT_BLUE, TEAL, SOFT_BLUE, WHITE, NEAR_BLACK,
    GRAY, LIGHT_GRAY, PALE_BLUE, ACCENT_OR,
    GRADE_A, GRADE_B, GRADE_C, GRADE_D, GRADE_F,
    FONT, SLIDE_W, SLIDE_H,
    add_filled_shape, add_textbox, add_label, add_multiline,
    page_chrome, set_text, clear_animations,
)

DST = Path(r"C:/Users/taha/Downloads/BMCE_Khadija_NEW_SLIDES_v3.pptx")


def _new_blank_slide(prs):
    blank = None
    for layout in prs.slide_layouts:
        if len(layout.placeholders) == 0:
            blank = layout; break
    return prs.slides.add_slide(blank or prs.slide_layouts[-1])


def _bridge(slide, text, y=0.72):
    add_textbox(slide, 0.40, y, 9.20, 0.30, text,
                font_size=11, bold=False, color=GRAY,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 0 — FEATURE ANALYSIS : Meilleur indicateur par famille
# ─────────────────────────────────────────────────────────────────────────────
def build_feature_analysis_results(prs, page_num=20):
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Feature Analysis",
                subtitle="Le meilleur indicateur retenu pour chaque famille")
    _bridge(s, "Pour chaque famille, un seul indicateur est sélectionné — celui dont le verdict est le plus fiable historiquement.")

    # ── 4 vertical lanes, each = one family's winner + its 2 verdict states
    winners = [
        {
            "family":  "TENDANCE",
            "color":   NAVY,
            "winner":  "SMA 50",
            "what":    "Position du prix vs sa moyenne mobile simple",
            "states": [
                ("Tendance haussière", "Prix  >  SMA 50",     GRADE_A, "↑"),
                ("Tendance baissière", "Prix  <  SMA 50",     GRADE_F, "↓"),
            ],
        },
        {
            "family":  "MOMENTUM",
            "color":   BLUE,
            "winner":  "MACD",
            "what":    "Différence MACD vs sa ligne de signal",
            "states": [
                ("Momentum haussier", "MACD  >  Signal",      GRADE_A, "↑"),
                ("Momentum baissier", "MACD  <  Signal",      GRADE_F, "↓"),
            ],
        },
        {
            "family":  "OSCILLATION",
            "color":   MID_BLUE,
            "winner":  "RSI 14",
            "what":    "Indice de force relative sur 14 jours",
            "states": [
                ("Suracheté",  "RSI  >  70",                  GRADE_F, "▲"),
                ("Survendu",   "RSI  <  30",                  GRADE_A, "▼"),
            ],
        },
        {
            "family":  "VOLUME",
            "color":   TEAL,
            "winner":  "A/D Line",
            "what":    "Ligne d'accumulation / distribution",
            "states": [
                ("Accumulation", "Pente A/D  >  0",           GRADE_A, "↑"),
                ("Distribution", "Pente A/D  <  0",           GRADE_F, "↓"),
            ],
        },
    ]

    n = len(winners)
    gap = 0.15
    margin = 0.40
    lane_w = (SLIDE_W - 2*margin - (n-1)*gap) / n
    lane_y = 1.10
    lane_h = 3.70

    for i, w in enumerate(winners):
        x = margin + i * (lane_w + gap)

        # Family header strip
        head = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, lane_y,
                                lane_w, 0.34, fill=w["color"])
        add_label(head, w["family"], font_size=12, bold=True, color=WHITE)

        # Lane body (white with border)
        body = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, lane_y + 0.34,
                                lane_w, lane_h - 0.34,
                                fill=WHITE, line=w["color"], line_width=0.75)

        # "Indicateur retenu" label
        add_textbox(s, x + 0.05, lane_y + 0.40, lane_w - 0.10, 0.22,
                    "Indicateur retenu", font_size=8, bold=True, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

        # Winning indicator (big, navy)
        win_box = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                   x + 0.10, lane_y + 0.65,
                                   lane_w - 0.20, 0.42,
                                   fill=PALE_BLUE)
        add_label(win_box, w["winner"], font_size=14, bold=True, color=NAVY)

        # Short description
        add_textbox(s, x + 0.08, lane_y + 1.13, lane_w - 0.16, 0.45,
                    w["what"], font_size=9, bold=False, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)

        # Divider line label
        add_textbox(s, x + 0.05, lane_y + 1.65, lane_w - 0.10, 0.22,
                    "Verdict", font_size=8, bold=True, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

        # Two verdict states stacked
        st_y0 = lane_y + 1.90
        st_h  = 0.70
        st_gap = 0.10
        for j, (label, cond, col, arrow) in enumerate(w["states"]):
            sy = st_y0 + j * (st_h + st_gap)
            # State header strip (colored)
            sh = add_filled_shape(s, MSO_SHAPE.RECTANGLE,
                                  x + 0.10, sy, lane_w - 0.20, 0.30,
                                  fill=col)
            add_label(sh, f"{arrow}  {label}", font_size=10, bold=True, color=WHITE)
            # Condition (white box under)
            cb = add_filled_shape(s, MSO_SHAPE.RECTANGLE,
                                  x + 0.10, sy + 0.30, lane_w - 0.20, 0.36,
                                  fill=WHITE, line=col, line_width=0.5)
            add_label(cb, cond, font_size=10, bold=True, color=NAVY)

    # Bottom synthesis bar
    syn_y = lane_y + lane_h + 0.12
    syn = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                           0.40, syn_y, SLIDE_W - 0.80, 0.36, fill=NAVY)
    add_label(syn,
              "4 verdicts indépendants → agrégés en un score composite [-100, +100]",
              font_size=11, bold=True, color=WHITE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE A — STRATÉGIE : Score composite des 4 familles
# ─────────────────────────────────────────────────────────────────────────────
def build_strategie(prs, page_num=21):
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Stratégie",
                subtitle="Un score composite issu de 4 familles d'indicateurs")
    _bridge(s, "20 indicateurs, 4 familles orthogonales, un seul score [-100, +100] — voici comment on agrège les votes.")

    # ── 4 family cards (top row) ───────────────────────────────────────────
    families = [
        ("TENDANCE",    "SMA · EMA · Ichimoku\nBollinger",       "Direction\nde fond",      NAVY),
        ("MOMENTUM",    "MACD · ROC · TRIX\nADX · TSI",          "Vitesse\ndu mouvement",   BLUE),
        ("OSCILLATION", "RSI · Stochastique\nCCI · MFI · Ult.",  "Zones\nd'excès",          MID_BLUE),
        ("VOLUME",      "OBV · CMF · VWAP\nA/D Line · Force",    "Conviction\ndes échanges", TEAL),
    ]
    n = len(families)
    gap = 0.15
    margin = 0.40
    card_w = (SLIDE_W - 2*margin - (n-1)*gap) / n
    card_h = 1.55
    card_y = 1.10

    for i, (name, indics, role, color) in enumerate(families):
        x = margin + i * (card_w + gap)
        # Header strip (colored)
        head = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, card_y,
                                card_w, 0.32, fill=color)
        add_label(head, name, font_size=12, bold=True, color=WHITE)
        # Body (white card with thin border)
        body = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, card_y + 0.32,
                                card_w, card_h - 0.32,
                                fill=WHITE, line=color, line_width=0.75)
        # Role line (gray italic)
        add_textbox(s, x + 0.05, card_y + 0.36, card_w - 0.10, 0.45,
                    role, font_size=9, bold=False, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # Indicators
        add_textbox(s, x + 0.05, card_y + 0.82, card_w - 0.10, 0.65,
                    indics, font_size=9, bold=True, color=NAVY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # Sub-score chip at bottom
        chip_y = card_y + card_h - 0.10
        chip = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                x + card_w*0.20, chip_y, card_w*0.60, 0.26,
                                fill=PALE_BLUE)
        add_label(chip, f"Sᵢ ∈ [-100, +100]", font_size=8, bold=True, color=NAVY)

    # ── Down arrows under each card pointing to formula ────────────────────
    arrow_y = card_y + card_h + 0.20
    for i in range(n):
        x = margin + i * (card_w + gap) + card_w/2 - 0.15
        a = add_filled_shape(s, MSO_SHAPE.DOWN_ARROW, x, arrow_y, 0.30, 0.28,
                             fill=LIGHT_BLUE)

    # ── Formula band ────────────────────────────────────────────────────────
    f_y = arrow_y + 0.32
    f_band = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                              0.40, f_y, SLIDE_W - 0.80, 0.48, fill=NAVY)
    add_label(f_band,
              "Score global  =  w₁·S_tendance  +  w₂·S_momentum  +  w₃·S_oscillation  +  w₄·S_volume",
              font_size=13, bold=True, color=WHITE)

    # ── Decision scale at bottom ────────────────────────────────────────────
    scale_y = f_y + 0.60
    zones = [
        ("Vente forte",  "[-100, -60]", GRADE_F),
        ("Vente",        "[-60, -20]",  GRADE_D),
        ("Neutre",       "[-20, +20]",  GRADE_C),
        ("Achat",        "[+20, +60]",  GRADE_B),
        ("Achat fort",   "[+60, +100]", GRADE_A),
    ]
    z_w = (SLIDE_W - 0.80) / len(zones)
    for i, (label, rng, col) in enumerate(zones):
        x = 0.40 + i * z_w
        z = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, scale_y, z_w, 0.32,
                             fill=col)
        add_label(z, label, font_size=10, bold=True, color=WHITE)
        add_textbox(s, x, scale_y + 0.34, z_w, 0.22, rng,
                    font_size=8, bold=True, color=NAVY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE B — BACKTEST : Mesurer l'edge du signal
# ─────────────────────────────────────────────────────────────────────────────
def build_backtest_edge(prs, page_num=22):
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Backtest",
                subtitle="Mesurer l'edge — trois critères statistiques")
    _bridge(s, "Un score élevé ne suffit pas : il doit prouver son edge hors échantillon, sur trois axes complémentaires.")

    # ── Top: definition strip ─────────────────────────────────────────────
    def_y = 1.05
    def_band = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                0.40, def_y, SLIDE_W - 0.80, 0.40,
                                fill=PALE_BLUE)
    add_label(def_band,
              "L'edge = capacité du signal à générer un rendement positif et régulier sur des données jamais vues.",
              font_size=11, bold=True, color=NAVY)

    # ── 3 evaluation cards ────────────────────────────────────────────────
    metrics = [
        {
            "name": "PROM",
            "full": "Pessimistic Return on Margin",
            "what": "Rentabilité pénalisée",
            "why":  "Réduit le poids des stratégies dont la performance dépend de quelques trades chanceux.",
            "form": "PROM = [(nW − √nW)·w̄ − (nL + √nL)·ℓ̄] / C",
            "color": NAVY,
        },
        {
            "name": "WFE",
            "full": "Walk-Forward Efficiency",
            "what": "Capacité à généraliser",
            "why":  "Compare la performance Out-of-Sample à celle In-Sample : un WFE proche de 1 signifie peu de sur-apprentissage.",
            "form": "WFE = Perf_OOS / Perf_IS",
            "color": BLUE,
        },
        {
            "name": "Robustesse",
            "full": "Régularité hors échantillon",
            "what": "Fréquence de succès",
            "why":  "Part des fenêtres de test WFO où la stratégie est rentable — mesure la régularité, pas seulement la moyenne.",
            "form": "R = N(plis OOS rentables) / N(plis OOS)",
            "color": TEAL,
        },
    ]

    n = len(metrics)
    gap = 0.20
    margin = 0.40
    card_w = (SLIDE_W - 2*margin - (n-1)*gap) / n
    card_h = 2.65
    card_y = 1.70

    for i, m in enumerate(metrics):
        x = margin + i * (card_w + gap)
        # Header
        head = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, card_y,
                                card_w, 0.40, fill=m["color"])
        add_label(head, m["name"], font_size=16, bold=True, color=WHITE)
        # Body card
        body = add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, card_y + 0.40,
                                card_w, card_h - 0.40,
                                fill=WHITE, line=m["color"], line_width=0.75)
        # Full name (italic-ish)
        add_textbox(s, x + 0.10, card_y + 0.44, card_w - 0.20, 0.30,
                    m["full"], font_size=9, bold=False, color=GRAY,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # What it measures (chip)
        chip = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                x + card_w*0.10, card_y + 0.80,
                                card_w*0.80, 0.30,
                                fill=PALE_BLUE)
        add_label(chip, m["what"], font_size=10, bold=True, color=NAVY)
        # Why (description)
        add_textbox(s, x + 0.12, card_y + 1.20, card_w - 0.24, 1.00,
                    m["why"], font_size=10, bold=False, color=NEAR_BLACK,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
        # Formula at bottom
        form_y = card_y + card_h - 0.40
        form_box = add_filled_shape(s, MSO_SHAPE.RECTANGLE,
                                    x + 0.05, form_y, card_w - 0.10, 0.32,
                                    fill=m["color"])
        add_label(form_box, m["form"], font_size=9, bold=True, color=WHITE)

    # ── Bottom synthesis bar ───────────────────────────────────────────────
    syn_y = card_y + card_h + 0.18
    syn = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                           0.40, syn_y, SLIDE_W - 0.80, 0.38, fill=NAVY)
    add_label(syn,
              "Décision finale  =  Score composite  ×  Grade WFO (A ou B requis pour être retenu)",
              font_size=12, bold=True, color=WHITE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE C — EDGE ANALYTICS : Critères statistiques de validation du signal
# ─────────────────────────────────────────────────────────────────────────────
def build_edge_analytics(prs, page_num=23):
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Edge Analytics",
                subtitle="Quatre critères pour valider qu'un signal a un edge réel")
    _bridge(s, "Avant d'être diffusé, chaque signal franchit quatre filtres statistiques — un seul échec et il est rejeté.")

    # ── Définition strip ───────────────────────────────────────────────────
    def_y = 1.05
    def_band = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                0.40, def_y, SLIDE_W - 0.80, 0.38,
                                fill=PALE_BLUE)
    add_label(def_band,
              "Edge réel  ≠  performance passée  —  c'est la probabilité statistique que le signal sur-performe le hasard.",
              font_size=11, bold=True, color=NAVY)

    # ── 4 criterion cards (2x2 grid) ───────────────────────────────────────
    criteria = [
        {
            "n":   "1",
            "name": "Retour attendu positif",
            "what": "E[R]  >  seuil",
            "expl": "La stratégie doit gagner en moyenne après coûts et slippage. "
                    "Calcul : E[R] = p · ḡ − (1−p) · l̄ , avec p = taux de succès, "
                    "ḡ = gain moyen, l̄ = perte moyenne.",
            "verdict": "Rejeté si  E[R]  ≤  0",
            "color": NAVY,
        },
        {
            "n":   "2",
            "name": "Borne inférieure de Wilson",
            "what": "Wilson(p̂, N, α)  >  p₀",
            "expl": "Vérifie que le taux de succès observé p̂ n'est pas un coup de chance. "
                    "Wilson calcule la borne inférieure d'un intervalle de confiance à 95 % "
                    "— elle doit dépasser le seuil p₀ (typiquement 0,50).",
            "verdict": "Rejeté si la borne basse  ≤  50 %",
            "color": BLUE,
        },
        {
            "n":   "3",
            "name": "Profit Factor",
            "what": "PF  =  Σ gains  /  Σ pertes",
            "expl": "Mesure le ratio entre les gains totaux et les pertes totales. "
                    "Un PF de 1,5 signifie que chaque dirham perdu est compensé par 1,50 DH gagné. "
                    "Plus robuste que le simple win-rate.",
            "verdict": "Rejeté si  PF  <  1,2",
            "color": MID_BLUE,
        },
        {
            "n":   "4",
            "name": "Taille d'échantillon",
            "what": "N(trades OOS)  ≥  N_min",
            "expl": "Sans assez de trades hors échantillon, les statistiques ne sont pas fiables. "
                    "On exige un minimum de trades sur l'ensemble des plis WFO pour que les "
                    "intervalles de confiance restent serrés.",
            "verdict": "Rejeté si  N_OOS  <  30",
            "color": TEAL,
        },
    ]

    # 2 columns × 2 rows grid
    margin = 0.40
    gap_x = 0.20
    gap_y = 0.18
    card_w = (SLIDE_W - 2*margin - gap_x) / 2
    card_h = 1.55
    grid_y0 = 1.55

    for idx, c in enumerate(criteria):
        col = idx % 2
        row = idx // 2
        x = margin + col * (card_w + gap_x)
        y = grid_y0 + row * (card_h + gap_y)

        # Number badge (left, colored circle)
        num = add_filled_shape(s, MSO_SHAPE.OVAL, x, y + 0.18, 0.50, 0.50,
                               fill=c["color"])
        add_label(num, c["n"], font_size=20, bold=True, color=WHITE)

        # Main card (right of number)
        cx = x + 0.60
        cw = card_w - 0.60
        body = add_filled_shape(s, MSO_SHAPE.RECTANGLE, cx, y, cw, card_h,
                                fill=WHITE, line=c["color"], line_width=0.75)

        # Top strip: criterion name
        head = add_filled_shape(s, MSO_SHAPE.RECTANGLE, cx, y, cw, 0.32,
                                fill=c["color"])
        add_label(head, c["name"], font_size=12, bold=True, color=WHITE,
                  align=PP_ALIGN.LEFT)

        # Formula chip
        form = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                                cx + 0.08, y + 0.38, cw - 0.16, 0.28,
                                fill=PALE_BLUE)
        add_label(form, c["what"], font_size=10, bold=True, color=NAVY)

        # Explanation
        add_textbox(s, cx + 0.10, y + 0.70, cw - 0.20, 0.60,
                    c["expl"], font_size=9, bold=False, color=NEAR_BLACK,
                    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)

        # Verdict line (red-ish strip at bottom)
        verd = add_filled_shape(s, MSO_SHAPE.RECTANGLE,
                                cx, y + card_h - 0.26, cw, 0.26,
                                fill=GRADE_F)
        add_label(verd, c["verdict"], font_size=9, bold=True, color=WHITE)

    # ── Bottom synthesis bar ───────────────────────────────────────────────
    syn_y = grid_y0 + 2*card_h + gap_y + 0.10
    syn = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                           0.40, syn_y, SLIDE_W - 0.80, 0.36, fill=NAVY)
    add_label(syn,
              "Signal validé  =  4 / 4 critères passés  →  affiché sur le tableau de bord",
              font_size=11, bold=True, color=WHITE)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE D — ARCHITECTURE : Diagramme des composants et flux
# ─────────────────────────────────────────────────────────────────────────────
def build_architecture(prs, page_num=24):
    s = _new_blank_slide(prs)
    page_chrome(s, page_num=page_num,
                title="Architecture",
                subtitle="Pipeline asynchrone — frontend, API, worker, persistance")
    _bridge(s, "Le noyau quant Python est partagé entre l'API et le worker ; les calculs lourds sont mis en file pour garder l'UI réactive.")

    # ── Helper: small arrow between two anchor points
    def arrow(x, y, w, h, *, fill=NAVY, kind="RIGHT_ARROW"):
        shp = MSO_SHAPE.RIGHT_ARROW if kind == "RIGHT_ARROW" else (
              MSO_SHAPE.DOWN_ARROW  if kind == "DOWN"        else MSO_SHAPE.LEFT_RIGHT_ARROW)
        return add_filled_shape(s, shp, x, y, w, h, fill=fill)

    def conn(x, y, w, h, *, fill=LIGHT_BLUE):
        # thin connector line as a rectangle
        return add_filled_shape(s, MSO_SHAPE.RECTANGLE, x, y, w, h, fill=fill)

    def box(x, y, w, h, title, sub, *, fill=WHITE, line=NAVY,
            title_color=NAVY, sub_color=GRAY, title_pt=11, sub_pt=8):
        b = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h,
                             fill=fill, line=line, line_width=1.0)
        add_textbox(s, x + 0.05, y + 0.06, w - 0.10, 0.30,
                    title, font_size=title_pt, bold=True, color=title_color,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, x + 0.05, y + 0.36, w - 0.10, h - 0.42,
                    sub, font_size=sub_pt, bold=False, color=sub_color,
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)
        return b

    # ── Layer band labels on the left ────────────────────────────────────
    def lane_label(y, h, text, color):
        lab = add_filled_shape(s, MSO_SHAPE.RECTANGLE, 0.10, y, 0.55, h,
                               fill=color)
        add_label(lab, text, font_size=9, bold=True, color=WHITE)
        return lab

    # ── Coordinates ───────────────────────────────────────────────────────
    bx0 = 0.80                          # diagram left edge
    bxw = SLIDE_W - bx0 - 0.20          # diagram width
    cx  = bx0 + bxw / 2.0               # center x

    # T1: USER ─ CADDY ─ FRONTEND (horizontal row)
    lane_label(1.00, 0.50, "CLIENT", MID_BLUE)
    u_w, u_h = 1.50, 0.50
    c_w, c_h = 1.30, 0.50
    f_w, f_h = 2.50, 0.50
    gap = 0.30
    total = u_w + c_w + f_w + 2*gap
    u_x = bx0 + (bxw - total) / 2.0
    c_x = u_x + u_w + gap
    f_x = c_x + c_w + gap
    box(u_x, 1.00, u_w, u_h, "Utilisateur", "Trader · Desk Actions", title_pt=10)
    arrow(u_x + u_w + 0.02, 1.13, gap - 0.04, 0.24, fill=LIGHT_BLUE)
    box(c_x, 1.00, c_w, c_h, "Caddy", "TLS · reverse proxy", title_pt=10)
    arrow(c_x + c_w + 0.02, 1.13, gap - 0.04, 0.24, fill=LIGHT_BLUE)
    box(f_x, 1.00, f_w, f_h, "Frontend · Next.js 14",
        "React · TypeScript · Tableau de bord", title_pt=10, line=BLUE)

    # Down arrow Frontend → API
    arrow(f_x + f_w/2 - 0.12, 1.55, 0.24, 0.30, fill=BLUE, kind="DOWN")
    add_textbox(s, f_x + f_w/2 + 0.18, 1.58, 1.20, 0.25,
                "REST + JSON", font_size=8, bold=True, color=GRAY)

    # T2: API
    lane_label(1.90, 0.55, "API", NAVY)
    api_w = 5.20
    api_x = bx0 + (bxw - api_w) / 2.0
    box(api_x, 1.90, api_w, 0.55, "FastAPI · Pydantic · OpenAPI",
        "/runs   /datasets   /signals   /ops", title_pt=11, line=NAVY)

    # API has 3 outgoing flows: write to Postgres (down-left), enqueue Redis (down-center), read MinIO (down-right)
    # Center: down arrow API → Redis
    arrow(api_x + api_w/2 - 0.12, 2.50, 0.24, 0.30, fill=NAVY, kind="DOWN")
    add_textbox(s, api_x + api_w/2 + 0.18, 2.53, 1.40, 0.25,
                "enqueue job", font_size=8, bold=True, color=GRAY)

    # T3: ASYNC layer — Redis + Worker side by side
    lane_label(2.85, 0.55, "ASYNC", BLUE)
    r_w, r_h = 1.80, 0.55
    w_w, w_h = 3.00, 0.55
    a_gap = 0.30
    a_total = r_w + w_w + a_gap
    r_x = bx0 + (bxw - a_total) / 2.0
    w_x = r_x + r_w + a_gap
    box(r_x, 2.85, r_w, r_h, "Redis · RQ",
        "File de jobs prioritisée", title_pt=11, line=BLUE)
    # arrow Redis → Worker
    arrow(r_x + r_w + 0.02, 2.98, a_gap - 0.04, 0.30, fill=BLUE)
    box(w_x, 2.85, w_w, w_h, "Worker · quant_core",
        "Numba JIT · WFO · PROM · Edge analytics", title_pt=11, line=BLUE)

    # Worker has 2 downward arrows: writes Postgres + writes MinIO
    # T4: PERSISTANCE — Postgres + MinIO side by side
    lane_label(3.95, 0.65, "DATA", TEAL)
    p_w, p_h = 2.20, 0.65
    m_w, m_h = 2.20, 0.65
    p_gap = 0.60
    p_total = p_w + m_w + p_gap
    p_x = bx0 + (bxw - p_total) / 2.0
    m_x = p_x + p_w + p_gap
    box(p_x, 3.95, p_w, p_h, "PostgreSQL",
        "runs · datasets · users · scores", title_pt=11, line=TEAL)
    box(m_x, 3.95, m_w, m_h, "MinIO (S3)",
        "signaux · plots PNG · CSV", title_pt=11, line=TEAL)

    # Worker → Postgres (diagonal-ish: down arrow from worker center-left to Postgres top)
    # We'll use a down arrow stub from each worker side to each persistence box
    arrow(w_x + 0.40, 3.45, 0.24, 0.45, fill=TEAL, kind="DOWN")
    arrow(w_x + w_w - 0.64, 3.45, 0.24, 0.45, fill=TEAL, kind="DOWN")

    # API also reads from Postgres/MinIO — show with bidirectional arrows on the LEFT side
    # A small "lecture API ↔ Postgres" callout
    # We'll add a thin bidirectional arrow from API down to Postgres on the far left
    arrow(p_x + p_w/2 - 0.12, 2.50, 0.24, 1.40, fill=PALE_BLUE, kind="DOWN")
    add_textbox(s, p_x - 0.10, 3.10, p_w + 0.20, 0.22,
                "lecture API (résultats)", font_size=7, bold=True,
                color=GRAY, align=PP_ALIGN.CENTER)

    # MinIO read by API (right side)
    arrow(m_x + m_w/2 - 0.12, 2.50, 0.24, 1.40, fill=PALE_BLUE, kind="DOWN")
    add_textbox(s, m_x - 0.10, 3.10, m_w + 0.20, 0.22,
                "téléchargement plots", font_size=7, bold=True,
                color=GRAY, align=PP_ALIGN.CENTER)

    # ── Deployment strip at bottom ─────────────────────────────────────────
    dep_y = 4.78
    dep = add_filled_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE,
                           0.40, dep_y, SLIDE_W - 0.80, 0.30, fill=NAVY)
    add_label(dep,
              "Déploiement  ·  Docker Compose  ·  GCP VM  ·  Cron quotidien (ingestion OHLCV)  ·  rdtalpha.xyz",
              font_size=10, bold=True, color=WHITE)


# ─────────────────────────────────────────────────────────────────────────────
def main():
    prs = Presentation()
    prs.slide_width  = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    build_feature_analysis_results(prs, page_num=20)
    build_strategie(prs, page_num=21)
    build_backtest_edge(prs, page_num=22)
    build_edge_analytics(prs, page_num=23)
    build_architecture(prs, page_num=24)
    DST.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(DST))
    print(f"OK  wrote {DST}  ({DST.stat().st_size} bytes, {len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
