"""Capture real, deep screenshots from rdtalpha.xyz after login."""
from playwright.sync_api import sync_playwright
from pathlib import Path
import time, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

OUT = Path(r'C:/Users/taha/Downloads/backtester_signal_engine_autoaccept/_pptx_build/shots')
OUT.mkdir(exist_ok=True)

EMAIL = "stg.tdazine@bmcek.co.ma"
PW    = "amaGAMER"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    # Use larger viewport for higher quality slides
    ctx = b.new_context(viewport={'width': 1920, 'height': 1080},
                        device_scale_factor=2)
    page = ctx.new_page()

    print("Loading login page")
    page.goto('https://rdtalpha.xyz/login', wait_until='domcontentloaded', timeout=30000)
    page.fill('input[type=email]', EMAIL)
    page.fill('input[type=password]', PW)
    page.click('button:has-text("Se connecter")')
    page.wait_for_load_state('networkidle', timeout=30000)
    time.sleep(3)
    print("Logged in")

    def shot(name, wait=5):
        time.sleep(wait)
        path = OUT / f'{name}.png'
        page.screenshot(path=str(path), full_page=False)
        print(f"  saved {name}.png")

    # ── 1. Dashboard
    print("Dashboard")
    page.goto('https://rdtalpha.xyz/dashboard', wait_until='domcontentloaded', timeout=30000)
    shot('dashboard')

    # ── 2. Data
    print("Data")
    page.goto('https://rdtalpha.xyz/data', wait_until='domcontentloaded', timeout=30000)
    shot('data')

    # ── 3. Signals - landing
    print("Signals landing")
    page.goto('https://rdtalpha.xyz/signals', wait_until='domcontentloaded', timeout=30000)
    shot('signals_landing')

    # ── 4. Click a strong-signal ticker (ATW = Attijariwafa Bank, Vente forte -63)
    print("Signals - ATW Technique tab")
    try:
        page.click('text=ATW', timeout=10000)
        time.sleep(4)
        shot('signals_atw_technique')
    except Exception as e:
        print(f"  ATW click failed: {e}")

    # ── 5. Signal Evidence tab
    print("Signal Evidence tab")
    try:
        page.click('text=Signal Evidence', timeout=10000)
        shot('signals_atw_evidence')
    except Exception as e:
        print(f"  Evidence tab failed: {e}")

    # ── 6. Indicateurs tab
    print("Indicateurs tab")
    try:
        page.click('text=Indicateurs', timeout=10000)
        shot('signals_atw_indicateurs')
    except Exception as e:
        print(f"  Indicateurs tab failed: {e}")

    # ── 7. WFO tab
    print("WFO tab")
    try:
        page.click('text=WFO', timeout=10000)
        shot('signals_atw_wfo')
    except Exception as e:
        print(f"  WFO tab failed: {e}")

    # ── 8. Backtest MC tab
    print("Backtest MC tab")
    try:
        page.click('text=Backtest MC', timeout=10000)
        shot('signals_atw_backtest')
    except Exception as e:
        print(f"  Backtest tab failed: {e}")

    # ── 9. Try an Achat fort ticker for contrast (ALM = Aluminium Maroc +58)
    print("Signals - ALM")
    try:
        page.goto('https://rdtalpha.xyz/signals', wait_until='domcontentloaded', timeout=30000)
        time.sleep(2)
        page.click('text=ALM', timeout=10000)
        time.sleep(4)
        shot('signals_alm_technique')
    except Exception as e:
        print(f"  ALM failed: {e}")

    b.close()
print("DONE")
