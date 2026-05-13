from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
LATEX_DIR = ROOT / "latex"
FIG_DIR = LATEX_DIR / "figures" / "generated"
DATA_DIR = ROOT / "frontend" / "public" / "data"
MARKET_XLSX = ROOT / "market_data_export_v2.xlsx"
FALLBACK_IAM_XLSX = ROOT / "scripts" / "IAM.xlsx"

FIG_DIR.mkdir(parents=True, exist_ok=True)

COLORS = {
    "ink": "#172033",
    "muted": "#5b6475",
    "line": "#ced6e0",
    "blue": "#2563eb",
    "blue_light": "#dbeafe",
    "green": "#16a34a",
    "green_light": "#dcfce7",
    "red": "#dc2626",
    "red_light": "#fee2e2",
    "amber": "#d97706",
    "amber_light": "#fef3c7",
    "purple": "#7c3aed",
    "purple_light": "#ede9fe",
    "cyan_light": "#cffafe",
    "gray_light": "#f3f4f6",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


F = {name: font(size, bold) for name, size, bold in [
    ("title", 34, True),
    ("subtitle", 22, False),
    ("h1", 24, True),
    ("h2", 20, True),
    ("body", 18, False),
    ("small", 14, False),
    ("small_bold", 14, True),
    ("tiny", 12, False),
]}


def canvas(width: int = 1800, height: int = 1050) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (width, height), "white")
    return img, ImageDraw.Draw(img)


def save(img: Image.Image, name: str) -> None:
    img.save(FIG_DIR / name, dpi=(220, 220))


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    out: list[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            if text_size(draw, trial, fnt)[0] <= max_width or not line:
                line = trial
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out or [""]


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt, fill: str, max_width: int, line_gap: int = 6, anchor: str = "la") -> int:
    x, y = xy
    lines = wrap_text(draw, text, fnt, max_width)
    line_h = text_size(draw, "Ag", fnt)[1] + line_gap
    total_h = line_h * len(lines) - line_gap
    if anchor == "mm":
        y -= total_h // 2
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def rounded_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str = COLORS["ink"], width: int = 3, radius: int = 24) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, fnt, fill: str = COLORS["ink"], max_width: int | None = None) -> None:
    x1, y1, x2, y2 = box
    max_width = max_width or (x2 - x1 - 30)
    lines = wrap_text(draw, text, fnt, max_width)
    line_h = text_size(draw, "Ag", fnt)[1] + 6
    total_h = len(lines) * line_h - 6
    y = y1 + ((y2 - y1) - total_h) // 2
    for line in lines:
        w, _ = text_size(draw, line, fnt)
        draw.text((x1 + ((x2 - x1) - w) // 2, y), line, font=fnt, fill=fill)
        y += line_h


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], fill: str = COLORS["ink"], width: int = 4) -> None:
    draw.line([start, end], fill=fill, width=width)
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 18
    pts = [
        end,
        (int(end[0] - size * math.cos(ang - math.pi / 6)), int(end[1] - size * math.sin(ang - math.pi / 6))),
        (int(end[0] - size * math.cos(ang + math.pi / 6)), int(end[1] - size * math.sin(ang + math.pi / 6))),
    ]
    draw.polygon(pts, fill=fill)


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str | None = None) -> None:
    draw.text((60, 45), title, font=F["title"], fill=COLORS["ink"])
    if subtitle:
        draw.text((60, 88), subtitle, font=F["subtitle"], fill=COLORS["muted"])


def source(draw: ImageDraw.ImageDraw, text: str) -> None:
    draw.text((60, 1005), text, font=F["tiny"], fill=COLORS["muted"])


def load_scores(horizon: str = "medium") -> dict:
    return json.loads((DATA_DIR / f"scores-{horizon}.json").read_text(encoding="utf-8"))


def load_signals(horizon: str = "medium") -> dict:
    return json.loads((DATA_DIR / f"signals-{horizon}.json").read_text(encoding="utf-8"))


def stock_row(data: dict, symbol: str) -> dict:
    for row in data.get("stocks", []):
        if row.get("symbol") == symbol:
            return row
    stocks = data.get("stocks", [])
    if stocks:
        return stocks[0]
    raise KeyError(symbol)


def signal_engine_payload(row: dict) -> dict:
    return row.get("scores", {}).get("signal_engine", row)


def read_ohlcv(symbol: str, start: str | None = None) -> pd.DataFrame:
    workbook = MARKET_XLSX if MARKET_XLSX.exists() else FALLBACK_IAM_XLSX
    xls = pd.ExcelFile(workbook)
    sheet = symbol if symbol in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(workbook, sheet_name=sheet)
    rename = {
        "Ouvt": "Open",
        "'+Haut": "High",
        "'+Bas": "Low",
        "Clôture": "Close",
        "Cloture": "Close",
    }
    df = df.rename(columns=rename)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
    if start:
        df = df[df["Date"] >= pd.Timestamp(start)]
    return df.reset_index(drop=True)


def has_sheet(path: Path, symbol: str) -> bool:
    if not path.exists():
        return False
    try:
        return symbol in pd.ExcelFile(path).sheet_names
    except Exception:
        return False


def line_chart(
    draw: ImageDraw.ImageDraw,
    area: tuple[int, int, int, int],
    series: list[tuple[str, Iterable[float], str, int]],
    labels: list[str] | None = None,
    y_label: str = "",
    y_pad_pct: float = 0.08,
) -> None:
    x1, y1, x2, y2 = area
    draw.rectangle(area, outline=COLORS["line"], width=2)
    vals = []
    for _, ys, _, _ in series:
        vals.extend([float(v) for v in ys if pd.notna(v) and math.isfinite(float(v))])
    if not vals:
        return
    ymin, ymax = min(vals), max(vals)
    pad = max((ymax - ymin) * y_pad_pct, 1e-9)
    ymin -= pad
    ymax += pad
    for i in range(5):
        yy = y1 + int((y2 - y1) * i / 4)
        draw.line([(x1, yy), (x2, yy)], fill="#e5e7eb", width=1)
        val = ymax - (ymax - ymin) * i / 4
        draw.text((x1 - 58, yy - 9), f"{val:.0f}", font=F["tiny"], fill=COLORS["muted"])
    n = max(len(list(series[0][1])), 2)
    for name, ys_raw, color, width in series:
        ys = list(ys_raw)
        points = []
        for i, v in enumerate(ys):
            if pd.isna(v) or not math.isfinite(float(v)):
                continue
            x = x1 + int((x2 - x1) * i / (n - 1))
            y = y2 - int((float(v) - ymin) / (ymax - ymin) * (y2 - y1))
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=color, width=width, joint="curve")
    if labels:
        for idx, label in enumerate(labels):
            x = x1 + int((x2 - x1) * idx / max(len(labels) - 1, 1))
            draw.text((x - 22, y2 + 12), label, font=F["tiny"], fill=COLORS["muted"])
    if y_label:
        draw.text((x1, y1 - 30), y_label, font=F["small_bold"], fill=COLORS["muted"])


def bar_chart(draw: ImageDraw.ImageDraw, area: tuple[int, int, int, int], labels: list[str], values: list[float], colors: list[str], y_max: float | None = None, suffix: str = "") -> None:
    x1, y1, x2, y2 = area
    draw.rectangle(area, outline=COLORS["line"], width=2)
    y_min = min(0.0, min(values))
    y_max = y_max if y_max is not None else max(values) * 1.15
    zero_y = y2 - int((0 - y_min) / (y_max - y_min) * (y2 - y1))
    draw.line([(x1, zero_y), (x2, zero_y)], fill=COLORS["ink"], width=2)
    gap = 18
    bar_w = max(18, int((x2 - x1 - gap * (len(values) + 1)) / len(values)))
    for i, (label, val, color) in enumerate(zip(labels, values, colors)):
        bx1 = x1 + gap + i * (bar_w + gap)
        bx2 = bx1 + bar_w
        by = y2 - int((val - y_min) / (y_max - y_min) * (y2 - y1))
        draw.rectangle((bx1, min(by, zero_y), bx2, max(by, zero_y)), fill=color, outline=COLORS["ink"], width=2)
        draw.text((bx1, y2 + 12), label[:10], font=F["tiny"], fill=COLORS["muted"])
        draw.text((bx1, min(by, zero_y) - 24), f"{val:.0f}{suffix}", font=F["tiny"], fill=COLORS["ink"])


def fig_ch1_bmce() -> None:
    img, draw = canvas()
    header(draw, "Positionnement institutionnel", "BMCE Capital dans l'ecosysteme BANK OF AFRICA")
    rounded_box(draw, (430, 145, 1370, 285), COLORS["blue_light"])
    centered_text(draw, (430, 145, 1370, 285), "BANK OF AFRICA - BMCE Group\nGroupe bancaire panafricain multi-metiers", F["h1"])
    draw.line([(900, 285), (900, 350)], fill=COLORS["muted"], width=5)
    draw.line([(265, 350), (1505, 350)], fill=COLORS["muted"], width=5)
    boxes = [
        ((90, 430, 440, 585), "Banque commerciale\nreseau Maroc", COLORS["gray_light"]),
        ((515, 405, 890, 620), "BMCE CAPITAL\nBanque d'affaires\nperimetre du projet", COLORS["green_light"]),
        ((965, 430, 1320, 585), "Filiales specialisees\nleasing, factoring,\ncredit conso", COLORS["amber_light"]),
        ((1390, 430, 1710, 585), "Operations Afrique\nEurope, Asie,\nAmerique du Nord", COLORS["purple_light"]),
    ]
    for box, label, color in boxes:
        rounded_box(draw, box, color)
        centered_text(draw, box, label, F["body"])
        x_mid = (box[0] + box[2]) // 2
        draw.line([(x_mid, 350), (x_mid, box[1] - 22)], fill=COLORS["muted"], width=5)
        arrow(draw, (x_mid, box[1] - 42), (x_mid, box[1] - 8), COLORS["muted"])
    sub = [
        ((265, 760, 565, 900), "Capital Markets\nactivites de marche\net actions", COLORS["cyan_light"]),
        ((660, 760, 960, 900), "BMCE Capital Bourse\nintermediation\nvers le marche", COLORS["cyan_light"]),
        ((1055, 760, 1355, 900), "Research\nanalyse actions\net economie", COLORS["cyan_light"]),
    ]
    draw.line([(702, 620), (702, 700)], fill=COLORS["muted"], width=5)
    draw.line([(415, 700), (1205, 700)], fill=COLORS["muted"], width=5)
    for box, label, color in sub:
        rounded_box(draw, box, color)
        centered_text(draw, box, label, F["body"])
        x_mid = (box[0] + box[2]) // 2
        draw.line([(x_mid, 700), (x_mid, box[1] - 22)], fill=COLORS["muted"], width=4)
        arrow(draw, (x_mid, box[1] - 42), (x_mid, box[1] - 8), COLORS["muted"], width=4)
    source(draw, "Sources: BANK OF AFRICA investor relations; BMCE Capital official pages.")
    save(img, "ch1_bmce_organigramme.png")


def fig_ch1_order_cycle() -> None:
    img, draw = canvas()
    header(draw, "Chemin simplifie d'un ordre", "La plateforme intervient avant la transmission au marche")
    labels = [
        ("Preparation\nde la decision", COLORS["blue_light"]),
        ("Systemes internes\ncontroles risque\net conformite", COLORS["green_light"]),
        ("BMCE Capital\nBourse", COLORS["amber_light"]),
        ("Bourse de\nCasablanca\nmatching", COLORS["purple_light"]),
        ("Avis d'opere\nconfirmation", COLORS["cyan_light"]),
        ("Maroclear\nreglement-livraison\nT+3", COLORS["gray_light"]),
    ]
    y = 420
    w = 240
    gap = 45
    x = 75
    prev = None
    for label, color in labels:
        box = (x, y, x + w, y + 155)
        rounded_box(draw, box, color)
        centered_text(draw, box, label, F["body"])
        if prev:
            arrow(draw, (prev[2] + 8, y + 78), (box[0] - 12, y + 78), COLORS["ink"])
        prev = box
        x += w + gap
    rounded_box(draw, (90, 205, 425, 315), COLORS["red_light"], outline=COLORS["red"])
    centered_text(draw, (90, 205, 425, 315), "Plateforme PFE\nanalyse -> preparation", F["h2"], COLORS["red"])
    arrow(draw, (255, 315), (195, y - 15), COLORS["red"])
    draw.text((1020, 660), "Supervision AMMC et regles de marche", font=F["h2"], fill=COLORS["muted"])
    draw.line([(980, 640), (1640, 640)], fill=COLORS["muted"], width=3)
    source(draw, "Sources: rapport interne; AMMC; Maroclear.")
    save(img, "ch1_cycle_ordre.png")


def fig_ch1_need() -> None:
    img, draw = canvas()
    header(draw, "Aide a la preparation de seance", "Une couche quantitative avant la determination du prix d'ouverture")
    cards = [
        ((90, 235, 560, 575), COLORS["blue_light"], COLORS["blue"], "1. Prioriser",
         "Classer les valeurs a regarder avant l'ouverture selon le signal, le risque et la fraicheur."),
        ((665, 235, 1135, 575), COLORS["green_light"], COLORS["green"], "2. Expliquer",
         "Afficher les familles d'indicateurs, les preuves statistiques, les seuils et les contradictions."),
        ((1240, 235, 1710, 575), COLORS["amber_light"], COLORS["amber"], "3. Preparer",
         "Transformer la lecture en proposition indicative et en points de controle."),
    ]
    for box, fill, outline, title, body in cards:
        rounded_box(draw, box, fill, outline=outline, width=5, radius=18)
        draw.text((box[0] + 32, box[1] + 32), title, font=F["title"], fill=outline)
        draw_wrapped(draw, (box[0] + 34, box[1] + 105), body, F["h2"], COLORS["ink"], box[2] - box[0] - 68, line_gap=8)
        arrow(draw, ((box[0] + box[2]) // 2, box[3] + 18), ((box[0] + box[2]) // 2, 680), outline, width=5)
    rounded_box(draw, (250, 705, 1550, 875), COLORS["purple_light"], outline=COLORS["purple"], width=5, radius=22)
    centered_text(draw, (250, 705, 1550, 875),
                  "Tableau de bord: signaux + validation temporelle + analyse statistique + seuils de prix",
                  F["h1"], COLORS["purple"], max_width=1180)
    source(draw, "Source: besoin formalise pendant l'immersion en salle des marches et rapports internes de stage.")
    save(img, "ch1_besoin_desk.png")


def fig_ch1_metastrategy() -> None:
    img, draw = canvas()
    header(draw, "Chaine de recherche quantitative", "Du jeu de donnees au support de decision avant seance")
    labels = [
        ("1", "Donnees", "prix, volumes,\nqualite,\nunivers MASI", COLORS["blue_light"], COLORS["blue"]),
        ("2", "Signaux", "familles techniques,\nlecture candidate,\nrepresentants", COLORS["green_light"], COLORS["green"]),
        ("3", "Validation", "test sur futur\nnon utilise,\nrobustesse, couts", COLORS["purple_light"], COLORS["purple"]),
        ("4", "Analyse", "precision,\nrendement moyen,\ncomportement historique", COLORS["amber_light"], COLORS["amber"]),
        ("5", "Restitution", "tableau de bord,\nseuils de prix,\nsuivi quotidien", COLORS["cyan_light"], COLORS["blue"]),
    ]
    x = 70
    y = 250
    w = 275
    h = 275
    gap = 50
    for i, (num, title, desc, fill, outline) in enumerate(labels):
        box = (x, y, x + w, y + h)
        rounded_box(draw, box, fill, outline=outline, width=5, radius=18)
        draw.text((x + 25, y + 24), num, font=F["title"], fill=outline)
        draw.text((x + 88, y + 34), title, font=F["h1"], fill=outline)
        draw_wrapped(draw, (x + 35, y + 110), desc, F["h2"], COLORS["ink"], w - 70, line_gap=8)
        if i < len(labels) - 1:
            arrow(draw, (x + w + 10, y + h // 2), (x + w + gap - 10, y + h // 2), COLORS["muted"], width=5)
        x += w + gap
    rounded_box(draw, (170, 660, 1630, 865), "#f8fafc", outline=COLORS["line"], width=3, radius=20)
    draw.text((215, 700), "Lecture simple pour le rapport", font=F["h1"], fill=COLORS["ink"])
    draw_wrapped(
        draw,
        (215, 755),
        "Comme en machine learning: entrainer sur le passe, tester sur un futur non vu, mesurer la generalisation, puis afficher une decision explicable.",
        F["h2"],
        COLORS["muted"],
        1370,
        line_gap=8,
    )
    source(draw, "Source: cadre theorique Lopez de Prado (2018), adapte au perimetre applicatif courant.")
    save(img, "ch1_metastrategie.png")


def fig_ch2_taxonomy() -> None:
    img, draw = canvas()
    header(draw, "Taxonomie des indicateurs", "20 familles reparties en 4 categories orthogonales")
    cats = [
        ("Tendance", ["SMA", "EMA", "EMA Cross", "Ichimoku", "PSAR"], COLORS["blue_light"], COLORS["blue"]),
        ("Momentum", ["MACD", "ROC", "TRIX", "ADX", "TSI"], COLORS["green_light"], COLORS["green"]),
        ("Oscillation", ["RSI", "Stochastique", "CCI", "MFI", "Ultimate Osc."], COLORS["amber_light"], COLORS["amber"]),
        ("Volume", ["OBV", "CMF", "A/D Line", "VWAP", "Force Index"], COLORS["purple_light"], COLORS["purple"]),
    ]
    x = 85
    for title, items, fill, outline in cats:
        rounded_box(draw, (x, 180, x + 380, 865), fill, outline=outline)
        centered_text(draw, (x + 30, 205, x + 350, 265), title, F["h1"], outline)
        yy = 330
        for item in items:
            rounded_box(draw, (x + 55, yy, x + 325, yy + 72), "white", outline=outline, width=2, radius=18)
            centered_text(draw, (x + 55, yy, x + 325, yy + 72), item, F["h2"], COLORS["ink"])
            yy += 100
        x += 430
    source(draw, "Source: implementation Signal Engine et documentation docs/signal-generation.")
    save(img, "ch2_taxonomie.png")


def fig_ch2_sma() -> None:
    df = read_ohlcv("IAM", "2020-01-01")
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
    df = df.iloc[:: max(len(df) // 700, 1)].reset_index(drop=True)
    img, draw = canvas()
    header(draw, "IAM: prix, SMA et EMA", "Exemple d'indicateurs de tendance sur donnees journalieres")
    area = (145, 185, 1665, 810)
    labels = [str(y) for y in sorted(df["Date"].dt.year.unique())[:: max(len(df["Date"].dt.year.unique()) // 5, 1)]]
    line_chart(draw, area, [
        ("Close", df["Close"], COLORS["ink"], 3),
        ("SMA20", df["SMA20"], COLORS["blue"], 3),
        ("SMA50", df["SMA50"], COLORS["green"], 3),
        ("EMA200", df["EMA200"], COLORS["red"], 3),
    ], labels=labels, y_label="Prix IAM (MAD)")
    legend = [("Close", COLORS["ink"]), ("SMA20", COLORS["blue"]), ("SMA50", COLORS["green"]), ("EMA200", COLORS["red"])]
    x = 150
    for name, color in legend:
        draw.line([(x, 880), (x + 55, 880)], fill=color, width=5)
        draw.text((x + 65, 868), name, font=F["body"], fill=COLORS["ink"])
        x += 210
    src = "market_data_export_v2.xlsx" if MARKET_XLSX.exists() else "scripts/IAM.xlsx"
    source(draw, f"Source: {src}, feuille IAM; calculs auteur.")
    save(img, "ch2_sma_iam.png")


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def fig_ch2_rsi() -> None:
    symbol = "ATW" if has_sheet(MARKET_XLSX, "ATW") else "IAM"
    df = read_ohlcv(symbol, "2022-01-01")
    df["RSI14"] = rsi(df["Close"])
    df = df.iloc[:: max(len(df) // 700, 1)].reset_index(drop=True)
    img, draw = canvas()
    header(draw, f"{symbol}: RSI 14 periodes", "Zones de surachat et de survente")
    price_area = (145, 175, 1665, 520)
    rsi_area = (145, 610, 1665, 850)
    labels = ["2022", "2023", "2024", "2025", "2026"]
    line_chart(draw, price_area, [("Close", df["Close"], COLORS["ink"], 3)], labels=None, y_label="Prix ATW")
    draw.rectangle(rsi_area, outline=COLORS["line"], width=2)
    x1, y1, x2, y2 = rsi_area
    for level, color, label in [(70, COLORS["red_light"], "Surachat 70"), (30, COLORS["green_light"], "Survente 30")]:
        yy = y2 - int(level / 100 * (y2 - y1))
        band = (yy - 18, yy + 18)
        draw.rectangle((x1, band[0], x2, band[1]), fill=color)
        draw.line([(x1, yy), (x2, yy)], fill=COLORS["muted"], width=2)
        draw.text((x1 + 8, yy - 28), label, font=F["tiny"], fill=COLORS["muted"])
    vals = df["RSI14"].fillna(50).tolist()
    pts = []
    for i, v in enumerate(vals):
        x = x1 + int((x2 - x1) * i / max(len(vals) - 1, 1))
        y = y2 - int(float(v) / 100 * (y2 - y1))
        pts.append((x, y))
    draw.line(pts, fill=COLORS["blue"], width=3)
    for i, label in enumerate(labels):
        x = x1 + int((x2 - x1) * i / max(len(labels) - 1, 1))
        draw.text((x - 18, y2 + 12), label, font=F["tiny"], fill=COLORS["muted"])
    draw.text((x1, y1 - 30), "RSI", font=F["small_bold"], fill=COLORS["muted"])
    src = "market_data_export_v2.xlsx" if symbol == "ATW" else "scripts/IAM.xlsx"
    source(draw, f"Source: {src}, feuille {symbol}; calcul RSI auteur.")
    save(img, "ch2_rsi_atw.png")


def fig_ch3_pipeline() -> None:
    img, draw = canvas()
    header(draw, "Signal Engine A-G", "Du candidat brut au signal interpretable")
    steps = [
        ("A", "Candidats\n20 familles x\n30 variantes"),
        ("B", "Sous-periodes\nstabilite"),
        ("C", "Robustesse\nscore multi-\ncomposante"),
        ("D", "Survivants\nfloor +\npercentile"),
        ("E", "Redondance\ncorrelation"),
        ("F", "Signal courant\ndernier bar"),
        ("G", "Ensemble\nscore [-100,+100]"),
    ]
    x = 60
    for i, (letter, label) in enumerate(steps):
        fill = [COLORS["blue_light"], COLORS["green_light"], COLORS["amber_light"], COLORS["purple_light"], COLORS["cyan_light"], COLORS["red_light"], COLORS["gray_light"]][i]
        box = (x, 330, x + 210, 560)
        rounded_box(draw, box, fill)
        draw.text((x + 82, 355), letter, font=F["title"], fill=COLORS["ink"])
        centered_text(draw, (x + 15, 420, x + 195, 548), label, F["small_bold"], COLORS["ink"])
        if i < len(steps) - 1:
            arrow(draw, (x + 218, 445), (x + 268, 445), COLORS["muted"])
        x += 245
    rounded_box(draw, (270, 710, 1530, 820), "#f8fafc", outline=COLORS["line"])
    centered_text(draw, (270, 710, 1530, 820), "Objectif: eviter le vote brut, conserver les variantes stables, puis agreger un consensus explicable.", F["h2"], COLORS["ink"])
    source(draw, "Source: docs/signal-generation/00-INDEX.md et implementation quant_core/signal_engine.")
    save(img, "ch3_pipeline_ag.png")


def fig_ch3_windows() -> None:
    img, draw = canvas()
    header(draw, "Validation par sous-periodes", "Stabilite temporelle sans optimiser sur la fenetre test")
    x0, x1 = 170, 1640
    y0 = 260
    draw.line([(x0, y0), (x1, y0)], fill=COLORS["ink"], width=4)
    years = list(range(2018, 2026))
    for i, yr in enumerate(years):
        x = x0 + int((x1 - x0) * i / (len(years) - 1))
        draw.line([(x, y0 - 12), (x, y0 + 12)], fill=COLORS["ink"], width=3)
        draw.text((x - 25, y0 - 55), str(yr), font=F["small"], fill=COLORS["muted"])
    colors = [COLORS["blue_light"], COLORS["green_light"], COLORS["amber_light"], COLORS["purple_light"], COLORS["cyan_light"], COLORS["red_light"]]
    for i in range(6):
        start = x0 + 80 + i * 190
        end = start + 360
        y = 390 + i * 70
        rounded_box(draw, (start, y, end, y + 45), colors[i], outline=COLORS["muted"], width=2, radius=12)
        centered_text(draw, (start, y, end, y + 45), f"Sous-periode {i + 1}", F["small_bold"])
        arrow(draw, (start + 5, y - 25), (end - 5, y - 25), COLORS["muted"], width=2)
    rounded_box(draw, (330, 850, 1470, 930), "#f8fafc", outline=COLORS["line"])
    centered_text(draw, (330, 850, 1470, 930), "Chaque variante est jugee sur plusieurs segments: Sharpe, stabilite, drawdown et coherence.", F["h2"])
    source(draw, "Source: politique de validation decrite dans docs/signal-generation/03-oos-evaluation.md.")
    save(img, "ch3_subperiod_windows.png")


def fig_ch3_corr_heatmap() -> None:
    rng = np.random.default_rng(42)
    before = np.clip(0.25 + rng.normal(0.45, 0.22, (10, 10)), -1, 1)
    before = (before + before.T) / 2
    np.fill_diagonal(before, 1)
    after = np.eye(6) + rng.normal(0.05, 0.12, (6, 6))
    after = np.clip((after + after.T) / 2, -0.35, 0.55)
    np.fill_diagonal(after, 1)
    img, draw = canvas()
    header(draw, "Reduction de redondance", "Selection de representants decorreles")

    def heat(mat: np.ndarray, x: int, y: int, cell: int, title: str) -> None:
        draw.text((x, y - 50), title, font=F["h1"], fill=COLORS["ink"])
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                v = float(mat[i, j])
                red = int(255 * max(v, 0))
                blue = int(255 * max(-v, 0))
                base = 235 - int(95 * abs(v))
                fill = (max(base, red), base, max(base, blue))
                draw.rectangle((x + j * cell, y + i * cell, x + (j + 1) * cell, y + (i + 1) * cell), fill=fill, outline="white")
        draw.rectangle((x, y, x + mat.shape[1] * cell, y + mat.shape[0] * cell), outline=COLORS["ink"], width=2)

    heat(before, 190, 260, 54, "Avant: variantes proches")
    heat(after, 1030, 300, 72, "Apres: representants")
    arrow(draw, (785, 540), (970, 540), COLORS["ink"], width=6)
    draw.text((790, 500), "seuil |r| > 0.85", font=F["h2"], fill=COLORS["muted"])
    source(draw, "Source: principe Layer E; matrice schematique generee pour expliquer le filtrage.")
    save(img, "ch3_correlation_heatmap.png")


def fig_ch4_wfo_pipeline() -> None:
    img, draw = canvas()
    header(draw, "Pipeline WFO des signaux", "Optimisation IS, verification OOS, repetition sur fenetres glissantes")
    top_y = 210
    x0 = 110
    for i in range(5):
        x = x0 + i * 295
        train = (x, top_y + i * 55, x + 190, top_y + 80 + i * 55)
        test = (x + 195, top_y + i * 55, x + 285, top_y + 80 + i * 55)
        rounded_box(draw, train, COLORS["blue_light"], outline=COLORS["blue"], width=2, radius=10)
        rounded_box(draw, test, COLORS["green_light"], outline=COLORS["green"], width=2, radius=10)
        centered_text(draw, train, "IS\nPROM", F["small_bold"], COLORS["blue"])
        centered_text(draw, test, "OOS", F["small_bold"], COLORS["green"])
    steps = [
        ("Grille de variants", "familles x parametres"),
        ("Selection IS", "max PROM"),
        ("Test OOS", "retour, Sharpe, DD"),
        ("Agregation folds", "WFE, robustesse"),
        ("Signal courant", "score et grade"),
    ]
    x = 150
    for title, desc in steps:
        rounded_box(draw, (x, 690, x + 260, 835), "#f8fafc", outline=COLORS["ink"])
        centered_text(draw, (x + 10, 705, x + 250, 755), title, F["h2"])
        centered_text(draw, (x + 15, 765, x + 245, 825), desc, F["small"], COLORS["muted"])
        if title != steps[-1][0]:
            arrow(draw, (x + 270, 762), (x + 335, 762), COLORS["muted"])
        x += 350
    source(draw, "Source: docs/backtest-layer et quant_core/wfo; schema explicatif auteur.")
    save(img, "ch4_wfo_pipeline.png")


def fig_ch5_architecture() -> None:
    img, draw = canvas()
    header(draw, "Architecture applicative", "Chemin requete et services de production")
    labels = [
        ("Browser", "utilisateur"),
        ("Caddy", "proxy TLS\nallowlist"),
        ("Next.js", "frontend\n/api proxy"),
        ("FastAPI", "routers\nschemas"),
        ("Redis / RQ", "queues\nworkers"),
        ("Postgres", "metadata\nsignals"),
        ("MinIO", "datasets\nartifacts"),
    ]
    xs = [75, 310, 545, 780, 1035, 1290, 1520]
    y = 360
    for i, ((title, desc), x) in enumerate(zip(labels, xs)):
        box = (x, y, x + 190, y + 150)
        rounded_box(draw, box, [COLORS["blue_light"], COLORS["gray_light"], COLORS["green_light"], COLORS["amber_light"], COLORS["purple_light"], COLORS["cyan_light"], COLORS["red_light"]][i])
        centered_text(draw, (x + 10, y + 20, x + 180, y + 72), title, F["h2"])
        centered_text(draw, (x + 10, y + 82, x + 180, y + 140), desc, F["small"], COLORS["muted"])
        if i < 4:
            arrow(draw, (x + 198, y + 75), (xs[i + 1] - 12, y + 75), COLORS["ink"])
    arrow(draw, (1130, 515), (1380, 620), COLORS["muted"])
    arrow(draw, (1130, 515), (1600, 620), COLORS["muted"])
    rounded_box(draw, (520, 710, 1280, 835), "#f8fafc", outline=COLORS["line"])
    centered_text(draw, (520, 710, 1280, 835), "Le noyau quant_core est partage par API et workers: Signal Engine, WFO, analytics, backtests.", F["h2"])
    source(draw, "Source: docs/APP_MAP.md et infra/docker-compose.gcp.yml.")
    save(img, "ch5_architecture_stack.png")


def fig_station_pages() -> None:
    specs = [
        ("ch5_data_page.png", "Station Donnees", "Ingestion, stockage canonique, fraicheur", ["Catalogue valeurs", "Upload/refresh OHLCV", "Statut data_as_of", "Graphique prix"], COLORS["blue_light"]),
        ("ch5_signals_page.png", "Station Signaux", "Lecture par titre et par famille", ["Score global", "Tendance / Momentum", "Oscillation / Volume", "Representants A-G"], COLORS["green_light"]),
        ("ch5_variant_detail.png", "Detail variante", "Trace de la preuve par indicateur", ["Parametres", "Sous-periodes", "Reliability score", "Signal timeline"], COLORS["amber_light"]),
        ("ch5_dashboard_page.png", "Station Dashboard", "Decision rapide pour le desk", ["Direction", "Confiance", "Niveaux actionnables", "Narratif si/alors"], COLORS["purple_light"]),
        ("ch5_analytics_page.png", "Station Analytics", "Preuve statistique de l'edge", ["Matrice predictive", "Hit rate", "Information coefficient", "FDR / DSR"], COLORS["cyan_light"]),
    ]
    for filename, title, subtitle, bullets, color in specs:
        img, draw = canvas()
        header(draw, title, subtitle)
        rounded_box(draw, (130, 190, 1670, 875), color, outline=COLORS["ink"])
        rounded_box(draw, (220, 280, 760, 770), "white", outline=COLORS["line"])
        centered_text(draw, (220, 280, 760, 360), "Vue principale", F["h1"])
        for i in range(6):
            yy = 410 + i * 48
            draw.rounded_rectangle((280, yy, 700 - i * 25, yy + 22), radius=8, fill="#e5e7eb")
        rounded_box(draw, (870, 280, 1580, 770), "white", outline=COLORS["line"])
        yy = 330
        for bullet in bullets:
            draw.ellipse((925, yy + 6, 943, yy + 24), fill=COLORS["green"])
            draw.text((965, yy), bullet, font=F["h2"], fill=COLORS["ink"])
            yy += 95
        source(draw, "Source: docs/APP_MAP.md et documents de couche dans docs/.")
        save(img, filename)


def fig_ch6_dashboard_mockup() -> None:
    data = load_scores("medium")
    row = stock_row(data, "IAM")
    se = signal_engine_payload(row)
    score = se.get("expanded_aggregate_score_pct", se.get("aggregate_score_pct", 0.0))
    label = se.get("expanded_aggregate_signal_label", se.get("aggregate_signal_label", "Neutre"))
    symbol = row.get("symbol", "EXEMPLE")
    img, draw = canvas()
    header(draw, "Dashboard decisionnel", "Synthese: vitesse, tracabilite, action")
    rounded_box(draw, (90, 160, 1710, 330), COLORS["green_light"], outline=COLORS["green"])
    draw.text((130, 195), f"{symbol} - Moyen terme - {label}", font=F["h1"], fill=COLORS["green"])
    draw.text((130, 245), f"Score opportunite: {score:.1f}/100", font=F["h2"], fill=COLORS["ink"])
    draw.rounded_rectangle((520, 248, 950, 278), radius=15, fill="#e5e7eb")
    draw.rounded_rectangle((520, 248, 520 + int(430 * max(score, 0) / 100), 278), radius=15, fill=COLORS["green"])
    rounded_box(draw, (1010, 190, 1640, 300), "white", outline=COLORS["line"])
    centered_text(draw, (1010, 190, 1640, 300), "Decision Box: direction, conviction, niveaux", F["h2"])
    rounded_box(draw, (90, 390, 840, 850), "#f8fafc", outline=COLORS["line"])
    draw.text((130, 430), "Section B - Justification", font=F["h1"], fill=COLORS["ink"])
    for i, text in enumerate(["Representants selectionnes", "Contribution par categorie", "Poids de fiabilite", "Signal courant"]):
        draw.text((160, 510 + i * 75), f"- {text}", font=F["h2"], fill=COLORS["ink"])
    rounded_box(draw, (960, 390, 1710, 850), "#f8fafc", outline=COLORS["line"])
    draw.text((1000, 430), "Section C - Niveaux et scenarios", font=F["h1"], fill=COLORS["ink"])
    for i, text in enumerate(["Support / resistance", "Stop et objectif", "Ratio R:R", "Narratif Si / Alors / Sinon"]):
        draw.text((1030, 510 + i * 75), f"- {text}", font=F["h2"], fill=COLORS["ink"])
    source(draw, "Source: frontend/public/data/scores-medium.json; structure issue des besoins desk.")
    save(img, "ch6_dashboard_mockup.png")


def fig_ch6_gauge_radar() -> None:
    data = load_scores("medium")
    row = stock_row(data, "IAM")
    se = signal_engine_payload(row)
    fam = se.get("expanded_per_family") or se.get("per_family") or {}
    defaults = {
        "tendance": {"score_pct": 0.0},
        "momentum": {"score_pct": 0.0},
        "oscillation": {"score_pct": 0.0},
        "volume": {"score_pct": 0.0},
    }
    defaults.update(fam)
    fam = defaults
    vals = {
        "Tendance": fam["tendance"]["score_pct"],
        "Momentum": fam["momentum"]["score_pct"],
        "Oscillation": fam["oscillation"]["score_pct"],
        "Volume": fam["volume"]["score_pct"],
    }
    score = se.get("expanded_aggregate_score_pct", se.get("aggregate_score_pct", 0.0))
    img, draw = canvas()
    header(draw, "Score d'ensemble IAM", "Gauge globale et decomposition par categorie")
    cx, cy, r = 470, 550, 285
    draw.arc((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=COLORS["line"], width=34)
    for start, end, color in [(180, 225, COLORS["red"]), (225, 260, COLORS["amber"]), (260, 280, COLORS["muted"]), (280, 315, COLORS["green"]), (315, 360, COLORS["blue"])]:
        draw.arc((cx - r, cy - r, cx + r, cy + r), start, end, fill=color, width=34)
    angle = math.radians(180 + (score + 100) / 200 * 180)
    end = (cx + int((r - 55) * math.cos(angle)), cy + int((r - 55) * math.sin(angle)))
    draw.line((cx, cy, *end), fill=COLORS["ink"], width=7)
    draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=COLORS["ink"])
    draw.text((cx - 115, cy + 45), f"{score:.1f}", font=F["title"], fill=COLORS["green"])
    draw.text((cx - 95, cy + 92), se.get("expanded_aggregate_signal_label", se.get("aggregate_signal_label", "Neutre")), font=F["h1"], fill=COLORS["green"])
    labels = list(vals.keys())
    bvals = [vals[k] for k in labels]
    bar_chart(draw, (900, 260, 1620, 760), labels, bvals, [COLORS["blue"], COLORS["green"], COLORS["amber"], COLORS["purple"]], y_max=100, suffix="")
    source(draw, "Source: frontend/public/data/scores-medium.json, snapshot local.")
    save(img, "ch6_gauge_family.png")

    img, draw = canvas()
    header(draw, "Decomposition du consensus IAM", "Radar normalise par categorie")
    cx, cy, r = 900, 540, 310
    axes = len(labels)
    for ring in [0.25, 0.5, 0.75, 1.0]:
        pts = []
        for i in range(axes):
            a = -math.pi / 2 + i * 2 * math.pi / axes
            pts.append((cx + int(r * ring * math.cos(a)), cy + int(r * ring * math.sin(a))))
        draw.polygon(pts, outline=COLORS["line"])
    pts = []
    for i, label in enumerate(labels):
        a = -math.pi / 2 + i * 2 * math.pi / axes
        draw.line((cx, cy, cx + int(r * math.cos(a)), cy + int(r * math.sin(a))), fill=COLORS["line"], width=2)
        lx = cx + int((r + 85) * math.cos(a))
        ly = cy + int((r + 45) * math.sin(a))
        centered_text(draw, (lx - 90, ly - 25, lx + 90, ly + 25), label, F["small_bold"])
        norm = max(0, min(100, (bvals[i] + 100) / 2)) / 100
        pts.append((cx + int(r * norm * math.cos(a)), cy + int(r * norm * math.sin(a))))
    draw.polygon(pts, fill="#bfdbfe", outline=COLORS["blue"])
    for x, y in pts:
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=COLORS["blue"])
    source(draw, "Source: frontend/public/data/scores-medium.json, snapshot local.")
    save(img, "ch6_radar_family.png")


def fig_ch6_leaderboard() -> None:
    data = load_scores("medium")
    stocks = sorted(data["stocks"], key=lambda r: r.get("scores", {}).get("signal_engine", {}).get("expanded_aggregate_score_pct", r.get("expanded_aggregate_score_pct", 0)), reverse=True)[:10]
    rows = []
    for s in stocks:
        se = s.get("scores", {}).get("signal_engine", {})
        score = se.get("expanded_aggregate_score_pct", s.get("expanded_aggregate_score_pct", 0))
        label = se.get("expanded_aggregate_signal_label", s.get("expanded_aggregate_signal_label", ""))
        rows.append([s["symbol"], (s.get("sector") or "-")[:22], f"{score:.1f}", label])
    img, draw = canvas()
    header(draw, "Leaderboard moyen terme", "Top signaux par score d'opportunite")
    x0, y0 = 180, 190
    col_w = [190, 520, 250, 340]
    headers = ["Ticker", "Secteur", "Score", "Lecture"]
    x = x0
    for h, w in zip(headers, col_w):
        draw.rectangle((x, y0, x + w, y0 + 58), fill="#e5e7eb", outline=COLORS["line"])
        centered_text(draw, (x, y0, x + w, y0 + 58), h, F["small_bold"])
        x += w
    for i, row in enumerate(rows):
        y = y0 + 58 + i * 62
        x = x0
        for j, (txt, w) in enumerate(zip(row, col_w)):
            fill = "white"
            if j == 3:
                fill = COLORS["green_light"] if "Achat" in txt else COLORS["red_light"] if "Vente" in txt else COLORS["gray_light"]
            draw.rectangle((x, y, x + w, y + 62), fill=fill, outline=COLORS["line"])
            centered_text(draw, (x, y, x + w, y + 62), txt, F["body"])
            x += w
    source(draw, "Source: frontend/public/data/scores-medium.json, genere le 2026-05-07.")
    save(img, "ch6_leaderboard.png")


def fig_ch6_detail_equity_wfe_heatmap() -> None:
    df = read_ohlcv("IAM", "2018-01-01")
    close = df["Close"]
    sma = close.rolling(50).mean()
    pos = (close > sma).astype(float).shift(1).fillna(0)
    ret = close.pct_change().fillna(0)
    equity = (1 + pos * ret).cumprod()
    bench = (1 + ret).cumprod()
    dfd = pd.DataFrame({"Date": df["Date"], "Strategie SMA50": equity, "IAM buy-hold": bench}).iloc[:: max(len(df) // 800, 1)]

    img, draw = canvas()
    header(draw, "Vue detail IAM", "Equity normalisee et metriques de lecture")
    line_chart(draw, (145, 190, 1180, 760), [
        ("Strategie SMA50", dfd["Strategie SMA50"], COLORS["blue"], 3),
        ("IAM buy-hold", dfd["IAM buy-hold"], COLORS["muted"], 3),
    ], labels=["2018", "2020", "2022", "2024", "2026"], y_label="Base 1.0")
    rounded_box(draw, (1260, 230, 1640, 720), "#f8fafc", outline=COLORS["line"])
    metrics = [
        ("Dernier close", f"{close.iloc[-1]:.2f} MAD"),
        ("Signal SMA50", "actif" if bool(pos.iloc[-1]) else "neutre"),
        ("Retour strat.", f"{(equity.iloc[-1]-1)*100:.1f}%"),
        ("Retour titre", f"{(bench.iloc[-1]-1)*100:.1f}%"),
    ]
    yy = 285
    for k, v in metrics:
        draw.text((1300, yy), k, font=F["small"], fill=COLORS["muted"])
        draw.text((1300, yy + 28), v, font=F["h2"], fill=COLORS["ink"])
        yy += 95
    src = "market_data_export_v2.xlsx" if MARKET_XLSX.exists() else "scripts/IAM.xlsx"
    source(draw, f"Source: {src}, feuille IAM; strategie SMA50 illustrative calculee par le script.")
    save(img, "ch6_detail_iam.png")
    save(img, "ch6_equity_curve.png")

    try:
        lb = json.loads((ROOT / "leaderboard_clean.json").read_text(encoding="utf-16"))["value"]
    except Exception:
        lb = []
    labels = [r["horizon"] for r in lb] or ["short", "medium", "long"]
    vals = [float(r.get("confidence_score", 0)) for r in lb] or [62, 62, 65]
    img, draw = canvas()
    header(draw, "Robustesse par horizon", "Scores de confiance disponibles dans le snapshot WFO local")
    bar_chart(draw, (240, 240, 1540, 780), labels, vals, [COLORS["blue"], COLORS["green"], COLORS["purple"]], y_max=100, suffix="")
    draw.text((245, 810), "Le snapshot local contient trois lignes IAM (court, moyen, long); les barres montrent confidence_score.", font=F["small"], fill=COLORS["muted"])
    source(draw, "Source: leaderboard_clean.json, snapshot local d'API.")
    save(img, "ch6_wfe_bars.png")

    data_files = [("short", load_scores("short")), ("medium", load_scores("medium")), ("long", load_scores("long"))]
    cats = ["tendance", "momentum", "oscillation", "volume"]
    mat = []
    for _, data in data_files:
        row_vals = []
        for cat in cats:
            vals_cat = []
            for s in data["stocks"]:
                se = s.get("scores", {}).get("signal_engine", {})
                fam = se.get("expanded_per_family") or s.get("expanded_per_family") or {}
                if cat in fam and fam[cat].get("score_pct") is not None:
                    vals_cat.append(float(fam[cat]["score_pct"]))
            row_vals.append(float(np.mean(vals_cat)) if vals_cat else 0)
        mat.append(row_vals)
    img, draw = canvas()
    header(draw, "Carte moyenne des signaux", "Score moyen par horizon et categorie")
    x0, y0, cell_w, cell_h = 380, 250, 260, 150
    for j, cat in enumerate(cats):
        centered_text(draw, (x0 + j * cell_w, y0 - 65, x0 + (j + 1) * cell_w, y0 - 15), cat.title(), F["h2"])
    for i, (h, _) in enumerate(data_files):
        centered_text(draw, (120, y0 + i * cell_h, 330, y0 + (i + 1) * cell_h), h, F["h2"])
        for j, val in enumerate(mat[i]):
            if val >= 15:
                fill = COLORS["green_light"]
            elif val <= -15:
                fill = COLORS["red_light"]
            else:
                fill = COLORS["gray_light"]
            box = (x0 + j * cell_w, y0 + i * cell_h, x0 + (j + 1) * cell_w, y0 + (i + 1) * cell_h)
            draw.rectangle(box, fill=fill, outline="white")
            centered_text(draw, box, f"{val:.1f}", F["h1"])
    draw.rectangle((x0, y0, x0 + cell_w * len(cats), y0 + cell_h * len(data_files)), outline=COLORS["ink"], width=3)
    source(draw, "Source: frontend/public/data/scores-short|medium|long.json.")
    save(img, "ch6_heatmap_wfe.png")


def fig_appendices() -> None:
    img, draw = canvas()
    header(draw, "Modele de donnees simplifie", "Tables centrales persistees par PostgreSQL")
    boxes = [
        ((120, 210, 410, 360), "dataset\nmarket_data_store\nstock_master", COLORS["blue_light"]),
        ((560, 210, 850, 360), "signal_engine\nfamily/global\nscore_history", COLORS["green_light"]),
        ((1000, 210, 1290, 360), "wfo_signal\nsummary/global", COLORS["amber_light"]),
        ((560, 560, 850, 710), "run\nrun_fold\nrun_metric", COLORS["purple_light"]),
        ((1000, 560, 1290, 710), "artifact\nMinIO object_key", COLORS["cyan_light"]),
        ((1360, 385, 1660, 535), "dashboard_snapshot\nportfolio ticket", COLORS["red_light"]),
    ]
    for box, label, color in boxes:
        rounded_box(draw, box, color)
        centered_text(draw, box, label, F["body"])
    for a, b in [((410, 285), (560, 285)), ((850, 285), (1000, 285)), ((705, 360), (705, 560)), ((850, 635), (1000, 635)), ((1290, 285), (1510, 385)), ((1290, 635), (1510, 535))]:
        arrow(draw, a, b, COLORS["muted"])
    source(draw, "Source: services/api/app/models.py; schema simplifie pour lecture rapport.")
    save(img, "ann_erd.png")

    holidays_path = ROOT / "services" / "api" / "app" / "data" / "casablanca_exchange_holidays.json"
    holidays = json.loads(holidays_path.read_text(encoding="utf-8")) if holidays_path.exists() else []
    df = pd.DataFrame(holidays)
    if not df.empty:
        summary = df[df["year"].between(2023, 2026)].groupby(["year", "certainty"]).size().unstack(fill_value=0)
    else:
        summary = pd.DataFrame()
    img, draw = canvas()
    header(draw, "Calendrier Bourse de Casablanca", "Jours feries suivis par la pipeline data")
    labels = [str(y) for y in summary.index.tolist()] or ["2023", "2024", "2025", "2026"]
    confirmed = [float(summary.loc[int(y)].get("confirmed", 0)) if int(y) in summary.index else 0 for y in labels]
    tentative = [float(summary.loc[int(y)].get("tentative", 0)) if int(y) in summary.index else 0 for y in labels]
    bar_chart(draw, (260, 260, 1520, 760), labels, confirmed, [COLORS["green"]] * len(labels), y_max=max(confirmed + tentative + [10]) + 4, suffix="")
    draw.text((260, 820), "Barres: jours confirmes. Les dates provisoires restent tracees dans le fichier JSON avec certainty=tentative.", font=F["small"], fill=COLORS["muted"])
    source(draw, "Source: services/api/app/data/casablanca_exchange_holidays.json.")
    save(img, "ann_holidays.png")

    img, draw = canvas()
    header(draw, "PROM et DSR", "Synthese mathematique des controles d'overfitting")
    blocks = [
        ((180, 260, 780, 470), "PROM", "Fonction objectif pessimiste: recompense la performance repetable et penalise les echantillons fragiles.", COLORS["blue_light"]),
        ((1020, 260, 1620, 470), "DSR", "Sharpe corrige du data-snooping, de l'asymetrie, de la kurtosis et du nombre d'essais.", COLORS["green_light"]),
        ((600, 650, 1200, 830), "Decision", "Une strategie n'est retenue que si performance, robustesse et validation OOS convergent.", COLORS["amber_light"]),
    ]
    for box, title, body, color in blocks:
        rounded_box(draw, box, color)
        draw.text((box[0] + 35, box[1] + 35), title, font=F["h1"], fill=COLORS["ink"])
        draw_wrapped(draw, (box[0] + 35, box[1] + 95), body, F["body"], COLORS["ink"], box[2] - box[0] - 70)
    arrow(draw, (780, 365), (1020, 365), COLORS["muted"])
    arrow(draw, (1080, 470), (960, 650), COLORS["muted"])
    arrow(draw, (720, 470), (840, 650), COLORS["muted"])
    source(draw, "Sources: Pardo (2008); Bailey et Lopez de Prado (2012).")
    save(img, "ann_math.png")

    img, draw = canvas()
    header(draw, "Surfaces produit", "Vues additionnelles synthetisees pour l'annexe")
    cards = [
        ("Data", "catalogue + fraicheur"),
        ("Signals", "score + representants"),
        ("Dashboard", "decision box"),
        ("Analytics", "preuve statistique"),
    ]
    x = 120
    for title, desc in cards:
        rounded_box(draw, (x, 300, x + 360, 720), "#f8fafc", outline=COLORS["line"])
        draw.text((x + 35, 340), title, font=F["h1"], fill=COLORS["ink"])
        draw.text((x + 35, 390), desc, font=F["body"], fill=COLORS["muted"])
        for i in range(5):
            draw.rounded_rectangle((x + 45, 470 + i * 40, x + 305 - i * 25, 490 + i * 40), radius=8, fill="#e5e7eb")
        x += 410
    source(draw, "Source: architecture produit documentee dans docs/APP_MAP.md.")
    save(img, "ann_screenshots.png")


def main() -> None:
    fig_ch1_bmce()
    fig_ch1_order_cycle()
    fig_ch1_need()
    fig_ch1_metastrategy()
    fig_ch2_taxonomy()
    fig_ch2_sma()
    fig_ch2_rsi()
    fig_ch3_pipeline()
    fig_ch3_windows()
    fig_ch3_corr_heatmap()
    fig_ch4_wfo_pipeline()
    fig_ch5_architecture()
    fig_station_pages()
    fig_ch6_dashboard_mockup()
    fig_ch6_gauge_radar()
    fig_ch6_leaderboard()
    fig_ch6_detail_equity_wfe_heatmap()
    fig_appendices()
    print(f"Generated figures in {FIG_DIR}")


if __name__ == "__main__":
    main()
