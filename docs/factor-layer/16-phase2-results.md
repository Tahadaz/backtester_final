# 16 — Phase 2 Results

> This file is a placeholder. It will be filled after the Phase 2 backtest runs. The template below defines what must be reported — including honest nulls.

## Pre-registration reference

- Freeze file: `services/worker/research/phase2_pre_registration.yaml`
- Freeze date: 2026-04-30
- Freeze tag: `phase2-preregistration` (to be applied before first backtest run)
- Methodology: `docs/factor-layer/13-cross-product-variants.md`

---

## Summary table (to be filled)

| Stock | Sector | Factor | Condition | Native TA baseline Sharpe | Conditioned Sharpe | Incremental Sharpe 95% CI | FDR pass | Value-adding? |
|---|---|---|---|---|---|---|---|---|
| ATW | banks | VIX | vix_z20_below_neg1 | — | — | — | — | — |
| ... | | | | | | | | |

---

## Per-stock verdicts (to be filled)

### ATW (banks)
*To be written after backtest.*

### BCP (banks)
*To be written after backtest.*

### BMCE (banks)
*To be written after backtest.*

### IAM (telecom)
*To be written after backtest.*

### CDM (materials)
*To be written after backtest.*

### ADDH (real_estate)
*To be written after backtest.*

### COSU (agri_food)
*To be written after backtest.*

### WAA (insurance)
*To be written after backtest.*

---

## Honest null reporting

Stocks for which no factor-conditioned variant beats its TA baseline:

*To be filled.*

---

## Statistical-only discoveries (no channel tag)

Factor-conditioned variants that survive FDR but lack a matching channel tag in `channel_tags.yaml` — reported separately, not promoted to headline results:

*To be filled.*

---

## Economic interpretation

*To be written after backtest. For each surviving variant: why does this factor condition improve this signal for this stock, given the sector channel?*

---

## Phase 3 justification decision

*Based on the above results, is there sufficient evidence to proceed with Phase 3 (deeper integration, regime-conditioned ensemble weights)?*

Decision: **pending results.**
