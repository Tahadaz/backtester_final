import uuid
from sqlalchemy import (
    Column, String, DateTime, Date, ForeignKey, Text, BigInteger, Float, UniqueConstraint, Index, Integer, Boolean, CheckConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from .db import Base

# ---------------------------------------------------------------------------
# Signal Engine Persistence — new tables added 2026-04-20
# ---------------------------------------------------------------------------



class Dataset(Base):
    __tablename__ = "dataset"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)      # e.g. "BMCE_CSV", "Yahoo"
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)   # e.g. "1D"
    data_hash = Column(String, nullable=False)

    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    object_key = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    meta_json = Column(JSONB, nullable=False, default=dict)

    start_ts = Column(DateTime(timezone=True), nullable=True)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class MarketDataStore(Base):
    __tablename__ = "market_data_store"
    symbol = Column(String, primary_key=True)
    timeframe = Column(String, primary_key=True, default="1d")  # optional composite PK
    object_key = Column(String, nullable=False)
    start_ts = Column(DateTime(timezone=True))
    end_ts = Column(DateTime(timezone=True))
    row_count = Column(Integer)
    last_dataset_id = Column(ForeignKey("dataset.id"))
    source_provider = Column(String, nullable=True)   # "bourse_direct"|"yahoo"|"bmce_excel"|"casablanca_bourse"
    data_as_of = Column(Date, nullable=True)           # last bar date (denormalized for freshness display)
    asset_class = Column(String(16), nullable=False, default="equity")  # "equity"|"index"|"factor"
    close_last = Column(Float, nullable=True)
    prev_close = Column(Float, nullable=True)
    adv_20d = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BourseLiveQuote(Base):
    """Latest scraped Bourse de Casablanca quote, separate from canonical OHLCV."""
    __tablename__ = "bourse_live_quote"

    symbol = Column(String, primary_key=True)
    session_date = Column(Date, nullable=True)
    quote_timestamp = Column(DateTime(timezone=True), nullable=True)
    open_price = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    high_price = Column(Float, nullable=True)
    low_price = Column(Float, nullable=True)
    prev_close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    source_provider = Column(String, nullable=False, default="casablanca_bourse_live")
    source_url = Column(String, nullable=True)
    raw_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_bourse_live_quote_updated_at", "updated_at"),
        Index("ix_bourse_live_quote_session_date", "session_date"),
    )


class BourseLiveQuoteHistory(Base):
    """Append-only snapshots captured by explicit live refresh requests."""
    __tablename__ = "bourse_live_quote_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    session_date = Column(Date, nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    quote_timestamp = Column(DateTime(timezone=True), nullable=True)
    open_price = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    high_price = Column(Float, nullable=True)
    low_price = Column(Float, nullable=True)
    prev_close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    source_provider = Column(String, nullable=False, default="casablanca_bourse_live")
    source_url = Column(String, nullable=True)
    raw_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_bourse_live_quote_history_symbol_observed_at", "symbol", "observed_at"),
        Index("ix_bourse_live_quote_history_session_symbol", "session_date", "symbol"),
        Index("ix_bourse_live_quote_history_observed_at", "observed_at"),
    )


class Run(Base):
    __tablename__ = "run"

    id = Column(UUID(as_uuid=True), primary_key=True)
    status = Column(String, nullable=False)            # created/queued/running/succeeded/failed
    run_type = Column(String, nullable=False, default="backtest")  # backtest/optimization

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    engine_version = Column(String, nullable=True)
    git_commit = Column(String, nullable=True)

    dataset_id = Column(UUID(as_uuid=True), ForeignKey("dataset.id"), nullable=True)

    spec_json = Column(JSONB, nullable=False)
    spec_hash = Column(String, nullable=False)         # stable hash from your run_spec
    error_message = Column(Text, nullable=True)

    mode = Column(String, nullable=False, server_default="single")
    seed = Column(Integer, nullable=True)
    dataset_hash = Column(String, nullable=True)
    code_version = Column(String, nullable=True)
    integrity_status = Column(String, nullable=True)

    rq_job_id = Column(String, nullable=True)
    progress_pct = Column(Float, nullable=True)
    progress_stage = Column(String, nullable=True)
    progress_message = Column(Text, nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)

    leaderboard_json = Column(JSONB, nullable=True)


class Artifact(Base):
    __tablename__ = "artifact"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    symbol = Column(String, nullable=True, index=True)

    artifact_type = Column(String, nullable=False)   # plotly_json, table_csv, manifest_json, etc.
    name = Column(String, nullable=False)            # e.g. equity_curve, price_trades

    object_key = Column(String, nullable=False)      # path in MinIO bucket
    bucket = Column(String, nullable=False, default="quant-artifacts")

    content_type = Column(String, nullable=False)    # application/json, text/csv
    size_bytes = Column(BigInteger, nullable=False, default=0)
    sha256 = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RunMetric(Base):
    __tablename__ = "run_metric"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol = Column(String, nullable=False)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "metric_name", name="uq_run_metric_run_id_symbol_metric_name"),
    )


class Fill(Base):
    __tablename__ = "fill"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fees = Column(Float, nullable=False, default=0.0)
    notional = Column(Float, nullable=False)
    meta = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_fill_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_fill_run_id_symbol_timestamp", "run_id", "symbol", "timestamp"),
    )


class PositionLedger(Base):
    __tablename__ = "position_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    available_qty = Column(Float, nullable=False)
    cmp = Column(Float, nullable=False)
    position_value_cost = Column(Float, nullable=False)
    pnl_realise = Column(Float, nullable=False)
    pnl_latent = Column(Float, nullable=False)
    mark_price = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_position_ledger_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_position_ledger_run_id_symbol_timestamp", "run_id", "symbol", "timestamp"),
    )


class StrategyLeaderboard(Base):
    __tablename__ = "strategy_leaderboard"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    strategy_kind = Column(String, nullable=False, index=True)
    rank = Column(Integer, nullable=False)

    pnl = Column(Float, nullable=True)
    cagr = Column(Float, nullable=True)
    efficiency = Column(Float, nullable=True)
    n_fills = Column(Integer, nullable=True)

    signal_label = Column(String, nullable=True)
    signal_today = Column(Float, nullable=True)
    signal_date = Column(DateTime(timezone=True), nullable=True)

    best_params_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "strategy_kind", "rank", name="uq_strategy_leaderboard_run_symbol_kind_rank"),
        Index("ix_strategy_leaderboard_run_symbol", "run_id", "symbol"),
        Index("ix_strategy_leaderboard_symbol_created_at", "symbol", "created_at"),
    )


class RunIntegrityCheck(Base):
    __tablename__ = "run_integrity_check"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    check_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "check_name", name="uq_run_integrity_check_run_name"),
    )


class RunFold(Base):
    __tablename__ = "run_fold"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    fold_index = Column(Integer, nullable=False)
    strategy_kind = Column(String(128), nullable=False, default="")
    train_start = Column(DateTime(timezone=True), nullable=True)
    train_end = Column(DateTime(timezone=True), nullable=True)
    test_start = Column(DateTime(timezone=True), nullable=True)
    test_end = Column(DateTime(timezone=True), nullable=True)
    fold_metrics_json = Column(JSONB, nullable=False, default=dict)
    fold_artifacts = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "strategy_kind", "fold_index", name="uq_run_fold_run_sk_index"),
    )


class RunWfoPeriod(Base):
    __tablename__ = "run_wfo_period"
    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id           = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol           = Column(String, nullable=False)
    strategy_kind    = Column(String(128), nullable=False)
    horizon          = Column(String(32), nullable=True)
    fold_no          = Column(Integer, nullable=False)
    train_start      = Column(DateTime(timezone=True), nullable=True)
    train_end        = Column(DateTime(timezone=True), nullable=True)
    test_start       = Column(DateTime(timezone=True), nullable=False)
    test_end         = Column(DateTime(timezone=True), nullable=False)
    winning_trial_id    = Column(String, nullable=False)
    optimal_params_json = Column(JSONB, nullable=False, default=dict)
    is_objective_name   = Column(String, nullable=True)
    is_objective_value  = Column(Float, nullable=True)
    oos_pnl          = Column(Float, nullable=True)
    oos_return       = Column(Float, nullable=True)
    oos_cagr         = Column(Float, nullable=True)
    oos_sharpe       = Column(Float, nullable=True)
    oos_max_drawdown = Column(Float, nullable=True)
    oos_win_pct      = Column(Float, nullable=True)
    oos_n_fills      = Column(Integer, nullable=True)
    cumulative_oos_pnl = Column(Float, nullable=True)
    is_holdout       = Column(Boolean, nullable=False, default=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("run_id","symbol","strategy_kind","horizon","fold_no",
                         name="uq_run_wfo_period_run_sk_horizon_fold"),
        Index("ix_run_wfo_period_run_id", "run_id"),
    )


class RunSignificance(Base):
    __tablename__ = "run_significance"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    method = Column(String, nullable=False)
    pvalue = Column(Float, nullable=True)
    statistic = Column(Float, nullable=True)
    mc_null_dist_ref = Column(String, nullable=True)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "method", name="uq_run_significance_run_method"),
    )


class RunRisk(Base):
    __tablename__ = "run_risk"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    kelly_fraction = Column(Float, nullable=True)
    half_kelly = Column(Float, nullable=True)
    chosen_leverage = Column(Float, nullable=True)
    mc_drawdown_pctl = Column(Float, nullable=True)
    mc_var = Column(Float, nullable=True)
    mc_cvar = Column(Float, nullable=True)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_run_risk_run_id"),
        Index("ix_run_risk_run_id", "run_id", unique=True),
    )


class StrategyDecision(Base):
    __tablename__ = "strategy_decision"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol = Column(String, nullable=False)
    strategy_kind = Column(String, nullable=False)
    trial_id = Column(String, nullable=False)
    rank = Column(Integer, nullable=True)
    params_hash = Column(String, nullable=False)
    params_json = Column(JSONB, nullable=True)
    opportunity_score = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    opportunity_subscores = Column(JSONB, nullable=False, default=dict)
    confidence_subscores = Column(JSONB, nullable=False, default=dict)
    decision_page_json = Column(JSONB, nullable=False, default=dict)
    explain_json = Column(JSONB, nullable=False, default=dict)
    status = Column(String, nullable=False, server_default="watch")
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "strategy_kind", "trial_id", name="uq_strategy_decision_run_symbol_kind_trial"),
        Index("ix_strategy_decision_run_symbol", "run_id", "symbol"),
        Index("ix_strategy_decision_run_symbol_kind_rank", "run_id", "symbol", "strategy_kind", "rank"),
    )


class DefaultsDiscoveryRun(Base):
    __tablename__ = "defaults_discovery_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_name = Column(String, nullable=False, server_default="sma_price")
    status = Column(String, nullable=False, server_default="queued")
    ticker = Column(String, nullable=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("dataset.id"), nullable=True)
    params_json = Column(JSONB, nullable=False, default=dict)
    results_json = Column(JSONB, nullable=True)
    artifacts_json = Column(JSONB, nullable=False, default=dict)
    rq_job_id = Column(String, nullable=True)
    progress_pct = Column(Float, nullable=True)
    progress_stage = Column(String, nullable=True)
    progress_message = Column(Text, nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)


class StrategyDefaultSet(Base):
    __tablename__ = "strategy_default_set"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_name = Column(String, nullable=False)
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("defaults_discovery_run.id"), nullable=True)
    defaults_json = Column(JSONB, nullable=False, default=dict)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OptTask(Base):
    __tablename__ = "opt_task"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    fold_id = Column(String, nullable=False)
    chunk_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="queued") # queued|running|succeeded|failed|canceled
    worker_job_id = Column(String, nullable=True, index=True)
    params_count = Column(Integer, nullable=False, default=0)
    spec_hash = Column(String, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_opt_task_run_fold_status", "run_id", "fold_id", "status"),
    )


class OptResult(Base):
    __tablename__ = "opt_result"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    fold_id = Column(String, nullable=False)
    chunk_id = Column(Integer, nullable=False)

    topk_json = Column(JSONB, nullable=False, default=list) # array length <= K
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "fold_id", "chunk_id", name="uq_opt_result_run_fold_chunk"),
    )


class StockMaster(Base):
    """Canonical registry of tracked Moroccan stocks."""
    __tablename__ = "stock_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String, nullable=False, unique=True)       # e.g. "ATW"
    display_name = Column(String, nullable=True)               # e.g. "Attijariwafa Bank"
    isin = Column(String, nullable=True)                       # e.g. "MA0000011926"
    sector = Column(String, nullable=True)                     # e.g. "Banques"
    market_cap_class = Column(String, nullable=True)           # "large"|"mid"|"small"
    asset_type = Column(String, nullable=False, default="equity")    # "equity"|"commodity"|"forex"|"bond"|"crypto"
    market_region = Column(String, nullable=True)              # "masi"|"us"|"european"|"asian"|null
    is_active = Column(Boolean, nullable=False, default=True)
    track_source = Column(String, nullable=False, default="bourse_direct")
    bourse_url = Column(String, nullable=True)              # direct link to Bourse de Casablanca stock page
    shares_outstanding = Column(BigInteger, nullable=True)  # latest "Nombre de titres" scraped from Bourse
    shares_source = Column(String, nullable=True)
    shares_as_of = Column(Date, nullable=True)
    shares_updated_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stock_master_is_active", "is_active"),
    )


class IndexMaster(Base):
    """Canonical registry of tracked Moroccan market indices (MASI, MASI 20, MADEX, etc.)."""
    __tablename__ = "index_master"

    symbol = Column(String, primary_key=True)           # e.g. "MASI", "MASI_20"
    display_name = Column(String, nullable=False)        # original French libellé
    family = Column(String, nullable=True)               # "all_share"|"blue_chip"|"esg"|"sector"
    market_region = Column(String, nullable=True)        # "masi"|"us"|"european"|"asian" — always 'masi' for current rows
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(String, nullable=False, default="casablanca_bourse")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_index_master_is_active", "is_active"),
    )


class MacroFactorMeta(Base):
    """DB-backed registry of macro factor series (replaces static MACRO_SERIES list in macro.py).

    asset_type maps to Data-page tabs: 'equity' | 'commodity' | 'forex' | 'bond' | 'crypto'.
    market_region maps to Data-page subtabs (equity only): 'us' | 'european' | 'asian' | None.
    """
    __tablename__ = "macro_factor_meta"

    canonical_id  = Column(String, primary_key=True)          # e.g. "VIX"
    yahoo_ticker  = Column(String, nullable=False, unique=True)  # e.g. "^VIX"
    display_name  = Column(String, nullable=False)
    asset_type    = Column(String, nullable=False)             # 'equity'|'commodity'|'forex'|'bond'|'crypto'
    market_region = Column(String, nullable=True)             # 'us'|'european'|'asian'|'masi'|NULL
    active        = Column(Boolean, nullable=False, default=True)
    added_via     = Column(String, nullable=False, default="system")  # 'system'|'user'
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes         = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_macro_factor_meta_active", "active"),
        Index("ix_macro_factor_meta_asset_type", "asset_type"),
    )


class FundamentalMacroConfig(Base):
    """Shared valuation macro assumptions for all fundamental symbols."""
    __tablename__ = "fundamental_macro_config"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    scope_key = Column(String, nullable=False, server_default="GLOBAL")
    version_label = Column(String(80), nullable=False, server_default="base")
    risk_free_mode = Column(String(20), nullable=False, server_default="tenor")
    treasury_tenor = Column(String(16), nullable=False, server_default="10Y")
    treasury_curve_json = Column(JSONB, nullable=False, default=dict)
    manual_risk_free_rate = Column(Float, nullable=True)
    erp_mode = Column(String(20), nullable=False, server_default="manual")
    erp_index_symbol = Column(String, nullable=False, server_default="MASI")
    erp_index_asset_class = Column(String(20), nullable=False, server_default="index")
    erp_lookback_years = Column(Float, nullable=False, server_default="10")
    erp_mean_method = Column(String(20), nullable=False, server_default="geometric")
    manual_equity_risk_premium = Column(Float, nullable=True)
    country_risk_mode = Column(String(20), nullable=False, server_default="auto")
    morocco_country_risk_premium = Column(Float, nullable=False, server_default="0")
    manual_country_risk_premium = Column(Float, nullable=True)
    computed_values_json = Column(JSONB, nullable=False, default=dict)
    source = Column(String(64), nullable=False, server_default="seeded_default")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_fundamental_macro_config_active", "scope_key", "is_active"),
    )


class FundamentalImport(Base):
    """One uploaded/imported structured fundamental workbook and v3 compute run."""
    __tablename__ = "fundamental_import"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("dataset.id"), nullable=True)
    filename = Column(String, nullable=False)
    source_hash = Column(String(64), nullable=False)
    object_key = Column(String, nullable=True)
    data_source = Column(String(16), nullable=False, server_default="workbook")
    source_universe = Column(String(16), nullable=True)
    status = Column(String(20), nullable=False, server_default="queued")
    methodology_version = Column(String(32), nullable=False, server_default="v3")
    rq_job_id = Column(String, nullable=True)
    company_count = Column(Integer, nullable=False, server_default="0")
    symbol_count = Column(Integer, nullable=False, server_default="0")
    annual_metric_count = Column(Integer, nullable=False, server_default="0")
    latest_snapshot_count = Column(Integer, nullable=False, server_default="0")
    quality_issue_count = Column(Integer, nullable=False, server_default="0")
    summary_json = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    imported_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_fundamental_import_status_created", "status", "created_at"),
        Index("ix_fundamental_import_rq_job_id", "rq_job_id"),
    )


class FundamentalCompanyMap(Base):
    """Ticker/company mapping captured from a fundamental workbook import."""
    __tablename__ = "fundamental_company_map"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    company_name = Column(String, nullable=False)
    mapped_company_name = Column(String, nullable=True)
    canonical_company_name = Column(String, nullable=True)
    symbol = Column(String, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    match_type = Column(String, nullable=True)
    score_note = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    is_duplicate_symbol = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "company_name", name="uq_fundamental_company_map_import_company"),
        Index("ix_fundamental_company_map_symbol", "symbol"),
    )


class FundamentalAnnualMetric(Base):
    """Normalized one-value-per-year fundamental metric with source lineage."""
    __tablename__ = "fundamental_annual_metric"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    statement_year = Column(Integer, nullable=False)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=True)
    raw_metric_name = Column(String, nullable=True)
    source_sheet = Column(String, nullable=True)
    source_field = Column(String, nullable=True)
    is_proxy = Column(Boolean, nullable=False, server_default="false")
    as_of_date = Column(Date, nullable=True)
    source_document_id = Column(BigInteger, ForeignKey("fundamental_source_document.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "symbol", "statement_year", "metric_name", name="uq_fundamental_annual_metric_key"),
        Index("ix_fundamental_annual_metric_symbol_year", "symbol", "statement_year"),
        Index("ix_fundamental_annual_metric_symbol_asof", "symbol", "as_of_date"),
    )


class FundamentalSourceDocument(Base):
    """BVC source document discovered or processed during a fundamental import."""
    __tablename__ = "fundamental_source_document"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    document_title = Column(Text, nullable=True)
    source_url = Column(Text, nullable=False)
    document_kind = Column(String(20), nullable=True)
    publication_date = Column(Date, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    period_type = Column(String(20), nullable=True)
    period_label = Column(String(20), nullable=True)
    period_end_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, server_default="queued")
    error_message = Column(Text, nullable=True)
    extracted_field_count = Column(Integer, nullable=False, server_default="0")
    raw_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "source_url", "symbol", name="uq_fundamental_source_document_import_url_symbol"),
        Index("ix_fundamental_source_document_import_symbol", "import_id", "symbol"),
        Index("ix_fundamental_source_document_period", "period_type", "fiscal_year"),
        Index("ix_fundamental_source_document_kind", "document_kind"),
    )


class FundamentalPeriodMetric(Base):
    """Normalized fundamental metric for annual, semiannual, and quarterly periods."""
    __tablename__ = "fundamental_period_metric"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    source_document_id = Column(BigInteger, ForeignKey("fundamental_source_document.id", ondelete="SET NULL"), nullable=True)
    symbol = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    period_type = Column(String(20), nullable=False, server_default="annual")
    period_label = Column(String(20), nullable=False, server_default="FY")
    period_end_date = Column(Date, nullable=True)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=True)
    raw_metric_name = Column(String, nullable=True)
    source_url = Column(Text, nullable=True)
    document_title = Column(Text, nullable=True)
    is_proxy = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "import_id",
            "symbol",
            "fiscal_year",
            "period_type",
            "period_label",
            "metric_name",
            name="uq_fundamental_period_metric_key",
        ),
        Index("ix_fundamental_period_metric_symbol_period", "symbol", "period_type", "fiscal_year"),
        Index("ix_fundamental_period_metric_import_symbol", "import_id", "symbol"),
    )


class FundamentalLatestSnapshot(Base):
    """Latest per-symbol fundamentals plus scores and model eligibility."""
    __tablename__ = "fundamental_latest_snapshot"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    latest_statement_year = Column(Integer, nullable=True)
    data_source = Column(String(16), nullable=False, server_default="workbook")
    metrics_json = Column(JSONB, nullable=False, default=dict)
    scores_json = Column(JSONB, nullable=False, default=dict)
    diagnostics_json = Column(JSONB, nullable=False, default=dict)
    coverage_json = Column(JSONB, nullable=False, default=dict)
    model_eligibility_json = Column(JSONB, nullable=False, default=dict)
    source_json = Column(JSONB, nullable=False, default=dict)
    as_of_date = Column(Date, nullable=True)
    source_document_id = Column(BigInteger, ForeignKey("fundamental_source_document.id", ondelete="SET NULL"), nullable=True)
    is_canonical = Column(Boolean, nullable=True, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "symbol", name="uq_fundamental_latest_snapshot_import_symbol"),
        Index("ix_fundamental_latest_snapshot_symbol", "symbol"),
        Index("ix_fundamental_latest_snapshot_symbol_asof", "symbol", "as_of_date"),
        Index("ix_fundamental_latest_snapshot_symbol_canonical", "symbol", "is_canonical"),
    )


class FundamentalQualityIssue(Base):
    """Import-level and symbol-level data-quality issue captured during v3 ingestion."""
    __tablename__ = "fundamental_quality_issue"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    severity = Column(String(20), nullable=False)
    code = Column(String(80), nullable=False)
    message = Column(Text, nullable=False)
    symbol = Column(String, nullable=True)
    metric_name = Column(String, nullable=True)
    statement_year = Column(Integer, nullable=True)
    context_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_fundamental_quality_issue_import_symbol", "import_id", "symbol"),
        Index("ix_fundamental_quality_issue_code", "code"),
    )


class FundamentalAssumptionSet(Base):
    """Versioned desk, sector, or symbol assumptions per scenario."""
    __tablename__ = "fundamental_assumption_set"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type = Column(String(20), nullable=False, server_default="symbol")
    scope_key = Column(String, nullable=False, server_default="GLOBAL")
    scenario = Column(String(32), nullable=False, server_default="base")
    version_label = Column(String(80), nullable=False, server_default="base")
    assumptions_json = Column(JSONB, nullable=False, default=dict)
    source = Column(String(32), nullable=False, server_default="seeded_default")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_type", "scope_key", "scenario", "version_label", name="uq_fundamental_assumption_scope_scenario_version"),
        Index("ix_fundamental_assumption_scope", "scope_type", "scope_key"),
        Index("ix_fundamental_assumption_active", "scenario", "is_active"),
    )


class FundamentalAssumptionOverride(Base):
    """Append-only per-symbol scenario assumption override history."""
    __tablename__ = "fundamental_assumption_override"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(Text, nullable=False)
    scenario = Column(Text, nullable=False)
    overrides = Column(JSONB, nullable=False, default=dict)
    note = Column(Text, nullable=True)
    created_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        CheckConstraint("scenario in ('bear','base','bull')", name="ck_fundamental_assumption_override_scenario"),
        Index(
            "uq_fundamental_assumption_override_current",
            "symbol",
            "scenario",
            unique=True,
            postgresql_where=text("is_current = true"),
            sqlite_where=text("is_current = 1"),
        ),
        Index("ix_fundamental_assumption_override_symbol_created", "symbol", "created_at"),
    )


class FundamentalMetricOverride(Base):
    """Append-only manual corrections for normalized annual metric values."""
    __tablename__ = "fundamental_metric_override"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(Text, nullable=False)
    statement_year = Column(Integer, nullable=False)
    metric_name = Column(Text, nullable=False)
    metric_value = Column(Float, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        Index(
            "uq_fundamental_metric_override_current",
            "symbol",
            "statement_year",
            "metric_name",
            unique=True,
            postgresql_where=text("is_current = true"),
            sqlite_where=text("is_current = 1"),
        ),
        Index("ix_fundamental_metric_override_symbol_created", "symbol", "created_at"),
        Index("ix_fundamental_metric_override_symbol_year", "symbol", "statement_year"),
    )


class FundamentalValuationResult(Base):
    """Persisted valuation model outputs for a symbol/scenario with model metadata."""
    __tablename__ = "fundamental_valuation_result"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    scenario = Column(String(32), nullable=False, server_default="base")
    model = Column(String(64), nullable=False)
    fair_value = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    upside_pct = Column(Float, nullable=True)
    confidence = Column(String(20), nullable=False, server_default="unavailable")
    confidence_score = Column(Float, nullable=True)
    weight = Column(Float, nullable=True)
    family = Column(String(32), nullable=False, server_default="intrinsic")
    methodology = Column(Text, nullable=True)
    model_version = Column(String(32), nullable=False, server_default="v3")
    is_proxy = Column(Boolean, nullable=False, server_default="false")
    data_quality_score = Column(Float, nullable=True)
    currency = Column(String(8), nullable=True)
    inputs_json = Column(JSONB, nullable=False, default=dict)
    outputs_json = Column(JSONB, nullable=False, default=dict)
    warnings_json = Column(JSONB, nullable=False, default=list)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "symbol", "scenario", "model", name="uq_fundamental_valuation_key"),
        Index("ix_fundamental_valuation_symbol", "symbol"),
    )


class FundamentalEnsembleResult(Base):
    """Confidence-weighted valuation range for a symbol/scenario."""
    __tablename__ = "fundamental_ensemble_result"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    scenario = Column(String(32), nullable=False, server_default="base")
    fair_value_low = Column(Float, nullable=True)
    fair_value_base = Column(Float, nullable=True)
    fair_value_high = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    upside_pct = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    usable_model_count = Column(Integer, nullable=False, server_default="0")
    excluded_model_count = Column(Integer, nullable=False, server_default="0")
    model_weights_json = Column(JSONB, nullable=False, default=dict)
    warnings_json = Column(JSONB, nullable=False, default=list)
    sensitivity_grids_json = Column(JSONB, nullable=True)
    currency = Column(String(8), nullable=True)
    model_dispersion_low = Column(Float, nullable=True)
    model_dispersion_base = Column(Float, nullable=True)
    model_dispersion_high = Column(Float, nullable=True)
    monte_carlo_low = Column(Float, nullable=True)
    monte_carlo_base = Column(Float, nullable=True)
    monte_carlo_high = Column(Float, nullable=True)
    fair_value_mean = Column(Float, nullable=True)
    model_dispersion_cv = Column(Float, nullable=True)
    dispersion_factor = Column(Float, nullable=True)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "symbol", "scenario", name="uq_fundamental_ensemble_key"),
        Index("ix_fundamental_ensemble_symbol", "symbol"),
    )


class FundamentalProjection(Base):
    """Persisted PIT projection lines and driver evidence for a symbol/scenario."""
    __tablename__ = "fundamental_projection"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    scenario = Column(String(32), nullable=False, server_default="base")
    fiscal_year = Column(Integer, nullable=False)
    periods_per_year = Column(Integer, nullable=False, server_default="1")
    period_type = Column(String(20), nullable=False, server_default="annual")
    period_index = Column(Integer, nullable=False, server_default="0")
    period_label = Column(String(20), nullable=False, server_default="FY")
    period_end_date = Column(Date, nullable=True)
    line_item = Column(String(80), nullable=False)
    projected_value = Column(Float, nullable=True)
    evidence_json = Column(JSONB, nullable=False, default=dict)
    as_of = Column(Date, nullable=True)
    is_override = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "symbol", "scenario", "fiscal_year", "period_type", "period_index", "line_item", name="uq_fundamental_projection_line"),
        Index("ix_fundamental_projection_symbol_asof", "symbol", "as_of"),
        Index("ix_fundamental_projection_symbol_scenario", "symbol", "scenario"),
        Index("ix_fundamental_projection_symbol_period", "symbol", "scenario", "period_type", "fiscal_year", "period_index"),
    )


class FundamentalSignalBacktest(Base):
    """Persisted PIT fundamental signal validation exhibit."""
    __tablename__ = "fundamental_signal_backtest"

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal = Column(String(32), nullable=False)
    universe = Column(String(32), nullable=False)
    rebalance = Column(String(16), nullable=False, server_default="M")
    as_of = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status = Column(String(20), nullable=False, server_default="succeeded")
    error_message = Column(Text, nullable=True)
    quintile_returns_json = Column(JSONB, nullable=False, default=list)
    ic_json = Column(JSONB, nullable=False, default=dict)
    equity_curve_json = Column(JSONB, nullable=False, default=list)
    turnover_json = Column(JSONB, nullable=False, default=list)
    holdings_json = Column(JSONB, nullable=False, default=list)
    params_json = Column(JSONB, nullable=False, default=dict)
    warnings_json = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_fundamental_signal_backtest_created", "created_at"),
        Index("ix_fundamental_signal_backtest_signal_universe", "signal", "universe"),
    )


class FundamentalBetaHistory(Base):
    """Point-in-time equity beta estimates used by fundamental valuation."""
    __tablename__ = "fundamental_beta_history"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    as_of = Column(Date, nullable=False)
    beta = Column(Float, nullable=False)
    raw_beta = Column(Float, nullable=True)
    method = Column(String(32), nullable=False)
    r2 = Column(Float, nullable=True)
    n_obs = Column(Integer, nullable=False, server_default="0")
    zero_week_frac = Column(Float, nullable=True)
    liquidity_flag = Column(Boolean, nullable=False, server_default="false")
    proxy = Column(String, nullable=False, server_default="MASI")
    frequency = Column(String(16), nullable=False, server_default="weekly")
    window_years = Column(Float, nullable=False, server_default="2")
    warnings_json = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "as_of", "proxy", "frequency", "window_years", name="uq_fundamental_beta_history_key"),
        Index("ix_fundamental_beta_history_symbol_asof", "symbol", "as_of"),
        Index("ix_fundamental_beta_history_proxy_asof", "proxy", "as_of"),
    )


class FundamentalIntegrityReport(Base):
    __tablename__ = "fundamental_integrity_report"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    statement_year = Column(Integer, nullable=False)
    overall_status = Column(String(20), nullable=False)
    confidence_haircut = Column(Float, nullable=False, default=0.0)
    checks_json = Column(JSONB, nullable=False, default=list)
    projected_statements_json = Column(JSONB, nullable=True)
    projection_checks_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "statement_year", "import_id", name="uq_fundamental_integrity_symbol_year_import"),
        Index("ix_fundamental_integrity_symbol_year", "symbol", "statement_year"),
        CheckConstraint("overall_status in ('pass','derived','warn','fail','unavailable')", name="ck_fundamental_integrity_status"),
    )


class FundamentalDataVerification(Base):
    """Auditable tie-out verdict for the raw annual data used by valuation."""
    __tablename__ = "fundamental_data_verification"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    statement_year = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False)
    reason = Column(Text, nullable=True)
    failed_checks_json = Column(JSONB, nullable=False, default=list)
    warnings_json = Column(JSONB, nullable=False, default=list)
    offending_metrics_json = Column(JSONB, nullable=False, default=dict)
    recomputed_metrics_json = Column(JSONB, nullable=False, default=dict)
    corrections_json = Column(JSONB, nullable=False, default=dict)
    provenance_json = Column(JSONB, nullable=False, default=dict)
    source_urls_json = Column(JSONB, nullable=False, default=list)
    stockanalysis_json = Column(JSONB, nullable=False, default=dict)
    tieout_report_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("import_id", "symbol", "statement_year", name="uq_fundamental_data_verification_import_symbol_year"),
        Index("ix_fundamental_data_verification_symbol_year", "symbol", "statement_year"),
        Index("ix_fundamental_data_verification_status", "status"),
        CheckConstraint("status in ('verified','data_unverified')", name="ck_fundamental_data_verification_status"),
    )


class FundamentalThesis(Base):
    __tablename__ = "fundamental_thesis"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    as_of = Column(Date, nullable=False)
    direction = Column(String(20), nullable=False)
    conviction = Column(String(20), nullable=False)
    core_thesis = Column(Text, nullable=False)
    bullish_drivers_json = Column(JSONB, nullable=False, default=list)
    bearish_drivers_json = Column(JSONB, nullable=False, default=list)
    target_price = Column(Float, nullable=True)
    target_horizon_months = Column(Integer, nullable=True)
    stop_price = Column(Float, nullable=True)
    invalidation_conditions_json = Column(JSONB, nullable=False, default=list)
    linked_catalyst_ids_json = Column(JSONB, nullable=False, default=list)
    created_by = Column(String, nullable=False, default="api")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        CheckConstraint("direction in ('long','short','pair_long','pair_short','avoid')", name="ck_fundamental_thesis_direction"),
        CheckConstraint("conviction in ('high','medium','low')", name="ck_fundamental_thesis_conviction"),
        Index("ix_fundamental_thesis_symbol_created", "symbol", "created_at"),
        Index(
            "uq_fundamental_thesis_current_symbol",
            "symbol",
            unique=True,
            postgresql_where=text("is_current = true"),
            sqlite_where=text("is_current = 1"),
        ),
    )


class FundamentalCatalyst(Base):
    __tablename__ = "fundamental_catalyst"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    event_type = Column(String(32), nullable=False)
    event_date = Column(Date, nullable=False)
    event_date_confidence = Column(String(20), nullable=False)
    impact_tier = Column(String(20), nullable=False)
    expected_direction = Column(String(20), nullable=True)
    title = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    source = Column(String, nullable=False)
    source_payload_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    superseded_by_id = Column(BigInteger, ForeignKey("fundamental_catalyst.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        CheckConstraint("event_type in ('earnings','dividend','ex_dividend','agm','guidance','regulatory','product','m_and_a','split','other')", name="ck_fundamental_catalyst_event_type"),
        CheckConstraint("event_date_confidence in ('confirmed','estimated','rumour')", name="ck_fundamental_catalyst_date_confidence"),
        CheckConstraint("impact_tier in ('high','moderate','routine')", name="ck_fundamental_catalyst_impact_tier"),
        CheckConstraint("(expected_direction is null) or expected_direction in ('positive','negative','neutral')", name="ck_fundamental_catalyst_expected_direction"),
        Index("ix_fundamental_catalyst_symbol_date", "symbol", "event_date"),
        Index("ix_fundamental_catalyst_active_date", "is_active", "event_date"),
        Index("ix_fundamental_catalyst_symbol_active_date", "symbol", "is_active", "event_date"),
    )


class FundamentalPillarScoreHistory(Base):
    __tablename__ = "fundamental_pillar_score_history"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    import_id = Column(UUID(as_uuid=True), ForeignKey("fundamental_import.id", ondelete="CASCADE"), nullable=False)
    as_of = Column(Date, nullable=False)
    value_score = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    growth_score = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    cash_flow_score = Column(Float, nullable=True)
    health_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)
    pillar_coverage_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "import_id", name="uq_fundamental_pillar_history_symbol_import"),
        Index("ix_fundamental_pillar_history_symbol_asof", "symbol", "as_of"),
    )


class BloombergIngestBatch(Base):
    """Immutable raw Bloomberg bridge upload plus normalized batch metadata."""
    __tablename__ = "bloomberg_ingest_batch"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bridge_id = Column(String(128), nullable=False)
    request_id = Column(String(160), nullable=False)
    bloomberg_source = Column(String(32), nullable=False)
    kind = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="succeeded")
    raw_object_key = Column(String, nullable=False)
    manifest_object_key = Column(String, nullable=False)
    normalized_object_key = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    data_sha256 = Column(String(64), nullable=False)
    row_count = Column(Integer, nullable=False, default=0)
    series_count = Column(Integer, nullable=False, default=0)
    manifest_json = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("bridge_id", "request_id", name="uq_bloomberg_ingest_batch_bridge_request"),
        Index("ix_bloomberg_ingest_batch_created_at", "created_at"),
        Index("ix_bloomberg_ingest_batch_bridge_id", "bridge_id"),
        Index("ix_bloomberg_ingest_batch_kind", "kind"),
    )


class BloombergSeries(Base):
    """Indexed Bloomberg time series derived from generic bridge uploads."""
    __tablename__ = "bloomberg_series"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    series_key = Column(String(64), nullable=False, unique=True)
    last_batch_id = Column(UUID(as_uuid=True), ForeignKey("bloomberg_ingest_batch.id"), nullable=False)
    security = Column(String(256), nullable=False)
    field = Column(String(128), nullable=False)
    periodicity = Column(String(32), nullable=True)
    overrides_hash = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False, default="time_series")
    object_key = Column(String, nullable=False)
    start_ts = Column(DateTime(timezone=True), nullable=True)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    row_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_bloomberg_series_security", "security"),
        Index("ix_bloomberg_series_field", "field"),
        Index("ix_bloomberg_series_updated_at", "updated_at"),
    )


class BloombergBridgeStatus(Base):
    """Last known state for a Bloomberg Terminal bridge listener."""
    __tablename__ = "bloomberg_bridge_status"

    bridge_id = Column(String(128), primary_key=True)
    status = Column(String(32), nullable=False, default="offline")
    capabilities_json = Column(JSONB, nullable=False, default=dict)
    preflight_json = Column(JSONB, nullable=False, default=dict)
    active_job_id = Column(UUID(as_uuid=True), ForeignKey("bloomberg_job.id"), nullable=True)
    error_message = Column(Text, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_bloomberg_bridge_status_last_seen_at", "last_seen_at"),
        Index("ix_bloomberg_bridge_status_status", "status"),
    )


class BloombergJob(Base):
    """Control-plane job requested by the app and executed by a Bloomberg bridge."""
    __tablename__ = "bloomberg_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    requested_by = Column(String(128), nullable=True)
    bridge_id = Column(String(128), nullable=True)
    spec_json = Column(JSONB, nullable=False, default=dict)
    progress_json = Column(JSONB, nullable=False, default=dict)
    result_json = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_bloomberg_job_status_created_at", "status", "created_at"),
        Index("ix_bloomberg_job_bridge_id", "bridge_id"),
        Index("ix_bloomberg_job_job_type", "job_type"),
    )


class BloombergJobEvent(Base):
    """Append-only status/progress events for Bloomberg control-plane jobs."""
    __tablename__ = "bloomberg_job_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("bloomberg_job.id"), nullable=False)
    bridge_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=True)
    message = Column(Text, nullable=True)
    payload_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_bloomberg_job_event_job_id_created_at", "job_id", "created_at"),
    )


class StockFactorRelevance(Base):
    """Stores the active factors selected for a specific stock by the Phase 3 econometric pipeline.
    
    A composite primary key on (symbol, horizon, factor_canonical_id) links a stock
    to its selected macro factor for a specific forecast horizon.
    """
    __tablename__ = "stock_factor_relevance"

    symbol = Column(String, primary_key=True)               # e.g. "ATW"
    horizon = Column(String, primary_key=True)              # 'short' | 'mid' | 'long'
    factor_canonical_id = Column(String, primary_key=True)  # e.g. "SP500", "VIX"
    rank = Column(Integer, nullable=True)
    ic = Column(Float, nullable=True)
    spearman_ic = Column(Float, nullable=True)
    pearson_corr = Column(Float, nullable=True)
    ic_t_stat = Column(Float, nullable=True)
    bh_p_adj = Column(Float, nullable=True)
    lasso_coef = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=False)         # compatibility mirror of lasso_coef
    n_obs = Column(Integer, nullable=True)
    selected_reason = Column(String(32), nullable=True)
    last_calibrated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    cusum_drift_score = Column(Float, nullable=True)        # CUSUM metric tracking parameter drift
    cusum_alarm = Column(Boolean, nullable=False, default=False)  # legacy compatibility
    cusum_status = Column(String, nullable=False, default="valid")
    regime_start = Column(Date, nullable=True)
    low_confidence = Column(Boolean, nullable=False, default=False)
    next_forced_recal = Column(DateTime(timezone=True), nullable=True)
    history_n_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stock_factor_relevance_symbol", "symbol"),
        Index("idx_sfr_active", "symbol", "horizon", postgresql_where=text("cusum_status = 'valid'")),
    )


class StockFactorStage1Cache(Base):
    """Internal cache for Phase 3 Stage 1 (BH-FDR NW IC) screening.
    
    Stores the pre-LASSO Information Coefficient metrics to avoid re-computing NW t-stats
    daily unless the factor/stock series have shifted.
    """
    __tablename__ = "stock_factor_stage1_cache"

    symbol = Column(String, primary_key=True)
    horizon = Column(String, primary_key=True)
    factor_canonical_id = Column(String, primary_key=True)
    ic_mean = Column(Float, nullable=False)
    spearman_ic = Column(Float, nullable=True)
    pearson_corr = Column(Float, nullable=True)
    ic_tstat = Column(Float, nullable=False)
    bh_p_adj = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
    n_obs = Column(Integer, nullable=True)
    selected_reason = Column(String(32), nullable=True)
    passed_fdr = Column(Boolean, nullable=False)
    regime_start = Column(Date, nullable=True)
    low_confidence = Column(Boolean, nullable=False, default=False)
    history_n_days = Column(Integer, nullable=True)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stage1_cache_symbol_horizon", "symbol", "horizon"),
    )


class ProviderSymbolMap(Base):
    """Maps internal canonical symbol to provider-specific ticker."""
    __tablename__ = "provider_symbol_map"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, ForeignKey("stock_master.symbol"), nullable=False)
    provider = Column(String, nullable=False)                  # "yahoo"|"bourse_direct"|"bmce_excel"
    provider_symbol = Column(String, nullable=False)           # e.g. "ATW.CS" for Yahoo
    confidence = Column(Float, nullable=False, default=1.0)   # 0.0–1.0
    is_verified = Column(Boolean, nullable=False, default=False)
    override_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "provider", name="uq_provider_symbol_map_symbol_provider"),
    )


class MarketRefreshRun(Base):
    """Tracks each bulk or single-symbol market data refresh job."""
    __tablename__ = "market_refresh_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_source = Column(String, nullable=False, default="manual")  # "manual"|"scheduled"|"api"
    scope = Column(String, nullable=False, default="all")              # "all"|"single"
    symbol = Column(String, nullable=True)                             # NULL if scope="all"
    timeframe = Column(String, nullable=False, default="1D")
    status = Column(String, nullable=False, default="queued")          # "queued"|"running"|"succeeded"|"partial"|"failed"
    rq_job_id = Column(String, nullable=True)
    symbols_total = Column(Integer, nullable=True)
    symbols_done = Column(Integer, nullable=True)
    symbols_failed = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    error_message = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_market_refresh_run_status", "status"),
        Index("ix_market_refresh_run_created_at", "created_at"),
    )


class SavedStrategy(Base):
    """Persisted trading strategy with configuration and snapshot."""
    __tablename__ = "saved_strategy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="draft")          # draft/modified/saved/archived
    side_policy = Column(String(20), nullable=False, default="long_only") # long_only/long_short
    horizon = Column(String(20), nullable=False, default="medium")        # short/medium/long
    config_json = Column(JSONB, nullable=False, default=dict)             # all layer configs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_saved_strategy_status", "status"),
        Index("ix_saved_strategy_updated_at", "updated_at"),
    )


class DashboardCustomIndex(Base):
    """Persisted custom dashboard index definition owned by one app user."""
    __tablename__ = "dashboard_custom_index"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = Column(String, nullable=True)
    name = Column(String(120), nullable=False)
    symbols = Column(JSONB, nullable=False, default=list)
    component_shares = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_dashboard_custom_index_updated_at", "updated_at"),
        Index("ix_dashboard_custom_index_owner_updated_at", "owner_user_id", "updated_at"),
        Index("uq_dashboard_custom_index_owner_name_ci", "owner_user_id", func.lower(name), unique=True),
    )


class DashboardPortfolio(Base):
    """Named dashboard portfolio definition and replay metadata owned by one app user."""
    __tablename__ = "dashboard_portfolio"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = Column(String, nullable=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    symbols = Column(JSONB, nullable=False, default=list)
    component_shares = Column(JSONB, nullable=False, default=dict)
    allocation_method = Column(String(24), nullable=False, default="share_quantities")
    side_policy = Column(String(20), nullable=False, default="long_only")
    total_capital_mad = Column(Float, nullable=False, default=1_000_000.0)
    cash_buffer_pct = Column(Float, nullable=False, default=0.0)
    stop_loss_pct = Column(Float, nullable=True)
    take_profit_pct = Column(Float, nullable=True)
    display_mode = Column(String(32), nullable=False, default="trade_opportunities")
    technical_direction_mode = Column(String(16), nullable=False, default="best")
    horizon = Column(String(20), nullable=False, default="monthly")
    is_default = Column(Boolean, nullable=False, default=False)
    replay_start_date = Column(Date, nullable=True)
    replay_end_date = Column(Date, nullable=True)
    replay_generated_at = Column(DateTime(timezone=True), nullable=True)
    last_replay_json = Column(JSONB, nullable=False, default=dict)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_dashboard_portfolio_owner_updated_at", "owner_user_id", "updated_at"),
        Index("uq_dashboard_portfolio_owner_name_ci", "owner_user_id", func.lower(name), unique=True),
        Index("ix_dashboard_portfolio_owner_default", "owner_user_id", "is_default"),
    )


class DeskPortfolioPosition(Base):
    """Manual current-position state used by the daily dashboard blotter."""
    __tablename__ = "desk_portfolio_position"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = Column(String, nullable=True)
    portfolio_id = Column(UUID(as_uuid=True), ForeignKey("dashboard_portfolio.id", ondelete="CASCADE"), nullable=True)
    symbol = Column(String, nullable=False)
    side = Column(String(16), nullable=False, default="long")
    quantity = Column(Float, nullable=False, default=0.0)
    average_price_mad = Column(Float, nullable=True)
    opened_at = Column(Date, nullable=True)
    planned_holding_bars = Column(Integer, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    notes = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", "side", name="uq_desk_portfolio_position_portfolio_symbol_side"),
        Index("ix_desk_portfolio_position_status", "status"),
        Index("ix_desk_portfolio_position_symbol", "symbol"),
        Index("ix_desk_portfolio_position_owner_status", "owner_user_id", "status"),
        Index("ix_desk_portfolio_position_portfolio_status", "portfolio_id", "status"),
    )


class DeskPortfolioFill(Base):
    """Manual fill audit trail for desk portfolio reconciliation."""
    __tablename__ = "desk_portfolio_fill"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = Column(String, nullable=True)
    portfolio_id = Column(UUID(as_uuid=True), ForeignKey("dashboard_portfolio.id", ondelete="CASCADE"), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String(16), nullable=False)
    quantity = Column(Float, nullable=False)
    price_mad = Column(Float, nullable=False)
    fees_mad = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_desk_portfolio_fill_owner_timestamp", "owner_user_id", "timestamp"),
        Index("ix_desk_portfolio_fill_portfolio_timestamp", "portfolio_id", "timestamp"),
        Index("ix_desk_portfolio_fill_timestamp", "timestamp"),
        Index("ix_desk_portfolio_fill_symbol_timestamp", "symbol", "timestamp"),
    )


class StrategyBacktestRun(Base):
    __tablename__ = "strategy_backtest_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("saved_strategy.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="")
    mode = Column(String(20), nullable=False, default="direct")
    status = Column(String(20), nullable=False, default="queued")
    horizon = Column(String(20), nullable=False, default="medium")
    execution_fingerprint = Column(String(64), nullable=False, default="")
    strategy_snapshot_json = Column(JSONB, nullable=False, default=dict)
    data_snapshot_json = Column(JSONB, nullable=False, default=dict)
    request_json = Column(JSONB, nullable=False, default=dict)
    summary_json = Column(JSONB, nullable=False, default=dict)
    result_json = Column(JSONB, nullable=False, default=dict)
    progress_json = Column(JSONB, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)
    rq_job_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_strategy_backtest_run_status", "status"),
        Index("ix_strategy_backtest_run_created_at", "created_at"),
        Index("ix_strategy_backtest_run_execution_fingerprint", "execution_fingerprint"),
    )


class StrategyBacktestStock(Base):
    __tablename__ = "strategy_backtest_stock"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("strategy_backtest_run.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    summary_json = Column(JSONB, nullable=False, default=dict)
    result_json = Column(JSONB, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_strategy_backtest_stock_run_symbol"),
        Index("ix_strategy_backtest_stock_run", "run_id"),
    )


class StrategyBacktestWindow(Base):
    __tablename__ = "strategy_backtest_window"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("strategy_backtest_run.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    window_index = Column(Integer, nullable=False)
    summary_json = Column(JSONB, nullable=False, default=dict)
    detail_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "window_index", name="uq_strategy_backtest_window_run_symbol_index"),
        Index("ix_strategy_backtest_window_run", "run_id"),
    )


class WfoSignalSummary(Base):
    """Cached WFO signal result for one (symbol, category, horizon) tuple."""
    __tablename__ = "wfo_signal_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    category = Column(String(32), nullable=False)       # "tendance" | "momentum" | "oscillation" | "volume"
    horizon = Column(String(16), nullable=False)         # "short" | "medium" | "long"
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, default="pending")  # "pending" | "running" | "succeeded" | "failed"

    # --- WFO results ---
    score_pct = Column(Float, nullable=True)             # -100.0 to +100.0  (ensemble score)
    signal_label = Column(String(60), nullable=True)     # French label from signal_type_label()
    representatives_json = Column(JSONB, nullable=False, default=list)
    folds_json = Column(JSONB, nullable=True)             # per-fold details (IS/OOS returns, winner, profile)
    config_json = Column(JSONB, nullable=True)            # WFO config used (train/test/step, grid_size, etc.)
    fragility_json = Column(JSONB, nullable=True)          # C.1 local-neighborhood fragility cache

    # --- WFO quality metrics ---
    wfe_pct = Column(Float, nullable=True)
    robustness_ratio = Column(Float, nullable=True)      # 0.0 to 1.0
    total_folds = Column(Integer, nullable=True)
    profitable_folds = Column(Integer, nullable=True)
    mean_oos_sharpe = Column(Float, nullable=True)
    total_oos_pnl = Column(Float, nullable=True)
    worst_fold_drawdown = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)       # pre-computed ranking score (0-100)
    robustness_grade = Column(String(2), nullable=True)  # "A" | "B" | "C" | "D" | "F"

    # --- Metadata ---
    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)             # last bar date in OHLCV when computed
    compute_seconds = Column(Float, nullable=True)       # wall-clock time for this family WFO
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "category", "horizon", "variant", name="uq_wfo_signal_summary_sym_cat_hz_var"),
        Index("ix_wfo_signal_summary_symbol_horizon", "symbol", "horizon"),
        Index("ix_wfo_signal_summary_status", "status"),
    )


class WfoGlobalSignal(Base):
    """Cached WFO global consensus signal for one (symbol, horizon) tuple."""
    __tablename__ = "wfo_global_signal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, default="pending")

    # --- Consensus signal ---
    global_score_pct = Column(Float, nullable=True)      # -100 to +100 (after S/R modulation)
    raw_score_pct = Column(Float, nullable=True)          # -100 to +100 (before S/R modulation)
    signal_label = Column(String(60), nullable=True)
    recommendation = Column(String(32), nullable=True)    # "achat_fort" | "achat" | "neutre" | "vente" | "vente_forte"

    # --- Family weights (WFO-optimized, sum to 1.0) ---
    weight_tendance = Column(Float, nullable=True)
    weight_momentum = Column(Float, nullable=True)
    weight_oscillation = Column(Float, nullable=True)
    weight_volume = Column(Float, nullable=True)

    # --- S/R modulation ---
    sr_modifier = Column(Float, nullable=True)            # multiplier applied (e.g., 1.12 or 0.88)
    sr_support_level = Column(Float, nullable=True)
    sr_resistance_level = Column(Float, nullable=True)
    sr_support_method = Column(String(40), nullable=True)
    sr_resistance_method = Column(String(40), nullable=True)
    sr_distance_support_atr = Column(Float, nullable=True)
    sr_distance_resistance_atr = Column(Float, nullable=True)

    # --- Cross-family ranking ---
    best_category = Column(String(32), nullable=True)     # "tendance" | "momentum" | ...
    best_category_score = Column(Float, nullable=True)
    categories_viable = Column(Integer, nullable=True)    # how many categories have grade >= C

    # --- WFO quality for the consensus pass ---
    consensus_wfe_pct = Column(Float, nullable=True)
    consensus_robustness = Column(Float, nullable=True)

    # --- Metadata ---
    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon", "variant", name="uq_wfo_global_signal_sym_hz_var"),
        Index("ix_wfo_global_signal_symbol", "symbol"),
    )


class SignalEngineFamilyResult(Base):
    """Persisted A→G signal engine output for one (symbol, family, horizon, variant).

    Mirrors WfoSignalSummary in structure. Enables export-scores.py to read
    from DB instead of recomputing the full pipeline on every run.
    """
    __tablename__ = "signal_engine_family_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Natural key
    symbol = Column(String, nullable=False)
    family = Column(String(64), nullable=False)        # "sma" | "macd" | "rsi" | …
    category = Column(String(32), nullable=False)      # denormalized from CATEGORY_FAMILIES
    horizon = Column(String(16), nullable=False)       # "short" | "medium" | "long"
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, server_default="pending")

    # Signal output
    family_score_pct = Column(Float, nullable=True)
    signal_label = Column(String(60), nullable=True)

    # Committed representative variants + weights (consumed by backtest)
    representatives_json = Column(JSONB, nullable=False, default=list)

    # Full family snapshot — verbatim _build_family_snapshot() output for export-scores.py
    family_detail_json = Column(JSONB, nullable=True)

    # Quality / selection counts
    tested_count = Column(Integer, nullable=True)
    viable_count = Column(Integer, nullable=True)
    competitive_count = Column(Integer, nullable=True)
    representative_count = Column(Integer, nullable=True)
    is_provisional = Column(Boolean, nullable=False, server_default="false")
    warning_message = Column(Text, nullable=True)

    # Staleness marker — SHA-256 of (data_as_of + cost_bps + cooldown_bars)
    input_hash = Column(String(64), nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    compute_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "family", "horizon", "variant", name="uq_sefr_sym_fam_hz_var"),
        Index("ix_sefr_symbol_horizon", "symbol", "horizon"),
        Index("ix_sefr_category_horizon", "category", "horizon"),
        Index("ix_sefr_status", "status"),
    )


class SignalEngineGlobalResult(Base):
    """Persisted A→G global aggregate for one (symbol, horizon, variant).

    Stores both legacy (1 family/category) and expanded (up to 5 families/category)
    aggregate scores plus per-category breakdowns. Mirrors WfoGlobalSignal.
    """
    __tablename__ = "signal_engine_global_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    variant = Column(String(64), nullable=False, server_default="expanded")
    status = Column(String(20), nullable=False, server_default="pending")

    # Aggregate scores
    aggregate_score_pct = Column(Float, nullable=True)           # legacy: 1 family per category
    expanded_aggregate_score_pct = Column(Float, nullable=True)  # expanded: up to 5 families per category
    signal_label = Column(String(60), nullable=True)

    # Per-category and per-family breakdowns
    per_category_json = Column(JSONB, nullable=True)    # {category: {score_pct, label, family_scores: {family: score}}}
    per_family_json = Column(JSONB, nullable=True)      # {family: {score_pct, label}}

    # Technical levels + S/R stored verbatim for export-scores.py backward compat
    technical_levels_json = Column(JSONB, nullable=True)
    support_resistance_json = Column(JSONB, nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon", "variant", name="uq_segr_sym_hz_var"),
        Index("ix_segr_symbol", "symbol"),
        Index("ix_segr_horizon_status", "horizon", "status"),
    )


class SignalScoreHistory(Base):
    """Per-bar category-aggregated signal score, used for predictive-ability analytics.

    One row per (date, symbol, source, category, horizon). `source` distinguishes
    engine_legacy / engine_expanded / wfo. `score_pct` is in [-100, +100] — for
    WFO it's discretized to {-100, 0, +100} (binary signal mapped from {-1,0,+1}).
    """
    __tablename__ = "signal_score_history"

    date = Column(Date, primary_key=True, nullable=False)
    symbol = Column(String, primary_key=True, nullable=False)
    source = Column(String(64), primary_key=True, nullable=False)
    category = Column(String(32), primary_key=True, nullable=False)
    horizon = Column(String(16), primary_key=True, nullable=False)
    score_pct = Column(Float, nullable=True)
    is_oos = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index("ix_ssh_symbol_source_horizon", "symbol", "source", "horizon"),
        Index("ix_ssh_symbol_date", "symbol", "date"),
    )


class ScoreHistoryJob(Base):
    """Tracks score-history population jobs (one per symbol)."""
    __tablename__ = "score_history_job"

    symbol = Column(String, primary_key=True, nullable=False)
    status = Column(String(20), nullable=False, server_default="pending")
    rq_job_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_shj_status", "status"),
    )


class StatArbPairSignal(Base):
    """Analytics-only statistical-arbitrage pair signal summary."""
    __tablename__ = "stat_arb_pair_signal"

    pair_id = Column(String(32), primary_key=True)
    symbol_y = Column(String, nullable=False)
    symbol_x = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    archetype = Column(String(32), nullable=False)
    lag_bars = Column(Integer, nullable=False, server_default="0")
    action_type = Column(String(32), nullable=False, server_default="none")
    current_signal = Column(String(32), nullable=False, server_default="none")
    direction = Column(String(32), nullable=False, server_default="none")
    validation_status = Column(String(20), nullable=False, server_default="pending")
    status = Column(String(20), nullable=False, server_default="pending")

    n_obs = Column(Integer, nullable=False, server_default="0")
    n_folds = Column(Integer, nullable=False, server_default="0")
    hedge_ratio = Column(Float, nullable=True)
    intercept = Column(Float, nullable=True)
    zscore = Column(Float, nullable=True)
    half_life = Column(Float, nullable=True)
    adf_pvalue = Column(Float, nullable=True)
    raw_pvalue = Column(Float, nullable=True)
    fdr_qvalue = Column(Float, nullable=True)
    oos_sharpe = Column(Float, nullable=True)
    oos_return = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    profitable_fold_ratio = Column(Float, nullable=True)
    data_as_of = Column(Date, nullable=True)

    cost_bps_per_side = Column(Float, nullable=False, server_default="33.0")
    slippage_bps_per_side = Column(Float, nullable=False, server_default="5.0")
    borrow_bps_annual = Column(Float, nullable=False, server_default="300.0")
    metrics_json = Column(JSONB, nullable=False, default=dict)
    chart_json = Column(JSONB, nullable=False, default=dict)
    warnings_json = Column(JSONB, nullable=False, default=list)

    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stat_arb_pair_horizon_status", "horizon", "status"),
        Index("ix_stat_arb_pair_symbols", "symbol_y", "symbol_x"),
        Index("ix_stat_arb_pair_archetype", "archetype"),
    )


class StatArbBatchJob(Base):
    """Tracks stat-arb recompute jobs by horizon."""
    __tablename__ = "stat_arb_batch_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    horizon = Column(String(16), nullable=False)
    status = Column(String(20), nullable=False, server_default="pending")
    rq_job_id = Column(String, nullable=True)
    total_pairs = Column(Integer, nullable=False, server_default="0")
    completed_pairs = Column(Integer, nullable=False, server_default="0")
    failed_pairs = Column(Integer, nullable=False, server_default="0")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_stat_arb_job_horizon_status", "horizon", "status"),
        Index("ix_stat_arb_job_created_at", "created_at"),
    )


class SignalBacktestRun(Base):
    """Persisted signal-based backtest result with Monte Carlo equity-fan data.

    One row per (symbol, horizon, source, scope, scope_key, variant, window_start, window_end, cooldown_bars).
    Equity curve and MC envelope are stored in JSONB (small arrays — ~80 daily bars max).
    """
    __tablename__ = "signal_backtest_run"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Natural key
    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    source = Column(String(10), nullable=False)        # "engine" | "wfo"
    scope = Column(String(20), nullable=False)         # "per_category" | "global" | "combination"
    scope_key = Column(String(64), nullable=False)     # "tendance" | "global" | "tendance+momentum"
    variant = Column(String(64), nullable=False, server_default="expanded")
    window_start = Column(Date, nullable=False)
    window_end = Column(Date, nullable=False)

    # Config (not part of unique key — overwrites on change)
    status = Column(String(20), nullable=False, server_default="pending")
    cost_bps = Column(Float, nullable=False, server_default="5.0")
    slippage_bps = Column(Float, nullable=False, server_default="5.0")
    side_policy = Column(String(16), nullable=False, server_default="long_only")
    cooldown_bars = Column(Integer, nullable=False, server_default="0")
    n_paths = Column(Integer, nullable=False, server_default="2000")
    mc_method = Column(String(20), nullable=False, server_default="block_bootstrap")
    block_mean = Column(Integer, nullable=True)        # null = auto ceil(T^(1/3))

    # Realized backtest outputs
    n_bars = Column(Integer, nullable=True)
    n_trades = Column(Integer, nullable=True)
    equity_json = Column(JSONB, nullable=True)         # float[n_bars], normalized start=1.0
    dates_json = Column(JSONB, nullable=True)          # "YYYY-MM-DD"[n_bars]

    # Denormalized metrics for fast sorting / filtering
    total_return = Column(Float, nullable=True)
    cagr = Column(Float, nullable=True)
    sharpe = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    win_rate = Column(Float, nullable=True)

    # Monte Carlo outputs
    # {p05, p25, p50, p75, p95} — each is float[n_bars]
    mc_envelope_json = Column(JSONB, nullable=True)
    # {total_return/cagr/sharpe/max_drawdown: {p05,p50,p95}, var95, cvar95, prob_positive_terminal}
    mc_stats_json = Column(JSONB, nullable=True)

    # Trade-level detail (added 2026-04-21)
    trades_json = Column(JSONB, nullable=True)           # list of {open_date,close_date,open_price,close_price,direction,pnl_return,bars_held}
    close_series_json = Column(JSONB, nullable=True)     # OHLCV close aligned to dates_json
    position_series_json = Column(JSONB, nullable=True)  # executed_position per bar
    signal_diagnostics_json = Column(JSONB, nullable=True)  # {flat_executed, target_nonzero_bars, ...}
    warning_code = Column(String(32), nullable=True)     # "flat_signal" | "few_trades" | null
    shuffle_stats_json = Column(JSONB, nullable=True)    # shuffled-trade bootstrap result

    # Staleness: SHA-256 of (representatives_json + data_as_of + cost/slippage/side/cooldown)
    input_hash = Column(String(64), nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    compute_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "horizon", "source", "scope", "scope_key", "variant",
            "window_start", "window_end", "cooldown_bars",
            name="uq_sbr_natural_key",
        ),
        Index("ix_sbr_symbol_horizon", "symbol", "horizon"),
        Index("ix_sbr_source_scope", "source", "scope"),
        Index("ix_sbr_status", "status"),
        Index("ix_sbr_data_as_of", "data_as_of"),
    )


class SignalEngineBatchJob(Base):
    """Tracks batch computation jobs for signal engine or backtest for a (symbol, horizon).

    Used for progress reporting and preventing concurrent duplicate runs.
    UUID PK consistent with Run / StrategyBacktestRun convention.
    """
    __tablename__ = "signal_engine_batch_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    variant = Column(String(64), nullable=False, server_default="expanded")
    job_type = Column(String(20), nullable=False)      # "signal_engine" | "signal_backtest"
    status = Column(String(20), nullable=False, server_default="pending")
    rq_job_id = Column(String, nullable=True)
    triggered_by = Column(String(32), nullable=True)   # "manual" | "market_refresh" | "scheduler"
    batch_id = Column(String(64), nullable=True)       # manual global launch grouping id

    total_units = Column(Integer, nullable=True)       # families (engine) or scopes (backtest)
    completed_units = Column(Integer, nullable=False, server_default="0")
    failed_units = Column(Integer, nullable=False, server_default="0")

    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_sebj_symbol_horizon_type", "symbol", "horizon", "job_type"),
        Index("ix_sebj_status", "status"),
        Index("ix_sebj_created_at", "created_at"),
        Index("ix_sebj_batch_id", "batch_id"),
    )


class SchedulerRun(Base):
    """Audit row for one scheduler dispatch attempt.

    The scheduler process only fans work out to RQ queues. This table records
    that dispatch layer so operations can see whether recurring jobs are
    firing, how much work they enqueued, and what failed before queueing.
    """
    __tablename__ = "scheduler_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(String(64), nullable=False)
    trigger_source = Column(String(32), nullable=False, server_default="scheduled")
    status = Column(String(20), nullable=False, server_default="running")
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
    enqueued_jobs = Column(Integer, nullable=False, server_default="0")
    error_message = Column(Text, nullable=True)
    meta_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_scheduler_run_schedule_started", "schedule_id", "started_at"),
        Index("ix_scheduler_run_status", "status"),
    )


class MarketRefreshError(Base):
    """Per-symbol error log within a refresh run."""
    __tablename__ = "market_refresh_error"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    refresh_run_id = Column(UUID(as_uuid=True), ForeignKey("market_refresh_run.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    provider = Column(String, nullable=False, default="bourse_direct")
    error_type = Column(String, nullable=True)    # "not_found"|"parse_error"|"network_error"|"validation_error"
    error_message = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)    # first 2000 chars of raw response for debugging
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_market_refresh_error_run", "refresh_run_id"),
        Index("ix_market_refresh_error_symbol", "symbol"),
    )


# ---------------------------------------------------------------------------
# Phase 0 — Pipeline lineage scaffolding
# ---------------------------------------------------------------------------


class PipelineRevision(Base):
    """One row per successful pipeline-stage output.

    Used to thread `upstream_rev` lineage through the snapshot/cache tables
    introduced in Phase 1+ (`dashboard_snapshot`, `signal_evaluation_cache`,
    `factor_relevance_cache`, etc.). Workers append a row before flipping
    a downstream snapshot to the new revision.
    """

    __tablename__ = "pipeline_revision"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    stage = Column(String(64), nullable=False)
    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_pipeline_revision_stage_created", "stage", "created_at"),
        UniqueConstraint("stage", "content_hash", name="uq_pipeline_revision_stage_content"),
    )


class DashboardSnapshot(Base):
    """Pre-computed dashboard payload for one (horizon, as_of_date).

    Written by the worker via CAS upsert. The API in snapshot/shadow mode
    reads ``payload_jsonb`` instead of running the live aggregation.
    """

    __tablename__ = "dashboard_snapshot"

    horizon = Column(String(16), primary_key=True)
    as_of_date = Column(Date, primary_key=True)
    payload_jsonb = Column(JSONB, nullable=False)
    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_dashboard_snapshot_horizon_computed", "horizon", "computed_at"),
    )


class SignalBestEvidenceSnapshot(Base):
    """Stored default signal-page artifact for one WFO best method."""

    __tablename__ = "signal_best_evidence_snapshot"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    cooldown_bars = Column(Integer, nullable=False, server_default="0")
    status = Column(String(20), nullable=False, server_default="pending")

    source = Column(String(16), nullable=False, server_default="wfo")
    variant = Column(String(64), nullable=False)
    scope = Column(String(20), nullable=False, server_default="global")
    scope_key = Column(String(64), nullable=False, server_default="global")
    side_policy = Column(String(16), nullable=False, server_default="long_short")

    evidence_payload_jsonb = Column(JSONB, nullable=True)
    chart_payload_jsonb = Column(JSONB, nullable=True)
    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    data_as_of = Column(Date, nullable=True)
    market_data_as_of = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon", "cooldown_bars", name="uq_signal_best_evidence_snapshot_key"),
        Index("ix_signal_best_evidence_snapshot_status", "status"),
        Index("ix_signal_best_evidence_snapshot_symbol_horizon", "symbol", "horizon"),
    )


class SnapshotColumns:
    """Mixin: every Phase 1+ snapshot/cache table inherits these columns.

    `upstream_rev` is the JSON tuple of producer revisions consumed
    (e.g. ``{"data_as_of": "...", "engine_run_id": "...", ...}``).
    `computed_at` is when the row was written.
    `as_of_date` is the point-in-time the row represents (immutable per date).
    """

    upstream_rev = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    as_of_date = Column(Date, nullable=True)


# ---------------------------------------------------------------------------
# Forward-estimate consensus store (brief 54)
# ---------------------------------------------------------------------------


class FundamentalConsensusEstimate(Base):
    """Forward-estimate consensus rows, isolated from reported actuals.

    Upsert key: (symbol, fiscal_year, metric, source) — latest as_of_date wins.
    is_estimate is always True; these rows MUST NOT be commingled with reported
    fundamentals in fundamental_annual_metric or fundamental_period_metric.
    """
    __tablename__ = "fundamental_consensus_estimate"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    period_type = Column(String(20), nullable=False, server_default="annual")
    metric = Column(String(40), nullable=False)   # canonical: EPS_Forward, PER_Forward, etc.
    value = Column(Float, nullable=True)
    source = Column(String(32), nullable=False)   # "bkgr", "marketscreener", …
    as_of_date = Column(Date, nullable=False)
    currency = Column(String(8), nullable=False, server_default="MAD")
    raw_label = Column(String(80), nullable=True)
    data_source = Column(String(16), nullable=False, server_default="bkgr")
    is_estimate = Column(Boolean, nullable=False, server_default="true")
    analyst_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "fiscal_year", "metric", "source",
            name="uq_fundamental_consensus_estimate_key",
        ),
        Index("ix_fundamental_consensus_estimate_symbol_year", "symbol", "fiscal_year"),
        Index("ix_fundamental_consensus_estimate_symbol_asof", "symbol", "as_of_date"),
        Index("ix_fundamental_consensus_estimate_metric_source", "metric", "source"),
        CheckConstraint("is_estimate = true", name="ck_fundamental_consensus_estimate_is_estimate"),
    )
