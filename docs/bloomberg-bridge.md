# Bloomberg bridge and market-data promotion

The deployed API queues Bloomberg jobs; the Terminal-side bridge claims them over outbound HTTPS using its enrolled credential, runs `blpapi`, and uploads normalized results. Daily OHLCV jobs may explicitly set `apply_to_market_data=true`. Promotion then validates symbol, date lineage, numeric values, positive prices, OHLC consistency, and non-negative volume before merging into the canonical per-symbol store. Bloomberg rows win exact duplicate dates and the store records provider and coverage metadata.

Required normalized daily fields are `security` (or an explicit internal symbol), `date`, `PX_OPEN`, `PX_HIGH`, `PX_LOW`, `PX_LAST`, and `VOLUME`. Promotion is opt-in and daily-only. Files without both security identity and observation dates are rejected rather than guessed.

The supplied `bloomberg-normalized-77b8e582-5432-4c05-a4f9-98f0626c0f1b.parquet` contains 358,588 rows and OHLCV columns but only a RangeIndex: it has no ticker/security or date column/index/metadata. It cannot be safely assigned to issuers or dates and was therefore not imported. Re-export it in long form with `security,date,field,value`, or wide form with the required columns above.

An end-to-end production check requires the bridge process on a Bloomberg-authorized workstation, successful `/bridge/bloomberg/health`, one daily test job, hash/idempotency verification, and confirmation that the promoted symbol appears in the canonical market-data store. Repository tests cover enrollment/authentication, job lifecycle, invalid-lineage rejection, and explicit promotion, but cannot prove Terminal entitlements from a non-Bloomberg host.
