# 07 — Gotchas and Verification

## Common mistakes to avoid

### Export script

1. **Do NOT import `_get_or_compute` from `strategy_signals.py`** — it depends on FastAPI `HTTPException` and the in-process cache. The export script replicates the core logic (load OHLCV, truncate, clean, run ensemble) as plain Python. See doc 01 for the implementation.

2. **OBV family will fail for stocks without volume data.** The export script must `try/except` per family and skip gracefully. A stock with 3 working families is still valid. Only skip the stock entirely if ALL families fail.

3. **Use `cost_bps=10.0`, `cooldown_bars=0`, `timeframe="1D"`** — these are the defaults from the signals page (`strategy_signals.py` request schemas). Do not hardcode different values.

4. **The `sector` field may come from 3 sources**: `stock_master` DB table, `_RAW_MASI_TICKERS` dict, or `_OFFICIAL_SECTOR_OVERRIDES` dict. The export script should use `get_masi_info(symbol)` from `masi_tickers.py` as fallback when `stock_master.sector` is NULL. See `market_data.py:1263-1264` for the pattern.

5. **Signal labels have NO accents.** `signal_type_label()` in `domain.py` returns `"Tres haussier"` (not `"Tres"`) and `"Surachete"` (not `"Surachete"`). This is by design in the existing codebase. Do NOT add accents anywhere.

6. **The DB must be running** when the export script runs. Default connection: `postgresql+psycopg2://app:app@127.0.0.1:5555/quant` (from `services/api/app/config.py:6`).

### Frontend components

7. **Do NOT use `apiFetcher` or `request()` for dashboard data.** The dashboard reads static JSON via `fetch('/data/scores-{horizon}.json')`. It does NOT go through the `/api` proxy. This is what makes it deployable to GitHub Pages.

8. **The `/data/` path in `fetch()` resolves to `frontend/public/data/`** in Next.js. This is the standard public file serving convention. Do not confuse with the `/data` page route.

9. **Handle missing `per_family` entries.** Not all stocks have all 4 families (OBV is commonly missing). When `stock.per_family.obv` is undefined, `<FamilyCell>` should show "—". Test this explicitly.

10. **Sort must be stable.** When two stocks have identical scores, maintain their original array order. Use the array index as a tiebreaker in the sort comparator:
    ```typescript
    .sort((a, b) => {
      const diff = getSortValue(b, sortKey) - getSortValue(a, sortKey)
      if (diff !== 0) return sortDir === "desc" ? diff : -diff
      return 0  // stable: preserve original order
    })
    ```

11. **Do NOT break existing navigation.** The `isActive` check in `signals-header.tsx` uses `pathname.startsWith(item.href)`. Since `/dashboard` doesn't collide with `/data`, `/signals`, `/strategy`, or `/backtest`, this works without modification.

12. **The `Tabs` component** exists at `frontend/components/ui/tabs.tsx`. Use it for horizon tabs. Do NOT create a custom tab implementation.

13. **The `Input` component** exists at `frontend/components/ui/input.tsx`. Use it for the search field in StockTable.

14. **The `Card` components** exist at `frontend/components/ui/card.tsx`. Use `Card, CardContent, CardHeader, CardTitle` for the IndexSummary and error/empty states.

15. **The `Skeleton` component** exists at `frontend/components/ui/skeleton.tsx`. Use it for loading states.

16. **The `Table` components** exist at `frontend/components/ui/table.tsx`. Use `Table, TableBody, TableCell, TableHead, TableHeader, TableRow` for both StockTable and SectorTable.

17. **The `Collapsible` component** exists at `frontend/components/ui/collapsible.tsx`. Use it for expandable sector rows in SectorTable.

### Static export

18. **`frontend/app/api/[...path]/route.ts` will break static export.** See doc 06 for the conditional approach using `STATIC_EXPORT` env variable.

19. **Dynamic route pages need `generateStaticParams()`** returning `[]` for static export. See doc 06.

20. **`basePath` must be prepended to raw `fetch()` calls.** The `use-dashboard.ts` hook already handles this with `process.env.NEXT_PUBLIC_BASE_PATH`. But if you add any other `fetch()` calls, remember to prepend it.

---

## Verification checklist

### After export script (doc 01)

```bash
cd <repo-root>
.venv/Scripts/python frontend/scripts/export-scores.py
```

- [ ] Script completes without errors
- [ ] 3 JSON files created in `frontend/public/data/`: `scores-short.json`, `scores-medium.json`, `scores-long.json`
- [ ] Each file has a `stocks` array with entries (count depends on how many symbols have data)
- [ ] Each stock entry has `per_family` with 3-4 families (OBV may be absent)
- [ ] Each stock has `aggregate_score_pct` (number) and `aggregate_signal_label` (string)
- [ ] `sectors` array has entries grouped by sector
- [ ] `index` has `breadth` object with `achat + neutre + vente` summing to total stocks
- [ ] Spot-check: pick a symbol, compare its scores with what the `/signals` page shows

### After types and constants (doc 02)

- [ ] `frontend/lib/dashboard-types.ts` exists with all interfaces
- [ ] `frontend/lib/dashboard-constants.ts` exists with all constants
- [ ] `frontend/hooks/use-dashboard.ts` exists
- [ ] No TypeScript errors in these files

### After components (doc 03)

- [ ] All 6 files exist in `frontend/components/dashboard/`
- [ ] `npm run dev` starts without errors
- [ ] No TypeScript errors in the component files

### After dashboard page (doc 04)

- [ ] `frontend/app/dashboard/page.tsx` exists
- [ ] Navigate to `/dashboard` — page loads with data from JSON
- [ ] Horizon tabs work — switching loads different JSON file, data changes
- [ ] View tabs work — stocks/secteurs/indice each render
- [ ] Stock table: search filters, sector dropdown filters, column sort works
- [ ] Sector table: click to expand shows constituent stocks
- [ ] Index summary: family cards render, breadth bar shows percentages
- [ ] Signal badges have correct colors (green = bullish, red = bearish, grey = neutral)
- [ ] Score bars render centered at zero, extend correct direction
- [ ] Loading skeleton appears briefly on horizon change
- [ ] If JSON files are missing, error card appears (not blank page)

### After navigation update (doc 05)

- [ ] Navigation bar shows 5 items: Tableau de Bord, Data, Signals, Strategy, Backtest
- [ ] "Tableau de Bord" is the FIRST item (leftmost)
- [ ] "Tableau de Bord" is highlighted when on `/dashboard`
- [ ] Clicking the "BT" logo navigates to `/dashboard`
- [ ] Navigate to `/` — redirects to `/dashboard`
- [ ] All existing pages still work: `/data`, `/signals`, `/strategy`, `/backtest`

### After static export (doc 06)

- [ ] `STATIC_EXPORT=true npm run build` completes
- [ ] `out/` directory contains `dashboard/index.html`
- [ ] `npx serve out` — dashboard loads at `localhost:3000/dashboard`
- [ ] No API calls in browser Network tab — only JSON file fetches
- [ ] Horizon tabs and view tabs work in static build

---

## Edge cases to test manually

| Scenario | Expected behavior |
|----------|------------------|
| Stock with no OBV data | 3 families shown, OBV column shows "—" |
| Stock with all families failing | Stock excluded from the list entirely |
| Sector with 1 stock | Sector row shows "(1 action)", expand shows 1 stock |
| All stocks in same sector | Sector view shows 1 sector row |
| Empty JSON (no stocks) | Dashboard shows "Aucune donnee disponible" with link to /data |
| JSON file missing (404) | Dashboard shows error card with message |
| Very long display_name | Text truncates with ellipsis (use `truncate` class) |
| Score exactly 0 | Score bar shows nothing at center, badge shows "Neutre" |
| Score exactly +100 or -100 | Score bar extends full width to the edge |
