"""Theme constants and helpers for the PFE deck rebuild."""
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree

# Palette (extracted from theme1.xml)
NAVY        = RGBColor(0x07, 0x3B, 0x66)   # accent2 - dark navy
BLUE        = RGBColor(0x0B, 0x5D, 0x8E)   # accent1
MID_BLUE    = RGBColor(0x2C, 0x7D, 0xA0)   # accent3
LIGHT_BLUE  = RGBColor(0x89, 0xC2, 0xD9)   # accent4
TEAL        = RGBColor(0x1D, 0x7F, 0xA8)   # accent5
SOFT_BLUE   = RGBColor(0x61, 0xA5, 0xC2)   # accent6
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
NEAR_BLACK  = RGBColor(0x1A, 0x1A, 0x1A)
GRAY        = RGBColor(0x6B, 0x72, 0x80)
LIGHT_GRAY  = RGBColor(0xE7, 0xEB, 0xF0)
PALE_BLUE   = RGBColor(0xEA, 0xF3, 0xFA)
ACCENT_OR   = RGBColor(0xEE, 0x7B, 0x08)   # hlink orange (used sparingly)
GRADE_A     = RGBColor(0x2F, 0xA8, 0x67)
GRADE_B     = RGBColor(0x73, 0xC0, 0x6A)
GRADE_C     = RGBColor(0xF2, 0xC5, 0x4E)
GRADE_D     = RGBColor(0xEE, 0x7B, 0x08)
GRADE_F     = RGBColor(0xC0, 0x39, 0x3A)

FONT = "Calibri"
TITLE_PT = 28
SUB_PT   = 14
BODY_PT  = 12
SMALL_PT = 10

PROJECT_TITLE = "Développement d'une plateforme d'aide à la décision en trading à la bourse de Casablanca"
YEAR = "2025/2026"

# Slide dimensions in inches (16:9, matches existing 9144000 x 5143500 EMU)
SLIDE_W = 10.0
SLIDE_H = 5.625


def set_text(tf, text, *, font_size=BODY_PT, bold=False, color=NEAR_BLACK,
             align=PP_ALIGN.LEFT, font=FONT):
    """Replace text frame content with a single styled paragraph."""
    tf.clear()
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.name = font
    r.font.size = Pt(font_size)
    r.font.bold = bold
    r.font.color.rgb = color


def add_textbox(slide, x, y, w, h, text, *, font_size=BODY_PT, bold=False,
                color=NEAR_BLACK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.text_frame.word_wrap = True
    tb.text_frame.margin_left = Emu(36000)
    tb.text_frame.margin_right = Emu(36000)
    tb.text_frame.margin_top = Emu(18000)
    tb.text_frame.margin_bottom = Emu(18000)
    tb.text_frame.vertical_anchor = anchor
    set_text(tb.text_frame, text, font_size=font_size, bold=bold,
             color=color, align=align)
    return tb


def add_filled_shape(slide, shape_type, x, y, w, h, *, fill=NAVY,
                     line=None, line_width=0.75, shadow=False):
    sh = slide.shapes.add_shape(shape_type, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(line_width)
    if not shadow:
        # disable default shadow
        sppr = sh._element.spPr
        for el in sppr.findall(qn("a:effectLst")):
            sppr.remove(el)
        sppr.append(etree.fromstring(
            '<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
        ))
    return sh


def add_label(shape, text, *, font_size=BODY_PT, bold=False,
              color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(36000)
    tf.margin_right = Emu(36000)
    tf.margin_top = Emu(18000)
    tf.margin_bottom = Emu(18000)
    tf.vertical_anchor = anchor
    set_text(tf, text, font_size=font_size, bold=bold,
             color=color, align=align)


def add_multiline(slide, x, y, w, h, lines, *, font_size=BODY_PT,
                  color=NEAR_BLACK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
                  bold_first=False, spacing=2):
    """lines: list of (text, bold) tuples or plain strings."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(36000); tf.margin_right = Emu(36000)
    tf.margin_top = Emu(18000); tf.margin_bottom = Emu(18000)
    tf.vertical_anchor = anchor
    tf.clear()
    for i, item in enumerate(lines):
        if isinstance(item, tuple):
            text, bold = item
        else:
            text, bold = item, (bold_first and i == 0)
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        r = p.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(font_size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tb


def draw_top_band(slide, *, title, subtitle=None):
    """Title band at top: navy left pentagon (auto-fit) + accent right chevron."""
    # auto-size title font based on length to prevent overflow
    n = len(title)
    if   n <= 18: tsz, pw = 22, 4.10
    elif n <= 26: tsz, pw = 20, 4.40
    elif n <= 34: tsz, pw = 18, 4.70
    else:         tsz, pw = 16, 5.00
    p_left = add_filled_shape(slide, MSO_SHAPE.PENTAGON,
                              0.10, 0.18, pw, 0.40, fill=NAVY)
    add_label(p_left, title, font_size=tsz, bold=True, color=WHITE)
    # right chevron — uses remaining width
    if subtitle is None:
        subtitle = ""
    sub_x = pw + 0.10
    sub_w = SLIDE_W - sub_x - 0.10
    p_right = add_filled_shape(slide, MSO_SHAPE.CHEVRON,
                               sub_x, 0.18, sub_w, 0.40, fill=LIGHT_BLUE)
    # auto-size subtitle too
    n2 = len(subtitle)
    ssz = 14 if n2 <= 40 else (12 if n2 <= 55 else 11)
    add_label(p_right, subtitle, font_size=ssz, bold=True, color=NAVY)


def draw_footer(slide, page_num):
    """Footer chevron with project title + page number."""
    # Long chevron base (light blue)
    add_filled_shape(slide, MSO_SHAPE.CHEVRON, 0.08, 5.22, 7.95, 0.32,
                     fill=LIGHT_BLUE)
    add_textbox(slide, 0.55, 5.22, 7.30, 0.32, PROJECT_TITLE,
                font_size=8, bold=True, color=NAVY,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
    # Right chevron - year + page
    add_filled_shape(slide, MSO_SHAPE.CHEVRON, 8.00, 5.22, 1.92, 0.32,
                     fill=NAVY)
    add_textbox(slide, 8.10, 5.22, 1.80, 0.32, f"{YEAR}   |   {page_num}",
                font_size=9, bold=True, color=WHITE,
                align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def draw_white_bg(slide):
    """Solid white background filling the slide."""
    bg = add_filled_shape(slide, MSO_SHAPE.RECTANGLE,
                          -0.05, -0.05, SLIDE_W + 0.1, SLIDE_H + 0.1,
                          fill=WHITE)
    # Send to back
    spTree = bg._element.getparent()
    spTree.remove(bg._element)
    spTree.insert(2, bg._element)
    return bg


def draw_corner_accent(slide):
    """Subtle navy accent strip top-right and bottom-left corner mark."""
    add_filled_shape(slide, MSO_SHAPE.RECTANGLE, 0.0, 0.0, 10.0, 0.08,
                     fill=NAVY)
    add_filled_shape(slide, MSO_SHAPE.RECTANGLE, 0.0, 0.08, 6.0, 0.02,
                     fill=LIGHT_BLUE)


def clear_animations(slide):
    """Remove all animation timing from a slide to avoid inherited Appear effects."""
    from lxml import etree
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    cSld_parent = slide._element
    # Remove <p:timing> entirely
    for el in cSld_parent.findall(qn("p:timing")):
        cSld_parent.remove(el)
    # Remove <p:transition> if any
    for el in cSld_parent.findall(qn("p:transition")):
        cSld_parent.remove(el)
    # Inject empty timing block identical to what plain slides have (none)
    # and a zero-duration transition matching existing slides
    trans = etree.fromstring(
        '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"'
        ' p14:dur="0"/>'
    )
    cSld_parent.append(trans)


def page_chrome(slide, page_num, title, subtitle):
    """Apply standard chrome: bg, accents, title band, footer."""
    clear_animations(slide)
    draw_white_bg(slide)
    draw_corner_accent(slide)
    draw_top_band(slide, title=title, subtitle=subtitle)
    draw_footer(slide, page_num)
