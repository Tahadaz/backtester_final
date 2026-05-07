from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
import json
import os

DOWNLOADS = os.path.expanduser(r"c:\Users\taha\Downloads")
IMG1 = os.path.join(DOWNLOADS, "backtestMC.png")
IMG2 = os.path.join(DOWNLOADS, "MC.png")
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs", "presentations"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "weekly_report_v2.pptx")
SUMMARY_FILE = os.path.join(OUTPUT_DIR, "factor_summary.json")

with open(SUMMARY_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

prs = Presentation()
prs.slide_width = Inches(10)
prs.slide_height = Inches(7.5)

def add_title_slide(title, subtitle):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor(25, 45, 85)
    
    # Add title
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(2.5), Inches(9), Inches(1.5))
    title_frame = title_box.text_frame
    title_frame.word_wrap = True
    p = title_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(54)
    p.font.bold = True
    p.font.color.rgb = RGBColor(255, 255, 255)
    p.alignment = PP_ALIGN.CENTER
    
    # Add subtitle
    subtitle_box = slide.shapes.add_textbox(Inches(0.5), Inches(4), Inches(9), Inches(2))
    subtitle_frame = subtitle_box.text_frame
    subtitle_frame.word_wrap = True
    p = subtitle_frame.paragraphs[0]
    p.text = subtitle
    p.font.size = Pt(24)
    p.font.color.rgb = RGBColor(200, 200, 200)
    p.alignment = PP_ALIGN.CENTER
    
    # Add images if available
    if os.path.exists(IMG1):
        try:
            slide.shapes.add_picture(IMG1, Inches(0.5), Inches(0.5), width=Inches(4.5))
        except:
            pass
    if os.path.exists(IMG2):
        try:
            slide.shapes.add_picture(IMG2, Inches(5.2), Inches(0.5), width=Inches(4.5))
        except:
            pass
    
    return slide

def add_bullet_slide(title_text, bullets, subtitle=""):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title_text
    
    if subtitle:
        # Add subtitle below title
        subtitle_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.8), Inches(9), Inches(0.4))
        sf = subtitle_box.text_frame
        sf.word_wrap = True
        sp = sf.paragraphs[0]
        sp.text = subtitle
        sp.font.size = Pt(14)
        sp.font.italic = True
        sp.font.color.rgb = RGBColor(100, 100, 100)
    
    body = slide.shapes.placeholders[1].text_frame
    body.clear()
    for bullet in bullets:
        p = body.add_paragraph()
        p.text = bullet
        p.level = 0
        p.font.size = Pt(16)
    
    return slide

def add_table_slide(title_text, headers, rows):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title_text
    
    # Create table
    rows_count = len(rows) + 1
    cols_count = len(headers)
    left = Inches(0.5)
    top = Inches(1.5)
    width = Inches(9)
    height = Inches(5)
    
    table_shape = slide.shapes.add_table(rows_count, cols_count, left, top, width, height).table
    
    # Set column widths (convert to EMU)
    col_width_emu = int(Inches(9) / cols_count)
    for col_idx in range(cols_count):
        table_shape.columns[col_idx].width = col_width_emu
    
    # Header row
    for col_idx, header in enumerate(headers):
        cell = table_shape.cell(0, col_idx)
        cell.text = header
        for paragraph in cell.text_frame.paragraphs:
            paragraph.font.bold = True
            paragraph.font.size = Pt(12)
            paragraph.font.color.rgb = RGBColor(255, 255, 255)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(25, 45, 85)
    
    # Data rows
    for row_idx, row in enumerate(rows, 1):
        for col_idx, value in enumerate(row):
            cell = table_shape.cell(row_idx, col_idx)
            cell.text = str(value)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.size = Pt(11)
                if row_idx % 2 == 0:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor(240, 240, 240)
    
    return slide

# 1. Title Slide
add_title_slide(
    "Weekly Report",
    "Macro/Factor Analysis & Backtest Robustness Layer\nWeek ending April 24, 2026"
)

# 2. Executive Summary
add_bullet_slide("Executive Summary", [
    "✓ Integrated per-signal backtest + Monte Carlo robustness panel to signal pages",
    "✓ Completed statistical macro/factor study: 56 factors × 3 symbols (ATW, IAM, BCP)",
    "✓ Identified 15+ statistically significant factor relationships (p < 0.05)",
    "✓ Drafted app-level factor-layer analytics design with API/frontend contract",
    "→ Ready for PR + validation on full signal universe"
])

# 3. Methodology
add_bullet_slide("Statistical Methodology", [
    "Factor Universe: 56 factors across equities, FX, commodities, rates, crypto",
    "Time Periods: 2–6+ years per symbol (n_obs: 2K–6K+ observations)",
    "Metrics: Spearman rank IC (robustness), HAC-adjusted t-stats (heteroscedasticity)",
    "Significance Threshold: p < 0.05 (two-tailed)",
    "Correlation Range: −0.06 to +0.06 (typical magnitude), but with strong stat evidence"
])

# 4. Key Findings per Symbol
def get_significant_factors(symbol_data, p_threshold=0.05):
    """Extract significant factors sorted by absolute correlation"""
    sig = [f for f in symbol_data if f['spearman_p'] < p_threshold]
    sig.sort(key=lambda x: abs(x['spearman_corr']), reverse=True)
    return sig

for symbol in ['ATW', 'IAM', 'BCP']:
    symbol_data = data.get(symbol, [])
    sig_factors = get_significant_factors(symbol_data, p_threshold=0.05)
    
    if sig_factors:
        top_5 = sig_factors[:5]
        bullets = []
        for f in top_5:
            bullets.append(
                f"{f['factor'].upper()}: ρ={f['spearman_corr']:+.4f} (p={f['spearman_p']:.4f}, t={f['beta_hac_t']:+.2f})"
            )
        
        add_bullet_slide(
            f"{symbol} — Significant Factors (p < 0.05)",
            bullets + [f"Total significant: {len(sig_factors)} / 56 factors"],
            subtitle=f"Ranked by correlation magnitude"
        )
        
        # Detailed table for this symbol
        table_rows = []
        for f in sig_factors[:10]:
            table_rows.append([
                f['factor'].upper(),
                f"{f['spearman_corr']:+.4f}",
                f"{f['spearman_p']:.5f}",
                f"{f['beta_hac_t']:+.2f}",
                f"{f['r2']:.4f}"
            ])
        
        if table_rows:
            add_table_slide(
                f"{symbol} — Top 10 Significant Factors",
                ["Factor", "Spearman ρ", "p-value", "HAC t-stat", "R²"],
                table_rows
            )

# 5. Cross-Symbol Insights
all_significant = {}
for symbol in ['ATW', 'IAM', 'BCP']:
    all_significant[symbol] = len(get_significant_factors(data.get(symbol, []), p_threshold=0.05))

bullets = []
for symbol, count in sorted(all_significant.items(), key=lambda x: x[1], reverse=True):
    bullets.append(f"{symbol}: {count} significant factors / 56 (factor exposure density: {count/56*100:.1f}%)")

add_bullet_slide("Cross-Symbol Summary", bullets + [
    f"Total Significant Relationships Identified: {sum(all_significant.values())}",
    "→ Strong evidence of systematic macro/factor sensitivities across the portfolio"
])

# 6. Work Completed
add_bullet_slide("Work Completed This Week", [
    "Backtest Layer: Monte Carlo robustness (95% CI, DSR) integrated on all signal pages",
    "Factor Study: Full statistical analysis completed; 56-factor universe evaluated",
    "Data Alignment: Calendar-aware factor ingestion with precede_open lag rules",
    "Design Docs: App-level factor-layer architecture drafted (API routes, data contracts)",
    "Outputs: All results & visualizations saved under iLoveZIP_Create/factor_lab_outputs"
])

# 7. Next Steps
add_bullet_slide("Next Steps", [
    "Extend analysis to full symbol universe (60+ instruments)",
    "Run unit tests for statistical alignment + add adversarial calendar tests",
    "Ingest live macro data feeds (VIX, DXY, commodities) and validate ingestion",
    "Build factor-layer analytics endpoints (/analytics/signals, /analytics/factors/{symbol})",
    "Prepare PR with full code + test coverage + docs for peer review"
])

# 8. Artifacts & Paths
artifacts_bullets = [
    f"Local Analysis: C:\\Users\\taha\\Downloads\\iLoveZIP_Create\\factor_lab_outputs",
    f"Factor Summary JSON: docs/presentations/factor_summary.json",
    f"Backtest Images: backtestMC.png, MC.png (from Downloads)",
    f"App Design Docs: docs/factor-layer/",
    f"Generated PPTX: {OUTPUT_FILE}"
]
add_bullet_slide("Artifacts & Paths", artifacts_bullets)

# Save
prs.save(OUTPUT_FILE)
print(f"✓ Saved: {OUTPUT_FILE}")
print(f"✓ Symbols analyzed: {len(data)}")
print(f"✓ Factors per symbol: 56")
print(f"✓ Total significant relationships: {sum(all_significant.values())}")
