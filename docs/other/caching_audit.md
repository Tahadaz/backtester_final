# Current-State Caching Audit

## Scope
The repository on disk is not the multi-service app described in the brief. The live code under `/mnt/c/Users/taha/Desktop/backtester` is a single-process Streamlit backtester plus an `others/` experimental pipeline. The requested `quant-backtesting-frontend`, `services/api`, `services/worker`, `core/quant_core`, `infra/docker-compose.yml`, Redis, MinIO, SWR, route handlers, and proxy fetch layers do not exist here.

A second `backtester/` package tree exists, but the documented entrypoint `streamlit run backtester/app.py` is currently non-runnable because `backtester/app.py`, `backtester/optimize.py`, and `backtester/portfolio.py` contain unresolved merge-conflict markers and fail `ast.parse` / `py_compile`. The conflict-free top-level files `app.py`, `data.py`, `indicators.py`, `engine.py`, `optimize.py`, `portfolio.py`, `results.py`, and `streamlit_app.py` are syntactically valid.

## Discovery Appendix
- Search patterns used:
  - `rg -n '(cache|cached|memo|SWR|stale|revalidate|poll|refreshInterval|dedup|idempot|redis|minio|artifact|sha256|hashlib|lru_cache|functools|localStorage|sessionStorage|indexedDB|best|latest|snapshot|global|singleton|ttl|etag|If-None-Match|Last-Modified)'`
  - `rg -n '@st.cache_data|st.session_state|_mem_cache|_framehash_cache|_cache_key\(|run_stats_only|persist'`
  - `rg -n '^(<<<<<<<|=======|>>>>>>>)' backtester`
  - `python3` + `ast.parse(...)` on top-level and `backtester/` copies
- Cache-relevant files found:
  - `app.py`
  - `streamlit_app.py`
  - `data.py`
  - `indicators.py`
  - `engine.py`
  - `optimize.py`
  - `portfolio.py`
  - `others/engine.py`
  - `others/optimizer.py`
  - `backtester/app.py`
  - `backtester/optimize.py`
  - `backtester/portfolio.py`
  - `README.md`
- Files inspected deeply:
  - `app.py`
  - `streamlit_app.py`
  - `data.py`
  - `indicators.py`
  - `engine.py`
  - `optimize.py`
  - `portfolio.py`
  - `results.py`
  - `strategy.py`
  - `others/engine.py`
  - `others/optimizer.py`
  - `backtester/app.py`
  - `backtester/optimize.py`
  - `backtester/portfolio.py`
- Files excluded from primary analysis:
  - `.git/**`
  - `.venv/**`
  - `__pycache__/**`
  - `.cache/**`
  - `backtester/.cache/**`
  - `runs/**` (empty/generated)
  - sample data files like `DATA IAM.xlsx`
  - `README.md` used only to confirm the documented entrypoint

## Mandatory Hotspots
- Frontend SWR polling/gating and proxy fetch behavior: absent from live repo.
- Worker artifact SHA dedupe and object-key reuse: absent.
- Worker local dataset/store caches and invalidation gaps: absent.
- Process-global market-data caches in `engine.py` and `optimize.py`: absent. This is an expensive no-cache path.
- Indicator/DataFrame cache reuse and mutation risk: present in `indicators.py`.
- Dataset upload dedupe and persisted best/latest snapshot tables: upload dedupe exists in `app.py`; persisted best/latest tables do not exist.
- Redis usage affecting idempotency or stale job state: absent.

## Part 1: Caching Map

| Layer | Mechanism | Location | Classification | Evidentiary status | What is retained/reused | Exact implemented identity/key construction fields | Identity fields missing for correctness | Scope | Lifetime / TTL | Invalidation / refresh | Explicit vs accidental | Category | Safety judgment | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Frontend | Uploaded file content-addressed path | `app.py` | persistence / artifact store | proven from code | Uploaded bytes on disk under `~/.backtester_cache/uploads` | `f"{tag}_{safe_sym}_{sha1(bytes)}{suffix}"` where `safe_sym` is sanitized symbol and `suffix` comes from filename extension | user/tenant, explicit file-content recheck of existing path | host filesystem | survives reruns and restarts | none; file reused if same path exists and size matches | explicit | correctness-sensitive reuse | Safe for identical bytes; shared-host multi-user isolation is absent | high |
| Frontend | Benchmark market data Streamlit cache | `app.py` | true cache | strongly indicated by code | Returned `MarketData` from benchmark loader | Streamlit `@st.cache_data` over function args: `bench_source_key, bench_symbol, timezone, interval, bmce_path, start, end, yf_period, yf_interval, yf_auto_adjust` | remote data freshness/version; `yf_period` is included in identity but ignored by behavior | Streamlit runtime | no TTL configured | arg change or external Streamlit cache clear only | explicit | ambiguous/unsafe reuse | BMCE path is content-addressed; yfinance benchmark can go stale | medium |
| Frontend | Backtest bundle session cache | `app.py` | true cache | proven from code | Full `BacktestBundle` in `st.session_state` | key is `("bundle", str(base_spec))`; `base_spec` repr includes `DataConfig`, `IndicatorsConfig`, `StrategyConfig`, `PortfolioConfig`, default benchmark config, plot indicators, rates | remote fetch freshness/version, code version, any benchmark mutation applied after bundle creation | Streamlit session | until session ends or key replaced | exact key change only | explicit | correctness-sensitive reuse | Safe for immutable BMCE uploads; stale for yfinance within one session | high |
| Frontend | Widget/session reuse | `app.py` | browser/runtime reuse | proven from code | `prev_strategy_kind`, upload paths, file hashes, param editor values | raw session-state keys such as `prev_strategy_kind`, `bmce_cached_path`, `bench_cached_path`, `dw_*` | broader form identity if results should be invalidated when inputs change | Streamlit session | until session ends | manual key deletion only for keys ending `_min/_max/_step/_choices` | explicit | ambiguous/unsafe reuse | Partial invalidation only; stale auxiliary UI state is possible | high |
| Frontend alt UI | Excel loader Streamlit cache | `streamlit_app.py` | true cache | strongly indicated by code | Loaded DataFrame from uploaded Excel | Streamlit `@st.cache_data` over `uploaded_file, sheet_name, start, end` | exact uploaded file content hash is delegated to Streamlit internals; no explicit TTL | Streamlit runtime | no TTL configured | arg change or cache clear | explicit | safe performance cache | Probably safe for static uploads; multi-user semantics depend on Streamlit internals | medium |
| Quant core | Data-source pickle cache | `data.py` | true cache | proven from code | Raw `dict[str, DataFrame]` pickled under `cache_dir/key.pkl` | `sha256(json.dumps({"cls": self.__class__.__name__, "symbols": list(symbols), "start": start, "end": end, "interval": interval, "timezone": self.timezone, "kwargs": kwargs}, sort_keys=True))` | local file content hash/mtime for BMCE paths, remote provider freshness/version, code version | process + shared filesystem if enabled | survives restarts if `cache_dir` configured | none; exact key miss only | explicit | ambiguous/unsafe reuse | Currently dormant in main flows because callers construct data sources without `cache_dir`; unsafe if enabled as-is | high |
| Quant core | Feature memory cache | `indicators.py` | true cache | proven from code | Cached feature `DataFrame` objects in `_mem_cache` | `f"{symbol}__{spec.spec_hash(engine_version)}__{data_hash}"`; `spec_hash` includes `indicator, sorted params, inputs, name, warmup, output_mode, version`; `data_hash` hashes index + input-column values | actual indicator implementation version unless `engine_version` is manually bumped | `IndicatorEngine` instance | object lifetime only | new engine instance or key miss | explicit | ambiguous/unsafe reuse | Returned by reference, not copied; current consumers appear read-only, but mutation would taint later hits | high |
| Quant core | Feature disk cache | `indicators.py` | true cache | proven from code | Pickled feature `DataFrame` files in `.cache/features` | same key as memory cache, file path `${cache_dir}/${key}.pkl` | code version unless `engine_version` changes; concurrency guards | shared filesystem | survives restarts | none; exact key miss only | explicit | correctness-sensitive reuse | No lock, no temp-file write, no atomic rename; multi-process readers/writers can race or corrupt | high |
| Quant core | Frame-hash reuse | `indicators.py` | memoization | proven from code | `data_hash` memoized in `_framehash_cache` | `(id(bars), tuple(inputs))` | bars content/version if `bars` mutates in place | `IndicatorEngine` instance | object lifetime only | new engine instance only | explicit | ambiguous/unsafe reuse | Correct only while `bars` object remains immutable | high |
| Quant core | In-run optimization bank reuse | `optimize.py` | memoization | proven from code | `md`, aligned `common_index`, precomputed feature bank arrays, `bars_close` reused across trial loop | no external key; reuse is lexical within one `run_optimization(...)` invocation | cross-call identity intentionally absent | function call | one optimization call | function return | explicit | safe performance cache | Safe and local; no cross-run staleness because nothing persists | high |
| Quant core | Market-data caching in engine/optimize | `engine.py`, `optimize.py` | not actually cache-like | proven from code | nothing retained | data sources are instantiated as `BMCEDataSource(timezone=...)` / `YahooFinanceDataSource(timezone=...)` with no `cache_dir` | all freshness and content reuse dimensions because no cache exists | per call | none | recomputes/reloads every call | accidental absence | expensive no-cache path | Safe for correctness, expensive for repeated runs | high |
| Experimental | Runner artifact cache | `others/optimizer.py` | true cache | proven from code | `RunArtifact` objects in `self.cache` | `sha256(f"{self.symbol}|{start}|{end}|{params_key}")`, `params_key` is sorted param string | bars content/version, feature provider version, strategy/execution/report code version, objective | `BacktestRunner` object | object lifetime only | none | explicit | ambiguous/unsafe reuse | Same mutable artifact object is returned by reference; `score` is mutated after retrieval and key ignores objective | high |
| Experimental | Result store under `runs/` | `others/engine.py` | persistence / artifact store | proven from code | JSON/CSV/parquet/PNG artifacts on disk | run dir from `_run_id`: first 16 hex of `sha256(json.dumps({"name","symbol","sorted params","start","end","data_kwargs"}, sort_keys=True))` | strategy factory / feature factory code identity, tags, code version | shared filesystem | survives restarts | none; always recomputed, then overwritten | explicit | ambiguous/unsafe reuse | Not a cache today because no read path exists; directory collisions can overwrite prior artifacts | high |
| Frontend broken duplicate | Persisted optimization snapshot in `backtester/app.py` | `backtester/app.py` | browser/runtime reuse | strongly indicated by code | `opt_best_bundle`, `opt_best`, `opt_top_df` reused on later reruns | presence-only checks on fixed session keys, no request signature | source, symbol, dataset, params, benchmark, strategy, code version | would be Streamlit session | until session ends | overwritten only by another optimization | explicit | ambiguous/unsafe reuse | If this file compiled, it would display stale optimization results across unrelated input changes; today the file is non-executable | medium |

## Part 2: End-to-End Flow

### Uploaded dataset run
1. Upload enters `app.py`.
2. `_persist_upload_to_cache` writes a content-addressed file under `~/.backtester_cache/uploads`; this is persistence/dedup, not a true cache.
3. Session state stores `bmce_cached_path` and `bmce_file_hash`.
4. Backtest uses `bmce_cached_path` to build `base_spec`.
5. `st.session_state.get(("bundle", str(base_spec)))` decides whether to reuse an existing `BacktestBundle`.
6. On a miss, `engine.py` calls `load_marketdata`, which creates `BMCEDataSource(timezone=...)` with no `cache_dir`; file data is reread and normalized every run. This is recomputed, not cached.
7. `IndicatorEngine` is created with disk and memory cache enabled by default. Feature reuse can hit memory or `.cache/features/*.pkl` keyed by symbol + spec hash + data hash.
8. Strategy signals are recomputed from market data and features.
9. Portfolio results are recomputed.
10. Results/report are recomputed.
11. The resulting bundle is cached in session state by exact `str(base_spec)` only.
12. Frontend display reads directly from the bundle; no polling exists.

### Canonical / market-data-backed run
1. UI builds `base_spec` with `source="yfinance"`.
2. Backtest bundle session cache still keys only on `str(base_spec)`.
3. On a miss, `engine.py` downloads from yfinance with no data cache.
4. Feature computation can hit `.cache/features` if the normalized bars hash matches a prior run.
5. Signals, portfolio, and report are recomputed.
6. On a later same-spec request in the same Streamlit session, the bundle cache can serve stale yfinance-backed results because no fetch freshness token participates in the key.

### Optimization / WFO-like path ending in artifacts and frontend display
1. Top-level optimization UI in `app.py` builds `active_params` and `OptimizeConfig`.
2. `optimize.py` loads market data once per optimization call. No market-data cache is active.
3. `optimize.py` precomputes the union of required SMA features once. This is memoization within the call, not a cross-run cache.
4. For each candidate, `optimize.py` optionally slices the common index, builds signals from precomputed arrays, and reuses `PortfolioEngine.run_stats_only(...)` when possible.
5. Optimization results are returned to the UI but are not persisted in the top-level app. A rerun loses them unless the user runs again.
6. If the user clicks “Run best configuration backtest”, the app recomputes a full `BacktestBundle` via `engine.py`.
7. Benchmark market data may be reused via `@st.cache_data`; report recomputation itself is not cached.
8. Experimental artifact persistence exists only in `others/engine.py` when `persist=True`, writing into `runs/<run_id>`. No current UI reads those artifacts back, so this is persistence, not cache reuse.

## Part 3: Bug Hunt
1. The documented `backtester/` app path is syntactically broken.
2. Feature disk cache is correctness-sensitive and unsafe under concurrent runs.
3. Top-level session bundle caching can return stale yfinance results.
4. Benchmark cache can also go stale for yfinance-backed benchmarks.
5. `IndicatorEngine` returns cached mutable `DataFrame`s by reference.
6. `_framehash_cache` relies on `id(bars)` rather than content identity.
7. Market data has no active cache in current app flows.
8. Dormant `BaseDataSource` cache would be stale for edited local files if enabled.
9. Experimental `BacktestRunner.cache` has incomplete identity and shared mutable artifacts.
10. Persisted artifacts in `others/engine.py` do not prevent recomputation.
11. Requested stale-data controls do not exist: no polling logic, no browser storage, no Redis, no MinIO, no worker idempotency, no API cache headers, and no invalidation discipline beyond exact-key changes.

## Part 4: Evidence

### Finding 1
- Mechanism name: Feature disk cache
- File path: `indicators.py`
- Function/class: `IndicatorEngine._compute_one_symbol_one_spec`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: `indicators.py` builds `key = f"{symbol}__{spec.spec_hash(self.engine_version)}__{data_hash}"`, loads `${cache_dir}/${key}.pkl`, and writes it back with `pickle.dump`.
- Observed behavior: A later feature computation for the same key reuses a previously written `DataFrame` from `.cache/features` instead of recomputing the indicator.
- Reuse trigger: existence of `${cache_dir}/${key}.pkl`.
- Identity/key fields actually used: `symbol`; `spec_hash(engine_version)` where `spec_hash` serializes `indicator`, sorted `params`, `inputs`, `name`, `warmup`, `output_mode`, and `version`; `data_hash` from hashed index and hashed input-column values.
- Identity/key fields that should matter to correctness: symbol, full indicator config, input columns, full bars content/index after normalization, indicator engine code version.
- Missing key dimensions: actual indicator implementation version unless `engine_version` is manually changed; any concurrency lease or write-generation marker.
- Scope/lifetime: shared filesystem under `.cache/features`; survives process restarts and is shared by all processes using the same working directory.
- Invalidation/refresh behavior: none except exact-key miss or manual deletion.
- Why this matters: Correctness depends on the key being complete and on writers not racing. Current code has no write lock or atomic rename, so concurrent runs can read or write partially written pickles.
- Risk level: high
- Confidence level: high

### Finding 2
- Mechanism name: Backtest bundle session cache
- File path: `app.py`
- Function/class: backtest submit path
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: `app.py` builds `key = ("bundle", str(base_spec))`, looks up `st.session_state.get(key)`, and stores the computed bundle under that key.
- Observed behavior: Within one Streamlit session, identical `str(base_spec)` values skip recomputation and reuse the earlier `BacktestBundle`.
- Reuse trigger: exact session-state key hit on `("bundle", str(base_spec))`.
- Identity/key fields actually used: the full dataclass string representation of `EngineSpec` built by `make_base_spec`, which includes source selection, symbol(s), interval/timezone/date filters, BMCE path or yfinance args, indicator config, strategy params, portfolio config, and defaults for remaining engine fields.
- Identity/key fields that should matter to correctness: full request config plus data-source freshness or content identity and code version.
- Missing key dimensions: fetched-at time / remote market-data version for yfinance; code version; any later benchmark mutation of the bundle.
- Scope/lifetime: one Streamlit session.
- Invalidation/refresh behavior: only a different `str(base_spec)` or session end.
- Why this matters: For BMCE uploads, the cached path contains a content hash, so reuse is mostly correct. For yfinance, same-spec reruns within the same session can serve stale results after market data changes upstream.
- Risk level: high
- Confidence level: high

### Finding 3
- Mechanism name: Benchmark market-data Streamlit cache
- File path: `app.py`
- Function/class: `load_benchmark_market_data_cached`
- Classification: true cache
- Evidentiary status: strongly indicated by code
- Code evidence: The function is decorated with `@st.cache_data(show_spinner=False)`, and all benchmark loads flow through this function.
- Observed behavior: Streamlit is instructed to reuse benchmark load results across reruns for identical argument sets.
- Reuse trigger: Streamlit cache hit for the argument tuple `bench_source_key, bench_symbol, timezone, interval, bmce_path, start, end, yf_period, yf_interval, yf_auto_adjust`.
- Identity/key fields actually used: the function arguments above; exact hashing is delegated to Streamlit.
- Identity/key fields that should matter to correctness: benchmark source config, BMCE file content or yfinance freshness/version, symbol, interval, time range, provider settings.
- Missing key dimensions: explicit yfinance freshness/version or TTL; the code also includes `yf_period` in the cache signature but does not use it to load data.
- Scope/lifetime: Streamlit runtime-managed data cache.
- Invalidation/refresh behavior: argument change or explicit cache clear; no TTL is configured in code.
- Why this matters: BMCE benchmark paths are content-addressed, so reuse is mostly safe. For yfinance benchmarks, the cache can remain stale indefinitely from the code’s perspective.
- Risk level: medium
- Confidence level: medium

### Finding 4
- Mechanism name: Feature memory cache plus shared mutable return
- File path: `indicators.py`
- Function/class: `IndicatorEngine._compute_one_symbol_one_spec`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: `indicators.py` returns `self._mem_cache[key]` directly and stores `df_feat` directly; no `.copy()` appears on cache hits.
- Observed behavior: Later memory-cache hits return the same cached `DataFrame` object by reference.
- Reuse trigger: `key in self._mem_cache`.
- Identity/key fields actually used: same composite feature key as the disk cache.
- Identity/key fields that should matter to correctness: same fields as the disk cache, plus object immutability if reference reuse is intentional.
- Missing key dimensions: no immutability or copy discipline.
- Scope/lifetime: one `IndicatorEngine` instance.
- Invalidation/refresh behavior: new engine instance or exact-key miss.
- Why this matters: Current downstream consumers appear read-only, so there is no present in-place mutation bug in the inspected code. But the cache is aliasing mutable `DataFrame` objects, so a future in-place write would silently poison subsequent hits.
- Risk level: medium
- Confidence level: high

### Finding 5
- Mechanism name: Frame-hash memoization by object identity
- File path: `indicators.py`
- Function/class: `IndicatorEngine._hash_frame_cached`
- Classification: memoization
- Evidentiary status: proven from code
- Code evidence: `indicators.py` uses `k = (id(bars), tuple(inputs))` and returns the stored hash if present.
- Observed behavior: Within one engine instance, repeated hashing of the same `bars` object and input tuple skips recomputing the pandas hash.
- Reuse trigger: same Python object identity for `bars` plus identical `inputs`.
- Identity/key fields actually used: `id(bars)` and `tuple(inputs)`.
- Identity/key fields that should matter to correctness: actual bars content and index values plus inputs.
- Missing key dimensions: bars contents when the same object is later mutated in place.
- Scope/lifetime: one `IndicatorEngine` instance.
- Invalidation/refresh behavior: none except engine recreation.
- Why this matters: The optimization path benefits from avoiding repeated expensive hashing, but correctness depends on upstream not mutating `bars` after the first hash. No current in-place mutation of `market_data.bars` was found, so this is a latent correctness hazard rather than a proven present bug.
- Risk level: medium
- Confidence level: high

### Finding 6
- Mechanism name: Dormant data-source pickle cache
- File path: `data.py`
- Function/class: `BaseDataSource.load`, `_cache_key`, `_try_load_cache`, `_save_cache`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: `data.py` computes `cache_key`, loads or saves pickled bars if `self.use_cache and self.cache_dir`; `engine.py` and `optimize.py` instantiate data sources without `cache_dir`.
- Observed behavior: The cache exists in the module but is not active in the main backtest or optimization flows. If enabled, it would reuse raw bars by pickle file.
- Reuse trigger: exact hash hit of serialized class/symbols/start/end/interval/timezone/kwargs payload.
- Identity/key fields actually used: `cls`, `symbols`, `start`, `end`, `interval`, `timezone`, `kwargs`.
- Identity/key fields that should matter to correctness: source content identity for local files; upstream freshness/version for remote data.
- Missing key dimensions: BMCE file contents or mtime; yfinance freshness/version; code version.
- Scope/lifetime: shared filesystem if configured.
- Invalidation/refresh behavior: none except exact-key miss or manual file deletion.
- Why this matters: Today this is a major no-cache gap rather than an active reuse bug. If someone enables it later, BMCE path edits would not invalidate old cached bars because the key uses path strings, not file contents.
- Risk level: medium
- Confidence level: high

### Finding 7
- Mechanism name: In-run optimization precompute bank
- File path: `optimize.py`
- Function/class: `run_optimization`
- Classification: memoization
- Evidentiary status: proven from code
- Code evidence: `optimize.py` loads market data once, computes the union SMA set once, and reuses `bank` and `bars_close` inside the candidate loop.
- Observed behavior: One optimization call avoids reloading data and recomputing indicators per trial.
- Reuse trigger: all candidates in the same `run_optimization(...)` call share the same local `md`, `bank`, and `bars_close`.
- Identity/key fields actually used: none externally; reuse is scoped to the call’s `base_spec`, `active_params`, and computed `common_index`.
- Identity/key fields that should matter to correctness: the loaded data, strategy kind, active parameter domains, and optional `data.window` slice.
- Missing key dimensions: none for current in-call correctness; there is intentionally no cross-call key.
- Scope/lifetime: one optimization function invocation.
- Invalidation/refresh behavior: automatic on function return.
- Why this matters: This is a safe performance optimization, but there is still no reuse across separate optimization button clicks.
- Risk level: low
- Confidence level: high

### Finding 8
- Mechanism name: Experimental runner artifact cache
- File path: `others/optimizer.py`
- Function/class: `BacktestRunner._cache_key`, `BacktestRunner.run`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: `others/optimizer.py` hashes `symbol|start|end|params_key`, returns `self.cache[ckey]`, stores the new `RunArtifact`, and later mutates `art.score`.
- Observed behavior: Repeated `run(...)` calls on the same `BacktestRunner` can reuse a previously computed `RunArtifact` object rather than rerunning features, strategy, execution, and reporting.
- Reuse trigger: exact match on `symbol`, `start`, `end`, and sorted param string.
- Identity/key fields actually used: `self.symbol`, `start`, `end`, `params_key`.
- Identity/key fields that should matter to correctness: bars content/version, `feature_provider` logic, `strategy_factory`, `execution_engine`, `report_builder`, and the scoring objective if `score` is treated as part of the artifact.
- Missing key dimensions: bars content/version; feature/execution/report code identity; objective.
- Scope/lifetime: one `BacktestRunner` object.
- Invalidation/refresh behavior: none.
- Why this matters: The artifact is mutable and reused by reference. If the same runner is used across changing bars or objectives, the cache can silently return semantically stale artifacts.
- Risk level: medium
- Confidence level: high

## Part 5: Severity Ranking

| Severity | Impact type | Issue | Why it matters | Example failure scenario | Affected boundary conditions |
|---|---|---|---|---|---|
| critical | correctness | Broken documented `backtester/` entrypoint and duplicate cache paths | The repo’s documented runtime path does not execute, so its cache behavior is not actually live and deployment can fail immediately | `streamlit run backtester/app.py` crashes on merge-conflict markers before any UI or caching path runs | every environment following `README.md` |
| high | correctness | Feature disk cache has no locking or atomic writes | Concurrent jobs can corrupt `.pkl` artifacts or observe partial writes | Two users run the same spec at once and one process reads a half-written pickle | multiple processes, multiple containers sharing one checkout, concurrent users |
| high | stale UI | Session bundle cache for yfinance has no freshness dimension | Same-session reruns can show old results after upstream market data changes | User reruns later in the day with unchanged inputs and still sees morning data | repeated requests in one process/session |
| high | correctness | `IndicatorEngine` / `_framehash_cache` assumes immutability of reused objects | Cached `DataFrame` references and object-identity memoization can go wrong if any caller mutates bars or features in place | A future plotting or preprocessing step mutates a cached feature frame and later runs reuse the mutated object | repeated requests in one process |
| medium | correctness | Dormant `BaseDataSource` cache keys local files by path, not content | If enabled later, editing a file in place would not invalidate cached bars | `data.xlsx` is corrected in place but the cache keeps serving the old bars | repeated requests, restarts, multiple users |
| medium | correctness | Experimental `BacktestRunner.cache` omits bars/provider/objective identity | Cached artifacts can be semantically stale even when params and dates match | A runner is reused with changed feature logic but old artifacts are returned | repeated requests in one process |
| medium | stale UI | Benchmark `@st.cache_data` has no TTL/freshness token | Cached yfinance benchmark can outlive backend reality | Strategy reruns with same benchmark args reuse yesterday’s cached benchmark | repeated requests, multi-user if cache is shared |
| medium | performance | No active market-data cache in main backtest/optimization flows | BMCE files are reread and yfinance is refetched every run | Repeated optimization clicks redownload the same symbol/time range | repeated requests, multiple users |
| low | maintainability | Duplicate top-level and `backtester/` trees diverge | Cache behavior is difficult to reason about and easy to break | A fix lands in top-level `app.py` but not in `backtester/app.py` | all development workflows |
| low | performance | Experimental `ResultStore` persists outputs but never reads them back | Expensive artifacts survive restarts but do not avoid future work | The same experiment reruns fully even though `runs/<run_id>` already exists | restarts, repeated batch runs |

## Part 6: Recommended Target Architecture
1. What should be cached
   - Market data for immutable BMCE uploads, keyed by file-content hash plus normalization config.
   - Market data for yfinance only with an explicit freshness boundary, such as a fetch timestamp bucket or manual refresh token.
   - Feature matrices keyed by full feature spec plus full normalized bars hash plus code/version salt.
   - Optimization-local feature banks within a single optimization call, which already exists and should stay local.
   - Benchmark market data with the same freshness rules as main market data.
2. What should never be cached
   - Mutable `BacktestBundle` objects by reference across unrelated requests unless copied or serialized.
   - Portfolio state objects and trade ledgers as shared mutable references.
   - Experimental run artifacts whose meaning depends on external factories or objectives unless those identities are in the key.
   - Any result object that is later mutated in place, such as `bundle.report`.
3. Required identity fields
   - BMCE/local file data: content hash of bytes, symbol mapping, timezone, interval, loader options, code version.
   - yfinance data: symbol(s), interval, start/end or period, auto-adjust, provider config, fetch freshness token, code version.
   - Features: symbol, indicator name, sorted params, inputs, warmup, output mode, normalized bars hash, engine code/version.
   - Session UI result caches: data freshness token, full spec, benchmark config, code version.
   - Experimental artifacts: bars content/version, feature provider version, strategy/execution/report versions, params, date window, objective if score is stored.
4. Invalidation rules
   - Data caches: invalidate on content hash change, freshness token change, or code version change.
   - Feature caches: invalidate on bars hash change, feature config change, or code/version change.
   - Session bundle caches: clear on any input change that affects results and on data freshness refresh.
   - Experimental artifact caches: clear whenever factories or bars change; do not store mutable score state inside reused artifacts.
5. Redis boundaries
   - None are needed in the current repo.
   - If a future multi-worker service is added, Redis should coordinate cache metadata only, not store mutable pandas objects.
6. Artifact persistence boundaries
   - `runs/` should remain persistence only.
   - If artifact reuse is desired later, add an explicit read path with versioned identities instead of treating persisted directories as implicit caches.
7. Stale-prevention rules
   - Frontend: do not reuse yfinance-backed bundles without a freshness token.
   - Quant core: write caches atomically and return defensive copies or immutable views on cache hits.
   - Storage: separate content-addressed immutable artifacts from session-only UI state.
   - Experimental pipeline: never let objective-dependent fields live inside cache entries whose keys omit the objective.

## Part 7: Actionable Fix Plan
1. Quick wins
   - Resolve the merge conflicts in `backtester/app.py`, `backtester/optimize.py`, and `backtester/portfolio.py`, or remove the broken duplicate tree from the documented entrypoint.
   - Add a short “current runnable entrypoint” note to the repo docs.
   - Add explicit comments where caches are intentionally session-only vs disk-persistent.
2. Correctness-critical fixes
   - Make feature disk-cache writes atomic and locked.
   - Add a code/version salt to feature-cache and data-cache keys.
   - Add a freshness token or manual refresh control for yfinance-backed session caches and benchmark caches.
   - Return defensive copies on mutable cache hits, or make cached structures immutable by convention and test it.
   - If `BaseDataSource` cache is enabled later, key BMCE/local files by content hash, not path string.
3. Performance-oriented caching improvements
   - Activate a real market-data cache in `engine.py` and `optimize.py` once the identity and invalidation rules are fixed.
   - Persist optimization result summaries by a full request signature if the UI needs rerun survival.
   - Reuse persisted artifacts only through an explicit, versioned read path.
4. Optional refactors
   - Collapse the duplicate top-level and `backtester/` trees into one source of truth.
   - Separate UI session state management from engine orchestration.
   - Move cache-key construction into dedicated helper functions so identity drift is reviewable.

## Final Summary Table

| Layer | Location | Current behavior | Risk | Recommended change |
|---|---|---|---|---|
| Frontend | `app.py` | Reuses full backtest bundles per session via `("bundle", str(base_spec))` | stale yfinance results | add freshness/version token and defensive-copy policy |
| Frontend | `app.py` | Streamlit caches benchmark loads with no TTL | stale benchmark | add explicit refresh boundary |
| Frontend | `app.py` | Uploads persist by content-addressed path | mostly safe dedupe, no tenant isolation | keep as persistence, not as implicit auth/isolation |
| Frontend alt UI | `streamlit_app.py` | Cached Excel loader for old UI | external cache semantics, no TTL | keep only if old UI remains supported |
| Quant core | `engine.py` | No market-data cache is active | expensive no-cache path | enable only after content/freshness identity is fixed |
| Quant core | `data.py` | Dormant pickle cache keys by path/kwargs | stale if enabled | key by file content / provider freshness |
| Quant core | `indicators.py` | Memory cache returns mutable frames by reference | aliasing risk | copy on hit or enforce immutability |
| Quant core | `indicators.py` | Disk feature cache shared under `.cache/features` | race/corruption/stale version risk | atomic writes, locks, version salt |
| Quant core | `indicators.py` | Frame hash memoized by `id(bars)` | wrong if bars mutate | hash immutable content or freeze inputs |
| Quant core | `optimize.py` | Reuses data/features only within one optimization call | no cross-run reuse | optional request-level optimization cache after correctness fixes |
| Experimental | `others/optimizer.py` | In-memory artifact cache with incomplete identity | stale artifact reuse | include bars/provider/objective identity |
| Experimental | `others/engine.py` | Persists artifacts to `runs/` but never reads them | recomputation despite persistence | keep as persistence or add explicit read-through cache |
| Documented runtime | `README.md` | Points to broken `backtester/app.py` | deploy/runtime failure | point docs at the actual runnable path or fix the package tree |
| API | repo-wide search | absent | requested scope not present | none in current repo |
| Worker / Redis / MinIO / Infra | repo-wide search | absent | requested scope not present | none in current repo |

## Top 5 Highest Correctness Risks
1. `backtester/app.py` documented runtime path plus `backtester/optimize.py` and `backtester/portfolio.py`: the package tree is syntactically broken, so the documented app does not run.
2. `indicators.py` disk feature cache: shared `.cache/features` writes are unlocked and non-atomic, so concurrent runs can corrupt or partially reuse cache files.
3. `app.py` session bundle cache for yfinance: exact-spec hits can serve stale results because no data freshness/version participates in the key.
4. `indicators.py` mutable cache hits and `id(bars)` memoization: correctness silently depends on upstream immutability, but the code does not enforce it.
5. `others/optimizer.py` `BacktestRunner.cache`: cached artifacts omit bars/provider/objective identity and are returned by mutable reference.

## Top 5 Most Expensive No-Cache Paths
1. `engine.py` / `optimize.py` market-data loading: no active market-data cache means BMCE reloads and yfinance refetches on every run.
2. `app.py` optimization flow: every optimization button click recomputes the whole candidate set; top-level app does not persist optimization results.
3. `engine.py` feature computation across backtest runs: a new `IndicatorEngine` is created every run, so memory reuse is lost between runs and optimization disables disk reuse by default.
4. `others/engine.py` persisted artifacts: results are written to disk but never read back, so persistence does not save future work.
5. `streamlit_app.py` old grid search UI: exhaustive `optimize_grid(...)` recomputes every combination on rerun with no retained optimization cache.

## Validation Notes
This report was produced from live source inspection plus static syntax checks. No mutable tests, cache clears, or code changes were run in the audited repository.
