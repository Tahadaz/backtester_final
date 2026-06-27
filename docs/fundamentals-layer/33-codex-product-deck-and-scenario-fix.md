# 33 — Codex brief: Screenshot-driven product deck + scenario governance fix

> **Status.** Executable brief for Codex. Two deliverables in one runbook:
> **(A)** Fix the scenario behaviour so the live UI is desk-correct (prerequisite — brief 32).
> **(B)** Produce a **product presentation of the fundamental module built from real screenshots of the running app** — French, for an internship supervisor / desk lead. This is NOT an abstract methodology deck; every content slide carries a real screenshot of the app.
>
> **Why A before B:** the screenshots must show the corrected, base-anchored UI (headline reco does not change when the scenario toggle is flipped). Land the scenario fix first, then capture.
>
> **Hard rule:** no placeholder/stock images. Every capability slide embeds a PNG captured from the running app in Phase 3. If a screen can't be captured, the slide is dropped, not faked.

---

## Repo facts Codex MUST rely on (verified 2026-06-02)

- **Stack:** `infra/docker-compose.yml` (services: `quant_postgres`, `quant_redis`, `quant_minio`, `quant_db_migrate` → `alembic -c services/api/alembic.ini upgrade head`, `quant_api`, `quant_frontend`, workers). API and frontend ports are defined in that file — read them, don't guess.
- **Frontend dev:** `frontend/` → `npm run dev` (Next.js, port **3000**).
- **Fundamental tear sheet route:** `frontend/app/signals/page.tsx` renders `frontend/components/strategy/signal-fundamental-view.tsx`. View state is in the **URL query**: `?scenario=`, `?fund_tab=`, `?fund_benchmark=`, `?fund_excluded_models=`. The tab keys come from `tabFromQuery(...)` — read the function for the exact values (do not invent tab names).
- **Seed path:** `scripts/backfill_stockanalysis_fundamentals.py` (argparse CLI) ingests StockAnalysis financials **and** calls `recompute_symbol_valuations_all_scenarios` — i.e. it both imports and values bear/base/bull. Shares come from `masi_stock_shares.xlsx` at repo root.
- **Playwright** is already present in the frontend (`frontend/.playwright-cli`).

If any path/port has changed, **report it in the PR and proceed**.

---

# PHASE 0 — Scenario governance fix (prerequisite)

Implement **brief 32** (`32-codex-scenario-governance.md`) in full. Summary of what must be true after this phase so the screenshots are correct:

- **G1** Headline `recommendation` / `target_price` / `conviction` are computed from the **base** ensemble and **do not change** when the user toggles bear/bull (`derive_research_overlay` call sites at `routers/fundamentals.py:~1772` and `~2229`).
- **G2** `_scenario_or_auto` defaults to `base`; the "closest-to-price" auto-selection (`_auto_scenario_from_ensembles`) is demoted to a labelled diagnostic, never the headline driver.
- **G3** Scenario probabilities move from the frontend constants (`signal-fundamental-view.tsx:~1841/1849/1857`) into `DEFAULT_ASSUMPTIONS` (`scenario_probability_bear/base/bull`), sum-to-1 validated, API-surfaced.
- **G4** UI shows base as the fixed headline with bear/bull as a labelled risk band; a banner appears when viewing a non-base scenario.

Run the brief-32 acceptance tests (`test_headline_invariant_across_scenarios`, etc.) green before moving on.

---

# PHASE 1 — Seed a realistic demo dataset

The fundamental screens are empty without data. Build a reproducible local dataset.

1. Bring up infra and migrate:
   ```bash
   docker compose -f infra/docker-compose.yml up -d quant_postgres quant_redis quant_minio quant_db_migrate
   # confirm alembic head includes u1v2w3x4y5z6 (desk rf override + ensemble diagnostics columns)
   ```
2. Seed **4–5 representative BVC names across sectors** so every screen is non-trivial (pick from stock_master; suggested spread: one **bank**, one **industrial/mining**, one **consumer/telecom**, one **utility/real-estate**). Read the CLI of `scripts/backfill_stockanalysis_fundamentals.py` and run it for those symbols. It imports + values all scenarios.
3. **CI fallback:** if StockAnalysis is unreachable from the build environment, seed instead from a **committed sample workbook fixture** through the workbook provider (reuse the fixtures under `core/tests/` as the template) so the deck build is deterministic offline. Document which path was used.
4. Verify in the DB that each seeded symbol has a base/bear/bull `FundamentalEnsembleResult` and a non-null `fair_value_base`.

**Acceptance:** a documented `make seed-demo` (or a short script) that, from a clean DB, produces ≥4 fully-valued symbols.

---

# PHASE 2 — Run the stack for capture

- Start `quant_api` (from compose) and `npm run dev` in `frontend/` (or the `quant_frontend` service). Confirm the frontend reaches the API.
- Pick one **"hero" symbol** with the richest data (e.g. the bank — exercises residual income + justified P/B) and one **secondary** (the industrial — exercises FCFF/FCFE). Note their tickers; the capture script will target them.

**Acceptance:** `http://localhost:3000/signals?...` renders a populated tear sheet for the hero symbol.

---

# PHASE 3 — Capture screenshots (Playwright)

Add `frontend/scripts/capture-fundamental-screens.mjs`:

- Launch Chromium, viewport **1600×1000**, `deviceScaleFactor: 2` (retina-crisp PNGs).
- For each target below, navigate to the URL (the hero symbol + the right `fund_tab`), `await` the key component to be visible, then screenshot **element-scoped** (preferred) or full-page. Read `signal-fundamental-view.tsx` for the real `fund_tab` keys and stable selectors / `data-` attributes; **add `data-capture="…"` attributes** to the relevant containers if none exist (small, harmless change).
- Save PNGs to `docs/fundamentals-layer/assets/screens/` with stable names.

Captures (one PNG each; skip+log any screen that can't render):

| File | Screen | What it shows |
|---|---|---|
| `01-tearsheet.png` | Overview tab | Reco (base-anchored), objectif de cours, conviction, fourchette |
| `02-valuation-models.png` | Valuation tab | Per-model fair values + ensemble (médiane pondérée) |
| `03-wacc-buildup.png` | WACC build-up panel | Ke = rf + β·PRA, Kd synthétique, poids, sources |
| `04-scenarios.png` | Scenario band + switcher (base) | Bear/Base/Bull band, base headline fixed |
| `05-sensitivity.png` | Sensitivity grid | 5×5 WACC × g heatmap |
| `06-scoring.png` | Scoring tab | 6 piliers + couverture |
| `07-diagnostics.png` | Diagnostics / justification | DuPont, Piotroski, drivers haussiers/baissiers |

**Acceptance:** `node frontend/scripts/capture-fundamental-screens.mjs` writes ≥6 non-empty PNGs; re-runnable.

---

# PHASE 4 — Assemble the French product deck

Add `scripts/build_fundamental_product_deck.py` (uses `python-pptx`):

- 16:9, clean blue/grey palette (`#1F4E79` / `#2E75B6` / `#D9E1F2` / greys), Calibri.
- **Screenshot-dominant layout:** on each capability slide the PNG occupies ≥ 60 % of the area; text is a short title + 2–3 caption bullets ("ce que ça montre" / "comment c'est calculé"), not paragraphs.
- Slide order:
  1. **Titre** — "Module d'analyse fondamentale — démonstration produit", auteur, date.
  2. **Tear sheet** (`01`) — la fiche valeur : reco, objectif, conviction, fourchette.
  3. **Valorisation multi-modèles** (`02`) — 7 modèles agrégés en une valeur robuste.
  4. **Coût du capital** (`03`) — WACC estimé titre par titre, build-up affiché.
  5. **Scénarios** (`04`) — Bear/Base/Bull, recommandation ancrée au base.
  6. **Sensibilité** (`05`) — robustesse de la conclusion (WACC × croissance).
  7. **Scoring** (`06`) — 6 piliers, classement sectoriel.
  8. **Diagnostics & justification** (`07`) — DuPont, Piotroski, drivers.
  9. **Garde-fous** — slide texte courte : intégrité 3-états, gating NR, normalisation (1 capture optionnelle d'un badge d'intégrité).
  10. **Feuille de route** — panneau de reproductibilité, football-field, backtest du signal.
- Output to `out/Module_Analyse_Fondamentale.pptx`; create `out/` if missing; **fail the build if any referenced screenshot is missing** (no silent placeholders).

**Acceptance:** one documented command (`python scripts/build_fundamental_product_deck.py`) builds a 10-slide deck where slides 2–8 each embed a real screenshot from Phase 3.

---

## Operator runbook (put in `docs/fundamentals-layer/assets/README.md`)

```
1. docker compose -f infra/docker-compose.yml up -d quant_postgres quant_redis quant_minio quant_db_migrate
2. python scripts/backfill_stockanalysis_fundamentals.py --symbols <BANK> <INDUS> <CONSO> <UTIL>   # or workbook fixture fallback
3. (start API)  +  cd frontend && npm run dev
4. node frontend/scripts/capture-fundamental-screens.mjs
5. python scripts/build_fundamental_product_deck.py    ->  out/Module_Analyse_Fondamentale.pptx
```

Some steps need a live machine (Docker, network for StockAnalysis, a browser). If the build environment is headless/offline, use the workbook-fixture seed (Phase 1.3) and the bundled Chromium from Playwright — both keep the pipeline reproducible without external services.

## PR discipline & sequencing
| Phase | PR | Touches | Gate |
|---|---|---|---|
| 0 | brief 32 | engine + API + FE | tests green |
| 1–2 | seed + run | `scripts/`, infra docs | ≥4 valued symbols |
| 3 | capture | `frontend/scripts/`, `data-capture` attrs, `assets/screens/` | ≥6 PNGs |
| 4 | deck build | `scripts/build_fundamental_product_deck.py`, `out/` | 10 slides w/ real screenshots |

## Cross-references
- Scenario fix detail: brief 32. Engine state / over-statement fixes already shipped: brief 31.
- Frontend entry: `frontend/app/signals/page.tsx` + `frontend/components/strategy/signal-fundamental-view.tsx` (read for `fund_tab` keys and selectors).
