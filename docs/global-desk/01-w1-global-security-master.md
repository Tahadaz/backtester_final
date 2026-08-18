# W1 — Global Security Master & Bloomberg Universe Expansion

**Depends on:** nothing. This is the unblocker for W2-W6.
**Status: BUILT 2026-08-17**, except §6, which needs a terminal.
**Implementer:** Claude, in-session (user instruction, 2026-08-17)
**Governing decisions:** G5 (source tagging), G8 (no access constraint → liquidity discipline), G9 (**nothing may assume Bloomberg**), G11 (regime-pertinent history)

---

## 1. Objective

Replace the Morocco-shaped instrument resolution with a **global security master**: one registry that maps a canonical instrument id to (a) a Bloomberg ticker, (b) a free-data fallback, and (c) the metadata the cross-asset engine already needs (`asset_class`, `currency`, `point_value`, roll rule, quote convention).

Then produce an **entitlement discovery report** — the empirical answer to G9's unknown.

---

## 2. The bottleneck (verified in source, 2026-08-17)

Bloomberg symbol resolution is currently two hardcoded Moroccan suffixes:

```python
# services/api/app/routers/bloomberg_bridge.py:168
def _symbol_to_bloomberg_candidates(symbol: str) -> list[str]:
    clean = symbol.strip().upper()
    if not clean:
        return []
    return [f"{clean} MA Equity", f"{clean} MC Equity"]
```

and one universe branch:

```python
# services/api/app/routers/bloomberg_bridge.py:177
if body.universe == "masi" and not symbols:
    symbols = [... all_masi_tickers() ...]
```

**Everything else in the bridge is already generic.** `BloombergUniverse` (`schemas/bloomberg.py:15`) already carries `"custom"` and `"bonds"` alongside `"masi"`/`"selected"`. Job types (`preflight | discovery | backfill | refresh`), modes, frequencies, chunking options and `security_candidates` probing all work unchanged for any ticker. The job spec already ships a `security_candidates` list precisely so discovery can probe alternatives.

So W1 is a **registry substitution, not a rewrite**. Do not restructure the bridge.

---

## 3. Deliverables

| File | Purpose | Status |
|---|---|---|
| `core/quant_core/cross_asset/security_master.py` | The registry: canonical id → Bloomberg candidates, free proxy, engine metadata. Pure data + lookup. | ✅ 47 instruments |
| `core/quant_core/cross_asset/universes.py` | Named instrument sets (`g10_fx`, `sovereign_rates`, `credit`, `commodities`, `equity_index`, `global_all`). | ✅ |
| `core/tests/test_ca_security_master.py` | Registry integrity tests (§7). *Named `test_ca_*` to match the existing cross-asset test convention rather than the name this brief originally gave.* | ✅ 148 pass |
| *edit* `services/api/app/routers/bloomberg_bridge.py` | Universe-scoped candidate resolution + global universe expansion in `_build_job_spec`. | ✅ |
| *edit* `services/api/app/schemas/bloomberg.py` | Extend `BloombergUniverse` with the named global sets. | ✅ |
| `services/api/tests/test_bloomberg_global_universe.py` | Global resolution + **MASI byte-identity regression**. | ✅ 17 pass |
| `tools/global_desk/build_entitlement_report.py` | Renders the §6 skeleton from the registry so it cannot drift. | ✅ |
| `docs/global-desk/reports/entitlement-discovery.md` | Generated output of §6. | ⏳ skeleton only — **needs a terminal** |

**Resolution is universe-scoped, not registry-first.** The brief originally said "registry lookup with the MA/MC suffixes retained only as the fallback". That is unsafe: `C`, `S`, `W`, `G`, `Z`, `US`, `TU` and `CL` are all canonical ids *and* plausible equity tickers, so a registry-first lookup would silently hijack a Moroccan symbol. `_symbol_to_bloomberg_candidates` therefore takes the universe and only consults the registry for global universes. Covered by `test_short_canonical_ids_do_not_hijack_moroccan_tickers`.

**Do not** create a new DB table. The registry is code (versioned, reviewable, diffable); `bloomberg_series` already indexes what actually arrives.

---

## 4. Starting universe (~47 instruments)

G8 removed the access constraint, so the discipline is liquidity, cost and data quality. Cap at 40-60 — a trend/carry book needs breadth for diversification, but every instrument added is one more that must be honestly modelled, rolled and cost-estimated.

**FX — 9 pairs.** Already defined at `services/api/app/services/cross_asset/datasources.py:11`; reuse those exact keys. `EURUSD, USDJPY, GBPUSD, USDCHF, AUDUSD, USDCAD, NZDUSD, USDNOK, USDSEK`. Bloomberg `EURUSD Curncy` + forward points for carry; free fallback `=X` spot + FRED policy rates (`FRED_RATE_SERIES`, same file `:23`).

**Sovereign rates — 12 futures.** US `TU/FV/TY/US`, Germany `DU/OE/RX/UB`, UK `G `, Japan `JB`, Italy `IK`, France `OAT` (all ` Comdty`). Free fallback: FRED `DGS2/5/10/30` (already wired, `:36`) and duration ETFs — **labelled proxy, not tradable**.

**Credit — 4 indices.** CDX IG, CDX HY, iTraxx Main, iTraxx Crossover. Free fallback: `LQD, HYG, IEAC, IHYG`. **Highest entitlement risk** — §6 decides whether this sleeve is real or proxy-only.

**Commodities — 14 futures.** Energy `CL, CO, NG, HO, XB`; metals `GC, SI, HG, PL`; ags `C , S , W , SB, KC`. Bloomberg gives genuine per-contract chains (this is G7's unlock). Free fallback: continuous front-month `=F` — **labelled non-tradable**, per the existing invariant §6.1.

**Equity indices — 8 futures.** `ES, NQ, VG, GX, CF, Z , NK, HI`. Free fallback: index level or ETF proxy.

Each entry declares its **history start and the reason**, per G11: EUR synthetic pre-1999, CDX/iTraxx from ~2004, several ags with materially thinner pre-2000 liquidity. The registry stores `history_start` and `history_note` as data — the backtest reads them rather than silently starting wherever data happens to begin.

---

## 5. Provenance (G5)

Every series resolved through the master carries `source ∈ {bloomberg, free_proxy, fixture}` end to end, and it must survive into the run record. Requirements:

1. A run can always answer "was any Bloomberg-derived series used?" — needed for the licensing boundary and for reproducing a run off the desk machine.
2. A sleeve running on `free_proxy` where `bloomberg` was expected emits a `warnings` entry. It does not silently downgrade.
3. `fixture` sources never reach anything labelled tradable.

---

## 6. Entitlement discovery report — the actual first deliverable

G9 says entitlements are unknown, so **measure them before scoping W4**. The existing discovery job already does this; it has only ever been pointed at MASI.

Procedure: queue `job_type="discovery"`, `mode="discovery_only"`, `universe="global_all"`, `frequency="daily"`, conservative fields, against the §4 list. The bridge probes each candidate and reports available / unavailable / partial / not-entitled per security — exactly as `FIELD_VISIT_RUNBOOK.md` step 7 does for MASI.

The report must record, per instrument: entitlement status, earliest available date, field coverage, and — for credit and commodities specifically — whether the fields needed for the *real* version of the sleeve exist (per-contract chains for commodities; asset-swap/z-spread fields for eurobond RV) or only price.

**This report is a gate.** W4's eurobond RV depth and W5's real-chain commodity work are both scoped from it, not before it.

---

## 7. Ship gate

- `pytest core/tests/test_security_master.py services/api/tests/test_bloomberg_bridge.py` green.
- Registry integrity: every instrument resolves to a Bloomberg ticker **and** a free fallback (or explicitly declares `free_proxy=None` with a reason); no duplicate canonical ids; every entry has `history_start`, `history_note`, `asset_class`, `currency`, and a roll rule valid against `FuturesContract.__post_init__`.
- **Regression: MASI resolution is unchanged.** An existing MASI discovery job produces a byte-identical job spec to today's. This is the invariant that keeps the Moroccan pipeline untouched.
- `security_master.py` imports no SQLAlchemy, no FastAPI, no network client.
- The entitlement discovery report exists and is committed.

---

## 8. Non-goals for W1

- No signal logic, no backtests, no portfolio construction — registry and discovery only.
- No new bridge job types, no bridge restructuring, no new tables.
- No intraday probing (G1). Daily only.
- No changes to the Moroccan path beyond routing it through the registry with identical output.
- No frontend work. The `/signals` restructure (G3) is a later workstream.
