# 64 — Codex brief: fundamental UX transparency & navigation polish

User walkthrough findings (2026-07-05), verified against the live stack. Read the binding
rules in `21-codex-briefs-INDEX.md`; doc-61 wording rules still apply to any displayed claim.

## Package 1 — P1: French recommendation labels

`derive_recommendation` (services/api/app/services/fundamentals.py:366) returns the 5-tier
ladder (buy / accumulate / hold / reduce / sell + NR); `RecChip`
(frontend/components/strategy/fundamental/shared/cards.tsx) renders the raw English enum.
- Add a display mapping: Acheter / Accumuler / Conserver / Alléger / Vendre / NR, with
  tones (buy/accumulate positive, hold neutral, reduce/sell negative, NR muted).
- Tooltip on the chip: the ladder definition ("rendement excédentaire vs coût des fonds
  propres: ≥ +6% Acheter, ≥ +3% Accumuler, ...") — read thresholds from
  `DEFAULT_ASSUMPTIONS['rating_*']`, do not hardcode.
- Backend enum values unchanged everywhere.

## Package 2 — P1: N/R triage (stale verdicts)

Live finding: 24 symbols have a `data_unverified` verdict somewhere in
`fundamental_data_verification`, but only **6** on their latest row per symbol. The UI
shows far more N/R than the latest verification state justifies.
- Audit every read path that decides NR (services/api/app/services/fundamentals.py and
  routers): the verdict MUST come from the latest verification row per (symbol, canonical
  import). Fix any path reading older rows or stale cached envelopes.
- Add an ops action (existing ops conventions) to re-run the live tie-out for all currently
  N/R symbols in one batch.
- Acceptance is live proof: after the fix + one batch re-run, report the list of symbols
  still N/R and why (failed check name). Expected order of magnitude: ~6, not ~24. Genuine
  failures STAY N/R — never soften the gate itself.

## Package 3 — P1: Altman (and Piotroski) calculation transparency

Backend `screens.py::altman_z` computes the score but does not expose components.
- Backend: return per-component detail — for each X1..X5: label, ratio value, weight,
  contribution, and the raw numerator/denominator values with their metric names and
  statement year (e.g. X1: Fonds de roulement 1 234 MMAD / Actif total 8 456 MMAD, FY2025).
  Same pattern for the Piotroski checklist items (pass/fail + the two values compared).
  Financials keep the existing not-applicable path, surfaced as such.
- Frontend (Comparables & Qualité tab): expandable calculation breakdown table under the
  Altman score; hover tooltip on every component chip showing the raw values. Reuse one
  generic `RatioBreakdown` tooltip component for both Altman and Piotroski.
- Deep-links: in the Synthèse tab Catalyseurs & Risques bullets, mentions of Altman /
  Piotroski / any pillar metric become links that switch to the Qualité tab and scroll to
  (and briefly highlight) the corresponding section. Use the existing tab-navigation
  callback (`onNavigate`) + element anchors; no new router machinery.

## Package 4 — P2: fullscreen & chart enlarge

- A fullscreen toggle on the fundamental research view container (expand to viewport,
  Esc/button to exit; persists across tab switches within the view). Native
  requestFullscreen with a CSS-maximized fallback.
- All "Trajectoire de croissance" charts (estimates-tab) and the sensitivity heatmap get a
  click-to-enlarge lightbox/modal (larger render, same data, close on Esc/backdrop). One
  shared `ChartLightbox` component; keep the small inline charts as-is.
- Sticky tab bar for the fundamental view so switching tabs doesn't require scrolling to
  the top on long pages.

## Constraints
- One commit per package; repo green each (pytest core + services, frontend build);
  `graphify update .` at the end.
- Package 2 acceptance = the live N/R list with reasons, not just green tests.
- No gate softening, no engine math changes, no SFC/edge changes. French labels, correct
  accents. Ambiguities → `## Open questions` here and stop.
