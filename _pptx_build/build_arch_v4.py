"""Architecture slide rebuilt with v2's actual visual style (Khadija theme).

Palette + fonts extracted from BMCE_Final_Khadija_v2.pptx slide 22.
Architecture content reflects ONLY components that exist in the repo:
  - infra/docker-compose.prod.yml services
  - services/api/app/routers/*.py
  - services/worker/* + tasks
  - frontend/ Next.js stack
"""
from __future__ import annotations
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from lxml import etree

# ── Khadija v2 design tokens (extracted from slide 22 XML) ─────────────────
NAVY        = RGBColor(0x0B, 0x25, 0x45)   # primary navy
NAVY_DARK   = RGBColor(0x0F, 0x17, 0x2A)   # near-black slate
NAVY_2      = RGBColor(0x20, 0x38, 0x64)
BLUE        = RGBColor(0x0B, 0x5D, 0x8E)
BMCE_RED    = RGBColor(0xC8, 0x10, 0x2E)   # BMCE accent red
BMCE_GOLD   = RGBColor(0xC9, 0xA2, 0x27)   # BMCE accent gold
SLATE_500   = RGBColor(0x47, 0x55, 0x69)
GRAY_600    = RGBColor(0x59, 0x59, 0x59)
LIGHT_BG    = RGBColor(0xF4, 0xF6, 0xF8)
SLATE_200   = RGBColor(0xE2, 0xE8, 0xF0)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
BLACK       = RGBColor(0x00, 0x00, 0x00)

FONT_TITLE = "Garamond"
FONT_BODY  = "Century Gothic"

SLIDE_W = 13.333   # widescreen 16:9 default
SLIDE_H = 7.5

DST = Path(r"C:/Users/taha/Downloads/BMCE_Khadija_ARCH_v4.pptx")


def _shape(slide, kind, x, y, w, h, *, fill=None, line=None, line_w=0.75):
    sh = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is not None:
        sh.fill.solid(); sh.fill.fore_color.rgb = fill
    else:
        sh.fill.background()
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(line_w)
    # strip default shadow
    sppr = sh._element.spPr
    for el in sppr.findall(qn("a:effectLst")):
        sppr.remove(el)
    sppr.append(etree.fromstring(
        '<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
    ))
    return sh


def _text(slide, x, y, w, h, lines, *, font_size=10, bold=False,
          color=NAVY_DARK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
          font=FONT_BODY):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(18000); tf.margin_right = Emu(18000)
    tf.margin_top = Emu(9000);  tf.margin_bottom = Emu(9000)
    tf.vertical_anchor = anchor
    tf.clear()
    if isinstance(lines, str):
        lines = [(lines, bold, font_size, color)]
    elif lines and not isinstance(lines[0], tuple):
        lines = [(s, bold, font_size, color) for s in lines]
    for i, item in enumerate(lines):
        if len(item) == 4:
            txt, b, sz, col = item
        elif len(item) == 3:
            txt, b, sz = item; col = color
        else:
            txt, b = item; sz = font_size; col = color
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run(); r.text = txt
        r.font.name = font
        r.font.size = Pt(sz)
        r.font.bold = b
        r.font.color.rgb = col
    return tb


def _label_in(shape, text, *, font_size=11, bold=True, color=WHITE,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_BODY):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(18000); tf.margin_right = Emu(18000)
    tf.margin_top = Emu(9000);  tf.margin_bottom = Emu(9000)
    tf.vertical_anchor = anchor
    tf.clear()
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text
    r.font.name = font; r.font.size = Pt(font_size)
    r.font.bold = bold; r.font.color.rgb = color


def _clear_anim(slide):
    cSld = slide._element
    for el in cSld.findall(qn("p:timing")): cSld.remove(el)
    for el in cSld.findall(qn("p:transition")): cSld.remove(el)
    cSld.append(etree.fromstring(
        '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"'
        ' p14:dur="0"/>'
    ))


def _bg(slide):
    bg = _shape(slide, MSO_SHAPE.RECTANGLE, -0.1, -0.1,
                SLIDE_W + 0.2, SLIDE_H + 0.2, fill=WHITE)
    spTree = bg._element.getparent()
    spTree.remove(bg._element); spTree.insert(2, bg._element)
    return bg


def _topband(slide, *, title, subtitle):
    # Top strip with title (Garamond) + thin gold rule
    _shape(slide, MSO_SHAPE.RECTANGLE, 0.0, 0.0, SLIDE_W, 0.05, fill=NAVY)
    _text(slide, 0.45, 0.22, SLIDE_W - 0.90, 0.60, title,
          font_size=26, bold=True, color=NAVY,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE,
          font=FONT_TITLE)
    _text(slide, 0.45, 0.78, SLIDE_W - 0.90, 0.32, subtitle,
          font_size=12, bold=False, color=SLATE_500,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
          font=FONT_BODY)
    # gold rule
    _shape(slide, MSO_SHAPE.RECTANGLE, 0.45, 1.18, 0.80, 0.04, fill=BMCE_GOLD)


def _footer(slide, page_num, total=29):
    # Footer strip with name + page
    _shape(slide, MSO_SHAPE.RECTANGLE, 0.0, SLIDE_H - 0.30, SLIDE_W, 0.30,
           fill=NAVY)
    _text(slide, 0.45, SLIDE_H - 0.30, SLIDE_W - 0.90, 0.30,
          "DAZINE Ahmed Taha  ·  EMI · GMIS  ·  2025 / 2026",
          font_size=9, bold=True, color=WHITE,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, SLIDE_W - 1.20, SLIDE_H - 0.30, 0.75, 0.30,
          f"{page_num} / {total}", font_size=9, bold=True, color=WHITE,
          align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)


def _chrome(slide, page_num, title, subtitle):
    _clear_anim(slide)
    _bg(slide)
    _topband(slide, title=title, subtitle=subtitle)
    _footer(slide, page_num)


def _new_blank(prs):
    blank = None
    for layout in prs.slide_layouts:
        if len(layout.placeholders) == 0:
            blank = layout; break
    return prs.slides.add_slide(blank or prs.slide_layouts[-1])


# ────────────────────────────────────────────────────────────────────────────
# Architecture slide
# ────────────────────────────────────────────────────────────────────────────
def build_architecture(prs, page_num=23):
    s = _new_blank(prs)
    _chrome(s, page_num=page_num,
            title="Architecture",
            subtitle="Stack micro-services déployée sur GCP — composants réels et flux de données")

    # ── Helpers for this slide ──
    def box(x, y, w, h, *, title, sub=None, fill=WHITE, line=NAVY,
            title_color=NAVY, sub_color=GRAY_600, title_pt=12, sub_pt=9,
            title_bold=True, header_strip=False, header_fill=NAVY):
        b = _shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h,
                   fill=fill, line=line, line_w=1.0)
        if header_strip:
            _shape(s, MSO_SHAPE.RECTANGLE, x, y, w, 0.30, fill=header_fill)
            _text(s, x, y, w, 0.30, title, font_size=title_pt, bold=title_bold,
                  color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
                  font=FONT_BODY)
            if sub:
                _text(s, x + 0.05, y + 0.34, w - 0.10, h - 0.36, sub,
                      font_size=sub_pt, color=sub_color,
                      align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP, font=FONT_BODY)
        else:
            _text(s, x + 0.05, y + 0.06, w - 0.10, 0.30, title,
                  font_size=title_pt, bold=title_bold, color=title_color,
                  align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, font=FONT_BODY)
            if sub:
                _text(s, x + 0.05, y + 0.36, w - 0.10, h - 0.42, sub,
                      font_size=sub_pt, color=sub_color,
                      align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP, font=FONT_BODY)
        return b

    def arrow_down(x, y, w=0.20, h=0.30, *, fill=NAVY_2):
        return _shape(s, MSO_SHAPE.DOWN_ARROW, x, y, w, h, fill=fill)

    def arrow_right(x, y, w=0.30, h=0.20, *, fill=NAVY_2):
        return _shape(s, MSO_SHAPE.RIGHT_ARROW, x, y, w, h, fill=fill)

    def vline(x, y, h, *, fill=SLATE_200, w=0.04):
        return _shape(s, MSO_SHAPE.RECTANGLE, x, y, w, h, fill=fill)

    def hline(x, y, w, *, fill=SLATE_200, h=0.04):
        return _shape(s, MSO_SHAPE.RECTANGLE, x, y, w, h, fill=fill)

    # ── Lane labels on left (5 layers) ──
    def lane(y, h, text, color):
        lab = _shape(s, MSO_SHAPE.RECTANGLE, 0.45, y, 0.85, h, fill=color)
        _label_in(lab, text, font_size=10, bold=True, color=WHITE)

    # ── Layout grid ──
    LX = 1.45                  # diagram left
    RX = SLIDE_W - 0.45        # diagram right
    DW = RX - LX               # diagram width

    # T1 — CLIENT band (User → Caddy → Frontend)
    y1 = 1.35
    lane(y1, 0.55, "CLIENT", NAVY)
    u_w, c_w, f_w = 1.80, 1.70, 3.30
    gap = 0.45
    t1_total = u_w + c_w + f_w + 2*gap
    u_x = LX + (DW - t1_total) / 2.0
    c_x = u_x + u_w + gap
    f_x = c_x + c_w + gap
    box(u_x, y1, u_w, 0.55,
        title="Utilisateur",
        sub="Trader · Desk Actions",
        title_pt=11, sub_pt=8)
    arrow_right(u_x + u_w + 0.06, y1 + 0.18, gap - 0.12, 0.18, fill=NAVY_2)
    box(c_x, y1, c_w, 0.55,
        title="Caddy",
        sub="edge_proxy · TLS · HSTS",
        title_pt=11, sub_pt=8)
    arrow_right(c_x + c_w + 0.06, y1 + 0.18, gap - 0.12, 0.18, fill=NAVY_2)
    box(f_x, y1, f_w, 0.55,
        title="quant_frontend  ·  Next.js 14",
        sub="React · TypeScript · NextAuth · Radix UI · lightweight-charts",
        title_pt=11, sub_pt=8, line=BLUE)

    # Arrow Frontend ↓ API
    arrow_down(f_x + f_w/2 - 0.10, y1 + 0.62, 0.20, 0.30, fill=NAVY)
    _text(s, f_x + f_w/2 + 0.18, y1 + 0.66, 1.80, 0.24,
          "REST + JSON", font_size=8, bold=True, color=SLATE_500)

    # T2 — API band
    y2 = y1 + 1.05
    lane(y2, 0.65, "API", NAVY)
    api_w = 7.50
    api_x = LX + (DW - api_w) / 2.0
    box(api_x, y2, api_w, 0.65,
        title="quant_api  ·  FastAPI + Pydantic + OpenAPI",
        sub="24 routeurs : runs · datasets · signals · wfo_signals · strategy · leaderboard · results · market_data · analytics · ops · …",
        title_pt=12, sub_pt=8, line=NAVY)

    # Arrow API ↓ Redis
    arrow_down(api_x + api_w/2 - 0.10, y2 + 0.72, 0.20, 0.30, fill=NAVY)
    _text(s, api_x + api_w/2 + 0.18, y2 + 0.76, 1.60, 0.24,
          "enqueue job (RQ)", font_size=8, bold=True, color=SLATE_500)

    # T3 — ASYNC band: Redis + 5 workers
    y3 = y2 + 1.15
    lane(y3, 1.05, "ASYNC", BLUE)
    r_w = 2.20
    w_total = 7.50
    r_x = api_x
    w_x = api_x + r_w + 0.30
    box(r_x, y3, r_w, 1.05,
        title="quant_redis  ·  RQ",
        sub="3 files :\nruns · defaults_discovery · wfo_signals",
        title_pt=11, sub_pt=9, line=BLUE)
    arrow_right(r_x + r_w + 0.04, y3 + 0.45, 0.22, 0.18, fill=BLUE)
    # Worker group container
    box(w_x, y3, w_total - r_w - 0.30, 1.05,
        title="Workers  ·  Python · Numba JIT · noyau quant_core",
        title_pt=11, sub_pt=9, line=BLUE)
    # 5 worker chips inside
    chips = ["quant_worker", "_defaults", "_signal_engine",
             "_score_history", "_wfo"]
    chip_y = y3 + 0.42
    chip_h = 0.42
    chip_gap = 0.10
    inner_x = w_x + 0.15
    inner_w = (w_total - r_w - 0.30) - 0.30
    chip_w = (inner_w - 4*chip_gap) / 5
    for i, name in enumerate(chips):
        cx = inner_x + i * (chip_w + chip_gap)
        ch = _shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, cx, chip_y,
                    chip_w, chip_h, fill=LIGHT_BG, line=BLUE, line_w=0.5)
        _label_in(ch, name, font_size=8, bold=True, color=NAVY)
    # scheduler note under
    _text(s, w_x + 0.05, y3 + 0.86, w_total - r_w - 0.40, 0.20,
          "+ quant_scheduler (jobs cron)", font_size=8, bold=False,
          color=GRAY_600, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

    # T4 — DATA band: Postgres + MinIO
    y4 = y3 + 1.55
    lane(y4, 0.95, "DATA", NAVY_2)
    p_w = 4.50
    m_w = 4.50
    p_gap = 0.40
    p_total = p_w + m_w + p_gap
    p_x = LX + (DW - p_total) / 2.0
    m_x = p_x + p_w + p_gap
    box(p_x, y4, p_w, 0.95,
        title="PostgreSQL 16  ·  base : quant",
        sub="runs · datasets · users · scores · trials · alembic migrations",
        title_pt=11, sub_pt=9, line=NAVY_2)
    box(m_x, y4, m_w, 0.95,
        title="MinIO (S3)  ·  bucket : quant-artifacts",
        sub="signaux · plots PNG · CSV · artefacts WFO",
        title_pt=11, sub_pt=9, line=NAVY_2)

    # Worker → Postgres + MinIO (two arrows from worker box down)
    arrow_down(w_x + 1.20, y3 + 1.07, 0.20, 0.40, fill=NAVY_2)
    arrow_down(w_x + (w_total - r_w - 0.30) - 1.40, y3 + 1.07, 0.20, 0.40, fill=NAVY_2)
    # Connect to Postgres + MinIO with thin horizontal stubs at top of data band
    hline(p_x + p_w*0.30, y4 - 0.04, p_w*0.40, fill=NAVY_2, h=0.04)
    hline(m_x + m_w*0.30, y4 - 0.04, m_w*0.40, fill=NAVY_2, h=0.04)

    # API also reads Postgres + MinIO — show with vertical pale connectors at the sides
    vline(p_x + 0.40, y2 + 0.65, y4 - (y2 + 0.65), fill=SLATE_200)
    _text(s, p_x - 0.10, (y2 + y4)/2 - 0.10, 1.60, 0.20,
          "lecture API", font_size=7, bold=True, color=GRAY_600,
          align=PP_ALIGN.LEFT)
    vline(m_x + m_w - 0.40, y2 + 0.65, y4 - (y2 + 0.65), fill=SLATE_200)
    _text(s, m_x + m_w - 1.50, (y2 + y4)/2 - 0.10, 1.60, 0.20,
          "lecture API", font_size=7, bold=True, color=GRAY_600,
          align=PP_ALIGN.RIGHT)

    # ── Deployment strip at the bottom ──
    dep_y = SLIDE_H - 0.78
    dep = _shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 0.45, dep_y,
                 SLIDE_W - 0.90, 0.36, fill=NAVY)
    _label_in(dep,
              "Déploiement  ·  Docker Compose  ·  GCP VM  ·  registre ghcr.io/tahadaz/bt-worker  ·  domaine rdtalpha.xyz",
              font_size=10, bold=True, color=WHITE)


def main():
    prs = Presentation()
    prs.slide_width  = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    build_architecture(prs, page_num=23)
    DST.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(DST))
    print(f"OK  wrote {DST}  ({DST.stat().st_size} bytes, {len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
