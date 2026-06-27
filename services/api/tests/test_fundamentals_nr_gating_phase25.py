from services.api.app import models
from services.api.app.services.fundamentals import derive_conviction, derive_recommendation


def test_zero_model_count_ensemble_is_not_rated() -> None:
    ensemble = models.FundamentalEnsembleResult(
        symbol="THIN",
        scenario="base",
        fair_value_base=200.0,
        current_price=100.0,
        upside_pct=1.0,
        confidence_score=0.90,
        usable_model_count=0,
        excluded_model_count=0,
        model_weights_json={"fcff_dcf": 1.0},
        warnings_json=[],
    )

    assert derive_recommendation(ensemble, current_price=100.0) == "NR"
    assert derive_conviction(ensemble) == 0


def test_withheld_warning_does_not_force_not_rated_when_fair_value_is_available() -> None:
    ensemble = models.FundamentalEnsembleResult(
        symbol="FAIL",
        scenario="base",
        fair_value_base=200.0,
        current_price=100.0,
        upside_pct=1.0,
        confidence_score=0.80,
        usable_model_count=4,
        excluded_model_count=0,
        model_weights_json={"fcff_dcf": 1.0},
        warnings_json=["withheld_integrity_fail"],
        model_dispersion_cv=0.05,
    )

    assert derive_recommendation(ensemble, current_price=100.0, cost_of_equity=0.10, forward_dividend_yield=0.0) == "BUY"
    assert derive_conviction(ensemble) > 0
