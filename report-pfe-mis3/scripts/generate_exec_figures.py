from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import patches


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "frontend" / "public" / "data"
OUT_DIR = ROOT / "report-pfe-mis3" / "figures" / "desk_signal_exec"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


SHORT = load("scores-short.json")
MEDIUM = load("scores-medium.json")
LONG = load("scores-long.json")
SIGNALS_MEDIUM = load("signals-medium.json")


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT_DIR / name, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def rounded_box(ax, x, y, w, h, title, body, face="#ffffff", edge="#d1d5db", title_color="#111827", body_color="#4b5563"):
    rect = patches.FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        facecolor=face,
        edgecolor=edge,
        linewidth=1.3,
        transform=ax.transAxes,
    )
    ax.add_patch(rect)
    ax.text(x + 0.03, y + h - 0.08, title, fontsize=12.5, weight="bold", color=title_color, transform=ax.transAxes)
    ax.text(x + 0.03, y + h - 0.14, body, fontsize=10.2, color=body_color, transform=ax.transAxes, va="top", wrap=True)


def fig_value_prop() -> None:
    fig, ax = plt.subplots(figsize=(12, 4.2))
    ax.axis("off")

    ax.text(0.03, 0.92, "Ce que le produit apporte au desk", fontsize=18, weight="bold", color="#111827", transform=ax.transAxes)
    ax.text(
        0.03,
        0.84,
        "Aider les traders a identifier plus vite les meilleures opportunites du marche.",
        fontsize=11,
        color="#4b5563",
        transform=ax.transAxes,
    )

    rounded_box(
        ax, 0.03, 0.18, 0.29, 0.52,
        "1. Standardiser la lecture",
        "Le moteur applique une meme logique a l'ensemble des titres pour reduire les lectures heterogenes et les arbitrages purement intuitifs.",
        face="#f8fafc",
    )
    rounded_box(
        ax, 0.355, 0.18, 0.29, 0.52,
        "2. Faire ressortir les opportunites",
        "Le dashboard transforme un univers actions en liste exploitable, afin de faire ressortir plus vite les titres a regarder en priorite.",
        face="#eff6ff",
        edge="#93c5fd",
    )
    rounded_box(
        ax, 0.68, 0.18, 0.29, 0.52,
        "3. Rendre le signal explicable",
        "La page Signals permet de revenir du score global vers les familles contributrices et les variantes retenues.",
        face="#ecfdf5",
        edge="#86efac",
    )
    save(fig, "value_prop.png")


def fig_product_surfaces() -> None:
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.axis("off")

    ax.text(0.03, 0.92, "Deux surfaces complementaires", fontsize=18, weight="bold", color="#111827", transform=ax.transAxes)
    ax.text(0.03, 0.84, "Le produit combine un ecran d'explication et un ecran de pilotage.", fontsize=11, color="#4b5563", transform=ax.transAxes)

    rounded_box(
        ax, 0.04, 0.18, 0.40, 0.56,
        "Page Signals",
        "Usage : analyser un titre en profondeur.\n\n"
        "Le desk y voit :\n"
        "- le signal technique global\n"
        "- la contribution des familles\n"
        "- le detail des signaux retenus\n"
        "- la justification du verdict",
        face="#faf5ff",
        edge="#c4b5fd",
    )
    rounded_box(
        ax, 0.56, 0.18, 0.40, 0.56,
        "Dashboard V1",
        "Usage : piloter l'univers couvert.\n\n"
        "Le desk y voit :\n"
        "- les titres prioritaires\n"
        "- la lecture par secteur\n"
        "- la tonalite de l'indice\n"
        "- la comparaison court / moyen / long terme",
        face="#fff7ed",
        edge="#fdba74",
    )

    ax.annotate(
        "",
        xy=(0.54, 0.46),
        xytext=(0.46, 0.46),
        arrowprops=dict(arrowstyle="->", lw=1.8, color="#374151"),
        xycoords=ax.transAxes,
        textcoords=ax.transAxes,
    )
    ax.text(0.50, 0.50, "du detail\nvers la synthese", ha="center", va="bottom", fontsize=10, color="#374151", transform=ax.transAxes)
    save(fig, "product_surfaces.png")


def fig_market_snapshot() -> None:
    fig, ax = plt.subplots(figsize=(12, 5.0))
    ax.axis("off")

    ax.text(0.03, 0.92, "Lecture de marche au 10 avril 2026", fontsize=18, weight="bold", color="#111827", transform=ax.transAxes)
    ax.text(0.03, 0.84, "Exemple de restitution multi-horizon directement exploitable.", fontsize=11, color="#4b5563", transform=ax.transAxes)

    cards = [
        ("Court terme", SHORT["index"]["aggregate_score_pct"], SHORT["index"]["aggregate_signal_label"], SHORT["index"]["breadth"]),
        ("Moyen terme", MEDIUM["index"]["aggregate_score_pct"], MEDIUM["index"]["aggregate_signal_label"], MEDIUM["index"]["breadth"]),
        ("Long terme", LONG["index"]["aggregate_score_pct"], LONG["index"]["aggregate_signal_label"], LONG["index"]["breadth"]),
    ]
    positions = [0.04, 0.355, 0.67]

    for x, (title, score, label, breadth) in zip(positions, cards):
        face = "#ecfdf5" if score > 15 else "#fffbeb" if score >= -15 else "#fef2f2"
        edge = "#86efac" if score > 15 else "#fcd34d" if score >= -15 else "#fca5a5"
        rect = patches.FancyBboxPatch(
            (x, 0.22), 0.27, 0.50,
            boxstyle="round,pad=0.012,rounding_size=0.03",
            facecolor=face, edgecolor=edge, linewidth=1.4, transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(x + 0.03, 0.66, title, fontsize=12.5, weight="bold", color="#111827", transform=ax.transAxes)
        ax.text(x + 0.03, 0.54, f"{score:+.2f}", fontsize=24, weight="bold", color="#111827", transform=ax.transAxes)
        ax.text(x + 0.03, 0.46, label, fontsize=12, color="#374151", transform=ax.transAxes)
        ax.text(
            x + 0.03,
            0.34,
            f"Achat : {breadth['achat']}\nNeutre : {breadth['neutre']}\nVente : {breadth['vente']}",
            fontsize=10.5,
            color="#4b5563",
            transform=ax.transAxes,
            va="top",
        )

    ax.text(
        0.03,
        0.08,
        "Lecture produit : un environnement favorable tactiquement, puis plus neutre a mesure que l'horizon s'allonge. "
        "Le systeme n'impose pas un verdict unique ; il rend visible la nuance utile pour le desk.",
        fontsize=10.2,
        color="#374151",
        transform=ax.transAxes,
        wrap=True,
    )
    save(fig, "market_snapshot.png")


def fig_case_study() -> None:
    stock = next(item for item in SIGNALS_MEDIUM["stocks"] if item["symbol"] == "ADH")
    fams = stock["families"]

    fig, ax = plt.subplots(figsize=(12, 4.9))
    ax.axis("off")

    ax.text(0.03, 0.92, "Cas d'usage - ADH en horizon moyen terme", fontsize=18, weight="bold", color="#111827", transform=ax.transAxes)
    ax.text(0.03, 0.84, "Exemple de signal fort, nuance comprise.", fontsize=11, color="#4b5563", transform=ax.transAxes)

    rounded_box(
        ax, 0.03, 0.22, 0.26, 0.50,
        "Signal global",
        f"ADH ressort en {stock['aggregate_signal_label']} avec un score de {stock['aggregate_score_pct']:+.1f}.\n\n"
        "Le message produit est clair, lisible et directement priorisable.",
        face="#eff6ff",
        edge="#93c5fd",
    )

    y = 0.60
    family_rows = [
        ("SMA", fams["sma"]["family_signal_label"]),
        ("MACD", fams["macd"]["family_signal_label"]),
        ("RSI", fams["rsi"]["family_signal_label"]),
        ("OBV", fams["obv"]["family_signal_label"]),
    ]
    for i, (family, label) in enumerate(family_rows):
        face = "#ecfdf5" if family != "RSI" else "#f3f4f6"
        rect = patches.FancyBboxPatch(
            (0.36, y - i * 0.11), 0.58, 0.085,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor=face, edgecolor="#d1d5db", linewidth=1.0, transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(0.39, y + 0.026 - i * 0.11, family, fontsize=11.5, weight="bold", color="#111827", transform=ax.transAxes)
        ax.text(0.52, y + 0.026 - i * 0.11, label, fontsize=10.5, color="#374151", transform=ax.transAxes)

    ax.text(
        0.36,
        0.20,
        "Lecture produit : la tendance, le momentum et le volume convergent. "
        "Le RSI reste neutre. Cette restitution est utile commercialement car elle combine conviction et prudence au lieu de sur-vendre un consensus parfait.",
        fontsize=10.3,
        color="#374151",
        transform=ax.transAxes,
        wrap=True,
    )
    save(fig, "case_study_adh.png")


if __name__ == "__main__":
    fig_value_prop()
    fig_product_surfaces()
    fig_market_snapshot()
    fig_case_study()
    print(f"Executive figures generated in {OUT_DIR}")
