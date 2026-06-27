"""Exit-policy horse-race harness.

Research module that scores competing TP/SL exit policies on WFO OOS trades
using triple-barrier simulation, bootstrap CIs, and Hansen's SPA.

Typical usage:
    from core.quant_core.research.exit_policy import HarnessConfig, run_harness
    report = run_harness(db, HarnessConfig(horizon="weekly", variant="expanded"))
    print(format_report(report))
"""
from .harness import HarnessConfig, HarnessReport, run_harness, format_report

__all__ = ["HarnessConfig", "HarnessReport", "run_harness", "format_report"]
