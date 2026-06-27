# 25 — Codex brief: per-symbol Bull / Base / Bear scenarios (P2)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/financial-analysis/0.1.1/skills/dcf-model/SKILL.md` § scenario block.
>
> **Why.** Danger D4. Today `SCENARIO_DEFAULT_OVERRIDES` shifts `wacc` / `terminal_growth` / `growth_cap` / `cost_of_equity` by **the same amount for every symbol**. That is meaningless: a regulated utility's bear case is not the same shift as a small-cap industrial's. Brief 25 lets users override the scenario assumptions per symbol while keeping the existing defaults as the fallback.

---

## Files Codex MUST read first

1. `core/quant_core/fundamentals/valuation.py` near the top — `DEFAULT_ASSUMPTIONS` and `SCENARIO_DEFAULT_OVERRIDES` (Codex greps the constant names; their lines have shifted historically).
2. `core/quant_core/fundamentals/valuation.py` — `compute_symbol_valuations` (~ line 916 at last check) and `compute_valuation_ensemble` (~ line 870 at last check). Codex greps the function names to find the current lines. **Do not modify these function bodies in this brief.**
3. `core/quant_core/fundamentals/domain.py` `AssumptionVersion` dataclass (grep — line has shifted). This is the canonical assumption-versioning shape; this brief reuses it.
4. `services/api/app/schemas/fundamentals.py` for the existing assumption surface.
5. `services/api/app/routers/fundamentals.py` — the router this brief extends. Codex confirms the file path by grep before adding endpoints.
6. `services/api/alembic/versions/` — Codex reads the latest existing migration file to copy its `revision = …` into the new migration's `down_revision`.

> **Line-number drift policy.** If any cited line has shifted, report the new line in the PR description and **proceed**. Do not stop. Codex finds the real lines by grepping the symbol names listed above.

---

## Scope

A per-(symbol, scenario) override table; an API to set/get/clear overrides; a single change point in the resolution function (today implicit in `compute_symbol_valuations`) where the override is merged on top of `SCENARIO_DEFAULT_OVERRIDES` which is merged on top of `DEFAULT_ASSUMPTIONS`.

Out of scope: per-symbol revenue / margin paths (that requires the projection driver from brief 22.B to be parameterised — separate follow-up brief if needed). This brief only overrides the *scalar* assumption set.

---

## Data model

### Table `fundamental_assumption_override`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | BIGSERIAL | PK |  |
| `symbol` | TEXT | NOT NULL |  |
| `scenario` | TEXT | NOT NULL CHECK in `('bear','base','bull')` |  |
| `overrides` | JSONB | NOT NULL | Subset of `DEFAULT_ASSUMPTIONS` keys with overriding values. Keys NOT in `DEFAULT_ASSUMPTIONS` → 422. |
| `note` | TEXT | NULL | Why this override exists (analyst rationale). |
| `created_by` | TEXT | NOT NULL |  |
| `created_at` | TIMESTAMP | NOT NULL DEFAULT now() |  |
| `is_current` | BOOLEAN | NOT NULL DEFAULT true |  |

Indexes:
- `UNIQUE (symbol, scenario) WHERE is_current = true`
- `(symbol, created_at DESC)`

History pattern is identical to brief 23 (`is_current` flip in the same transaction).

### Migration

- File path pattern: `services/api/alembic/versions/<rev>_add_fundamental_assumption_override.py`. Generate `<rev>` the same way the other migrations did (alembic revision id).
- `down_revision`: Codex MUST read the latest existing file in `services/api/alembic/versions/` and copy its `revision = …` string verbatim. Do not hand-pick a parent.
- Upgrade body: create `fundamental_assumption_override` with the columns and indexes spec'd above.
- Downgrade body: `op.drop_table('fundamental_assumption_override')` — no data preservation.
- Acceptance: the sequence `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` MUST be clean (no errors, no leftover objects). Add this to the PR description as a manual verification step.

---

## Resolution function

Add `resolve_assumptions(symbol, scenario, *, overrides_loader)` to `core/quant_core/fundamentals/valuation.py` (or to a new `assumptions.py` sibling — Codex chooses; **must be importable from both worker and API**, no circular import).

```python
def resolve_assumptions(
    symbol: str,
    scenario: str,
    overrides_loader: Callable[[str, str], dict[str, float] | None] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Returns (resolved_assumptions, provenance).

    provenance[key] is one of 'default' / 'scenario' / 'symbol'.
    Every key present in `resolved_assumptions` MUST appear in `provenance`.
    """
    resolved = dict(DEFAULT_ASSUMPTIONS)
    provenance: dict[str, str] = {k: "default" for k in resolved}

    scenario_overlay = SCENARIO_DEFAULT_OVERRIDES.get(scenario, {})
    for k, v in scenario_overlay.items():
        resolved[k] = v
        provenance[k] = "scenario"

    if overrides_loader is not None:
        sym_override = overrides_loader(symbol, scenario) or {}
        for k, v in sym_override.items():
            if k not in DEFAULT_ASSUMPTIONS:
                raise ValueError(f"unknown assumption key: {k}")
            resolved[k] = float(v)
            provenance[k] = "symbol"

    return resolved, provenance
```

`overrides_loader` is injected so the pure-domain layer stays DB-free. The worker / API supply a loader that reads from `fundamental_assumption_override` for `is_current=true` rows.

### Loader factory (API)

- Lives in `services/api/app/services/fundamentals.py` (Codex confirms by grep; do not invent a new module).
- Signature: `make_overrides_loader(db: Session) -> Callable[[str, str], dict[str, float] | None]`.
- Builds a closure that issues `SELECT overrides FROM fundamental_assumption_override WHERE symbol = :s AND scenario = :sc AND is_current = true` per call. Sessions are request-scoped — no module-level caches.
- **Circular-import guardrail:** `core/quant_core/**` MUST NOT import anything under `services/**`. The pure-domain `resolve_assumptions` only knows about the injected callable.

### Bulk loader (worker)

The worker refresh loop calls `compute_symbol_valuations` for many symbols × 3 scenarios. A per-call loader would issue 3N queries. For the worker path:

- Pre-fetch all overrides for the refresh batch in **one** query: `SELECT symbol, scenario, overrides FROM fundamental_assumption_override WHERE symbol IN (...) AND is_current = true`.
- Build an in-memory `dict[(symbol, scenario), dict[str, float]]` and wrap the dict lookup in a closure that matches `Callable[[str, str], dict[str, float] | None]`.
- The API hot path (single-symbol request) keeps the naive per-call loader — overhead is negligible there.

**Call sites that change**: wherever today the code does `assumptions = dict(DEFAULT_ASSUMPTIONS); assumptions.update(SCENARIO_DEFAULT_OVERRIDES.get(scenario, {}))`, replace with `resolved, provenance = resolve_assumptions(symbol, scenario, overrides_loader=...)`. Both halves must flow through. Codex finds the call sites by grepping `SCENARIO_DEFAULT_OVERRIDES` — there should be at most 2.

`SCENARIO_DEFAULT_OVERRIDES` and `DEFAULT_ASSUMPTIONS` themselves are NOT modified.

---

## API surface

All endpoints live in `services/api/app/routers/fundamentals.py` (Codex confirms the file path by grep before adding).

| Method | Path | Notes |
|---|---|---|
| `GET` | `/fundamentals/{symbol}/assumptions/{scenario}` | Returns the *resolved* dict (after all three layers) + a `provenance: dict[key, "default"\|"scenario"\|"symbol"]`. Public read (same auth as other read endpoints in this router). |
| `GET` | `/fundamentals/{symbol}/assumptions/{scenario}/override` | Returns the current `fundamental_assumption_override` row or 404. Public read. |
| `PUT` | `/fundamentals/{symbol}/assumptions/{scenario}/override` | Body `{overrides: dict, note: str}`. Validates keys ∈ `DEFAULT_ASSUMPTIONS`; validates value types (all floats). Writes new row, flips prior. Requires authenticated principal (see below). |
| `DELETE` | `/fundamentals/{symbol}/assumptions/{scenario}/override` | Flips current to `is_current=false`. The resolved view reverts to defaults. Requires authenticated principal. |

### Authorization and audit

- PUT / DELETE MUST reuse the **same role gate** as the existing fundamental-thesis endpoints. Codex greps `services/api/app/routers/fundamentals.py` for the dependency injected by the thesis routes (brief 23) and reuses it verbatim. Do not introduce a new role.
- `created_by` is filled from the authenticated principal (e.g. `current_user.email` or whatever the codebase calls it). **Never** accept `created_by` from the request body — strip it if present.
- `401` if unauthenticated, `403` if authenticated but not allowed, `422` on unknown assumption key or non-float value.

---

## Snapshot envelope

### Verify the envelope shape before depending on it

Brief 25 assumes the per-symbol envelope endpoint already returns three `EnsembleResult`s (one per scenario, indirectly via `compute_valuation_ensemble`). Codex MUST verify this **before** building on it:

1. Read `services/api/app/schemas/fundamentals.py` and identify the envelope schema returned by the per-symbol endpoint.
2. Determine whether it carries a single scenario (`base` only) or all three (`bear` / `base` / `bull`).
3. **If single-scenario today:** brief 25 also has to widen the envelope. Codex must (a) call this out explicitly in the PR description, (b) extend the schema, (c) update the router to compute three ensembles per request, (d) update the worker write path if the persistence shape also assumes one scenario, (e) refresh the frontend contract types in `frontend/lib/`. This is non-trivial added scope — flag it before starting work.
4. **If multi-scenario today:** confirm in the PR description and proceed.

Do not let Codex discover this mismatch at integration time.

### Provenance field

Add `assumption_provenance: dict[scenario, dict[key, "default"|"scenario"|"symbol"]]` to the envelope so the UI can render which assumptions were overridden. Provenance is produced by `resolve_assumptions` (Patch C in plan) — pipe the second return value through unchanged.

---

## UI spec update

This brief updates `docs/fundamentals-layer/20-claude-design-handoff.md` Valorisation tab **only** — design spec, not React code:

- A small "Hypothèses" expander per scenario showing the resolved value with a chip (`défaut` / `scénario` / `personnalisé`) per key.
- An Edit button that opens a form with the keys of `DEFAULT_ASSUMPTIONS` (typed numeric inputs, with the default shown as placeholder).

**Out of scope for this brief:**
- Any React / TSX component code.
- Chart re-rendering / debouncing on assumption edit.
- Zustand / TanStack store or mutation hooks.
- Optimistic UI on PUT.

The actual frontend wiring (component, hook, store, render plumbing) is a follow-up brief once the API is live.

---

## Tests

`core/tests/test_assumption_resolution.py`:
- `test_resolve_returns_defaults_when_no_override` — `bull` scenario, no override, resolved dict equals `DEFAULT_ASSUMPTIONS | SCENARIO_DEFAULT_OVERRIDES['bull']`, provenance maps each touched key to `"scenario"` and untouched keys to `"default"`.
- `test_resolve_applies_symbol_override` — loader returns `{wacc: 0.10}` for `(ATW, bull)`, resolved has `wacc=0.10`, provenance has `wacc="symbol"`.
- `test_resolve_rejects_unknown_key` — loader returns `{foo: 1}`, raises `ValueError`.
- `test_resolve_provenance_layering` — round-trip a key set across all three layers; provenance string is exactly `"default"` / `"scenario"` / `"symbol"` per key.
- `test_bulk_loader_one_query_for_many_symbols` — instantiate the worker bulk loader for 50 symbols × 3 scenarios; use `sqlalchemy.event.listen` on `do_execute` to count queries; assert exactly **1** SELECT against `fundamental_assumption_override`.

`services/api/tests/test_fundamentals_assumption_overrides.py`:
- PUT, GET resolved, GET override, DELETE, second PUT supersedes prior.
- 422 on unknown key, 422 on non-float value.
- 401 unauthenticated PUT, 403 authenticated-but-not-allowed PUT (using the same role fixture as the thesis tests in brief 23).
- `created_by` from request body is ignored — server fills from principal.

---

## Acceptance criteria

- [ ] All tests green.
- [ ] Migration upgrade / downgrade clean.
- [ ] Calling `compute_symbol_valuations` with no override produces the SAME fair values as today (regression test on at least one MASI symbol). The brief MUST NOT silently shift fair values.
- [ ] Calling with an override changes the fair value in the expected direction (e.g. `wacc += 100 bps` lowers FCFF/FCFE DCF fair value).
- [ ] `assumption_provenance` field is populated on the envelope response.
