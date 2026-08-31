"""Fail-closed live-trading readiness policy for the fundamental strategy.

The research engine is allowed to compute signals and paper portfolios.  It is
not allowed to imply that those artefacts authorize live orders.  Live
authorization is a conjunction of auditable evidence gates: one failed or
unreviewed gate keeps the strategy in ``RESEARCH_ONLY`` state.

The policy deliberately contains no probabilistic decision, random seed, or
fitted score.  A gate changes only when its cited evidence changes and a human
review updates the evidence record.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


READINESS_POLICY_VERSION = "fundamental_live_readiness_v2_1_2026_08_31"


@dataclass(frozen=True)
class ReadinessGate:
    gate_id: str
    requirement: str
    passed: bool
    evidence: str
    remediation: str


@dataclass(frozen=True)
class ProductionReadinessReport:
    policy_version: str
    strategy: str
    status: str
    live_trading_authorized: bool
    gates: tuple[ReadinessGate, ...]

    @property
    def blockers(self) -> tuple[ReadinessGate, ...]:
        return tuple(gate for gate in self.gates if not gate.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "strategy": self.strategy,
            "status": self.status,
            "live_trading_authorized": self.live_trading_authorized,
            "gates": [asdict(gate) for gate in self.gates],
            "blocker_ids": [gate.gate_id for gate in self.blockers],
        }


class LiveTradingNotAuthorized(RuntimeError):
    """Raised when a caller tries to cross the research/live boundary."""


def evaluate_production_readiness(
    gates: tuple[ReadinessGate, ...],
    *,
    strategy: str = "Structural Value (B/M)",
) -> ProductionReadinessReport:
    if not gates:
        raise ValueError("At least one explicit readiness gate is required")
    gate_ids = [gate.gate_id for gate in gates]
    if len(set(gate_ids)) != len(gate_ids):
        raise ValueError("Readiness gate ids must be unique")
    authorized = all(gate.passed for gate in gates)
    return ProductionReadinessReport(
        policy_version=READINESS_POLICY_VERSION,
        strategy=strategy,
        status="LIVE_AUTHORIZED" if authorized else "RESEARCH_ONLY",
        live_trading_authorized=authorized,
        gates=gates,
    )


def current_repository_readiness() -> ProductionReadinessReport:
    """Return the evidence-backed status reviewed on 2026-08-31.

    Evidence paths are intentionally embedded in every gate.  This prevents a
    future green status from being produced by changing an undocumented magic
    threshold or by treating missing evidence as a pass.
    """

    gates = (
        ReadinessGate(
            gate_id="deterministic_frozen_signal",
            requirement="The production candidate has a frozen, interpretable formula and no random production input.",
            passed=True,
            evidence="Structural Value v2 is a deterministic B/M rank; ic_study.py now reports deterministic Newey-West HAC inference and does not run a bootstrap.",
            remediation="Keep stochastic inputs out of the signal, portfolio authorization, and primary validation evidence.",
        ),
        ReadinessGate(
            gate_id="observed_pit_filing_vintages",
            requirement="Every accounting input used by a historical decision has an observed availability timestamp and preserved vintage.",
            passed=False,
            evidence="Structural Value v2 rejects unverified dates; 194 StockAnalysis metric rows were exactly reconciled to official BVC values/dates and six missing official-document dates were recovered from the BVC archive with lineage. However, 33,025 StockAnalysis metric rows remain unmatched, four archive-date conflicts and six ambiguous filenames remain quarantined, and the source archive is not yet preserved as immutable vintages.",
            remediation="Complete immutable official filing capture and exact value-level reconciliation, then independently adjudicate quarantined conflicts; unmatched values remain ineligible rather than receiving assumed dates.",
        ),
        ReadinessGate(
            gate_id="pit_market_equity",
            requirement="B/M uses market equity known on the decision date: traded close times effective point-in-time shares outstanding.",
            passed=False,
            evidence="Structural Value v2 now forbids stored MarketCap_Calc and computes close x shares. After official archive reconciliation, the strict 2026-05-31 cross-section has 20 B/M-eligible names out of 66 rows, but historical shares are not yet certified against splits, rights, issues, cancellations, and other capital changes.",
            remediation="Build and independently reconcile a corporate-action-aware effective share ledger, then rerun the frozen study; do not reuse the withdrawn v1 performance.",
        ),
        ReadinessGate(
            gate_id="verified_historical_universe",
            requirement="Listings, delistings, suspensions, and eligibility are verified point in time for every security in the test.",
            passed=False,
            evidence="data/universe/bvc_pit_universe.csv contains predominantly unverified active rows; the data-quality verdict also states never-ingested and delisted fundamentals are absent.",
            remediation="Reconstruct and independently reconcile the security master and delisting outcomes against official exchange/regulator records.",
        ),
        ReadinessGate(
            gate_id="total_return_and_corporate_actions",
            requirement="Strategy and benchmark returns use verified total-return data with splits, dividends, rights, suspensions, and delistings handled.",
            passed=False,
            evidence="Bourse adapters now reject undated sessions and no longer label raw Close as Adj Close, but the engine and MASI benchmark still lack certified total-return/corporate-action series.",
            remediation="Load and reconcile adjusted total-return series plus explicit corporate-action cash flows and terminal delisting proceeds.",
        ),
        ReadinessGate(
            gate_id="executable_timing",
            requirement="Orders execute strictly after signal availability using a tested market-session convention.",
            passed=False,
            evidence="LiveLikeConfig.execution_lag_days exists but is not applied; research-out/live-like-value-strategy/20260706-202635/execution_and_holding_rules.md.",
            remediation="Implement next-session execution prices, suspension/no-fill rules, and rerun the backtest from the same frozen signals.",
        ),
        ReadinessGate(
            gate_id="liquidity_capacity_and_concentration",
            requirement="Eligibility and sizing enforce point-in-time liquidity, capacity, name, and sector controls.",
            passed=False,
            evidence="Structural Value v2.1 applies strictly lagged 20-session ADTV eligibility, minimum-ticket and two-sided participation caps, preserves residual cash/positions, and reports rejected/partial orders. Defaults remain research calibrations and name/sector concentration limits are not implemented.",
            remediation="Obtain desk approval for the editable liquidity parameters and add desk-approved name, sector, suspension, auction, and cash limits.",
        ),
        ReadinessGate(
            gate_id="verified_transaction_costs",
            requirement="Fees, taxes, spread, impact, and borrow/settlement assumptions come from dated external schedules or desk records.",
            passed=False,
            evidence="The 33 bps per-filled-side input is versioned from the desk-certified fees_trades_equity (1).xlsx workbook with creator, creation date and SHA-256 lineage. A size-dependent spread/market-impact calibration from executable BVC quotes is still absent.",
            remediation="Confirm whether 33 bps is explicitly all-in; otherwise calibrate spread and nonlinear impact by order size and liquidity bucket, then obtain desk/model-risk sign-off.",
        ),
        ReadinessGate(
            gate_id="independent_out_of_sample_validation",
            requirement="The frozen specification passes a genuinely untouched out-of-sample period with dependence-aware inference.",
            passed=False,
            evidence="A corrected deterministic v2.1 run now completes, but strict PIT eligibility leaves only four monthly observations (2026-03-31 through 2026-06-30), which is not an independent or statistically meaningful holdout. Earlier v1 performance remains withdrawn.",
            remediation="Rerun on completed PIT data with an untouched holdout and deterministic HAC/non-overlapping evidence under a pre-registered protocol.",
        ),
        ReadinessGate(
            gate_id="paper_trading_and_reconciliation",
            requirement="Paper orders have been reconciled against fills, costs, holdings, cash, and corporate actions under the frozen production code path.",
            passed=False,
            evidence="The repository labels the strategy research-only and contains no validated paper-trading track record.",
            remediation="Complete desk-governed shadow trading and reconciliation; promote only through signed model-risk and trading approvals.",
        ),
        ReadinessGate(
            gate_id="live_risk_controls",
            requirement="The live path has pre-trade limits, stale-data rejection, duplicate-order protection, kill switch, monitoring, and incident ownership.",
            passed=False,
            evidence="Snapshot persistence/staleness checks exist, but the reviewed fundamental path is not an approved order-management or live-risk system.",
            remediation="Integrate with the desk OMS and risk controls, test failure modes, and record accountable approvals.",
        ),
    )
    return evaluate_production_readiness(gates)


def assert_live_trading_authorized(report: ProductionReadinessReport | None = None) -> None:
    checked = report or current_repository_readiness()
    if checked.live_trading_authorized:
        return
    blockers = ", ".join(gate.gate_id for gate in checked.blockers)
    raise LiveTradingNotAuthorized(f"Fundamental strategy is RESEARCH_ONLY; failed gates: {blockers}")


__all__ = [
    "LiveTradingNotAuthorized",
    "ProductionReadinessReport",
    "READINESS_POLICY_VERSION",
    "ReadinessGate",
    "assert_live_trading_authorized",
    "current_repository_readiness",
    "evaluate_production_readiness",
]
