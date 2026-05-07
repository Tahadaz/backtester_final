# Current-State Caching Audit

## Gating Step
1. Current working directory: `/mnt/c/Users/taha/Downloads/backtester_final`
2. Expected multi-service architecture present: `YES`
3. Expected paths:
   - `quant-backtesting-frontend/`: `YES`
   - `services/api/`: `YES`
   - `services/worker/`: `YES`
   - `core/quant_core/`: `YES`
   - `infra/docker-compose.yml`: `YES`
4. The repo matches the intended target app, so the audit continues.
5. Audit method: code inspection only. No code/config/schema/storage mutation was performed.

## Discovery Appendix
- Search patterns used:
  - `rg -n 'cache|cached|lru_cache|memo|memoize|useMemo|useCallback|SWR|React Query|stale|revalidate|fetch\(|headers|ETag|Cache-Control|Redis|exists\(|if exists|hash|fingerprint|singleton|module-level state|global dict|persisted store|localStorage|sessionStorage|snapshot|default|latest|best|artifact reuse|object key|SHA|dedupe' quant-backtesting-frontend services core infra`
  - `rg -n 'best_strategy_snapshot|default-sets/latest|dataset_symbol_map|_MARKET_DATA_CACHE|_mem_cache|_framehash_cache|_ARTIFACT_SHA_CACHE|_DATASET_PATH_CACHE|refreshInterval|revalidateOnFocus|cache: "no-store"'`
  - `rg --files quant-backtesting-frontend services core infra`
- Cache-relevant files found:
  - Frontend:
    - `quant-backtesting-frontend/hooks/use-api.ts`
    - `quant-backtesting-frontend/lib/api.ts`
    - `quant-backtesting-frontend/hooks/use-toast.ts`
    - `quant-backtesting-frontend/app/api/[...path]/route.ts`
    - `quant-backtesting-frontend/app/api/artifacts/fetch/route.ts`
    - `quant-backtesting-frontend/app/new-run/page.tsx`
    - `quant-backtesting-frontend/app/runs/[runId]/page.tsx`
    - `quant-backtesting-frontend/app/defaults-discovery/page.tsx`
    - `quant-backtesting-frontend/app/page.tsx`
  - API:
    - `services/api/app/main.py`
    - `services/api/app/models.py`
    - `services/api/app/storage.py`
    - `services/api/app/queue.py`
    - `services/api/app/services/hash_utils.py`
    - `services/api/app/services/snapshot.py`
    - `services/api/app/services/catalog.py`
    - `services/api/app/routers/datasets.py`
    - `services/api/app/routers/runs.py`
    - `services/api/app/routers/results.py`
    - `services/api/app/routers/defaults.py`
    - `services/api/app/routers/market_data.py`
    - `services/api/app/routers/snapshot.py`
    - `services/api/app/routers/leaderboard.py`
  - Worker:
    - `services/worker/worker.py`
    - `services/worker/storage.py`
    - `services/worker/cancel.py`
    - `services/worker/tasks/execute_run.py`
    - `services/worker/tasks/evaluate_chunk.py`
    - `services/worker/tasks/parallel_opt.py`
    - `services/worker/tasks/ingest_market_data.py`
    - `services/worker/tasks/refresh_market_data.py`
    - `services/worker/tasks/defaults_discovery.py`
  - Quant core:
    - `core/quant_core/data.py`
    - `core/quant_core/indicators.py`
    - `core/quant_core/engine.py`
    - `core/quant_core/optimize.py`
    - `core/quant_core/pipeline.py`
    - `core/quant_core/run_spec.py`
    - `core/quant_core/s3_keys.py`
  - Infra:
    - `infra/docker-compose.yml`
- Files inspected deeply:
  - All files above except `run_spec.py` and `s3_keys.py`, which were inspected for key construction only.
  - Supporting tests:
    - `core/tests/test_caching_and_optimization.py`
    - `core/tests/test_optimize_regression.py`
    - `services/worker/tests/test_execute_run_multi_horizon.py`
- Files excluded from primary analysis:
  - `.next/**`
  - `node_modules/**`
  - build outputs
  - `_patch_*`
  - local scratch/snapshot files including `quant-backtesting-frontend/app/new-run/page.tsx.overwritten-2026-02-27-144222`
  - `infra/docker-compose.gcp.yml`

## Part 1: Caching Map

| Layer | Mechanism name | Location | Classification | Evidentiary status | Retained/reused | Exact identity/key fields | Missing identity fields for correctness | Scope | Lifetime/TTL | Invalidation/refresh | Explicit vs accidental | Category | Safety | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Frontend | SWR run list cache | `quant-backtesting-frontend/hooks/use-api.ts` | true cache | proven from code | SWR response objects | URL path + serialized query params | backend freshness/version, tenant dimension | browser runtime | tab/runtime | polling, focus revalidate, mutate | explicit | ambiguous/unsafe reuse | ambiguous | high |
| Frontend | Run-status polling gate | `quant-backtesting-frontend/hooks/use-api.ts` | polling / refresh logic | proven from code | no durable retained state beyond SWR | `/runs/{runId}` | version after terminal status | browser runtime | mounted component | 2s polling until terminal status | explicit | correctness-sensitive reuse | ambiguous | high |
| Frontend | Generic request `no-store` | `quant-backtesting-frontend/lib/api.ts` | not actually cache-like | proven from code | none | none | n/a | request | none | every request re-fetches | explicit | expensive no-cache path | safe | high |
| Frontend | Next proxy pass-through | `quant-backtesting-frontend/app/api/[...path]/route.ts` | not actually cache-like | proven from code | none | target URL | n/a | request | none | every request | explicit | expensive no-cache path | safe | high |
| Frontend | Artifact URL refresh | `quant-backtesting-frontend/lib/api.ts` | polling / refresh logic | proven from code | refreshed presigned URL only | extracted `object_key`, matched via `getArtifacts(runId)` | body caching, artifact version | browser runtime | per request | retry on expired presigned URL | explicit | correctness-sensitive reuse | ambiguous | high |
| Frontend | Latest dataset wins map | `quant-backtesting-frontend/app/new-run/page.tsx` | derived snapshot/default state | proven from code | symbol->dataset id map | `created_at desc`, first dataset per normalized symbol | dataset content/version, tenant, explicit source choice | component state | until refetch | rerender on fetched dataset list change | explicit | correctness-sensitive reuse | ambiguous | high |
| Frontend | Defaults page polling | `quant-backtesting-frontend/app/defaults-discovery/page.tsx` | polling / refresh logic | proven from code | recent run list + current run in component state | `currentRunId`, fixed list query | version/etag semantics | browser runtime | mounted component | 5s interval + 2s active poll | explicit | correctness-sensitive reuse | ambiguous | high |
| Frontend | Toast memory state | `quant-backtesting-frontend/hooks/use-toast.ts` | process-global state | proven from code | module-level toast state | none | n/a | browser runtime | page lifetime | dismiss/remove | explicit | not actually cache-like | safe | high |
| API | Dataset upload dedupe | `services/api/app/routers/datasets.py` | deduplication | proven from code | existing dataset row and object for identical bytes | `sha256(file bytes)` | tenant/ownership | DB + S3 | persisted | none | explicit | correctness-sensitive reuse | ambiguous | high |
| API | Run create idempotency | `services/api/app/routers/runs.py` | deduplication | proven from code | existing run row | `spec_hash`, `dataset_id`, exact `spec_json` equality | tenant, code version | DB | persisted | failed/canceled purge/recreate | explicit | correctness-sensitive reuse | ambiguous | high |
| API | Start-run queue dedupe | `services/api/app/routers/runs.py` | deduplication | proven from code | avoids duplicate enqueue | `run.status`, Redis `rq:job:{rq_job_id}` | job generation/attempt | API + Redis | Redis job lifetime | re-enqueue if key absent | explicit | ambiguous/unsafe reuse | ambiguous | high |
| API | Defaults discovery dedupe | `services/api/app/routers/defaults.py` | deduplication | proven from code | existing queued/running defaults job | `strategy_name`, `status`, `created_at >= now-2h`, and `dataset_id` or `ticker` | timeframe, date range, WFO config, buckets, score settings, cost model, signal params | DB + Redis | 2-hour window | RQ sync + dedupe window | explicit | ambiguous/unsafe reuse | unsafe | high |
| API | Snapshot/default rows | `services/api/app/services/snapshot.py`, `routers/defaults.py`, `routers/leaderboard.py` | derived snapshot/default state | proven from code | persisted best/latest rows | best snapshot `(ticker,freq,dataset_id,start_at,end_at,strategy_name,portfolio_hash)`; latest defaults `created_at desc` | run spec hash, objective, code version, provider/source, tenant | DB | persisted | explicit writes only | explicit | ambiguous/unsafe reuse | ambiguous | high |
| Worker | Artifact SHA cache | `services/worker/tasks/execute_run.py` | true cache | proven from code | prior object key for identical bytes | `(sha256(content), content_type)` + DB lookup on `sha256, content_type, bucket` | logical artifact identity fields | worker process + DB + S3 | process lifetime + persisted artifact rows | none | explicit | ambiguous/unsafe reuse | ambiguous | high |
| Worker | Local dataset/store cache | `services/worker/tasks/execute_run.py` | true cache | proven from code | local files under `/tmp/datasets` | uploads: `uploaded/{data_hash}`; store: `store/{sha256(object_key)}` | store object content version/etag | worker filesystem | container filesystem lifetime | none | explicit | ambiguous/unsafe reuse | unsafe for store | high |
| Worker | Chunk dataset path cache | `services/worker/tasks/evaluate_chunk.py` | true cache | proven from code | dataset temp file path | `dataset_hash` | file existence, extension/object key | worker process | process lifetime | FIFO-style eviction only | explicit | ambiguous/unsafe reuse | ambiguous | high |
| Worker | Candidate eval cache | `services/worker/tasks/evaluate_chunk.py` | memoization | proven from code | per-chunk duplicate trial results | `_trial_params_key(params)` | none intended across calls | function call | one task | function return | explicit | safe performance cache | safe | high |
| Worker | Canonical store parquet persistence | `services/worker/tasks/ingest_market_data.py`, `refresh_market_data.py` | persistence / artifact store | proven from code | canonical parquet at stable key | `market_data/symbols/{SYMBOL}/ohlcv.parquet` | content generation/version | S3 + DB | persisted | overwrite on changed merge | explicit | correctness-sensitive reuse | ambiguous | high |
| Quant core | Synthetic date-range cache | `core/quant_core/data.py` | process-global state | proven from code | shared `DatetimeIndex` | `(start, end, freq, "UTC")` | none material | process | interpreter lifetime | none | explicit | safe performance cache | safe | high |
| Quant core | Engine market-data cache | `core/quant_core/engine.py` | true cache | proven from code | `MarketData` objects | serialized `DataConfig` fields: source, symbols, timezone, interval, start, end, periods, freq, include/exclude windows, bmce_paths, yf_period, yf_interval, yf_auto_adjust, synthetic, parquet_paths | file content hash, object version, code version | process | interpreter lifetime | none | explicit | ambiguous/unsafe reuse | unsafe/ambiguous | high |
| Quant core | Optimize market-data cache | `core/quant_core/optimize.py` | true cache | proven from code | `MarketData` objects | same serialized `DataConfig` payload | file content hash, object version, code version | process | interpreter lifetime | none | explicit | ambiguous/unsafe reuse | unsafe/ambiguous | high |
| Quant core | Indicator feature caches | `core/quant_core/indicators.py` | true cache | proven from code | feature `DataFrame`s in memory and disk | `symbol + spec.spec_hash(engine_version) + data_hash` | stronger version salt, immutability, concurrency generation | engine instance + filesystem | instance + `.cache/features` | none | explicit | ambiguous/unsafe reuse | unsafe/ambiguous | high |
| Quant core | Frame hash memoization | `core/quant_core/indicators.py` | memoization | proven from code | cached frame hash | `(id(bars), tuple(inputs))` | content identity if bars mutates | engine instance | object lifetime | none | explicit | ambiguous/unsafe reuse | ambiguous | high |
| Quant core | Optimization eval memoization | `core/quant_core/optimize.py` | memoization | strongly indicated by code | duplicate trial results within one call | `_trial_params_key(params)` | none intended across calls | function call | one optimization call | function return | explicit | safe performance cache | safe | medium |

## Part 2: End-to-End Flow

### Uploaded dataset run
1. Frontend loads datasets from API.
   - Reused from SWR in some screens or direct fetch on mount.
   - Identity: `/datasets`.
   - Risk: frontend symbol selection uses latest dataset by `created_at`, not explicit version pinning.
2. New-run page builds either `dataset_id` or `data.dataset_symbol_map`.
   - Location: `quant-backtesting-frontend/app/new-run/page.tsx`.
   - Identity: selected symbols plus derived dataset mapping.
3. API `create_run` computes `spec_hash`, `dataset_hash`, and a stable run UUID from spec+dataset.
   - Location: `services/api/app/routers/runs.py`.
   - Behavior: dedupes identical runs instead of creating a new row.
4. API `start_run` checks Redis job existence and enqueues if needed.
   - Reused state: Redis RQ job metadata.
   - Risk: stale queued DB row if Redis key expired.
5. Worker materializes uploaded file from MinIO into local dataset cache.
   - Identity: `uploaded/{data_hash}`.
   - Reuse boundary: local worker filesystem.
6. Quant core loads bars and may hit process-global market-data cache.
   - Identity: serialized `DataConfig` including local file path.
   - Risk: path-based, not content-based.
7. Indicator engine computes/reuses features.
   - Identity: symbol + feature spec hash + input frame hash.
   - Risk: mutable DataFrame aliasing, pickle race.
8. Worker uploads artifacts.
   - Identity: content SHA + content type for dedupe.
   - Risk: logical artifact aliasing across runs.
9. API returns artifact rows with presigned URLs.
10. Frontend uses SWR for metadata and artifact proxy for content.
   - Artifact body is not cached locally.

### Canonical / market-data-backed run
1. Frontend submits run with `source_key = "store"`.
2. Worker resolves canonical store object key from `market_data_store`.
3. Worker materializes parquet into local cache keyed by `sha256(object_key)`.
   - Risk: object key is stable while content is overwritten by refresh tasks.
4. Quant core loads local parquet and may reuse process-global `MarketData`.
5. Feature and artifact behaviors are the same as uploaded dataset runs.
6. Frontend polls until run becomes terminal, then stops.
   - Risk: later backend changes are not automatically shown.

### Optimization / WFO path ending in persisted artifacts and frontend display
1. Frontend builds optimization or WFO spec in `new-run/page.tsx`.
2. API stores run row and worker starts processing.
3. `parallel_opt` chunks candidates and persists `opt_task` rows.
   - Persistence, not cache.
4. `evaluate_chunk` reuses local dataset temp file by `dataset_hash` and duplicate param results by `_trial_params_key(params)`.
5. Quant core optimization may reuse process-global market-data cache and in-call memoization.
6. `opt_result.topk_json` is UPSERTed per `(run_id, fold_id, chunk_id)`.
   - Persistence, not cache.
7. Best candidate reruns persist artifacts under `runs/{rid}/...` object-key patterns.
   - Actual object may still be reused via SHA dedupe.
8. API exposes rows and presigned URLs.
9. Frontend run detail page derives visible slices via `useMemo` from fetched leaderboard/decision/metric payloads.
   - Derived snapshot state, not persistent cache.

## Part 3: Bug Hunt
1. `services/api/app/routers/defaults.py`: defaults-discovery dedupe key is too weak and can merge distinct requests.
2. `services/worker/tasks/execute_run.py`: canonical store local cache can serve stale parquet because it keys on stable object key, not object content version.
3. `core/quant_core/engine.py` and `core/quant_core/optimize.py`: process-global market-data caches return shared mutable objects by reference.
4. `core/quant_core/indicators.py`: feature disk cache has no locking or atomic rename; shared volume makes concurrency races realistic.
5. `core/quant_core/indicators.py`: cached DataFrames are returned directly with no defensive copy.
6. `services/worker/tasks/evaluate_chunk.py`: dataset temp-path cache does not validate file existence/size on cache hit.
7. `services/worker/tasks/execute_run.py`: artifact SHA dedupe can alias logical artifacts across different runs.
8. `quant-backtesting-frontend/hooks/use-api.ts`: terminal polling stops without version-based revalidation.
9. `services/api/app/services/snapshot.py` and `services/api/app/routers/defaults.py`: persisted “best/latest” rows are easy to treat as safe caches but are derived state with incomplete identity.
10. `quant-backtesting-frontend/lib/api.ts` and several API paths: major expensive no-cache paths remain.

## Part 4: Evidence

### Finding 1
- Mechanism name: Frontend SWR polling and key-based reuse
- File path: `quant-backtesting-frontend/hooks/use-api.ts`
- Function/class: `useRuns`, `useRun`, `useArtifacts`, `useDatasets`, `useRefreshRun`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: `useSWR` with URL-string keys and polling options is used throughout the file.
- Observed behavior: Browser-side in-memory reuse occurs for identical SWR keys; some endpoints are timer-polled.
- Reuse trigger: identical SWR key string.
- Identity/key fields actually used: URL path and query string only.
- Identity/key fields that should matter to correctness: URL plus backend freshness/version if same URL can change materially.
- Missing key dimensions: explicit version or revalidation token.
- Scope/lifetime: browser runtime/tab.
- Invalidation/refresh behavior: polling, focus revalidate, manual `mutate()`.
- Why this matters: This is the frontend’s primary cache mechanism.
- Risk level: medium
- Confidence level: high

### Finding 2
- Mechanism name: Dataset upload content-hash dedupe
- File path: `services/api/app/routers/datasets.py`
- Function/class: `upload_dataset`
- Classification: deduplication
- Evidentiary status: proven from code
- Code evidence: SHA-256 is computed from raw file bytes and existing dataset rows are matched by `data_hash`.
- Observed behavior: Duplicate uploads of the same bytes reuse the prior dataset row/object rather than storing a new copy.
- Reuse trigger: `Dataset.data_hash == digest`.
- Identity/key fields actually used: raw file SHA-256.
- Identity/key fields that should matter to correctness: file content hash and, if datasets are user-scoped, tenant/owner identity.
- Missing key dimensions: tenant/ownership.
- Scope/lifetime: DB + MinIO.
- Invalidation/refresh behavior: none; metadata is merged into existing row.
- Why this matters: Good dedupe for content-addressed storage, weak for multi-user separation.
- Risk level: medium
- Confidence level: high

### Finding 3
- Mechanism name: Run creation idempotency reuse
- File path: `services/api/app/routers/runs.py`
- Function/class: `create_run`
- Classification: deduplication
- Evidentiary status: proven from code
- Code evidence: `spec_hash` is recomputed from canonical JSON and run UUIDs are derived from `spec_hash|dataset_id`; exact reuse requires same stored `spec_json` and `dataset_id`.
- Observed behavior: Identical run submissions reuse the same run row; failed/canceled rows are purged and recreated.
- Reuse trigger: existing row with candidate run id plus exact spec equality.
- Identity/key fields actually used: `spec_hash`, `dataset_id`, `spec_json`.
- Identity/key fields that should matter to correctness: full spec, dataset identity/content, tenant, possibly code version.
- Missing key dimensions: tenant/ownership, code version.
- Scope/lifetime: DB-persistent.
- Invalidation/refresh behavior: failed/canceled purge/recreate, otherwise reuse.
- Why this matters: Correctness depends on spec equality being enough; it is not enough in multi-tenant contexts.
- Risk level: high
- Confidence level: high

### Finding 4
- Mechanism name: Defaults discovery active-run dedupe
- File path: `services/api/app/routers/defaults.py`
- Function/class: `discover_sma_defaults`
- Classification: deduplication
- Evidentiary status: proven from code
- Code evidence: active queued/running rows from the last two hours are searched by `ticker` or `dataset_id` and returned before launching a new job.
- Observed behavior: A new request can reuse a prior queued/running defaults discovery job even when most of the request payload differs.
- Reuse trigger: existing recent active row for same ticker or dataset.
- Identity/key fields actually used: `strategy_name`, `status`, recent `created_at`, `ticker` or `dataset_id`.
- Identity/key fields that should matter to correctness: timeframe, date range, buckets, score settings, signal params, walk-forward config, cost model.
- Missing key dimensions: most request semantics.
- Scope/lifetime: DB + Redis.
- Invalidation/refresh behavior: 2-hour dedupe window, RQ sync.
- Why this matters: This can return the wrong job for a valid new request.
- Risk level: critical
- Confidence level: high

### Finding 5
- Mechanism name: Worker local dataset/store cache
- File path: `services/worker/tasks/execute_run.py`
- Function/class: `_materialize_object_to_cache`, `_materialize_dataset_file`, `_materialize_store_parquet`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: local file reuse is based on existing non-empty cache path; uploaded datasets key by `data_hash`, canonical store by `sha256(object_key)`.
- Observed behavior: Workers skip MinIO downloads when a prior local file is present.
- Reuse trigger: cache file exists and is non-empty.
- Identity/key fields actually used: upload `data_hash`; store `sha256(object_key)`.
- Identity/key fields that should matter to correctness: for store parquet, object content version or ETag.
- Missing key dimensions: store object content/version.
- Scope/lifetime: worker-local filesystem.
- Invalidation/refresh behavior: none.
- Why this matters: Uploaded dataset reuse is mostly safe; canonical store reuse is stale-prone.
- Risk level: high
- Confidence level: high

### Finding 6
- Mechanism name: Worker artifact SHA dedupe
- File path: `services/worker/tasks/execute_run.py`
- Function/class: `_upload_content`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: content SHA and content type are used first in memory, then via DB lookup, then validated by S3 object metadata.
- Observed behavior: Byte-identical artifacts can reuse prior object keys and skip object upload.
- Reuse trigger: matching content SHA and content type with successful S3 metadata validation.
- Identity/key fields actually used: `sha256(content)`, `content_type`, `bucket`.
- Identity/key fields that should matter to correctness: logical artifact identity if callers assume object keys are run-local.
- Missing key dimensions: run_id, symbol, strategy kind, artifact logical name.
- Scope/lifetime: worker process + DB + S3.
- Invalidation/refresh behavior: none beyond cache miss/metadata mismatch.
- Why this matters: Good performance optimization, but weak object-key identity semantics.
- Risk level: medium
- Confidence level: high

### Finding 7
- Mechanism name: Process-global market-data caches
- File path: `core/quant_core/engine.py`, `core/quant_core/optimize.py`
- Function/class: `_MARKET_DATA_CACHE`, `load_marketdata`, `_load_market_data_from_spec`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: both modules declare global caches keyed by serialized `DataConfig` payloads and return the same `MarketData` object on hit; tests assert object identity reuse.
- Observed behavior: Repeated loads in one process return the same mutable `MarketData` instance.
- Reuse trigger: identical serialized `DataConfig` payload.
- Identity/key fields actually used: source, symbols, time bounds, windows, path fields, yfinance flags, synthetic config.
- Identity/key fields that should matter to correctness: file content hashes, object versions, code version.
- Missing key dimensions: content/version identity and code version.
- Scope/lifetime: Python process.
- Invalidation/refresh behavior: none.
- Why this matters: Shared mutable objects and weak freshness identity make this correctness-sensitive.
- Risk level: high
- Confidence level: high

### Finding 8
- Mechanism name: Indicator feature caches and frame hash memoization
- File path: `core/quant_core/indicators.py`
- Function/class: `IndicatorEngine`
- Classification: true cache
- Evidentiary status: proven from code
- Code evidence: memory and disk caches use `symbol + spec_hash + data_hash`; frame hash memoization uses `(id(bars), tuple(inputs))`; disk writes use plain pickle writes with no lock/atomic rename.
- Observed behavior: Feature `DataFrame`s are reused directly, and frame hashes are reused while the same bars object identity survives.
- Reuse trigger: identical feature key or identical bars object id plus inputs.
- Identity/key fields actually used: `symbol`, feature spec hash, input frame hash, `(id(bars), tuple(inputs))` for frame-hash memoization.
- Identity/key fields that should matter to correctness: code version, immutable input identity, concurrency generation.
- Missing key dimensions: automatic code-version salt, mutation protection, write coordination.
- Scope/lifetime: engine instance + filesystem.
- Invalidation/refresh behavior: exact-key miss only.
- Why this matters: This is the main quant-core performance cache and a major correctness hotspot.
- Risk level: high
- Confidence level: high

### Finding 9
- Mechanism name: Persisted best/latest/default rows
- File path: `services/api/app/services/snapshot.py`, `services/api/app/routers/defaults.py`, `services/api/app/routers/leaderboard.py`
- Function/class: `upsert_best_snapshot`, `get_latest_sma_default_set`, `global_leaderboard`
- Classification: derived snapshot/default state
- Evidentiary status: proven from code
- Code evidence: `best_strategy_snapshot` is upserted only when score improves; latest defaults returns the newest row by `created_at`; leaderboard queries persisted snapshot rows directly.
- Observed behavior: Callers read persisted summaries instead of recomputing current truth.
- Reuse trigger: SQL query on persisted snapshot/default tables.
- Identity/key fields actually used: best snapshot composite key; latest defaults by most recent row only.
- Identity/key fields that should matter to correctness: run spec hash, objective, code version, provider/source, tenant, source run identity.
- Missing key dimensions: several semantic dimensions, especially for “latest”.
- Scope/lifetime: DB-persistent.
- Invalidation/refresh behavior: only explicit writers update them.
- Why this matters: These behave like caches to consumers but are actually lossy derived state.
- Risk level: high
- Confidence level: high

## Part 5: Severity Ranking

| Severity | Impact type | Why it matters | Example failure scenario | Affected boundary conditions |
|---|---|---|---|---|
| critical | correctness | Defaults discovery dedupe key is too weak | Two different SMA defaults-discovery requests for the same ticker but different horizons/date ranges collapse into one active run and return the wrong result | repeated requests, multiple users, multi-run production |
| high | correctness | Canonical store local cache keys only on stable object key | Worker reuses stale parquet after market refresh overwrote the MinIO object at the same key | multiple worker jobs, long-lived containers, restarts |
| high | correctness | Engine and optimize process-global market-data caches return shared mutable objects | One path mutates cached market data and contaminates later runs | repeated requests in one process, same-worker parallelism |
| high | correctness | Indicator disk cache is shared and non-atomic | Two workers race on the same cache file and one reads a corrupt pickle | multiple workers/containers sharing `featurecache` |
| high | correctness | Snapshot/default tables are treated as current truth without full identity | “latest” defaults or “best” snapshot survive incompatible source/config changes | restarts, multi-run, multi-user |
| medium | stale UI | Terminal polling stops without version validation | Backend result changes after terminal state, UI keeps stale result until manual refresh | repeated requests in one tab |
| medium | scalability | Artifact SHA dedupe aliases logical artifacts to prior keys | Multiple run rows refer to one object key, complicating lifecycle/deletion | multiple users, many reruns |
| medium | performance | No HTTP caching and many timer refreshes | High request volume for unchanged data | repeated requests, larger user count |
| medium | performance | API re-reads S3 artifacts for enrichment | Leaderboard repeatedly parses the same artifact CSVs | repeated API requests |
| low | maintainability | Snapshot/persistence semantics are mixed | Engineers mistake persistence for safe cache reuse | all environments |

## Part 6: Recommended Target Architecture
1. What should be cached
   - Canonical market-data materializations only with object content version in the key.
   - Uploaded dataset local files keyed by dataset content hash.
   - Quant-core market data keyed by content/version-aware identity.
   - Feature matrices keyed by full feature spec + bars content hash + code version.
   - Request-local enrichment caches for repeated artifact parsing.
2. What should never be cached
   - “Latest” and “best” tables as if they were authoritative current truth.
   - Shared mutable `MarketData`, `DataFrame`, or result objects by reference.
   - Canonical store parquet by stable object key alone.
3. Required identity fields
   - Defaults discovery: ticker/dataset_id, timeframe, date range, walk-forward config, buckets, score settings, signal params, cost model.
   - Store-local cache: object key plus ETag/content hash.
   - MarketData cache: source, symbols, interval, time bounds, path/object content identity, provider config, code version.
   - Feature cache: symbol, normalized input frame hash, `FeatureSpec`, engine/code version.
   - Snapshot/default state: source run id, spec hash, objective, version, provider/source, tenant if applicable.
4. Invalidation rules
   - Invalidate store-local cache on object content/version change.
   - Invalidate market-data and feature caches on code version change.
   - Invalidate snapshot/default views when upstream source run semantics change.
5. Redis boundaries
   - Keep Redis as queue/job-state only.
   - Do not rely on Redis job existence alone as durable idempotency.
6. Artifact persistence boundaries
   - Keep run-scoped logical artifact naming.
   - If SHA dedupe remains, treat it as internal storage optimization only.
7. Stale-prevention rules
   - Frontend: polling is not freshness proof; provide explicit refresh on terminal views.
   - API: mark latest/best endpoints as snapshot semantics.
   - Worker: version local caches for overwritten canonical objects.
   - Quant core: copy or freeze cached mutable objects.

## Part 7: Actionable Fix Plan
1. Quick wins
   - Strengthen defaults-discovery dedupe identity.
   - Mark snapshot/default endpoints as derived state.
   - Add explicit terminal-page refresh actions.
2. Correctness-critical fixes
   - Version canonical store local cache by object content hash/ETag.
   - Add atomic write + locking for feature disk cache.
   - Add defensive copy or immutability guarantees for cached market data and features.
   - Include code/version salt in market-data and feature cache keys.
   - Improve DB/Redis reconciliation for queued job idempotency.
3. Performance-oriented caching improvements
   - Add request-local cache for repeated artifact CSV reads.
   - Add safe HTTP caching only for immutable endpoints.
   - Consider bounded TTL/invalidation for SWR datasets and market catalog.
4. Optional refactors
   - Consolidate snapshot/best/latest semantics.
   - Centralize cache-key construction helpers.
   - Separate logical artifact identity from storage dedupe identity.

## Final Summary Table

| Layer | Location | Current behavior | Risk | Recommended change |
|---|---|---|---|---|
| Frontend | `quant-backtesting-frontend/hooks/use-api.ts` | SWR reuses by URL key and polls | polling-only freshness | treat SWR as UI cache only; improve terminal refresh |
| Frontend | `quant-backtesting-frontend/lib/api.ts` | `fetch` uses `cache: "no-store"` | expensive no-cache path | keep for mutable endpoints; selectively cache immutable ones |
| Frontend | `quant-backtesting-frontend/app/new-run/page.tsx` | latest dataset wins per symbol | cross-upload symbol collision | require explicit source/version selection or stronger mapping identity |
| Frontend | `quant-backtesting-frontend/app/defaults-discovery/page.tsx` | polling + derived active defaults | stale/ambiguous derived state | make snapshot semantics explicit and refreshable |
| API | `services/api/app/routers/datasets.py` | upload dedupe by content hash | ownership/isolation ambiguity | add tenant boundary if datasets are user-scoped |
| API | `services/api/app/routers/runs.py` | run idempotency by spec + dataset | cross-user collision risk | add tenant dimension or ownership checks |
| API | `services/api/app/routers/defaults.py` | dedupe by ticker/dataset + 2h window | wrong-run reuse | include full request signature |
| API | `services/api/app/services/snapshot.py` | persisted best snapshot rows | stale derived state mistaken for cache | version/scope snapshot identity explicitly |
| Worker | `services/worker/tasks/execute_run.py` | local dataset/store cache and artifact SHA dedupe | stale canonical data, object-key aliasing | version store cache by content; separate logical from physical identity |
| Worker | `services/worker/tasks/evaluate_chunk.py` | dataset temp-path cache and per-task eval memoization | dangling path, weak dataset-key validation | validate path on hit; keep per-task eval memoization |
| Worker | `services/worker/tasks/ingest_market_data.py` | stable canonical object keys are overwritten | downstream stale-cache risk | expose content version and key caches on it |
| Quant core | `core/quant_core/engine.py` | process-global market-data cache returns same object | stale/mutation contamination | version by content and return defensive copies |
| Quant core | `core/quant_core/optimize.py` | same cache pattern in optimization | same as engine | same fix as engine |
| Quant core | `core/quant_core/indicators.py` | memory/disk feature caches reuse mutable `DataFrame`s | mutation and disk-race risk | atomic writes, locks, copy/freeze semantics |
| Infra | `infra/docker-compose.yml` | shared `featurecache` volume across workers | cross-worker cache contention | keep only with safe locking/version discipline |

## Top 5 Highest Correctness Risks
1. `services/api/app/routers/defaults.py` active-run dedupe: request identity is too weak and can collapse distinct discovery jobs.
2. `services/worker/tasks/execute_run.py` store parquet local cache: object-key-only identity can serve stale canonical market data after refresh.
3. `core/quant_core/engine.py` and `core/quant_core/optimize.py` process-global market-data caches: shared mutable objects are returned by reference with no invalidation.
4. `core/quant_core/indicators.py` disk feature cache: shared volume plus non-atomic pickle writes creates concurrency corruption risk.
5. `services/api/app/services/snapshot.py` plus latest/default endpoints: persisted snapshot rows omit important correctness dimensions.

## Top 5 Most Expensive No-Cache Paths
1. `quant-backtesting-frontend/lib/api.ts` request path: `cache: "no-store"` forces refetch on direct frontend API calls.
2. `services/api/app/routers/runs.py` leaderboard enrichment: repeated S3 reads of trade-performance CSVs per request.
3. `services/api/app/routers/runs.py` materialization helpers: repeated MinIO downloads into temp files for dataset/store-backed detail endpoints.
4. `quant-backtesting-frontend/app/defaults-discovery/page.tsx` polling loops: repeated list/detail fetches every 2s/5s without stronger delta semantics.
5. `services/api/app/routers/market_data.py` technical study fallback: repeatedly loads canonical parquet or latest uploaded dataset objects with no request-level reuse.
