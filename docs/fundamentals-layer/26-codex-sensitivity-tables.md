# 26 — Codex brief: sensitivity tables (P2 quick win)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/financial-analysis/0.1.1/skills/dcf-model/SKILL.md` § sensitivity tables.
>
> **Why.** Danger D7. A 50 bps WACC shift can move fair value 15–25 %. The user today sees one base fair value and one quartile band; they cannot tell whether the upside is robust to assumption noise. Brief 26 adds a 5×5 grid per scenario per symbol.

---

## Files Codex MUST read first

1. `core/quant_core/fundamentals/valuation.py` — specifically `compute_symbol_valuations` (line 814) and `compute_valuation_ensemble` (line 742). The sensitivity helper REUSES these — it does not duplicate model math.
2. `core/quant_core/fundamentals/domain.py` `EnsembleResult`. The sensitivity result is **not** a new dataclass type — it is a JSON-serialisable nested dict attached to `EnsembleResult.diagnostics` (Codex adds a `diagnostics: dict | None` field to the dataclass if it does not exist; see "Domain change" below).
3. `services/api/app/schemas/fundamentals.py` for the existing valuation schema shape.

---

## Scope

A pure-function `compute_sensitivity_grid` that, given a symbol, scenario, and a list of two assumption keys to vary, returns a 5×5 grid of ensemble fair values. Two grids are computed by default per scenario:
- `wacc` × `terminal_growth`
- `wacc` × `growth_cap`

Result is attached to the existing valuation response — additive only.

---

## Function signature

Add to `core/quant_core/fundamentals/valuation.py` (or `sensitivity.py` sibling — Codex's call, but importable from the worker):

```python
def compute_sensitivity_grid(
    snapshot: FundamentalSnapshot,
    scenario: str,
    overrides_loader: Callable[[str, str], dict[str, float] | None] | None,
    axis_x: tuple[str, list[float]],   # ("wacc", [-0.01, -0.005, 0, 0.005, 0.01])
    axis_y: tuple[str, list[float]],   # ("terminal_growth", [-0.01, -0.005, 0, 0.005, 0.01])
    *,
    rng: Random | None = None,
) -> dict[str, Any]:
    """
    Returns:
      {
        "axis_x": {"key": "wacc", "values": [resolved_wacc + delta for delta in ...]},
        "axis_y": {"key": "terminal_growth", "values": [...]},
        "fair_value_base": [[float|None, ...], ...],   # 5x5
        "upside_pct":       [[float|None, ...], ...],  # 5x5
        "confidence_score": [[float|None, ...], ...],
      }
    """
```

The deltas are **additive** to the resolved assumption value (so the centre cell `[2][2]` reproduces the no-shift ensemble). Symmetric deltas around 0 are the default; the absolute steps come from new constants in `DEFAULT_ASSUMPTIONS`:

```python
"sensitivity_wacc_step": 0.005,
"sensitivity_terminal_growth_step": 0.005,
"sensitivity_growth_cap_step": 0.01,
```

Add those three keys to `DEFAULT_ASSUMPTIONS` in `valuation.py:16-33`. Document in `08-assumptions-and-defaults.md`.

The function MUST NOT mutate snapshot. It MUST go through `resolve_assumptions` (brief 25) so per-symbol overrides are honoured. For each grid cell, build a *temporary* assumption dict, call `compute_symbol_valuations` + `compute_valuation_ensemble`, take `fair_value_base`. Performance budget: 25 cells × 7 models per cell — acceptable; Codex does not add caching in this brief.

If `compute_valuation_ensemble` returns `fair_value_base=None` for a cell (e.g. all models below confidence threshold), the cell is `None` in the grid, not zero.

---

## Domain change

If `EnsembleResult` does not already have a free-form diagnostics field, add one as **optional** to preserve backward compat:

```python
@dataclass(frozen=True)
class EnsembleResult:
    ...
    sensitivity_grids: dict[str, Any] | None = None
```

Two grids are stored: `sensitivity_grids["wacc_x_terminal_growth"]` and `sensitivity_grids["wacc_x_growth_cap"]`.

Wiring point: in the worker/API layer that calls `compute_valuation_ensemble`, after the ensemble call, run `compute_sensitivity_grid` twice and merge into the returned `EnsembleResult` (use `dataclasses.replace`). Do **not** call the grid from inside `compute_valuation_ensemble` — that function stays pure / cheap.

---

## API surface

`EnsembleResultOut` gains `sensitivity_grids: dict[str, SensitivityGridOut] | None`.

`SensitivityGridOut`:
```
{
  axis_x: {key: str, values: list[float]},
  axis_y: {key: str, values: list[float]},
  fair_value_base: list[list[float | None]],
  upside_pct: list[list[float | None]],
  confidence_score: list[list[float | None]],
}
```

No new endpoint — the grids ride on the existing valuation envelope.

---

## UI spec

Update `docs/fundamentals-layer/20-claude-design-handoff.md` Valorisation tab:
- A "Sensibilité" block per scenario, with two heatmap tables (5×5 each). Cells colour-graded by `upside_pct` (red < 0, neutral 0–10 %, green > 10 %). Center cell highlighted.

No frontend code in this brief.

---

## Tests

`core/tests/test_sensitivity_grid.py`:
- `test_center_cell_matches_ensemble` — `grid["fair_value_base"][2][2] == compute_valuation_ensemble(...).fair_value_base` to floating tolerance.
- `test_monotonic_in_wacc` — for a healthy snapshot with positive FCF, raising `wacc` lowers `fair_value_base` monotonically along the WACC axis.
- `test_grid_handles_none_cells` — synthetic snapshot where some cells fail confidence threshold returns `None` in those cells, not 0.
- `test_grid_does_not_mutate_snapshot` — pre/post equality.
- `test_grid_respects_symbol_override` — with a symbol override that bumps WACC by 100 bps, the centre cell value matches the override ensemble (not the default-only ensemble).

---

## Acceptance criteria

- [ ] All tests green; no regression in the existing 91+ tests.
- [ ] Performance: full envelope response for one symbol completes in < 3 s on the existing benchmark machine (the budget is informal; Codex flags if blown).
- [ ] `EnsembleResultOut.sensitivity_grids` is populated on the API response.
- [ ] `08-assumptions-and-defaults.md` mentions the three new keys.
