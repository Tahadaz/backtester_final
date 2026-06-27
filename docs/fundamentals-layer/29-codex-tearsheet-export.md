# 29 — Codex brief: tear-sheet / IC-memo / morning-note export (P2)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/equity-research/0.1.2/skills/morning-note/SKILL.md`, `…/initiating-coverage/SKILL.md`, `~/.claude/plugins/cache/claude-for-financial-services/valuation-reviewer/0.1.1/skills/ic-memo/SKILL.md`.
>
> **Why.** Danger D10. All the data is on the API; nothing is exportable. This brief adds three server-side rendered artefacts (HTML → optional PDF) that consume only what the per-symbol envelope already exposes. **No new computation.** No new DB tables.

---

## Files Codex MUST read first

1. The plugin SKILL.mds above — each describes a section layout. Reuse the section names verbatim where possible (in French in the UI; English allowed in code identifiers).
2. `services/api/app/schemas/fundamentals.py` and `services/api/app/routers/fundamentals.py` — the envelope this brief consumes.
3. `docs/fundamentals-layer/19-ui-tear-sheet-spec.md` and `20-claude-design-handoff.md` — the print stylesheet and visual spec already drafted. Reuse, do not replace.

---

## Scope

Three render paths, all server-side. Each takes the per-symbol envelope (already built by other endpoints) and produces an HTML string. PDF is *optional* in v1 — gate it behind an env var and a library check.

Out of scope: pptx export (separate; reuse the plugin `pptx-author` skill later if needed), email delivery, scheduled distribution.

---

## Three artefacts

| Artefact | Purpose | Sections (in order) |
|---|---|---|
| **Tear sheet** (1–2 pages) | Per-symbol research summary | Header (logo + symbol + name + sector + rating chip) · Snapshot KPIs (price, mcap, target, upside) · Thèse (from brief 23) · Valorisation football-field (uses ensemble + sensitivity from brief 26) · Quality pillars + Integrity block (brief 22) · Comparables table (brief 27) · Catalyseurs (brief 24) · Disclaimers |
| **Morning note** (½ page) | Overnight + today's call across coverage | Date · Top 3 movers (link to per-symbol tear sheets) · Today's catalysts (brief 24, `event_date=today`, all symbols, high+moderate tier) · One-line per symbol with thesis chip + score delta from yesterday (brief 28 history) · Disclaimers |
| **IC memo** (full page) | Investment-committee artefact | Cover (symbol, recommendation, target, downside) · Investment thesis (long-form from brief 23 `core_thesis` + drivers) · Valuation summary (4 models surfaced, full assumption table from brief 25, sensitivity grids from brief 26) · Risks (`bearish_drivers` + `invalidation_conditions`) · Catalysts table · Appendix: integrity report + projected statements |

Templates live in `services/api/app/templates/fundamentals/` (Codex confirms the existing template directory pattern; if there isn't one, create the directory). Use Jinja2 — it is already pulled in by FastAPI. Do NOT add a new template engine.

Templates are language-aware: French for UI labels, English code-side. A `lang` query param (`fr` default, `en` allowed) toggles label dictionaries that live in `…/templates/fundamentals/labels_fr.json` and `…_en.json`.

---

## Renderer

Add a thin orchestrator `core/quant_core/fundamentals/tearsheet.py` that takes a typed `TearsheetContext` (a typed dict of envelope fields it consumes) and returns the rendered HTML. **`tearsheet.py` MUST NOT touch the DB or the API layer** — it accepts pre-fetched data only. The API layer assembles `TearsheetContext` and passes it in.

This separation matters: it lets the renderer be unit-tested with synthetic context.

Optional PDF: if `WEASYPRINT_AVAILABLE` (env var or import-guard), expose a `?format=pdf` query that pipes HTML through WeasyPrint. If unavailable, return HTML with a `Content-Type: text/html`. **Do NOT install WeasyPrint as a hard dep** — leave it as a soft import.

---

## API surface

All under existing auth.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/fundamentals/{symbol}/tearsheet?lang=fr&format=html` | HTML (or PDF if available + requested). |
| `GET` | `/fundamentals/morning-note?date=YYYY-MM-DD&symbols=ATW,IAM,LHM&lang=fr` | HTML. Defaults: date=today, symbols=current universe. |
| `GET` | `/fundamentals/{symbol}/ic-memo?lang=fr` | HTML. |

These endpoints **read** other endpoints' data via the existing service layer — do NOT make them call other HTTP endpoints over the wire. Reuse the service functions directly.

---

## Data the renderer needs (pre-flight check)

Before rendering, the orchestrator verifies the envelope has the required fields. If a required field is missing, the rendered artefact shows a placeholder `— données indisponibles` and a top-of-page banner listing the missing pieces. Codex does NOT crash on missing data; the artefact is always renderable.

Required-vs-optional mapping per artefact:

| Artefact | Required (must render to be useful) | Optional (shown if present) |
|---|---|---|
| Tear sheet | symbol, current price, latest pillar scores, latest ensemble | thesis, catalysts, sensitivity grids, integrity report, comps table |
| Morning note | date, list of symbols with current ensembles + score deltas | catalysts of the day, thesis chips |
| IC memo | symbol, thesis, ensemble across all three scenarios, assumption resolution, integrity report | sensitivity grids, comps table, projected statements |

---

## Tests

`core/tests/test_tearsheet_renderer.py`:
- `test_renders_with_full_context` — synthetic full context → HTML contains key section markers (e.g. `id="section-valuation"`, `id="section-thesis"`).
- `test_renders_with_missing_optional_sections` — context without thesis → HTML still renders, contains the missing-section placeholder string.
- `test_renders_with_missing_required_field_banners` — context without ensemble → top banner present, no 500.
- `test_language_toggle_changes_labels` — `lang="en"` produces "Investment Thesis", `lang="fr"` produces "Thèse d'investissement".

`services/api/tests/test_fundamentals_tearsheet_api.py`:
- `test_get_tearsheet_returns_html` — `Content-Type: text/html`, status 200, body contains symbol.
- `test_pdf_returns_html_when_weasyprint_unavailable` — under the soft-import-disabled fixture, `?format=pdf` still returns 200 with HTML.
- `test_morning_note_filters_by_date` — seed catalysts for two dates, request one, only that day's catalysts in the body.

---

## Acceptance criteria

- [ ] Tests green; full suite green.
- [ ] No new hard dependencies in `pyproject.toml` / `requirements.txt` (WeasyPrint is soft).
- [ ] HTML validates as well-formed (Codex runs `html.parser` on the rendered output in one test; non-fatal but expected).
- [ ] The three endpoints return 200 for one MASI symbol end-to-end.
- [ ] `docs/fundamentals-layer/19-ui-tear-sheet-spec.md` updated with a short pointer to the new endpoints; print stylesheet section unchanged.
- [ ] No change to any computed fair value or pillar score.

---

## Reminder of what NOT to do

- Do not add a workbook (`.xlsx`) export in this brief. The plugin `xlsx-author` skill is the right pattern for that; it is a separate brief if/when needed.
- Do not introduce a queue/async path for rendering. The artefacts are cheap; rendering is synchronous.
- Do not put any business logic in the templates. They consume `TearsheetContext` only; calculations live in `tearsheet.py` or upstream.
- Do not localise numerical formats (currency / thousands separator) via the template — use a single `format_money` / `format_pct` helper in `tearsheet.py` parametrised by `lang`.
