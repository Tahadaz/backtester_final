"""Tests for the canonical resolver added to cgnc_mapping in Phase 0."""
from __future__ import annotations

import pytest

from core.quant_core.fundamentals.cgnc_mapping import (
    CANONICAL_METRICS,
    METRIC_ALIASES,
    _ALIAS_TO_CANONICAL,
    canonicalize_metrics,
    resolve_metric_name,
)


# ---------------------------------------------------------------------------
# resolve_metric_name
# ---------------------------------------------------------------------------

class TestResolveMetricName:
    def test_every_alias_resolves_to_its_canonical(self) -> None:
        for canonical, aliases in METRIC_ALIASES.items():
            for alias in aliases:
                result = resolve_metric_name(alias)
                assert result == canonical, (
                    f"resolve_metric_name({alias!r}) = {result!r}, expected {canonical!r}"
                )

    def test_canonical_names_are_idempotent(self) -> None:
        # A selection of canonical names — resolving them must return themselves
        for name in (
            "Revenue", "NetIncome", "EBIT", "EBITDA", "Total_Assets", "Total_Equity",
            "ROE", "ROA", "PER", "Price_to_Book", "Operating_Margin", "Net_Margin",
            "Revenue_Growth", "Debt_to_Equity", "Current_Ratio", "Net_Interest_Margin",
        ):
            assert resolve_metric_name(name) == name, (
                f"resolve_metric_name({name!r}) must be idempotent"
            )

    def test_unknown_name_passes_through_unchanged(self) -> None:
        assert resolve_metric_name("SomeObscureKey_XYZ") == "SomeObscureKey_XYZ"
        assert resolve_metric_name("") == ""

    def test_specific_aliases(self) -> None:
        assert resolve_metric_name("Clean_Chiffre_daffaires") == "Revenue"
        assert resolve_metric_name("Chiffre_daffaires") == "Revenue"
        assert resolve_metric_name("Resultat_net") == "NetIncome"
        assert resolve_metric_name("Clean_Resultat_net") == "NetIncome"
        assert resolve_metric_name("Net_Income") == "NetIncome"
        assert resolve_metric_name("Resultat_dexploitation") == "EBIT"
        assert resolve_metric_name("Excedent_brut_dexploitation") == "EBITDA"
        assert resolve_metric_name("Total_Actif") == "Total_Assets"
        assert resolve_metric_name("Capitaux_propres") == "Total_Equity"
        assert resolve_metric_name("Clean_Capitaux_propres") == "Total_Equity"
        assert resolve_metric_name("Equity") == "Total_Equity"
        assert resolve_metric_name("Dettes_de_financement") == "Total_Debt"
        assert resolve_metric_name("Debt_Total") == "Total_Debt"
        assert resolve_metric_name("NetDebt") == "Net_Debt"
        assert resolve_metric_name("Tresorerie_Actif") == "Cash"
        assert resolve_metric_name("CF_Operating") == "Operating_Cash_Flow"
        assert resolve_metric_name("Capacite_dautofinancement") == "CAF"
        assert resolve_metric_name("Dividends_Paid") == "Dividendes"
        assert resolve_metric_name("Clean_Dividendes") == "Dividendes"
        assert resolve_metric_name("Produit_Net_Bancaire") == "PNB"
        assert resolve_metric_name("Creances_sur_la_clientele") == "Loans_Net"
        assert resolve_metric_name("Cost_of_Risk") == "Cout_du_risque"


# ---------------------------------------------------------------------------
# No alias collision — each alias string maps to exactly one canonical
# ---------------------------------------------------------------------------

class TestAliasCollision:
    def test_no_alias_appears_in_two_canonical_groups(self) -> None:
        seen: dict[str, str] = {}
        for canonical, aliases in METRIC_ALIASES.items():
            for alias in aliases:
                if alias in seen:
                    pytest.fail(
                        f"Alias {alias!r} is listed under both "
                        f"{seen[alias]!r} and {canonical!r}"
                    )
                seen[alias] = canonical

    def test_alias_to_canonical_inverted_map_matches_metric_aliases(self) -> None:
        # _ALIAS_TO_CANONICAL is built at module load — verify it matches METRIC_ALIASES
        expected = {
            alias: canonical
            for canonical, aliases in METRIC_ALIASES.items()
            for alias in aliases
        }
        assert _ALIAS_TO_CANONICAL == expected

    def test_no_canonical_is_its_own_alias(self) -> None:
        # A canonical must not appear in any alias tuple — that would create an
        # ambiguous cycle (resolve_metric_name would map it to a different name).
        all_aliases: set[str] = {alias for aliases in METRIC_ALIASES.values() for alias in aliases}
        for canonical in METRIC_ALIASES:
            assert canonical not in all_aliases, (
                f"{canonical!r} is both a canonical key and an alias — ambiguous"
            )


# ---------------------------------------------------------------------------
# canonicalize_metrics
# ---------------------------------------------------------------------------

class TestCanonicalizeMetrics:
    def test_canonical_wins_when_both_present_and_non_null(self) -> None:
        result = canonicalize_metrics({"Clean_Chiffre_daffaires": 1.0, "Revenue": 2.0})
        assert result == {"Revenue": 2.0}

    def test_alias_promoted_when_canonical_absent(self) -> None:
        result = canonicalize_metrics({"Clean_Chiffre_daffaires": 1.0})
        assert result == {"Revenue": 1.0}

    def test_alias_value_fills_in_when_canonical_is_null(self) -> None:
        result = canonicalize_metrics({"Revenue": None, "Clean_Chiffre_daffaires": 3.5})
        assert result.get("Revenue") == 3.5

    def test_canonical_null_does_not_override_non_null_alias(self) -> None:
        # alias arrives first in dict iteration — canonical null must not clobber alias value
        result = canonicalize_metrics({"Chiffre_daffaires": 4.2, "Revenue": None})
        # canonical key present but null; alias was already promoted
        assert result.get("Revenue") == pytest.approx(4.2)

    def test_multiple_aliases_all_resolve_to_same_canonical(self) -> None:
        result = canonicalize_metrics({
            "Chiffre_daffaires": 10.0,
            "Clean_Chiffre_daffaires": 10.0,
            "Revenue": 10.0,
        })
        assert result == {"Revenue": 10.0}

    def test_output_is_new_dict_input_not_mutated(self) -> None:
        original = {"Clean_Chiffre_daffaires": 5.0, "Resultat_net": 1.0}
        import copy
        snapshot = copy.copy(original)
        canonicalize_metrics(original)
        assert original == snapshot

    def test_non_alias_keys_pass_through_unchanged(self) -> None:
        result = canonicalize_metrics({"SomeFutureMetric": 99.0, "Revenue": 1.0})
        assert result["SomeFutureMetric"] == 99.0
        assert result["Revenue"] == 1.0


# ---------------------------------------------------------------------------
# CANONICAL_METRICS sanity
# ---------------------------------------------------------------------------

class TestCanonicalMetricsSet:
    def test_all_scorer_pillar_metrics_are_canonical(self) -> None:
        required = {
            # value
            "PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA",
            "FCF_Yield", "Dividend_Yield",
            # quality
            "ROE", "ROA", "Operating_Margin", "Net_Margin",
            # growth
            "Revenue_Growth", "EBIT_Growth", "NetIncome_Growth",
            # risk
            "Debt_to_Equity", "NetDebt_to_EBITDA", "Equity_Multiplier",
            # cash flow
            "FCF_Margin", "Operating_CF_Margin", "CAF_Margin",
            # health
            "Current_Ratio", "Cash_Ratio", "Interest_Coverage",
            # bank-specific
            "Net_Interest_Margin", "Cost_to_Income", "Loans_to_Deposits",
        }
        missing = required - CANONICAL_METRICS
        assert not missing, f"Missing from CANONICAL_METRICS: {sorted(missing)}"

    def test_no_alias_in_canonical_metrics(self) -> None:
        all_aliases: set[str] = {alias for aliases in METRIC_ALIASES.values() for alias in aliases}
        overlap = all_aliases & CANONICAL_METRICS
        assert not overlap, (
            f"These names are both aliases and canonical — ambiguous: {sorted(overlap)}"
        )
