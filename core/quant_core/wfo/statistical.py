from __future__ import annotations

from dataclasses import dataclass
from math import inf, log, sqrt
from random import Random
from statistics import NormalDist, mean, pstdev


@dataclass(frozen=True)
class MonteCarloResult:
    p_value: float
    actual_metric: float
    actual_curve: list[float]
    sampled_curves: list[list[float]]
    percentile_bands: dict[int, list[float]]
    percentile_rank: float
    n_simulations: int


@dataclass(frozen=True)
class BootstrapRobustnessResult:
    actual_curve: list[float]
    sampled_curves: list[list[float]]
    percentile_bands: dict[int, list[float]]
    percentile_rank: float
    n_simulations: int
    block_length: int
    terminal_return_summary: dict[str, float]
    max_drawdown_summary: dict[str, float]


@dataclass(frozen=True)
class DeflatedSharpeResult:
    observed_sharpe: float
    benchmark_sharpe: float
    dsr_statistic: float
    p_value: float
    skewness: float
    kurtosis: float
    n_trades: int
    n_variants: int
    significant: bool


def compute_equity_curve(returns: list[float], *, start: float = 1.0) -> list[float]:
    curve = [start]
    equity = start
    for value in returns:
        equity *= 1.0 + value
        curve.append(equity)
    return curve


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0]
    worst = 0.0
    for point in curve:
        peak = max(peak, point)
        if peak > 0:
            worst = min(worst, point / peak - 1.0)
    return abs(worst)


def compute_metric(returns: list[float], metric: str = "return_over_drawdown") -> float:
    if not returns:
        return 0.0
    curve = compute_equity_curve(returns)
    if metric == "total_return":
        return curve[-1] - 1.0
    if metric == "sharpe":
        sigma = pstdev(returns)
        return 0.0 if sigma == 0 else mean(returns) / sigma
    if metric == "return_over_drawdown":
        total_return = curve[-1] - 1.0
        max_dd = _max_drawdown(curve)
        return inf if max_dd == 0 else total_return / max_dd
    raise ValueError(f"Unsupported metric: {metric}")


def monte_carlo_permutation_test(
    returns: list[float],
    *,
    n_simulations: int = 10_000,
    metric: str = "return_over_drawdown",
    seed: int | None = None,
    sample_curves: int = 200,
) -> MonteCarloResult:
    if n_simulations <= 0:
        raise ValueError("n_simulations must be positive")

    rng = Random(seed)
    actual_metric = compute_metric(returns, metric)
    actual_curve = compute_equity_curve(returns)
    exceed_count = 0
    simulated_curves: list[list[float]] = []
    final_equities: list[float] = []
    step_values: list[list[float]] = [[] for _ in range(len(actual_curve))]

    for index in range(n_simulations):
        shuffled = list(returns)
        rng.shuffle(shuffled)
        sim_metric = compute_metric(shuffled, metric)
        curve = compute_equity_curve(shuffled)
        final_equities.append(curve[-1])
        for step_index, point in enumerate(curve):
            step_values[step_index].append(point)
        if index < sample_curves:
            simulated_curves.append(curve)
        if sim_metric >= actual_metric:
            exceed_count += 1

    percentile_bands: dict[int, list[float]] = {}
    for pct in (5, 25, 50, 75, 95):
        band: list[float] = []
        for values in step_values:
            ordered = sorted(values)
            slot = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
            band.append(ordered[slot])
        percentile_bands[pct] = band

    percentile_rank = sum(1 for value in final_equities if value <= actual_curve[-1]) / len(final_equities)
    p_value = (exceed_count + 1) / (n_simulations + 1)
    return MonteCarloResult(
        p_value=p_value,
        actual_metric=actual_metric,
        actual_curve=actual_curve,
        sampled_curves=simulated_curves,
        percentile_bands=percentile_bands,
        percentile_rank=percentile_rank,
        n_simulations=n_simulations,
    )


def _percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    slot = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return float(ordered[slot])


def _draw_block_sample(
    returns: list[float],
    *,
    target_length: int,
    block_length: int,
    rng: Random,
) -> list[float]:
    if not returns:
        return []
    n = len(returns)
    if n == 1:
        return [returns[0]] * target_length
    sample: list[float] = []
    while len(sample) < target_length:
        start = rng.randrange(0, n)
        for offset in range(block_length):
            sample.append(returns[(start + offset) % n])
            if len(sample) >= target_length:
                break
    return sample[:target_length]


def block_bootstrap_equity_paths(
    returns: list[float],
    *,
    n_simulations: int = 1_000,
    block_length: int | None = None,
    seed: int | None = None,
    sample_curves: int = 200,
) -> BootstrapRobustnessResult:
    if n_simulations <= 0:
        raise ValueError("n_simulations must be positive")
    if not returns:
        return BootstrapRobustnessResult(
            actual_curve=[1.0],
            sampled_curves=[],
            percentile_bands={5: [1.0], 25: [1.0], 50: [1.0], 75: [1.0], 95: [1.0]},
            percentile_rank=0.0,
            n_simulations=n_simulations,
            block_length=0,
            terminal_return_summary={"p5": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p95": 0.0},
            max_drawdown_summary={"p5": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p95": 0.0},
        )

    n_obs = len(returns)
    resolved_block = block_length or min(20, max(5, round(sqrt(n_obs))))
    resolved_block = max(1, min(resolved_block, n_obs))
    rng = Random(seed)

    actual_curve = compute_equity_curve(returns)
    sampled_curves: list[list[float]] = []
    final_equities: list[float] = []
    max_drawdowns: list[float] = []
    step_values: list[list[float]] = [[] for _ in range(len(actual_curve))]

    for index in range(n_simulations):
        sampled = _draw_block_sample(
            returns,
            target_length=n_obs,
            block_length=resolved_block,
            rng=rng,
        )
        curve = compute_equity_curve(sampled)
        final_equities.append(curve[-1])
        max_drawdowns.append(_max_drawdown(curve))
        for step_index, point in enumerate(curve):
            step_values[step_index].append(point)
        if index < sample_curves:
            sampled_curves.append(curve)

    percentile_bands: dict[int, list[float]] = {}
    for pct in (5, 25, 50, 75, 95):
        percentile_bands[pct] = [_percentile(values, pct) for values in step_values]

    actual_terminal = actual_curve[-1]
    percentile_rank = sum(1 for value in final_equities if value <= actual_terminal) / len(final_equities)
    terminal_returns = [value - 1.0 for value in final_equities]

    return BootstrapRobustnessResult(
        actual_curve=actual_curve,
        sampled_curves=sampled_curves,
        percentile_bands=percentile_bands,
        percentile_rank=percentile_rank,
        n_simulations=n_simulations,
        block_length=resolved_block,
        terminal_return_summary={
            "p5": _percentile(terminal_returns, 5),
            "p25": _percentile(terminal_returns, 25),
            "p50": _percentile(terminal_returns, 50),
            "p75": _percentile(terminal_returns, 75),
            "p95": _percentile(terminal_returns, 95),
        },
        max_drawdown_summary={
            "p5": _percentile(max_drawdowns, 5),
            "p25": _percentile(max_drawdowns, 25),
            "p50": _percentile(max_drawdowns, 50),
            "p75": _percentile(max_drawdowns, 75),
            "p95": _percentile(max_drawdowns, 95),
        },
    )


def _skewness(values: list[float]) -> float:
    sigma = pstdev(values)
    if sigma == 0:
        return 0.0
    mu = mean(values)
    return sum(((value - mu) / sigma) ** 3 for value in values) / len(values)


def _kurtosis(values: list[float]) -> float:
    sigma = pstdev(values)
    if sigma == 0:
        return 3.0
    mu = mean(values)
    return sum(((value - mu) / sigma) ** 4 for value in values) / len(values)


def deflated_sharpe_ratio(
    returns: list[float],
    *,
    n_variants_tested: int,
    risk_free_rate: float = 0.0,
) -> DeflatedSharpeResult:
    if len(returns) < 2:
        return DeflatedSharpeResult(
            observed_sharpe=0.0,
            benchmark_sharpe=0.0,
            dsr_statistic=0.0,
            p_value=1.0,
            skewness=0.0,
            kurtosis=3.0,
            n_trades=len(returns),
            n_variants=max(1, n_variants_tested),
            significant=False,
        )

    sigma = pstdev(returns)
    if sigma == 0:
        observed_sharpe = 0.0
    else:
        observed_sharpe = (mean(returns) - risk_free_rate) / sigma

    skewness = _skewness(returns)
    kurtosis = _kurtosis(returns)
    trade_count = len(returns)
    n_variants = max(1, n_variants_tested)
    variance = (1.0 - skewness * observed_sharpe + ((kurtosis - 1.0) / 4.0) * (observed_sharpe ** 2)) / trade_count
    sr_std = sqrt(max(variance, 1e-12))
    benchmark = sqrt(2.0 * log(n_variants)) * sr_std
    dsr = (observed_sharpe - benchmark) / sr_std
    p_value = 1.0 - NormalDist().cdf(dsr)
    return DeflatedSharpeResult(
        observed_sharpe=observed_sharpe,
        benchmark_sharpe=benchmark,
        dsr_statistic=dsr,
        p_value=p_value,
        skewness=skewness,
        kurtosis=kurtosis,
        n_trades=trade_count,
        n_variants=n_variants,
        significant=p_value < 0.05,
    )
