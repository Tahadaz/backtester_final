-- Deploy-day SQL Purge Script
-- Purges legacy Factor×TA results before enabling the new dynamic econometric pipeline.

BEGIN;

-- 1. Delete all Factor×TA results from the Signal Engine (Layer A-G pipeline)
DELETE FROM signal_engine_family_result 
WHERE variant = 'factor_x_ta';

-- 2. Delete all Factor×TA results from the WFO engine (Walk-Forward Optimization)
DELETE FROM wfo_signal_summary 
WHERE variant = 'factor_x_ta';

-- 3. (Optional) Reset the Phase 1 Stage 1 BH-FDR caches if you want a complete cold start
-- TRUNCATE TABLE stock_factor_stage1_cache;
-- TRUNCATE TABLE stock_factor_relevance;

COMMIT;

-- VACUUM FULL; -- Uncomment if you need to reclaim disk space immediately after purge
