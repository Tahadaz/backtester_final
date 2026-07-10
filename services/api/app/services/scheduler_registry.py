"""Single source of truth for recurring operations schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger


ScheduleKind = Literal[
    "market_refresh",
    "dashboard_snapshot",
    "factor_monitor",
    "factor_recalibration",
    "fundamental_beta_refresh",
    "fundamental_cross_section",
    "fundamental_refresh",
    "value_strategy_refresh",
    "wfo_dispatch",
    "signal_backtest_dispatch",
    "signal_best_evidence_snapshot",
    "signal_history_dispatch",
]


@dataclass(frozen=True)
class ScheduleSpec:
    id: str
    label: str
    kind: ScheduleKind
    queue: str
    cron: str
    timezone: str
    description: str

    def trigger(self) -> CronTrigger:
        return CronTrigger.from_crontab(self.cron, timezone=ZoneInfo(self.timezone))

    def next_run_at(self, now: datetime | None = None) -> datetime | None:
        reference = now or datetime.now(ZoneInfo(self.timezone))
        return self.trigger().get_next_fire_time(None, reference)


SCHEDULE_SPECS: tuple[ScheduleSpec, ...] = (
    ScheduleSpec(
        id="daily_market_refresh",
        label="Daily market refresh",
        kind="market_refresh",
        queue="market_refresh",
        cron="0 20 * * mon-fri",
        timezone="Africa/Casablanca",
        description="Refresh active tracked market data after the Casablanca session.",
    ),
    ScheduleSpec(
        id="daily_dashboard_snapshot",
        label="Daily dashboard snapshot",
        kind="dashboard_snapshot",
        queue="market_refresh",
        cron="30 23 * * mon-fri",
        timezone="Africa/Casablanca",
        description="Maintenance rebuild for dashboard snapshots after the refresh/signal chain.",
    ),
    ScheduleSpec(
        id="daily_factor_monitor",
        label="Daily factor monitor",
        kind="factor_monitor",
        queue="market_refresh",
        cron="0 22 * * mon-fri",
        timezone="Africa/Casablanca",
        description="Run factor parameter drift monitoring.",
    ),
    ScheduleSpec(
        id="quarterly_factor_recalibration",
        label="Quarterly factor recalibration",
        kind="factor_recalibration",
        queue="market_refresh",
        cron="0 2 1 1,4,7,10 *",
        timezone="Africa/Casablanca",
        description="Run full factor-selection recalibration at quarter start.",
    ),
    ScheduleSpec(
        id="weekly_fundamental_refresh",
        label="Weekly fundamental refresh",
        kind="fundamental_refresh",
        queue="market_refresh",
        cron="0 20 * * sat",
        timezone="UTC",
        description="Refresh MASI fundamentals from StockAnalysis before weekly signal dispatch.",
    ),
    ScheduleSpec(
        id="weekly_fundamental_beta_refresh",
        label="Weekly fundamental beta refresh",
        kind="fundamental_beta_refresh",
        queue="market_refresh",
        cron="0 19 * * sat",
        timezone="UTC",
        description="Refresh market-data-derived fundamental betas and valuation WACC inputs.",
    ),
    ScheduleSpec(
        id="weekly_fundamental_cross_section",
        label="Weekly SFC cross-section",
        kind="fundamental_cross_section",
        queue="market_refresh",
        cron="30 20 * * sat",
        timezone="UTC",
        description="Recompute the publication-date PIT SFC cross-section after the weekly fundamentals window.",
    ),
    ScheduleSpec(
        id="weekly_value_strategy_refresh",
        label="Weekly value strategy snapshot",
        kind="value_strategy_refresh",
        queue="market_refresh",
        cron="45 20 * * sat",
        timezone="UTC",
        description="Recompute the canonical B/M+CF/P six-vintage strategy snapshot after the weekly fundamentals/SFC window.",
    ),
    ScheduleSpec(
        id="weekly_wfo_dispatch",
        label="Weekly WFO dispatch",
        kind="wfo_dispatch",
        queue="wfo_signals",
        cron="0 21 * * sun",
        timezone="UTC",
        description="Enqueue stale WFO signal tuples for all data-backed instruments.",
    ),
    ScheduleSpec(
        id="weekly_signal_backtest_dispatch",
        label="Weekly signal backtest dispatch",
        kind="signal_backtest_dispatch",
        queue="signal_backtest",
        cron="0 23 * * sun",
        timezone="UTC",
        description="Enqueue signal backtest jobs after weekly Signal Engine dispatch.",
    ),
    ScheduleSpec(
        id="weekly_signal_history_dispatch",
        label="Weekly signal history dispatch",
        kind="signal_history_dispatch",
        queue="score_history",
        cron="30 23 * * sun",
        timezone="UTC",
        description="Recompute predictive score-history / signal-validation series after weekly WFO and Signal Engine dispatch.",
    ),
    ScheduleSpec(
        id="weekly_signal_best_evidence_snapshot",
        label="Weekly best signal evidence snapshot",
        kind="signal_best_evidence_snapshot",
        queue="signal_backtest",
        cron="30 1 * * mon",
        timezone="UTC",
        description="Persist one WFO-best signal evidence and chart artifact per stock/horizon.",
    ),
)


SCHEDULE_BY_ID = {spec.id: spec for spec in SCHEDULE_SPECS}


LEGACY_RQ_SCHEDULER_IDS = (
    "weekly_signal_engine_batch",
    "weekly_wfo_signal_batch",
    "weekly_signal_backtest_batch",
)


QUEUE_NAMES = (
    "runs",
    "market_refresh",
    "signal_engine",
    "wfo_signals",
    "signal_backtest",
    "score_history",
    "defaults_discovery",
)


def get_schedule_spec(schedule_id: str) -> ScheduleSpec:
    try:
        return SCHEDULE_BY_ID[schedule_id]
    except KeyError as exc:
        raise ValueError(f"Unknown schedule_id {schedule_id!r}") from exc
