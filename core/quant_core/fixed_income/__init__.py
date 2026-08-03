"""Fixed-income calculation engine — Offshore Markets Lab, Phase 1.

Pure, stateless bond math: day counts, cash-flow schedules, pricing, risk
measures, and yield-shock scenarios. No I/O, no DB, no FastAPI imports.

HAND-CODED LEARNING BUILD. The bodies of these modules are yours to write by
hand (docs/trader-prep/04-build-track.md, Build 1; Iron Rule in
docs/trader-prep/08-coding-readiness.md). The spec is
docs/ai/offshore-lab-phase1-fixed-income.md. The tests in
core/tests/test_fixed_income_*.py are your acceptance harness: make them green.
"""

from .daycount import year_fraction, accrual_fraction_icma
from .cashflows import (
    BondDefinition,
    CashFlow,
    generate_schedule,
    previous_coupon_date,
)
from .pricing import (
    accrued_interest,
    dirty_price,
    clean_price,
    yield_to_maturity,
    current_yield,
)
from .riskmeasures import RiskMeasures, risk_measures
from .scenarios import ShockResult, shock_table, carry

__all__ = [
    "year_fraction",
    "accrual_fraction_icma",
    "BondDefinition",
    "CashFlow",
    "generate_schedule",
    "previous_coupon_date",
    "accrued_interest",
    "dirty_price",
    "clean_price",
    "yield_to_maturity",
    "current_yield",
    "RiskMeasures",
    "risk_measures",
    "ShockResult",
    "shock_table",
    "carry",
]
