"""
Build two professional PowerPoint presentations.
Run: python docs/build_presentations.py
Outputs:
  - docs/Presentation_1_Architecture_Plateforme.pptx
  - docs/Presentation_2_Moteur_de_Signaux.pptx
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
import os

# ── Design System ───────────────────────────────────────────────
NAVY      = RGBColor(0x0B, 0x14, 0x26)
DARK_CARD = RGBColor(0x14, 0x20, 0x38)
BLUE      = RGBColor(0x38, 0x9F, 0xDD)
GREEN     = RGBColor(0x27, 0xAE, 0x7A)
AMBER     = RGBColor(0xE6, 0xA8, 0x1E)
PURPLE    = RGBColor(0x8B, 0x72, 0xCF)
CORAL     = RGBColor(0xE0, 0x5D, 0x5D)
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
SILVER    = RGBColor(0xA0, 0xAE, 0xC0)
LIGHT     = RGBColor(0xD0, 0xD8, 0xE4)
MUTED     = RGBColor(0x6B, 0x7B, 0x93)

W = Inches(13.333)
H = Inches(7.5)

# ── Helpers ─────────────────────────────────────────────────────

def bg(slide, color=NAVY):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color

def rect(slide, l, t, w, h, color, text="", sz=14, fc=WHITE, bold=False, align=PP_ALIGN.CENTER):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l, t, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    sh.shadow.inherit = False
    if text:
        tf = sh.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(sz)
        p.font.color.rgb = fc
        p.font.bold = bold
        p.alignment = align
    return sh

def txt(slide, l, t, w, h, text, sz=18, color=WHITE, bold=False, align=PP_ALIGN.LEFT, name="Calibri"):
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(sz)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = name
    p.alignment = align
    return tf

def para(tf, text, sz=18, color=WHITE, bold=False, before=Pt(4), align=PP_ALIGN.LEFT):
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(sz)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = "Calibri"
    p.space_before = before
    p.alignment = align
    return p

def arrow_r(slide, l, t, w=Inches(0.35), h=Inches(0.3), color=SILVER):
    sh = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, l, t, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()

def arrow_d(slide, l, t, w=Inches(0.3), h=Inches(0.3), color=SILVER):
    sh = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, l, t, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()

def header_bar(slide, title, accent_color=BLUE):
    rect(slide, Inches(0), Inches(0), W, Inches(1.05), DARK_CARD)
    rect(slide, Inches(0.6), Inches(0.2), Inches(0.12), Inches(0.65), accent_color)
    txt(slide, Inches(0.9), Inches(0.15), Inches(11), Inches(0.8), title, sz=26, bold=True)

def footer(slide, text, page=""):
    txt(slide, Inches(0.5), Inches(7.05), Inches(8), Inches(0.35), text, sz=9, color=MUTED)
    if page:
        txt(slide, Inches(11.5), Inches(7.05), Inches(1.5), Inches(0.35), page, sz=9, color=MUTED, align=PP_ALIGN.RIGHT)

def bullet_slide(prs, title, bullets, accent=BLUE, foot="", pg=""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, title, accent)
    y = Inches(1.4)
    for b in bullets:
        tf = txt(s, Inches(1.2), y, Inches(11), Inches(0.48), f"▸   {b}", sz=16, color=LIGHT)
        y += Inches(0.58)
    if foot:
        footer(s, foot, pg)
    return s


# ═══════════════════════════════════════════════════════════════
#  PRESENTATION 1 — Architecture Générale
# ═══════════════════════════════════════════════════════════════

def build_pres1():
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H

    # ── 1. TITLE ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    # Decorative line
    rect(s, Inches(2), Inches(2.2), Inches(9.3), Inches(0.04), BLUE)
    txt(s, Inches(2), Inches(2.5), Inches(9.3), Inches(1.2),
        "Plateforme de Backtesting\nQuantitatif", sz=38, bold=True, align=PP_ALIGN.LEFT)
    txt(s, Inches(2), Inches(4.0), Inches(9.3), Inches(0.8),
        "Architecture modulaire inspirée des trading desks quantitatifs", sz=18, color=BLUE)
    rect(s, Inches(2), Inches(5.2), Inches(9.3), Inches(0.04), DARK_CARD)
    txt(s, Inches(2), Inches(5.5), Inches(9.3), Inches(0.4),
        "Stage — Banque d'Investissement  •  Casablanca", sz=13, color=SILVER)
    footer(s, "", "")

    # ── 2. CONTEXTE ──
    s = bullet_slide(prs, "Contexte & Objectif", [
        "Les approches traditionnelles de backtesting mélangent tout dans un seul pipeline",
        "Résultat : on confond chance et performance réelle (overfitting)",
        "Les grandes firmes quantitatives (Two Sigma, AQR, Man Group) structurent leur recherche en étapes indépendantes",
        "Marcos López de Prado formalise cette approche dans « Advances in Financial Machine Learning » (2018)",
        "Objectif : construire une plateforme qui respecte cette discipline, adaptée au marché marocain",
    ], foot="Ref: de Prado, AFML Ch. 1 — « Structure research as a production chain »", pg="2")

    # ── 3. DE PRADO PRODUCTION CHAIN ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Comment un Desk Quantitatif Fonctionne")
    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.5),
        "De Prado décrit 5 méta-étapes dans la production d'une stratégie (AFML, Ch. 1) :", sz=15, color=SILVER)

    steps = [
        ("Data\nCuration", "Données propres,\nvérifiées, sans biais", BLUE),
        ("Feature\nAnalysis", "Signaux évalués\net validés OOS", GREEN),
        ("Strategy\nDesign", "Règles d'entrée,\nsortie, sizing", AMBER),
        ("Back-\ntesting", "Validation\nwalk-forward", PURPLE),
        ("Deploy-\nment", "Exécution live\net monitoring", CORAL),
    ]
    x = Inches(0.5)
    for i, (name, desc, clr) in enumerate(steps):
        rect(s, x, Inches(2.0), Inches(2.15), Inches(1.3), clr, name, sz=17, bold=True)
        txt(s, x + Inches(0.1), Inches(3.45), Inches(2.0), Inches(0.9), desc, sz=12, color=SILVER, align=PP_ALIGN.CENTER)
        if i < 4:
            arrow_r(s, x + Inches(2.2), Inches(2.5))
        x += Inches(2.55)

    tf = txt(s, Inches(1.0), Inches(5.0), Inches(11), Inches(1.2),
        "« Chaque étape est un module indépendant. Un data scientist ne touche pas au code d'exécution.\n"
        "Un portfolio manager ne modifie pas le pipeline de données. »", sz=14, color=MUTED)
    para(tf, "Principe clé : le livrable de chaque étape est validé avant de passer à la suivante.", sz=14, color=LIGHT, bold=True, before=Pt(12))
    footer(s, "Ref: de Prado, Advances in Financial Machine Learning, Ch. 1, Fig. 1.1", "3")

    # ── 4. NOTRE IMPLEMENTATION ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Notre Implémentation : 4 Pages")

    pages = [
        ("DATA", "Curation", "Importer, valider et surveiller\nles données OHLCV", BLUE, "Opérationnel"),
        ("SIGNAL", "Analyse", "Évaluer et filtrer les signaux\ntechniques via OOS", GREEN, "Opérationnel"),
        ("STRATEGY", "Construction", "Construire des règles de\ntrading paramétrées", AMBER, "En cours"),
        ("BACKTEST", "Validation", "Valider la stratégie complète\nen walk-forward", PURPLE, "En cours"),
    ]
    x = Inches(0.5)
    for i, (name, role, desc, clr, status) in enumerate(pages):
        # Card
        rect(s, x, Inches(1.5), Inches(2.9), Inches(4.0), DARK_CARD)
        # Colored header inside card
        rect(s, x + Inches(0.15), Inches(1.7), Inches(2.6), Inches(0.9), clr, name, sz=22, bold=True)
        txt(s, x + Inches(0.15), Inches(2.7), Inches(2.6), Inches(0.4), role, sz=13, color=clr, bold=True, align=PP_ALIGN.CENTER)
        txt(s, x + Inches(0.2), Inches(3.2), Inches(2.5), Inches(1.2), desc, sz=13, color=LIGHT, align=PP_ALIGN.CENTER)
        # Status
        st_color = GREEN if status == "Opérationnel" else AMBER
        rect(s, x + Inches(0.5), Inches(4.7), Inches(1.9), Inches(0.45), st_color, status, sz=11, bold=True)
        if i < 3:
            arrow_r(s, x + Inches(3.0), Inches(3.2), Inches(0.25), Inches(0.25))
        x += Inches(3.15)

    txt(s, Inches(0.9), Inches(5.8), Inches(11), Inches(0.7),
        "Chaque page produit un livrable validé. Un signal n'est jamais utilisé sans preuve.\n"
        "Une stratégie n'est jamais backtestée sans signaux validés en amont.", sz=14, color=SILVER)
    footer(s, "", "4")

    # ── 5. POURQUOI CETTE SEPARATION ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Pourquoi Séparer en 4 Étapes ?")

    reasons = [
        ("Éviter l'Overfitting", "Si les signaux sont validés AVANT la stratégie, on ne peut pas ajuster\nles paramètres pour flatter le backtest. C'est le piège n°1 en finance quantitative.", BLUE),
        ("Réutilisabilité", "Un signal validé (ex: SMA robuste sur ATW) peut alimenter plusieurs\nstratégies différentes sans être recalculé.", GREEN),
        ("Traçabilité", "Si un backtest échoue, on peut identifier précisément la cause :\ndonnées manquantes ? Signal faible ? Mauvaise stratégie ?", AMBER),
        ("Collaboration", "Data Engineer → Page Data  |  Quant → Page Signal\nPortfolio Manager → Strategy + Backtest. Chacun son périmètre.", PURPLE),
    ]
    y = Inches(1.3)
    for title, desc, clr in reasons:
        rect(s, Inches(0.8), y, Inches(0.12), Inches(1.05), clr)
        txt(s, Inches(1.15), y + Inches(0.02), Inches(4.0), Inches(0.4), title, sz=17, bold=True, color=clr)
        txt(s, Inches(1.15), y + Inches(0.4), Inches(11), Inches(0.65), desc, sz=13, color=LIGHT)
        y += Inches(1.3)

    footer(s, "Ref: de Prado, AFML Ch. 1, 11-12 — Backtesting pitfalls & overfitting", "5")

    # ── 6. PAGE DATA ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Page Data — Les Données comme Fondation", BLUE)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Les données sont un actif de première classe — pas un fichier CSV qu'on charge et qu'on oublie.", sz=15, color=SILVER)

    features = [
        ("Import Intelligent", "3 formats Excel supportés (Bourse de Casablanca ancien/nouveau, Investing.com).\n"
         "Détection automatique du format. Parsing des dates ambiguës via programmation dynamique.", BLUE),
        ("Qualité & Observabilité", "Calendrier jour par jour : chaque cellule montre si la donnée existe, manque,\n"
         "ou correspond à un jour férié marocain. Les gaps sont immédiatement visibles.", GREEN),
        ("Mise à Jour Automatique", "Refresh quotidien à 18h (après clôture de la Bourse de Casablanca).\n"
         "Merge delta : seules les valeurs qui diffèrent sont mises à jour. L'historique n'est jamais supprimé.", AMBER),
        ("Métadonnées", "Chaque symbole a un nom, un ISIN, un secteur, un lien vers la fiche officielle.\n"
         "Auto-remplissage depuis le site de la Bourse de Casablanca.", PURPLE),
    ]
    y = Inches(1.8)
    for title, desc, clr in features:
        rect(s, Inches(0.9), y, Inches(2.8), Inches(1.1), DARK_CARD, title, sz=14, bold=True, fc=clr)
        txt(s, Inches(4.0), y + Inches(0.1), Inches(8.5), Inches(0.9), desc, sz=12, color=LIGHT)
        y += Inches(1.25)

    footer(s, "de Prado, AFML Ch. 2-3 : « Data curation is the most underappreciated step »", "6")

    # ── 7. PAGE SIGNAL (aperçu) ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Page Signal — Évaluation Rigoureuse des Indicateurs", GREEN)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Chaque indicateur technique est évalué en walk-forward OOS avant d'être utilisé.", sz=15, color=SILVER)

    # Pipeline visual
    pipeline = [
        ("120\nCandidats", "4 familles × 30\nvariantes chacune", BLUE),
        ("~50\nViables", "Passent le test\nde viabilité OOS", GREEN),
        ("~30\nCompétitifs", "Top performers\npar fiabilité", AMBER),
        ("~12\nReprésentatifs", "Diversifiés,\nnon redondants", PURPLE),
        ("1 Score\n[-100, +100]", "Ensemble pondéré\npar fiabilité", CORAL),
    ]
    x = Inches(0.4)
    for i, (count, desc, clr) in enumerate(pipeline):
        rect(s, x, Inches(2.0), Inches(2.2), Inches(1.0), clr, count, sz=16, bold=True)
        txt(s, x, Inches(3.1), Inches(2.2), Inches(0.8), desc, sz=11, color=SILVER, align=PP_ALIGN.CENTER)
        if i < 4:
            arrow_r(s, x + Inches(2.25), Inches(2.3), Inches(0.25), Inches(0.25))
        x += Inches(2.55)

    tf = txt(s, Inches(0.9), Inches(4.3), Inches(11), Inches(2.0),
        "Familles d'indicateurs : SMA (tendance) • RSI (mean-reversion) • MACD (momentum) • OBV (volume)", sz=14, color=LIGHT)
    para(tf, "Pipeline en 7 couches (A→G) avec walk-forward strict, scoring multi-critères,", sz=14, color=LIGHT)
    para(tf, "filtrage par percentile et réduction de redondance par corrélation.", sz=14, color=LIGHT)
    para(tf, "", sz=8, color=MUTED)
    para(tf, "Détail complet dans la Présentation 2 — Moteur de Signaux.", sz=14, color=BLUE, bold=True)

    footer(s, "Ref: Pardo (2008), Walk-Forward Analysis  |  de Prado, AFML Ch. 6-8", "7")

    # ── 8. PAGES A VENIR ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Prochaines Étapes : Strategy & Backtest")

    # Strategy card
    rect(s, Inches(0.7), Inches(1.5), Inches(5.7), Inches(4.5), DARK_CARD)
    rect(s, Inches(0.7), Inches(1.5), Inches(5.7), Inches(0.8), AMBER, "PAGE STRATEGY", sz=20, bold=True)
    items_s = [
        "Combiner les scores de plusieurs familles de signaux",
        "Définir des seuils d'entrée/sortie paramétrés",
        "Ajouter des contraintes de risque (drawdown max, position sizing)",
        "Optimiser les paramètres en walk-forward",
        "Chaque stratégie est construite à partir de signaux déjà validés",
    ]
    y = Inches(2.6)
    for item in items_s:
        txt(s, Inches(1.0), y, Inches(5.0), Inches(0.4), f"▸  {item}", sz=13, color=LIGHT)
        y += Inches(0.45)

    # Backtest card
    rect(s, Inches(6.9), Inches(1.5), Inches(5.7), Inches(4.5), DARK_CARD)
    rect(s, Inches(6.9), Inches(1.5), Inches(5.7), Inches(0.8), PURPLE, "PAGE BACKTEST", sz=20, bold=True)
    items_b = [
        "Walk-Forward Optimization complète sur la stratégie",
        "Métriques OOS : Sharpe, CAGR, Max Drawdown, Win Rate",
        "Equity curve, drawdown chart, trade ledger détaillé",
        "Deflated Sharpe Ratio pour corriger le biais de sélection",
        "Leaderboard multi-horizon pour comparer les stratégies",
    ]
    y = Inches(2.6)
    for item in items_b:
        txt(s, Inches(7.2), y, Inches(5.0), Inches(0.4), f"▸  {item}", sz=13, color=LIGHT)
        y += Inches(0.45)

    txt(s, Inches(0.9), Inches(6.3), Inches(11), Inches(0.5),
        "Principe : chaque étape en aval consomme uniquement des livrables validés par l'étape en amont.", sz=14, color=SILVER)
    footer(s, "", "8")

    # ── 9. STACK TECHNIQUE ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Stack Technique")

    layers = [
        ("Frontend", "Next.js 14  •  React  •  TypeScript  •  Tailwind CSS  •  Plotly.js", BLUE),
        ("API", "FastAPI  •  Pydantic  •  REST  •  Cache en mémoire avec TTL", GREEN),
        ("Core Quantitatif", "Python  •  Signal Engine  •  Optimizer  •  Numba JIT (38× speedup)", AMBER),
        ("Infrastructure", "PostgreSQL 16  •  Redis (queues)  •  MinIO (stockage S3)  •  Docker", PURPLE),
    ]
    y = Inches(1.5)
    for name, desc, clr in layers:
        rect(s, Inches(0.8), y, Inches(3.0), Inches(1.0), clr, name, sz=17, bold=True)
        txt(s, Inches(4.1), y + Inches(0.25), Inches(8.5), Inches(0.5), desc, sz=15, color=LIGHT)
        y += Inches(1.2)

    txt(s, Inches(0.9), Inches(6.5), Inches(11), Inches(0.4),
        "Tout s'exécute localement via Docker Compose — aucune dépendance cloud externe.", sz=13, color=MUTED)
    footer(s, "", "9")

    # ── 10. VALEUR AJOUTÉE ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Valeur Ajoutée")

    values = [
        ("Discipline Institutionnelle", "La même rigueur que les fonds quantitatifs de référence (Two Sigma, AQR),\nappliquée au contexte du marché marocain.", BLUE),
        ("Adapté au Marché Local", "Formats Bourse de Casablanca, jours fériés marocains, symboles locaux,\nrefresh automatique des cours après clôture.", GREEN),
        ("Transparence Totale", "Chaque décision est traçable : pourquoi ce signal ? Pourquoi cette variante\na été éliminée ? Quelle est sa performance OOS fenêtre par fenêtre ?", AMBER),
        ("Évolutif", "Ajouter une nouvelle famille d'indicateurs = 2 fonctions Python.\nAucune modification du pipeline, de l'API ou du frontend nécessaire.", PURPLE),
    ]
    y = Inches(1.3)
    for title, desc, clr in values:
        rect(s, Inches(0.8), y, Inches(0.12), Inches(1.15), clr)
        txt(s, Inches(1.15), y + Inches(0.02), Inches(5.0), Inches(0.35), title, sz=17, bold=True, color=clr)
        txt(s, Inches(1.15), y + Inches(0.4), Inches(11), Inches(0.7), desc, sz=13, color=LIGHT)
        y += Inches(1.35)

    footer(s, "", "10")

    # ── 11. REFERENCES ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Références")

    refs = [
        ("de Prado, M.L. (2018)", "Advances in Financial Machine Learning — Wiley", "Pipeline modulaire, feature importance, overfitting"),
        ("Pardo, R. (2008)", "The Evaluation and Optimization of Trading Strategies — Wiley", "Walk-Forward Analysis, validation OOS"),
        ("Bailey & de Prado (2014)", "The Deflated Sharpe Ratio — Journal of Portfolio Management", "Correction du biais de sélection multiple"),
        ("Grinold & Kahn (2000)", "Active Portfolio Management — McGraw-Hill", "Scoring multi-facteurs, information ratio"),
        ("de Prado, M.L. (2020)", "Machine Learning for Asset Managers — Cambridge University Press", "Feature importance, qualité de signal"),
    ]
    y = Inches(1.4)
    for author, title, usage in refs:
        txt(s, Inches(0.9), y, Inches(5.0), Inches(0.35), author, sz=14, bold=True, color=BLUE)
        txt(s, Inches(0.9), y + Inches(0.35), Inches(5.0), Inches(0.35), title, sz=12, color=LIGHT)
        txt(s, Inches(6.5), y + Inches(0.1), Inches(6.0), Inches(0.5), f"→  {usage}", sz=13, color=SILVER)
        y += Inches(0.95)

    footer(s, "", "11")

    # ── 12. CLOSING ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    rect(s, Inches(2), Inches(2.5), Inches(9.3), Inches(0.04), BLUE)
    txt(s, Inches(2), Inches(2.8), Inches(9.3), Inches(0.8),
        "Merci", sz=40, bold=True, align=PP_ALIGN.LEFT)
    txt(s, Inches(2), Inches(3.7), Inches(9.3), Inches(0.5),
        "Questions & Discussion", sz=20, color=BLUE)
    rect(s, Inches(2), Inches(4.6), Inches(9.3), Inches(0.04), DARK_CARD)
    tf = txt(s, Inches(2), Inches(5.0), Inches(9.3), Inches(1.5),
        "« The key to avoiding false discoveries is to structure your", sz=14, color=MUTED)
    para(tf, "research process as a production chain. »", sz=14, color=MUTED)
    para(tf, "— Marcos López de Prado, Advances in Financial Machine Learning", sz=12, color=BLUE, bold=True, before=Pt(8))

    return prs


# ═══════════════════════════════════════════════════════════════
#  PRESENTATION 2 — Moteur de Signaux
# ═══════════════════════════════════════════════════════════════

def build_pres2():
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H

    # ── 1. TITLE ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    rect(s, Inches(2), Inches(2.2), Inches(9.3), Inches(0.04), GREEN)
    txt(s, Inches(2), Inches(2.5), Inches(9.3), Inches(1.2),
        "Le Moteur de Signaux", sz=38, bold=True)
    txt(s, Inches(2), Inches(3.6), Inches(9.3), Inches(0.8),
        "De 120 variantes testées à un signal unique — sans overfitting", sz=18, color=GREEN)
    rect(s, Inches(2), Inches(4.8), Inches(9.3), Inches(0.04), DARK_CARD)
    txt(s, Inches(2), Inches(5.1), Inches(9.3), Inches(0.4),
        "Pipeline de filtrage OOS en 7 couches (A → G)", sz=14, color=SILVER)

    # ── 2. LE PROBLÈME ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Pourquoi Ne Pas Prendre « Le Meilleur » Indicateur ?", CORAL)

    tf = txt(s, Inches(0.9), Inches(1.3), Inches(11), Inches(3.5),
        "Le piège du cherry-picking", sz=20, bold=True, color=CORAL)
    para(tf, "", sz=6)
    para(tf, "Si on teste 100 variantes d'indicateurs et qu'on choisit la meilleure,", sz=16, color=LIGHT)
    para(tf, "on a de très fortes chances de sélectionner du bruit, pas du signal.", sz=16, color=LIGHT)
    para(tf, "", sz=10)
    para(tf, "Bailey & de Prado (2014) montrent que le Sharpe Ratio apparent", sz=16, color=LIGHT)
    para(tf, "est gonflé proportionnellement à  √(2 × ln(N))  quand on teste N stratégies.", sz=16, color=LIGHT)
    para(tf, "", sz=10)
    para(tf, "Exemple : un SMA-47 peut surperformer un SMA-50 purement par hasard", sz=16, color=LIGHT)
    para(tf, "sur une période donnée. Le choisir serait de l'overfitting.", sz=16, color=LIGHT)
    para(tf, "", sz=14)
    para(tf, "La solution : ne pas choisir « le meilleur ».", sz=18, bold=True, color=GREEN)
    para(tf, "Éliminer les mauvais, puis combiner les survivants.", sz=18, bold=True, color=GREEN)

    footer(s, "Ref: Bailey & de Prado (2014), The Deflated Sharpe Ratio, J. Portfolio Management", "2")

    # ── 3. VUE D'ENSEMBLE PIPELINE ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Pipeline en 7 Couches", GREEN)

    layers = [
        ("A", "Univers des\nCandidats", "30 variantes\npar famille", BLUE),
        ("B", "Évaluation\nWalk-Forward", "Sharpe, PnL, DD\npar fenêtre OOS", BLUE),
        ("C", "Score de\nRobustesse", "4 critères →\nscore [0, 1]", GREEN),
        ("D", "Filtrage\nSurvivants", "Viable →\nCompétitif", AMBER),
        ("E", "Réduction\nRedondance", "Corrélation\nPearson < 0.85", AMBER),
        ("F", "Signal\nCourant", "BUY / SELL /\nHOLD par variante", PURPLE),
        ("G", "Ensemble\nPondéré", "Score final\n[-100, +100]", CORAL),
    ]
    x = Inches(0.25)
    for letter, name, desc, clr in layers:
        rect(s, x, Inches(1.5), Inches(1.7), Inches(0.5), clr, f"Couche {letter}", sz=13, bold=True)
        rect(s, x, Inches(2.1), Inches(1.7), Inches(1.2), DARK_CARD, name, sz=13, bold=True)
        txt(s, x + Inches(0.05), Inches(3.4), Inches(1.6), Inches(0.8), desc, sz=10, color=SILVER, align=PP_ALIGN.CENTER)
        if letter != "G":
            arrow_r(s, x + Inches(1.73), Inches(2.5), Inches(0.15), Inches(0.2))
        x += Inches(1.85)

    tf = txt(s, Inches(0.9), Inches(4.5), Inches(11), Inches(2.0),
        "4 familles d'indicateurs, chacune avec 30 variantes = 120 candidats évalués", sz=15, color=LIGHT)
    para(tf, "", sz=6)
    para(tf, "SMA — Tendance (prix vs moyenne mobile)", sz=14, color=BLUE)
    para(tf, "RSI — Mean-reversion (surachat / survente)", sz=14, color=GREEN)
    para(tf, "MACD — Momentum (croisement de lignes)", sz=14, color=AMBER)
    para(tf, "OBV — Volume (confirmation par les volumes)", sz=14, color=PURPLE)

    footer(s, "", "3")

    # ── 4. COUCHE A ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Couche A — Univers des Candidats", BLUE)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Explorer systématiquement l'espace des paramètres — pas de choix subjectif.", sz=15, color=SILVER)

    # Table header
    rect(s, Inches(0.8), Inches(1.9), Inches(2.5), Inches(0.5), BLUE, "Famille", sz=13, bold=True)
    rect(s, Inches(3.3), Inches(1.9), Inches(3.0), Inches(0.5), BLUE, "Logique du Signal", sz=13, bold=True)
    rect(s, Inches(6.3), Inches(1.9), Inches(3.5), Inches(0.5), BLUE, "Paramètres explorés", sz=13, bold=True)
    rect(s, Inches(9.8), Inches(1.9), Inches(2.7), Inches(0.5), BLUE, "Variantes", sz=13, bold=True)

    rows = [
        ("SMA", "Achat si prix > moyenne mobile", "Fenêtres : 3 à 400 jours", "30"),
        ("RSI", "Achat si RSI < seuil de survente", "Périodes × seuils (30/70, 25/75...)", "30"),
        ("MACD", "Achat si ligne MACD > signal", "Fast × slow × signal", "30"),
        ("OBV", "Achat si volume > sa tendance", "Périodes EMA : 3 à 400 jours", "30"),
    ]
    y = Inches(2.5)
    for fam, logic, params, n in rows:
        rect(s, Inches(0.8), y, Inches(2.5), Inches(0.55), DARK_CARD, fam, sz=14, bold=True, fc=LIGHT)
        txt(s, Inches(3.4), y + Inches(0.1), Inches(2.9), Inches(0.4), logic, sz=12, color=LIGHT, align=PP_ALIGN.CENTER)
        txt(s, Inches(6.4), y + Inches(0.1), Inches(3.4), Inches(0.4), params, sz=12, color=LIGHT, align=PP_ALIGN.CENTER)
        rect(s, Inches(9.8), y, Inches(2.7), Inches(0.55), DARK_CARD, n, sz=14, bold=True, fc=GREEN)
        y += Inches(0.65)

    tf = txt(s, Inches(0.9), Inches(5.2), Inches(11), Inches(1.5),
        "Les paramètres sont adaptés à l'horizon d'investissement :", sz=14, color=LIGHT)
    para(tf, "Court terme — fenêtres courtes (3-90 jours), données sur 5 ans", sz=13, color=SILVER)
    para(tf, "Moyen terme — fenêtres moyennes (10-250 jours), données sur 10 ans", sz=13, color=SILVER)
    para(tf, "Long terme — fenêtres longues (20-400 jours), données sur 20 ans", sz=13, color=SILVER)

    footer(s, "Chaque variante a un identifiant unique déterministe (SHA-256) pour la reproductibilité", "4")

    # ── 5. COUCHE B — Walk-Forward ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Couche B — Évaluation Walk-Forward OOS", BLUE)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Le cœur de la rigueur : aucun regard vers le futur.", sz=15, color=SILVER)

    # Visual: rolling windows
    colors_w = [BLUE, GREEN, AMBER, PURPLE, CORAL]
    for i in range(5):
        # Train block
        train_left = Inches(1.5 + i * 1.2)
        rect(s, train_left, Inches(2.0 + i * 0.65), Inches(3.5), Inches(0.45),
             colors_w[i], f"TRAIN {i+1}", sz=11, bold=True)
        # Test block
        rect(s, train_left + Inches(3.6), Inches(2.0 + i * 0.65), Inches(1.5), Inches(0.45),
             DARK_CARD, f"TEST {i+1}", sz=11, bold=True, fc=colors_w[i])

    txt(s, Inches(8.0), Inches(2.0), Inches(4.8), Inches(0.4),
        "Protocole strict :", sz=15, bold=True, color=GREEN)
    rules = [
        "Signal calculé une seule fois sur\ntout l'historique",
        "Évaluation uniquement sur la\npériode TEST (out-of-sample)",
        "Rendement = bar suivant\n(pas de look-ahead)",
        "Coûts de transaction inclus\ndans chaque évaluation",
        "Minimum 3 fenêtres valides\n(≥ 20 bars chacune)",
    ]
    y = Inches(2.6)
    for rule in rules:
        txt(s, Inches(8.0), y, Inches(4.8), Inches(0.55), f"▸  {rule}", sz=11, color=LIGHT)
        y += Inches(0.6)

    footer(s, "Ref: Pardo (2008), The Evaluation and Optimization of Trading Strategies, Ch. 7-9", "5")

    # ── 6. COUCHE C — Scoring ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Couche C — Score de Robustesse", GREEN)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Agréger les résultats de toutes les fenêtres OOS en un score unique de fiabilité [0 → 1].", sz=15, color=SILVER)

    components = [
        ("Sharpe Score", "35%", "Performance ajustée au risque", "La performance est le critère\nprincipal (de Prado, Ch. 14)", BLUE),
        ("Stabilité", "30%", "% de fenêtres avec Sharpe > 0", "Un signal qui échoue en crise\nest dangereux", GREEN),
        ("Consistance", "20%", "Faible variance entre fenêtres", "Sharpe [0.8, 1.0, 1.2] est mieux\nque [-1, 1, 3]", AMBER),
        ("Drawdown", "15%", "Protection du capital", "Un drawdown > 30% est\nconsidéré inacceptable", PURPLE),
    ]
    y = Inches(1.8)
    for name, weight, what, why, clr in components:
        # Weight circle
        rect(s, Inches(0.8), y, Inches(1.0), Inches(1.1), clr, weight, sz=20, bold=True)
        # Name
        txt(s, Inches(2.0), y + Inches(0.05), Inches(2.5), Inches(0.35), name, sz=16, bold=True, color=clr)
        # What it measures
        txt(s, Inches(2.0), y + Inches(0.4), Inches(3.5), Inches(0.5), what, sz=13, color=LIGHT)
        # Why this weight
        txt(s, Inches(6.5), y + Inches(0.1), Inches(6.0), Inches(0.8), why, sz=12, color=SILVER)
        y += Inches(1.25)

    rect(s, Inches(0.8), Inches(6.8), Inches(11.7), Inches(0.04), GREEN)
    txt(s, Inches(0.9), Inches(6.45), Inches(11), Inches(0.4),
        "Score final = 0.35 × Sharpe + 0.30 × Stabilité + 0.20 × Consistance + 0.15 × Drawdown",
        sz=14, bold=True, color=GREEN)

    footer(s, "Inspiré du multi-factor scoring de Grinold & Kahn (2000), Active Portfolio Management", "6")

    # ── 7. COUCHE D — Filtrage ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Couche D — De « Testé » à « Compétitif »", AMBER)

    # Funnel visual
    funnel_steps = [
        ("TESTÉES", "30", "Toutes les variantes\ngénérées", MUTED, Inches(0.5), Inches(11.5)),
        ("VIABLES", "~18", "≥ 3 fenêtres valides ET\n≥ 40% de fenêtres à Sharpe positif", BLUE, Inches(1.5), Inches(9.5)),
        ("COMPÉTITIFS", "~11", "Score de fiabilité ≥ 0.25 ET\ntop 60% par score de fiabilité", GREEN, Inches(2.5), Inches(7.5)),
    ]
    for name, count, criteria, clr, x_offset, width in funnel_steps:
        y = Inches(1.5) + (x_offset - Inches(0.5)) * 1.7
        rect(s, x_offset, y, width, Inches(1.1), DARK_CARD)
        rect(s, x_offset, y, Inches(2.5), Inches(1.1), clr, f"{name}\n({count})", sz=14, bold=True)
        txt(s, x_offset + Inches(2.7), y + Inches(0.15), Inches(6.5), Inches(0.8), criteria, sz=13, color=LIGHT)

    tf = txt(s, Inches(0.9), Inches(5.2), Inches(11), Inches(2.0),
        "Pourquoi un filtre à deux étages ?", sz=16, bold=True, color=AMBER)
    para(tf, "", sz=6)
    para(tf, "▸  Le plancher absolu (0.25) empêche de garder des variantes médiocres dans une famille faible", sz=14, color=LIGHT)
    para(tf, "▸  Le percentile relatif (top 60%) garde de la diversité au lieu de ne choisir que « le meilleur »", sz=14, color=LIGHT)
    para(tf, "▸  Ensemble, ils évitent à la fois le laxisme et la sur-sélection", sz=14, color=LIGHT)

    footer(s, "", "7")

    # ── 8. COUCHE E — Redondance ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Couche E — Réduction de Redondance", AMBER)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Problème : SMA-48, SMA-50 et SMA-52 sont quasi-identiques. Les garder biaiserait l'ensemble.", sz=15, color=SILVER)

    # Example
    examples = [
        ("SMA-50", "0.78", "SÉLECTIONNÉ", "(premier — meilleur score)", GREEN),
        ("SMA-48", "0.75", "ÉLIMINÉ", "corrélé à SMA-50 (r = 0.97)", CORAL),
        ("SMA-100", "0.71", "SÉLECTIONNÉ", "corrélation faible avec SMA-50 (r = 0.45)", GREEN),
        ("SMA-52", "0.69", "ÉLIMINÉ", "corrélé à SMA-50 (r = 0.95)", CORAL),
        ("SMA-20", "0.65", "SÉLECTIONNÉ", "indépendant de tous les sélectionnés", GREEN),
    ]
    y = Inches(1.9)
    for name, score, status, reason, clr in examples:
        rect(s, Inches(0.8), y, Inches(1.5), Inches(0.5), DARK_CARD, name, sz=14, bold=True, fc=LIGHT)
        rect(s, Inches(2.4), y, Inches(1.0), Inches(0.5), DARK_CARD, score, sz=14, fc=SILVER)
        rect(s, Inches(3.5), y, Inches(2.2), Inches(0.5), clr, status, sz=12, bold=True)
        txt(s, Inches(5.9), y + Inches(0.08), Inches(6.5), Inches(0.35), reason, sz=13, color=SILVER)
        y += Inches(0.6)

    tf = txt(s, Inches(0.9), Inches(5.1), Inches(11), Inches(2.0),
        "Algorithme glouton :", sz=16, bold=True, color=AMBER)
    para(tf, "1. Trier par score de fiabilité décroissant", sz=14, color=LIGHT)
    para(tf, "2. Pour chaque variante : si |corrélation Pearson| < 0.85 avec TOUS les déjà sélectionnés → garder", sz=14, color=LIGHT)
    para(tf, "3. Sinon → éliminer (en traçant la raison)", sz=14, color=LIGHT)
    para(tf, "4. Maximum 10 représentants", sz=14, color=LIGHT)

    footer(s, "Ref: de Prado, AFML Ch. 8 — « Correlated features should be clustered to avoid double-counting »", "8")

    # ── 9. COUCHE F+G — Signal & Ensemble ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Couches F & G — Signal Courant et Ensemble Pondéré", PURPLE)

    txt(s, Inches(0.9), Inches(1.2), Inches(11), Inches(0.4),
        "Chaque représentant vote, pondéré par sa fiabilité historique.", sz=15, color=SILVER)

    # Voting example
    rect(s, Inches(0.8), Inches(1.9), Inches(2.2), Inches(0.45), DARK_CARD, "Représentant", sz=12, bold=True, fc=SILVER)
    rect(s, Inches(3.1), Inches(1.9), Inches(1.2), Inches(0.45), DARK_CARD, "Signal", sz=12, bold=True, fc=SILVER)
    rect(s, Inches(4.4), Inches(1.9), Inches(1.2), Inches(0.45), DARK_CARD, "Poids", sz=12, bold=True, fc=SILVER)
    rect(s, Inches(5.7), Inches(1.9), Inches(2.0), Inches(0.45), DARK_CARD, "Contribution", sz=12, bold=True, fc=SILVER)

    votes = [
        ("SMA-50", "BUY (+1)", "0.78", "+1.0 × 0.78 = +0.78", GREEN),
        ("SMA-100", "BUY (+1)", "0.71", "+1.0 × 0.71 = +0.71", GREEN),
        ("SMA-20", "SELL (-1)", "0.65", "-1.0 × 0.65 = -0.65", CORAL),
    ]
    y = Inches(2.45)
    for name, sig, weight, contrib, clr in votes:
        rect(s, Inches(0.8), y, Inches(2.2), Inches(0.45), DARK_CARD, name, sz=13, fc=LIGHT)
        rect(s, Inches(3.1), y, Inches(1.2), Inches(0.45), clr, sig, sz=12, bold=True)
        txt(s, Inches(4.5), y + Inches(0.07), Inches(1.0), Inches(0.3), weight, sz=13, color=LIGHT, align=PP_ALIGN.CENTER)
        txt(s, Inches(5.8), y + Inches(0.07), Inches(1.8), Inches(0.3), contrib, sz=12, color=SILVER, align=PP_ALIGN.CENTER)
        y += Inches(0.5)

    # Result
    rect(s, Inches(0.8), y + Inches(0.15), Inches(6.9), Inches(0.6), GREEN,
         "Score = (+0.78 + 0.71 - 0.65) / 2.14 = +39.3%  →  ACHAT", sz=15, bold=True)

    # Scale
    txt(s, Inches(8.5), Inches(1.9), Inches(4.0), Inches(0.4),
        "Échelle de décision :", sz=15, bold=True, color=PURPLE)

    thresholds = [
        ("< -50", "VENTE FORTE", CORAL),
        ("-50 à -15", "VENTE", RGBColor(0xE0, 0x9D, 0x5D)),
        ("-15 à +15", "NEUTRE", SILVER),
        ("+15 à +50", "ACHAT", RGBColor(0x5D, 0xBE, 0x8A)),
        ("> +50", "ACHAT FORT", GREEN),
    ]
    y = Inches(2.5)
    for threshold, label, clr in thresholds:
        rect(s, Inches(8.5), y, Inches(1.5), Inches(0.4), DARK_CARD, threshold, sz=11, fc=SILVER)
        rect(s, Inches(10.1), y, Inches(2.2), Inches(0.4), clr, label, sz=12, bold=True)
        y += Inches(0.48)

    tf = txt(s, Inches(0.9), Inches(5.2), Inches(11), Inches(1.5),
        "Pourquoi la pondération par fiabilité ?", sz=16, bold=True, color=PURPLE)
    para(tf, "▸  L'equal-weighting donnerait trop de pouvoir aux variantes marginales", sz=14, color=LIGHT)
    para(tf, "▸  Les variantes les plus robustes historiquement ont plus d'influence sur la décision", sz=14, color=LIGHT)
    para(tf, "▸  Même principe que le boosting en machine learning (Breiman, 1996)", sz=14, color=LIGHT)

    footer(s, "", "9")

    # ── 10. ENTONNOIR COMPLET ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "L'Entonnoir Complet — Exemple SMA, Moyen Terme")

    stages = [
        ("TESTÉES", "30", "Toutes les variantes SMA\n(fenêtres de 10 à 250 jours)", MUTED),
        ("VIABLES", "18", "-12 éliminées\n(Sharpe négatif > 60% du temps)", BLUE),
        ("COMPÉTITIFS", "11", "-7 éliminées\n(score < 0.25 ou hors top 60%)", GREEN),
        ("REPRÉSENTATIFS", "5", "-6 éliminées\n(corrélation > 0.85 avec un meilleur)", PURPLE),
        ("SCORE FINAL", "+42.7%", "→ ACHAT\n(3 BUY + 2 HOLD pondérés)", CORAL),
    ]
    y = Inches(1.4)
    for name, count, desc, clr in stages:
        rect(s, Inches(1.0), y, Inches(2.8), Inches(0.85), clr, name, sz=14, bold=True)
        rect(s, Inches(4.0), y, Inches(1.2), Inches(0.85), DARK_CARD, count, sz=22, bold=True, fc=clr)
        txt(s, Inches(5.5), y + Inches(0.08), Inches(7.0), Inches(0.7), desc, sz=13, color=LIGHT)
        if name != "SCORE FINAL":
            arrow_d(s, Inches(2.3), y + Inches(0.9), Inches(0.25), Inches(0.2))
        y += Inches(1.1)

    footer(s, "Les chiffres varient selon le symbole et l'horizon — ceci est un exemple représentatif", "10")

    # ── 11. HONNETETÉ ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Honnêteté Méthodologique")

    items = [
        ("Pas de cherry-picking", "On ne choisit jamais « le meilleur » indicateur.\nOn élimine les mauvais et on combine les survivants.", GREEN),
        ("Pas de look-ahead", "Le signal est calculé une fois, évalué uniquement\ndans le futur relatif de chaque fenêtre.", GREEN),
        ("Pas de faux signaux", "Les familles non encore implémentées (RSI, MACD, OBV)\naffichent « N/A », pas un score provisoire.", AMBER),
        ("Pas de seuils optimisés", "Les seuils (0.85 corrélation, 0.25 plancher, 40% viabilité)\nsont fixés a priori, pas ajustés sur les données.", AMBER),
        ("Transparence totale", "Chaque élimination est tracée avec sa raison.\nChaque fenêtre OOS est inspectable individuellement.", BLUE),
    ]
    y = Inches(1.3)
    for title, desc, clr in items:
        rect(s, Inches(0.8), y, Inches(0.12), Inches(0.95), clr)
        txt(s, Inches(1.15), y + Inches(0.02), Inches(4.5), Inches(0.35), title, sz=16, bold=True, color=clr)
        txt(s, Inches(1.15), y + Inches(0.38), Inches(11), Inches(0.55), desc, sz=13, color=LIGHT)
        y += Inches(1.1)

    footer(s, "En cas de doute, le système produit NEUTRE — jamais de signal forcé", "11")

    # ── 12. INTERFACE ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Interface Utilisateur — Navigation en 3 Niveaux")

    levels = [
        ("Niveau 0\nVue d'ensemble", "Speedomètre avec score global\nUn chiffre, une direction", "Le décideur veut\nune réponse rapide", BLUE),
        ("Niveau 1\n4 Familles", "SMA | RSI | MACD | OBV\nChaque famille avec son score", "L'analyste veut savoir\nquelle famille contribue", GREEN),
        ("Niveau 2\nDrilldown", "Entonnoir de filtrage + représentants\nCliquer → page détail variante", "Le quant veut inspecter\nchaque variante", PURPLE),
    ]
    y = Inches(1.4)
    for level, content, audience, clr in levels:
        rect(s, Inches(0.8), y, Inches(2.5), Inches(1.5), clr, level, sz=15, bold=True)
        txt(s, Inches(3.6), y + Inches(0.15), Inches(5.0), Inches(1.2), content, sz=14, color=LIGHT)
        txt(s, Inches(9.0), y + Inches(0.15), Inches(3.5), Inches(1.2), audience, sz=13, color=SILVER)
        if level.startswith("Niveau 0") or level.startswith("Niveau 1"):
            arrow_d(s, Inches(2.0), y + Inches(1.55), Inches(0.25), Inches(0.2))
        y += Inches(1.8)

    txt(s, Inches(0.9), Inches(6.9), Inches(11), Inches(0.4),
        "Chaque niveau s'adresse à un profil utilisateur différent, du plus synthétique au plus granulaire.", sz=13, color=MUTED)
    footer(s, "", "12")

    # ── 13. EXTENSIBILITÉ ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Extensibilité — Ajouter une Famille d'Indicateurs")

    tf = txt(s, Inches(0.9), Inches(1.3), Inches(11), Inches(4.5),
        "Processus en 2 étapes :", sz=18, bold=True, color=GREEN)
    para(tf, "", sz=10)
    para(tf, "Étape 1 — Enregistrer les variantes (candidates.py)", sz=16, bold=True, color=BLUE)
    para(tf, "@register_family(\"bollinger\", n_variants=30)", sz=14, color=LIGHT)
    para(tf, "def _bollinger_variants(horizon):", sz=14, color=LIGHT)
    para(tf, "    return [VariantDef(..., params={\"period\": p, \"std\": s}) for p, s in grid]", sz=14, color=LIGHT)
    para(tf, "", sz=10)
    para(tf, "Étape 2 — Enregistrer le calcul du signal (oos_eval.py)", sz=16, bold=True, color=BLUE)
    para(tf, "@register_signal(\"bollinger\", \"bb_squeeze\")", sz=14, color=LIGHT)
    para(tf, "def _bollinger_signal(close, volume, params):", sz=14, color=LIGHT)
    para(tf, "    upper, lower = bollinger_bands(close, params[\"period\"], params[\"std\"])", sz=14, color=LIGHT)
    para(tf, "    return np.where(close < lower, +1.0, np.where(close > upper, -1.0, 0.0))", sz=14, color=LIGHT)
    para(tf, "", sz=14)
    para(tf, "C'est tout. Le pipeline (couches B→G) s'applique automatiquement.", sz=16, bold=True, color=GREEN)
    para(tf, "Aucune modification de l'API, du frontend, ou du pipeline de filtrage.", sz=14, color=SILVER)

    footer(s, "", "13")

    # ── 14. REFERENCES ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    header_bar(s, "Fondements Théoriques")

    refs = [
        ("Walk-Forward Analysis", "Pardo (2008), Ch. 7-9", "Couche B : fenêtres roulantes OOS", BLUE),
        ("Deflated Sharpe Ratio", "Bailey & de Prado (2014)", "Justification du filtrage vs. sélection du « meilleur »", BLUE),
        ("Feature Clustering", "de Prado (2018), Ch. 8", "Couche E : réduction de redondance", GREEN),
        ("Ensemble Methods", "Breiman (1996)", "Couche G : combinaison pondérée de weak learners", GREEN),
        ("Multi-Factor Scoring", "Grinold & Kahn (2000)", "Couche C : pondération multi-critères", AMBER),
        ("Reality Check", "White (2000)", "Jamais d'évaluation sur données d'entraînement", AMBER),
        ("Transaction Costs", "de Prado (2018), Ch. 14", "Couche B : coûts inclus dans chaque fenêtre", PURPLE),
    ]
    y = Inches(1.4)
    for concept, source, application, clr in refs:
        rect(s, Inches(0.8), y, Inches(0.08), Inches(0.6), clr)
        txt(s, Inches(1.1), y, Inches(3.0), Inches(0.3), concept, sz=14, bold=True, color=clr)
        txt(s, Inches(1.1), y + Inches(0.3), Inches(3.0), Inches(0.3), source, sz=12, color=SILVER)
        txt(s, Inches(5.0), y + Inches(0.1), Inches(7.5), Inches(0.4), f"→  {application}", sz=13, color=LIGHT)
        y += Inches(0.72)

    footer(s, "", "14")

    # ── 15. CLOSING ──
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s)
    rect(s, Inches(2), Inches(2.2), Inches(9.3), Inches(0.04), GREEN)
    txt(s, Inches(2), Inches(2.8), Inches(9.3), Inches(0.8),
        "Merci", sz=40, bold=True)
    txt(s, Inches(2), Inches(3.7), Inches(9.3), Inches(0.5),
        "Questions & Discussion", sz=20, color=GREEN)
    rect(s, Inches(2), Inches(4.6), Inches(9.3), Inches(0.04), DARK_CARD)
    tf = txt(s, Inches(2), Inches(5.0), Inches(9.3), Inches(1.5),
        "« The goal is not to find the best strategy,", sz=14, color=MUTED)
    para(tf, "but to eliminate the worst ones and combine the survivors. »", sz=14, color=MUTED)
    para(tf, "— Principe d'ensemble (Breiman, 1996 ; de Prado, 2018)", sz=12, color=GREEN, bold=True, before=Pt(8))

    return prs


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "docs")

    p1 = build_pres1()
    path1 = os.path.join(out_dir, "Presentation_1_Architecture_Plateforme.pptx")
    p1.save(path1)
    print(f"OK  {path1}")

    p2 = build_pres2()
    path2 = os.path.join(out_dir, "Presentation_2_Moteur_de_Signaux.pptx")
    p2.save(path2)
    print(f"OK  {path2}")
