from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patches


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "frontend" / "public" / "data"
FIG_DIR = ROOT / "report-pfe-mis3" / "figures" / "desk_signal_report"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


SHORT = load_json("scores-short.json")
MEDIUM = load_json("scores-medium.json")
LONG = load_json("scores-long.json")
SIGNALS_MEDIUM = load_json("signals-medium.json")


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIG_DIR / name, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def style_axis(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.18, linestyle="--")


def fig_pipeline_ag() -> None:
    fig, ax = plt.subplots(figsize=(12, 2.8))
    ax.axis("off")

    labels = [
        ("A", "Candidats"),
        ("B", "Evaluation\nOOS"),
        ("C", "Robustesse"),
        ("D", "Filtrage"),
        ("E", "Redondance"),
        ("F", "Signal\ncourant"),
        ("G", "Ensemble"),
    ]
    colors = ["#dbeafe", "#d1fae5", "#ede9fe", "#fef3c7", "#fde68a", "#fee2e2", "#cffafe"]
    x_positions = np.linspace(0.05, 0.89, len(labels))

    for idx, ((step, label), x) in enumerate(zip(labels, x_positions)):
        box = patches.FancyBboxPatch(
            (x, 0.25),
            0.1,
            0.5,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            linewidth=1.2,
            edgecolor="#1f2937",
            facecolor=colors[idx],
            transform=ax.transAxes,
        )
        ax.add_patch(box)
        ax.text(x + 0.05, 0.57, step, ha="center", va="center", fontsize=13, weight="bold", transform=ax.transAxes)
        ax.text(x + 0.05, 0.40, label, ha="center", va="center", fontsize=10, transform=ax.transAxes)
        if idx < len(labels) - 1:
            ax.annotate(
                "",
                xy=(x + 0.115, 0.5),
                xytext=(x + 0.1, 0.5),
                arrowprops=dict(arrowstyle="->", lw=1.4, color="#374151"),
                xycoords=ax.transAxes,
                textcoords=ax.transAxes,
            )

    ax.text(
        0.5,
        0.08,
        "Logique du moteur: eliminer les variantes faibles, conserver les survivants robustes, puis agreger un signal interpretable.",
        ha="center",
        va="center",
        fontsize=10,
        color="#374151",
        transform=ax.transAxes,
    )
    save(fig, "pipeline_ag.png")


def fig_product_flow() -> None:
    fig, ax = plt.subplots(figsize=(11.5, 3.0))
    ax.axis("off")

    blocks = [
        ("OHLCV\ncanonique", "#e0f2fe"),
        ("Signal Engine\nanalyse technique", "#dcfce7"),
        ("Page Signals\nexplication par titre", "#ede9fe"),
        ("Dashboard V1\npriorisation du desk", "#fee2e2"),
    ]
    x_positions = [0.05, 0.29, 0.55, 0.80]

    for i, ((label, color), x) in enumerate(zip(blocks, x_positions)):
        rect = patches.FancyBboxPatch(
            (x, 0.22),
            0.15,
            0.56,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            linewidth=1.2,
            edgecolor="#1f2937",
            facecolor=color,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(x + 0.075, 0.50, label, ha="center", va="center", fontsize=11, weight="bold", transform=ax.transAxes)
        if i < len(blocks) - 1:
            ax.annotate(
                "",
                xy=(x + 0.19, 0.50),
                xytext=(x + 0.15, 0.50),
                arrowprops=dict(arrowstyle="->", lw=1.5, color="#374151"),
                xycoords=ax.transAxes,
                textcoords=ax.transAxes,
            )

    ax.text(0.365, 0.80, "scores par famille", fontsize=9, color="#4b5563", transform=ax.transAxes)
    ax.text(0.67, 0.80, "lecture, classement,\ncomparaison multi-horizon", fontsize=9, color="#4b5563", ha="center", transform=ax.transAxes)
    save(fig, "product_flow.png")


def fig_market_overview() -> None:
    horizons = ["Court terme", "Moyen terme", "Long terme"]
    scores = [
        SHORT["index"]["aggregate_score_pct"],
        MEDIUM["index"]["aggregate_score_pct"],
        LONG["index"]["aggregate_score_pct"],
    ]
    breadth = [
        SHORT["index"]["breadth"],
        MEDIUM["index"]["breadth"],
        LONG["index"]["breadth"],
    ]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3))

    colors = ["#16a34a" if score > 15 else "#f59e0b" if score >= -15 else "#dc2626" for score in scores]
    axes[0].bar(horizons, scores, color=colors, edgecolor="#111827")
    axes[0].axhline(0, color="#111827", linewidth=1)
    axes[0].set_title("Score agrege de l'indice par horizon", fontsize=12, weight="bold")
    axes[0].set_ylabel("Score")
    axes[0].set_ylim(-10, 40)
    style_axis(axes[0])
    for idx, score in enumerate(scores):
        axes[0].text(idx, score + 1.1, f"{score:.2f}", ha="center", fontsize=10, weight="bold")

    achat = [b["achat"] for b in breadth]
    neutre = [b["neutre"] for b in breadth]
    vente = [b["vente"] for b in breadth]
    axes[1].bar(horizons, achat, label="Achat", color="#22c55e", edgecolor="#111827")
    axes[1].bar(horizons, neutre, bottom=achat, label="Neutre", color="#9ca3af", edgecolor="#111827")
    axes[1].bar(
        horizons,
        vente,
        bottom=np.array(achat) + np.array(neutre),
        label="Vente",
        color="#ef4444",
        edgecolor="#111827",
    )
    axes[1].set_title("Breadth par horizon", fontsize=12, weight="bold")
    axes[1].set_ylabel("Nombre de titres")
    axes[1].legend(frameon=False, loc="upper right")
    style_axis(axes[1])

    fig.suptitle("Lecture de marche extraite des snapshots du 10 avril 2026", fontsize=13, weight="bold", y=1.02)
    save(fig, "market_overview.png")


def fig_dashboard_ranking() -> None:
    stocks = sorted(SHORT["stocks"], key=lambda item: item["aggregate_score_pct"], reverse=True)
    top = stocks[:8]

    rows = []
    for stock in top:
        rows.append(
            [
                stock["symbol"],
                stock.get("sector") or "-",
                f'{stock["aggregate_score_pct"]:.2f}',
                stock["aggregate_signal_label"],
            ]
        )

    fig, ax = plt.subplots(figsize=(10.5, 4.2))
    ax.axis("off")
    ax.set_title("Illustration de restitution dashboard - classement court terme", fontsize=13, weight="bold", pad=16)

    table = ax.table(
        cellText=rows,
        colLabels=["Titre", "Secteur", "Score global", "Lecture"],
        cellLoc="center",
        colColours=["#e5e7eb"] * 4,
        bbox=[0.03, 0.02, 0.94, 0.86],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.45)

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#9ca3af")
        if row == 0:
            cell.set_text_props(weight="bold", color="#111827")
        elif col == 3:
            label = rows[row - 1][3].lower()
            if "achat" in label:
                cell.set_facecolor("#dcfce7")
            elif "vente" in label:
                cell.set_facecolor("#fee2e2")
            else:
                cell.set_facecolor("#f3f4f6")

    ax.text(
        0.03,
        -0.05,
        "Exemple de lecture transversale: le dashboard classe les titres, conserve une etiquette simple et permet de remonter au detail via la page Signals.",
        fontsize=9,
        color="#374151",
        transform=ax.transAxes,
    )
    save(fig, "dashboard_ranking.png")


def fig_adh_breakdown() -> None:
    stock = next(item for item in SIGNALS_MEDIUM["stocks"] if item["symbol"] == "ADH")
    families = ["sma", "macd", "rsi", "obv"]
    labels = ["SMA", "MACD", "RSI", "OBV"]
    scores = [stock["families"][fam]["family_score_pct"] for fam in families]
    text_labels = [stock["families"][fam]["family_signal_label"] for fam in families]
    rep_counts = [stock["families"][fam]["representative_count"] for fam in families]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))

    bar_colors = ["#16a34a" if val > 15 else "#9ca3af" if val >= -15 else "#dc2626" for val in scores]
    axes[0].bar(labels, scores, color=bar_colors, edgecolor="#111827")
    axes[0].set_ylim(-20, 110)
    axes[0].axhline(0, color="#111827", linewidth=1)
    axes[0].set_title("ADH - score par famille (moyen terme)", fontsize=12, weight="bold")
    axes[0].set_ylabel("Score")
    style_axis(axes[0])
    for idx, score in enumerate(scores):
        axes[0].text(idx, score + 3, f"{score:.0f}", ha="center", fontsize=10, weight="bold")

    axes[1].axis("off")
    axes[1].set_title("Lecture interpretable du signal", fontsize=12, weight="bold")
    y_positions = [0.82, 0.60, 0.38, 0.16]
    card_colors = ["#ecfdf5", "#eff6ff", "#f9fafb", "#fef2f2"]
    for y, fam, label, sig_label, rep_count, color in zip(y_positions, labels, text_labels, text_labels, rep_counts, card_colors):
        rect = patches.FancyBboxPatch(
            (0.05, y - 0.09),
            0.9,
            0.15,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            facecolor=color,
            edgecolor="#9ca3af",
            linewidth=1,
            transform=axes[1].transAxes,
        )
        axes[1].add_patch(rect)
        axes[1].text(0.10, y, fam, transform=axes[1].transAxes, fontsize=11, weight="bold", va="center")
        axes[1].text(0.28, y, label, transform=axes[1].transAxes, fontsize=10, va="center")
        axes[1].text(0.92, y, f"{rep_count} rep.", transform=axes[1].transAxes, fontsize=10, va="center", ha="right")

    axes[1].text(
        0.05,
        0.02,
        "Sur ce cas, la tendance, le momentum et le volume convergent. Le RSI reste neutre, ce qui montre que le moteur conserve la nuance au lieu de forcer un consensus artificiel.",
        fontsize=9.2,
        color="#374151",
        transform=axes[1].transAxes,
        wrap=True,
    )

    save(fig, "adh_breakdown.png")


if __name__ == "__main__":
    fig_pipeline_ag()
    fig_product_flow()
    fig_market_overview()
    fig_dashboard_ranking()
    fig_adh_breakdown()
    print(f"Figures generated in {FIG_DIR}")
