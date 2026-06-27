# Brief 49 — Multi-source consensus forward estimates → forward-P/E valuation (Sonnet)

**Owner:** Sonnet implementer · **Branch:** `feature/fundamental-ui-consolidation`
**Goal:** Anchor valuation to **external analyst consensus forward earnings** (forward EPS / target
price), aggregated from **multiple sources**, instead of the engine's mechanical projection. Build a
**pluggable consensus layer**: one normalized estimate store, many source adapters. Feed **forward
P/E** (and forward earnings into the DCF stage-1 base), with graceful fallback to the mechanical path
where no consensus exists.

> "Path A", multi-source. Backend-only. Tag estimates so a forecast can never pollute reported
> actuals. Add sources behind a common adapter interface so new ones are cheap.

---

## 0. Data reality (confirmed — don't re-investigate)

- The engine already projects forward mechanically (`fundamental_projection`, ~370k rows). That
  mechanical forward is the weak link — extrapolation, not a forecast.
- **No external consensus is ingested, and there is NO investing.com scraper** (the `investing.com`
  data_source on IBC was a one-off manual import; every code hit for "investing" is `CF_Investing`).
- Existing tooling to reuse:
  - **Attijari Global Research parser** — `scripts/backfill_attijari_morning_brief_fundamentals.py`
    (new/unrun). Fetches Casablanca-Bourse publications (2024+), forward-year-aware, extracts
    per-`fiscal_year` metrics. Uses `curl_cffi` chrome-impersonation (the anti-bot pattern to copy).
  - **BKGR stock guide PDF** — `bkgr-stock-guide-juin-2026.pdf`, has forecast EPS / forward-P/E
    tables (currently only mined for target/upside). Point-in-time cross-check.

### Honest constraints (set expectations before building)
- **Consensus can't be cleanly PIT-backtested** (brief 48 style): we only have consensus from ~2024
  and not as as-of snapshots. Validation here is **face-validity + recent-period sanity + BKGR
  cross-check**, not a backtested-alpha claim.
- **investing.com is anti-bot (Cloudflare) and ToS-gray.** Treat it as one adapter, behind the same
  interface, with retries/caching and a clear note. Do not let the whole effort block on it — land
  the cheap/safe sources first.

---

## Phase 0 — the consensus layer (schema + adapter interface)

### 0a. Normalized store
A single representation for an external estimate, independent of source:
`ConsensusEstimate(symbol, fiscal_year, period_type, metric, value, source, as_of_date,
currency, raw_label)` where `metric` ∈ a small canonical set (start with `EPS_Forward`,
`NetIncome_Forward`, `Revenue_Forward`, `Target_Price`, `Rating`). Persist tagged as estimate
(`data_source` like `attijari_research` / `bkgr_guide` / `investing_com`, explicit estimate flag,
`as_of`). **Never** merge into reported-actual rows; latest consensus per
(symbol, fiscal_year, metric, source) wins.

### 0b. Adapter interface
`class ConsensusSource(Protocol): name; fetch(symbols) -> list[ConsensusEstimate]`. Each source
normalizes its raw output into `ConsensusEstimate`. Adding a source = one adapter, no pipeline
changes. Build a tiny runner that fans out across enabled adapters and upserts into the store.

### 0c. Reconciliation policy (multi-source)
When several sources give the same (symbol, fiscal_year, metric): default to **median across
sources** (robust to one bad print), keep all raw rows for audit, and record which sources
contributed. Make the policy a single function so it's easy to change (median / source-priority /
mean).

---

## Phase 1 — source adapters (land cheapest/safest first)

1. **Attijari adapter** (reuse the existing parser). Phase-0 gate: run it on a few names, confirm it
   extracts **forward-year EPS / Net Income** (FY2026E/2027E) + target, normalize into
   `ConsensusEstimate`. If it only yields targets (no EPS), report that.
2. **BKGR guide adapter** — parse the PDF forecast table for forward EPS / forward P/E / target.
3. **investing.com adapter** — scrape per-symbol analyst estimates (forward EPS, target, # analysts)
   via `curl_cffi` impersonation + on-disk cache + polite rate limiting. **Caveat in code**: anti-bot
   + ToS; isolate failures so a block on investing.com never breaks the others.
4. (Extensible) leave the interface obvious so other MA research houses / a data API can be added.

**GATE after Phase 1:** print, per source, how many (symbol, fiscal_year, forward-EPS) rows were
obtained. If no source reliably yields **forward EPS** (only targets), STOP and report — we can still
use target prices, but the "forward P/E" plan needs forward EPS; re-scope rather than fake it.

## Phase 2 — wire consensus into valuation
- **Forward P/E (highest leverage):** where consensus forward EPS exists, value the multiple model off
  **forward** EPS (`relative_multiples` already backtested well in brief 48 — feeding it forward EPS is
  the analyst-grade upgrade). Use the reconciled (median) consensus value.
- **DCF stage-1 base:** seed near-term earnings from reconciled consensus instead of the mechanical
  CAGR proxy, where available.
- **Target-price blend (optional):** expose consensus target as context next to the engine fair value;
  do not silently average them.
- **Fallback:** no consensus for a (symbol, year) → mechanical projection. **No coverage regression,
  no new N/R.**
- **PIT discipline if backtesting:** a consensus value is valid only from its `as_of` forward — never
  use a 2026 estimate to value a 2024 as-of date.

## Phase 3 — validate (face-validity, not IC)
- BKGR validator: expect the −40% bias to shrink and rank-agreement to rise; report deltas (sanity,
  not a fit target).
- Spot-check the brief-47 worst (TQM, AKT, SID, MSA): does forward-P/E give analyst-plausible values?
- Report per-source coverage (how many symbols got consensus, from which sources) and the reconciled
  blend.
- Full core suite green.

---

## Acceptance criteria
1. Pluggable layer: normalized `ConsensusEstimate` store + adapter interface + median reconciliation;
   adding a source is one adapter.
2. ≥2 sources live (Attijari + BKGR at minimum; investing.com if it cooperates), tagged, never
   commingled with actuals; latest-per-(symbol,year,metric,source) wins.
3. Valuation consumes reconciled consensus forward EPS (forward P/E + DCF stage-1) with mechanical
   fallback; no coverage regression / no new N/R.
4. BKGR bias shrinks materially; spot-checked names look analyst-plausible.
5. Core suite green; unit tests for: each adapter's normalization, estimate-vs-actual isolation,
   multi-source reconciliation, forward-P/E math, fallback.

## Guardrails
- **Estimates ≠ actuals** — tag and isolate; a forecast must never pollute reported history.
- **Per-source isolation** — one source failing (esp. investing.com anti-bot) must not break the
  others or the valuation.
- **Graceful fallback** to the mechanical projection; consensus is an upgrade, not a hard dependency.
- **Honest validation** — face-validity + sanity, not backtested alpha (no consensus PIT history).
- Respect source ToS / rate limits; cache aggressively; don't hammer investing.com.
- Keep brief-31 sanity caps and brief-48 IC weights; this changes the *forward input*, not the
  ensemble weighting.
- Backend-only.
