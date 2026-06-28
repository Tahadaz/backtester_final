from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from dataclasses import replace
from math import isfinite, sqrt
from pathlib import Path
from random import Random
from statistics import mean, median
from typing import Any, Callable, Iterable

from .domain import AnnualMetricRow, EnsembleResult, FundamentalSnapshot, IntegrityReport, ValuationResult
from .minority import resolve_minority_roe_basis
from .projection import Projection, _pick_best_row_per_year, annual_rate_to_period_rate, build_projection

_IC_WEIGHTS_PATH = Path(__file__).parent / "ic_ensemble_weights.json"
_IC_WEIGHTS_CACHE: dict[str, float] | None | bool = False  # False = unloaded


def _load_ic_weights() -> dict[str, float] | None:
    """Load IC-shrunk ensemble weights from config; returns None if unavailable."""
    global _IC_WEIGHTS_CACHE
    if _IC_WEIGHTS_CACHE is not False:
        return _IC_WEIGHTS_CACHE  # type: ignore[return-value]
    try:
        with _IC_WEIGHTS_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        weights = {str(k): float(v) for k, v in data.get("weights", {}).items()}
        _IC_WEIGHTS_CACHE = weights if weights else None
    except Exception:
        _IC_WEIGHTS_CACHE = None
    return _IC_WEIGHTS_CACHE  # type: ignore[return-value]


MODEL_VERSION = "v3.1"
DEFAULT_CURRENCY = "MAD"
MODEL_SHOCK_CORRELATION = 0.60

# Calibrated 2026-05 against:
#   - SGTM IPO prospectus (AMMC, Oct 2025): rf=2.88% BDT 10Y, ERP=6.07% broker avg, tax=35%
#   - Attijari GR (Oct 2025, 6.7%), CFG Research (Mar 2025, 5.0%), BMCE Capital GR (Feb 2025, 6.5%)
#   - Damodaran ctryprem (Jan 2026): Morocco total ERP 7.47% = 4.23% mature + 3.24% CRP
# We follow the Moroccan broker / SGTM convention: a single combined ERP that already
# embeds country risk, and no separate CRP layered on top (avoid double-counting).
DEFAULT_ASSUMPTIONS: dict[str, float] = {
    "risk_free_rate": 0.035,          # BDT 10Y, BAM curve mid-2026 (~3.5%); up from 2.88% Oct-2025
    "equity_risk_premium": 0.060,     # Moroccan broker consensus (Attijari/CFG/BMCE avg ~6.07%)
    "country_risk_premium": 0.000,    # already embedded in ERP above; do NOT double-count
    "cost_of_equity": 0.095,          # rf + 1.0 × ERP at default beta=1.0 (0.035 + 0.060)
    "cost_of_equity_floor": 0.065,    # rf + 0.5 × ERP minimum equity return after CAPM
    "cost_of_debt": 0.055,            # MAD corporate spread; consistent with SGTM
    "scenario_erp_addon": 0.0,
    "scenario_cost_of_debt_addon": 0.0,
    "scenario_probability_bear": 0.25,
    "scenario_probability_base": 0.55,
    "scenario_probability_bull": 0.20,
    "tax_rate": 0.35,                 # current effective IS for large groups (post-2023 reform)
    "wacc": 0.077225,                 # 0.70 x 0.095 + 0.30 x 0.055 x (1-0.35)
    "beta": 1.0,
    "beta_window_years": 2.0,
    "beta_zero_return_threshold": 0.30,
    "beta_min_observations": 60.0,
    "default_debt_weight": 0.30,
    "default_equity_weight": 0.70,
    "use_balance_sheet_capital_weights": 1.0,
    "terminal_growth": 0.025,         # SGTM uses 2.5%; Moroccan IB practice 2.0-2.75%
    "terminal_growth_firm": 0.025,
    "terminal_growth_equity": 0.025,
    "terminal_growth_floor": 0.000,
    "terminal_growth_discount_buffer": 0.010,
    "terminal_growth_ceiling_source": 1.0,
    "forecast_years": 5.0,
    "mid_year_discounting": 1.0,
    "mid_year_terminal": 0.0,
    "fade_years": 5.0,
    "stable_payout_ratio": 0.55,
    "maintenance_capex_pct": 0.04,
    "peer_min_count": 3.0,
    "justified_multiple_ratio_mask": 3.0,  # bitmask: P/B=1, P/E=2
    "relative_multiple_ratio_mask": 15.0,  # bitmask: P/E=1, P/B=2, P/S=4, EV/EBITDA=8
    "proxy_weight_cap": 0.25,
    "ensemble_outlier_mad_k": 3.0,
    "ensemble_small_sample_floor_to_median": 0.25,
    "ensemble_small_sample_ceiling_to_median": 4.0,
    "ensemble_confidence_weight_coverage": 0.35,
    "ensemble_confidence_weight_agreement": 0.35,
    "ensemble_confidence_weight_data_quality": 0.30,
    "ensemble_confidence_target_models": 5.0,
    "rating_agreement_min": 0.40,
    "rating_confidence_min": 0.45,
    "rating_buy_excess_return": 0.10,
    "rating_accumulate_excess_return": 0.03,
    "rating_reduce_excess_return": -0.03,
    "rating_sell_excess_return": -0.10,
    "headline_review_upside_ceiling": 1.50,
    "headline_review_downside_floor": -0.95,
    "headline_review_min_coverage": 0.80,
    "headline_review_min_class_agreement": 0.40,
    "headline_review_confident_downside_band": -0.60,
    "headline_review_shared_flag_majority": 0.50,
    "headline_review_lone_driver_share": 0.90,
    "headline_review_lone_comp_divergence": 0.25,
    "headline_review_lone_thin_comp_upside_ceiling": 1.00,
    "ensemble_reliability_floor": 0.10,
    "ensemble_reliability_structural_flag_penalty": 0.75,
    "minority_materiality_epsilon": 0.05,
    "bs_balance_warn_bps": 50.0,
    "bs_balance_fail_bps": 200.0,
    "sensitivity_wacc_step": 0.005,
    "sensitivity_terminal_growth_step": 0.005,
    # Ensemble model weight overrides — 0.0 = use auto (IC / reliability) weighting.
    # Positive values are renormalised over the usable set by compute_valuation_ensemble.
    # Keys derived from ENSEMBLE_INTRINSIC_METHOD_MODELS | ENSEMBLE_MARKET_METHOD_MODELS.
    "ensemble_weight_ddm": 0.0,
    "ensemble_weight_fcfe_dcf": 0.0,
    "ensemble_weight_fcff_dcf": 0.0,
    "ensemble_weight_justified_multiples": 0.0,
    "ensemble_weight_relative_multiples": 0.0,
    "ensemble_weight_residual_income": 0.0,
}

_ASSUMPTION_META_OVERRIDES: dict[str, dict[str, Any]] = {
    "risk_free_rate": {
        "label": "Taux sans risque",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "BDT 10 ans, courbe BAM. Mis a jour mid-2026 a 3.5% (etait 2.88% oct-2025).",
        "source": "Courbe BAM / convention broker Maroc",
        "plausible_range": [0.025, 0.060],
    },
    "equity_risk_premium": {
        "label": "Prime de risque actions",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Consensus brokers marocains, pays inclus.",
        "source": "Attijari, CFG, BMCE Capital GR",
        "plausible_range": [0.035, 0.090],
    },
    "country_risk_premium": {
        "label": "Prime pays separee",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Defaut a zero car la prime pays est deja incluse dans l'ERP.",
        "source": "Damodaran / calibration Maroc",
        "plausible_range": [0.0, 0.040],
    },
    "beta": {
        "label": "Beta fallback",
        "unit": "x",
        "group": "cost_of_capital",
        "derivation": "Utilise seulement si aucun beta PIT n'est disponible.",
        "source": "FundamentalBetaHistory puis fallback registry",
        "plausible_range": [0.4, 2.0],
        "scope": "symbol",
    },
    "beta_window_years": {
        "label": "Fenetre beta",
        "unit": "years",
        "group": "beta",
        "derivation": "Defaut desk: 2 ans hebdomadaires; 5 ans mensuels en alternative.",
        "source": "Decisions log",
        "plausible_range": [1.0, 5.0],
    },
    "beta_zero_return_threshold": {
        "label": "Seuil semaines sans variation",
        "unit": "percent",
        "group": "beta",
        "derivation": "Au-dessus du seuil, routage Dimson+Blume ou peer beta.",
        "source": "Decisions log",
        "plausible_range": [0.10, 0.60],
    },
    "beta_min_observations": {
        "label": "Observations beta minimum",
        "unit": "count",
        "group": "beta",
        "derivation": "Garde de liquidite sur semaines traitees.",
        "source": "Decisions log",
        "plausible_range": [30.0, 120.0],
    },
    "cost_of_debt": {
        "label": "Cout de la dette",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Spread corporate MAD estime.",
        "source": "Calibration SGTM / broker",
        "plausible_range": [0.035, 0.085],
    },
    "scenario_erp_addon": {
        "label": "Addon ERP scenario",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Prime ajoutee a l'ERP par scenario avant le calcul CAPM.",
        "source": "Scenario desk",
        "plausible_range": [-0.030, 0.040],
    },
    "scenario_cost_of_debt_addon": {
        "label": "Addon cout dette scenario",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Prime ajoutee au cout de dette par scenario avant le calcul WACC.",
        "source": "Scenario desk",
        "plausible_range": [-0.020, 0.030],
    },
    "scenario_probability_bear": {
        "label": "Probabilite scenario bear",
        "unit": "percent",
        "group": "scenario",
        "derivation": "Probabilite maison appliquee au cas bear dans la distribution scenario.",
        "source": "Desk scenario policy",
        "plausible_range": [0.0, 1.0],
    },
    "scenario_probability_base": {
        "label": "Probabilite scenario base",
        "unit": "percent",
        "group": "scenario",
        "derivation": "Probabilite maison appliquee au cas central; le base reste la house call.",
        "source": "Desk scenario policy",
        "plausible_range": [0.0, 1.0],
    },
    "scenario_probability_bull": {
        "label": "Probabilite scenario bull",
        "unit": "percent",
        "group": "scenario",
        "derivation": "Probabilite maison appliquee au cas bull dans la distribution scenario.",
        "source": "Desk scenario policy",
        "plausible_range": [0.0, 1.0],
    },
    "tax_rate": {
        "label": "Taux IS",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Taux effectif cible pour grands groupes marocains.",
        "source": "Reforme IS post-2023",
        "plausible_range": [0.20, 0.40],
    },
    "wacc": {
        "label": "WACC calcule",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Ke et Kd apres impot ponderes par les poids dette/fonds propres.",
        "source": "CAPM + structure capital",
        "plausible_range": [0.050, 0.140],
        "editable": False,
    },
    "cost_of_equity": {
        "label": "Cout des fonds propres calcule",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Rf + beta x ERP.",
        "source": "CAPM",
        "plausible_range": [0.045, 0.180],
        "editable": False,
    },
    "cost_of_equity_floor": {
        "label": "Plancher cout des fonds propres",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Plancher desk applique apres CAPM: taux sans risque 3.5% + beta defensif 0.5 x ERP 6.0% = 6.5%.",
        "source": "Brief 39 CAPM policy / Moroccan broker ERP registry",
        "plausible_range": [0.035, 0.095],
    },
    "minority_materiality_epsilon": {
        "label": "Seuil minoritaires immateriels",
        "unit": "percent",
        "group": "data_verification",
        "derivation": "Seuil de materialite: si les interets minoritaires ou l'ecart fonds propres groupe/total restent <= 5%, le ROE groupe est NetIncome / Total_Equity.",
        "source": "Brief 41 data-verification policy",
        "plausible_range": [0.0, 0.20],
    },
    "default_debt_weight": {
        "label": "Poids dette par defaut",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Structure cible 30/70 si les poids marche ne sont pas actives.",
        "source": "Assumption registry",
        "plausible_range": [0.0, 0.70],
    },
    "default_equity_weight": {
        "label": "Poids fonds propres par defaut",
        "unit": "percent",
        "group": "cost_of_capital",
        "derivation": "Structure cible 70/30 si les poids marche ne sont pas actives.",
        "source": "Assumption registry",
        "plausible_range": [0.30, 1.0],
    },
    "use_balance_sheet_capital_weights": {
        "label": "Poids bilan / capitalisation",
        "unit": "flag",
        "group": "cost_of_capital",
        "derivation": "1 = poids marche par defaut; 0 = forcer les poids cible desk.",
        "source": "Assumption registry",
        "plausible_range": [0.0, 1.0],
    },
    "terminal_growth": {
        "label": "Croissance terminale legacy",
        "unit": "percent",
        "group": "projection",
        "derivation": "Override maitre: s'il est defini par scenario ou analyste, il remplace les chemins firm/equity.",
        "source": "SGTM / pratique broker",
        "plausible_range": [0.010, 0.035],
    },
    "terminal_growth_firm": {
        "label": "Croissance terminale firm",
        "unit": "percent",
        "group": "projection",
        "derivation": "Defaut calcule par reinvestment rate x ROIC, plafonne au taux sans risque.",
        "source": "ROIC et reinvestissement historiques",
        "plausible_range": [0.0, 0.055],
        "scope": "symbol",
    },
    "terminal_growth_equity": {
        "label": "Croissance terminale equity",
        "unit": "percent",
        "group": "projection",
        "derivation": "Defaut calcule par retention x ROE, plafonne au taux sans risque.",
        "source": "ROE et payout historiques",
        "plausible_range": [0.0, 0.055],
        "scope": "symbol",
    },
    "terminal_growth_floor": {
        "label": "Plancher g terminal",
        "unit": "percent",
        "group": "projection",
        "derivation": "Borne basse appliquee apres calcul durable.",
        "source": "Assumption registry",
        "plausible_range": [-0.010, 0.020],
    },
    "terminal_growth_discount_buffer": {
        "label": "Marge taux - g",
        "unit": "percent",
        "group": "projection",
        "derivation": "Garde que g terminal reste sous le taux d'actualisation du modele.",
        "source": "Valuation engine",
        "plausible_range": [0.0025, 0.030],
    },
    "terminal_growth_ceiling_source": {
        "label": "Plafond g = rf",
        "unit": "flag",
        "group": "projection",
        "derivation": "1 = plafonner au taux sans risque; 0 = utiliser seulement la garde taux - g.",
        "source": "Assumption registry",
        "plausible_range": [0.0, 1.0],
    },
    "forecast_years": {
        "label": "Horizon explicite",
        "unit": "years",
        "group": "projection",
        "derivation": "Cinq ans explicites puis terminal Gordon.",
        "source": "Decisions log",
        "plausible_range": [3.0, 7.0],
    },
    "mid_year_discounting": {
        "label": "Actualisation mi-annee",
        "unit": "flag",
        "group": "projection",
        "derivation": "Convention desk: flux explicites actualises aux periodes 0.5, 1.5, ...",
        "source": "Decisions log",
        "plausible_range": [0.0, 1.0],
    },
    "mid_year_terminal": {
        "label": "TV mi-annee",
        "unit": "flag",
        "group": "projection",
        "derivation": "0 = terminal Gordon actualise fin annee N; 1 = ancienne convention mi-annee.",
        "source": "Decisions log",
        "plausible_range": [0.0, 1.0],
    },
    "stable_payout_ratio": {
        "label": "Payout stable",
        "unit": "percent",
        "group": "dividends",
        "derivation": "Fallback DDM/RIM si le payout historique est absent ou aberrant.",
        "source": "Valuation engine",
        "plausible_range": [0.0, 0.90],
    },
    "maintenance_capex_pct": {
        "label": "Capex maintenance",
        "unit": "percent",
        "group": "projection",
        "derivation": "Norme structurelle de maintenance utilisee comme plancher avec D&A/revenus.",
        "source": "Valuation engine",
        "plausible_range": [0.0, 0.15],
    },
    "ensemble_outlier_mad_k": {
        "label": "Seuil outlier MAD",
        "unit": "count",
        "group": "ensemble",
        "derivation": "Rejet robuste standard: mediane +/- k x 1.4826 x MAD, equivalent 3 sigma sous normalite.",
        "source": "Desk research policy / robust statistics",
        "plausible_range": [2.0, 5.0],
    },
    "ensemble_small_sample_floor_to_median": {
        "label": "Borne basse petit echantillon",
        "unit": "x",
        "group": "ensemble",
        "derivation": "Garde structurelle large quand moins de quatre modeles survivent: multiple de la mediane inter-modeles, pas du prix de marche.",
        "source": "Desk research policy / robust statistics",
        "plausible_range": [0.10, 0.50],
    },
    "ensemble_small_sample_ceiling_to_median": {
        "label": "Borne haute petit echantillon",
        "unit": "x",
        "group": "ensemble",
        "derivation": "Garde structurelle large quand moins de quatre modeles survivent: multiple de la mediane inter-modeles, pas du prix de marche.",
        "source": "Desk research policy / robust statistics",
        "plausible_range": [2.0, 8.0],
    },
    "ensemble_confidence_weight_coverage": {
        "label": "Poids confiance couverture",
        "unit": "percent",
        "group": "ensemble_confidence",
        "derivation": "Composante additive: nombre de modeles survivants / cible de couverture.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_confidence_weight_agreement": {
        "label": "Poids confiance accord",
        "unit": "percent",
        "group": "ensemble_confidence",
        "derivation": "Composante additive: 1 - robust CV inter-modeles, sans double penalisation.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_confidence_weight_data_quality": {
        "label": "Poids confiance qualite donnees",
        "unit": "percent",
        "group": "ensemble_confidence",
        "derivation": "Composante additive: fraction des entrees modeles observees, apres penalite proxy/peer/assumption/missing.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_confidence_target_models": {
        "label": "Cible couverture modeles",
        "unit": "count",
        "group": "ensemble_confidence",
        "derivation": "Nombre de modeles survivants correspondant a une couverture complete.",
        "source": "Desk research policy",
        "plausible_range": [3.0, 7.0],
    },
    "headline_review_upside_ceiling": {
        "label": "Seuil revue hausse headline",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Au-dela de +150% d'upside, le headline est publie seulement si la couverture et l'accord entre classes de methodes sont suffisants.",
        "source": "Brief 40 ensemble review policy",
        "plausible_range": [0.50, 3.00],
    },
    "headline_review_downside_floor": {
        "label": "Seuil revue baisse headline",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Sous -95% d'upside, le headline est publie seulement si la couverture et l'accord entre classes de methodes sont suffisants.",
        "source": "Brief 40 ensemble review policy",
        "plausible_range": [-1.00, -0.50],
    },
    "headline_review_min_coverage": {
        "label": "Couverture minimale headline extreme",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Reutilise la logique de couverture du score de confiance: modeles survivants / cible de couverture. Les extremes peu couverts passent en revue.",
        "source": "Brief 40 ensemble review policy",
        "plausible_range": [0.40, 1.00],
    },
    "headline_review_min_class_agreement": {
        "label": "Accord minimal classes headline extreme",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Seuil aligne sur rating_agreement_min: si les representants intrinsic/market divergent trop, un headline extreme passe en revue.",
        "source": "Brief 40 ensemble review policy",
        "plausible_range": [0.0, 1.0],
    },
    "headline_review_confident_downside_band": {
        "label": "Bande baisse confiante headline",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Un headline sous -60% construit sur des modeles a faible information (drapeaux midcycle/fallback/proxy partages) passe en revue/NR plutot que d'etre publie comme un SELL confiant. Bande plus stricte que le plancher -95% qui ne se declenchait jamais sur les cas type TQM/AKT.",
        "source": "Brief 44 ensemble review policy",
        "plausible_range": [-0.90, -0.30],
    },
    "headline_review_shared_flag_majority": {
        "label": "Majorite drapeau partage headline",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Si une majorite des modeles utilisables portent le meme drapeau a faible information (midcycle_*, *_fallback, earnings_growth_proxy, relative_peers_*, terminal_value_above_75pct*), l'accord numerique est traite comme un biais partage et non comme une confirmation: routage en revue.",
        "source": "Brief 44 ensemble review policy",
        "plausible_range": [0.0, 1.0],
    },
    "headline_review_lone_driver_share": {
        "label": "Part dominante driver unique headline",
        "unit": "ratio",
        "group": "ensemble",
        "derivation": "Part de poids au-dela de laquelle le headline est considere porte par un seul modele. Combine avec un comparable peu peuple (relative_peers_count_below_5) et une divergence materielle vis-a-vis des modeles co-utilisables ignores, ce cas (ex. assureur dont le seul modele a IC positif est le comparable) passe en revue au lieu d'etre publie.",
        "source": "Brief 44 lone thin-comp review (WAA)",
        "plausible_range": [0.50, 1.00],
    },
    "headline_review_lone_comp_divergence": {
        "label": "Divergence comparable unique vs corroborateurs",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Ecart relatif au modele independant le PLUS PROCHE en-deca duquel le comparable unique dominant est considere corrobore (et publie). Un comparable proche d'au moins un autre modele utilisable est corrobore; un comparable eloigne de tous est un pari isole et passe en revue.",
        "source": "Brief 44 lone thin-comp review (WAA)",
        "plausible_range": [0.05, 1.00],
    },
    "headline_review_lone_thin_comp_upside_ceiling": {
        "label": "Plafond upside comparable unique peu peuple",
        "unit": "percent",
        "group": "ensemble",
        "derivation": "Un comparable unique peu peuple (relative_peers_count_below_5) ne peut justifier seul un upside extreme. Au-dela de ce plafond, et sans corroboration par un modele proche, le headline passe en revue plutot que d'etre publie (cas WAA +148% vs modeles intrinseques negatifs). Plus strict que le plafond general (+150%) qui suppose une corroboration.",
        "source": "Brief 44 lone thin-comp review (WAA)",
        "plausible_range": [0.50, 1.50],
    },
    "ensemble_reliability_floor": {
        "label": "Plancher de fiabilite modele",
        "unit": "ratio",
        "group": "ensemble",
        "derivation": "Plancher du multiplicateur de fiabilite afin qu'un modele a faible information soit sous-pondere mais jamais totalement exclu par la ponderation (preserve la couverture; l'exclusion reste reservee aux drapeaux severes).",
        "source": "Brief 44 reliability weighting",
        "plausible_range": [0.0, 0.50],
    },
    "ensemble_reliability_structural_flag_penalty": {
        "label": "Penalite par drapeau structurel",
        "unit": "ratio",
        "group": "ensemble",
        "derivation": "Multiplicateur applique par drapeau structurel a faible information non capte par les tokens generiques (relative_peers_count_below_5, terminal_value_above_75pct*, midcycle_normalization_thin_history, cyclical_trough_unnormalized).",
        "source": "Brief 44 reliability weighting",
        "plausible_range": [0.30, 1.0],
    },
    "rating_agreement_min": {
        "label": "Accord minimum rating",
        "unit": "percent",
        "group": "rating_policy",
        "derivation": "Quorum qualitatif: accord inter-modeles minimum avant publication d'une recommandation directionnelle.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 1.0],
    },
    "rating_confidence_min": {
        "label": "Confiance minimum rating",
        "unit": "percent",
        "group": "rating_policy",
        "derivation": "Confiance ensemble minimum avant publication d'une recommandation directionnelle.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 1.0],
    },
    "rating_buy_excess_return": {
        "label": "Seuil Acheter",
        "unit": "percent",
        "group": "rating_policy",
        "derivation": "Exces de rendement attendu au-dessus du cout des fonds propres pour Acheter.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 0.25],
    },
    "rating_accumulate_excess_return": {
        "label": "Seuil Accumuler",
        "unit": "percent",
        "group": "rating_policy",
        "derivation": "Exces de rendement attendu au-dessus du cout des fonds propres pour Accumuler.",
        "source": "Desk research policy",
        "plausible_range": [0.0, 0.15],
    },
    "rating_reduce_excess_return": {
        "label": "Seuil Alleger",
        "unit": "percent",
        "group": "rating_policy",
        "derivation": "Exces de rendement attendu sous le cout des fonds propres separant Conserver et Alleger.",
        "source": "Desk research policy",
        "plausible_range": [-0.15, 0.0],
    },
    "rating_sell_excess_return": {
        "label": "Seuil Vendre",
        "unit": "percent",
        "group": "rating_policy",
        "derivation": "Exces de rendement attendu sous le cout des fonds propres pour Vendre.",
        "source": "Desk research policy",
        "plausible_range": [-0.25, 0.0],
    },
    "justified_multiple_ratio_mask": {
        "label": "Ratios multiples justifies",
        "unit": "count",
        "group": "multiples",
        "derivation": "Bitmask stock-level: P/B=1, P/E=2. Controls which justified multiples feed the model median.",
        "source": "Analyst selection",
        "plausible_range": [0.0, 3.0],
        "scope": "symbol",
    },
    "relative_multiple_ratio_mask": {
        "label": "Ratios multiples relatifs",
        "unit": "count",
        "group": "multiples",
        "derivation": "Bitmask stock-level: P/E=1, P/B=2, P/S=4, EV/EBITDA=8. Controls which peer multiples feed the model median.",
        "source": "Analyst selection",
        "plausible_range": [0.0, 15.0],
        "scope": "symbol",
    },
    "ensemble_weight_fcff_dcf": {
        "label": "Poids ensemble — FCFF DCF",
        "unit": "ratio",
        "group": "ensemble_weights",
        "derivation": "Poids manuel desk pour ce modele dans l'ensemble. 0 = ponderation automatique (IC puis fiabilite). Les poids positifs sont renormalises sur les seuls modeles utilisables (les modeles exclus pour qualite de donnees ne peuvent pas etre reintroduits).",
        "source": "Brief 51 desk weighting policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_weight_fcfe_dcf": {
        "label": "Poids ensemble — FCFE DCF",
        "unit": "ratio",
        "group": "ensemble_weights",
        "derivation": "Poids manuel desk pour ce modele dans l'ensemble. 0 = ponderation automatique (IC puis fiabilite). Les poids positifs sont renormalises sur les seuls modeles utilisables (les modeles exclus pour qualite de donnees ne peuvent pas etre reintroduits).",
        "source": "Brief 51 desk weighting policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_weight_ddm": {
        "label": "Poids ensemble — DDM",
        "unit": "ratio",
        "group": "ensemble_weights",
        "derivation": "Poids manuel desk pour ce modele dans l'ensemble. 0 = ponderation automatique (IC puis fiabilite). Les poids positifs sont renormalises sur les seuls modeles utilisables (les modeles exclus pour qualite de donnees ne peuvent pas etre reintroduits).",
        "source": "Brief 51 desk weighting policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_weight_residual_income": {
        "label": "Poids ensemble — Revenu residuel",
        "unit": "ratio",
        "group": "ensemble_weights",
        "derivation": "Poids manuel desk pour ce modele dans l'ensemble. 0 = ponderation automatique (IC puis fiabilite). Les poids positifs sont renormalises sur les seuls modeles utilisables (les modeles exclus pour qualite de donnees ne peuvent pas etre reintroduits).",
        "source": "Brief 51 desk weighting policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_weight_justified_multiples": {
        "label": "Poids ensemble — Multiples justifies",
        "unit": "ratio",
        "group": "ensemble_weights",
        "derivation": "Poids manuel desk pour ce modele dans l'ensemble. 0 = ponderation automatique (IC puis fiabilite). Les poids positifs sont renormalises sur les seuls modeles utilisables (les modeles exclus pour qualite de donnees ne peuvent pas etre reintroduits).",
        "source": "Brief 51 desk weighting policy",
        "plausible_range": [0.0, 1.0],
    },
    "ensemble_weight_relative_multiples": {
        "label": "Poids ensemble — Comparables",
        "unit": "ratio",
        "group": "ensemble_weights",
        "derivation": "Poids manuel desk pour ce modele dans l'ensemble. 0 = ponderation automatique (IC puis fiabilite). Les poids positifs sont renormalises sur les seuls modeles utilisables (les modeles exclus pour qualite de donnees ne peuvent pas etre reintroduits).",
        "source": "Brief 51 desk weighting policy",
        "plausible_range": [0.0, 1.0],
    },
}

ASSUMPTION_META: dict[str, dict[str, Any]] = {
    key: {
        "value": value,
        "label": key.replace("_", " ").title(),
        "unit": "number",
        "group": "general",
        "derivation": "Default valuation-engine assumption.",
        "source": "Valuation engine",
        "plausible_range": None,
        "scope": "desk",
        "editable": True,
        **_ASSUMPTION_META_OVERRIDES.get(key, {}),
    }
    for key, value in DEFAULT_ASSUMPTIONS.items()
}

SCENARIO_DEFAULT_OVERRIDES: dict[str, dict[str, float]] = {
    "bear": {
        "scenario_erp_addon": 0.015,
        "scenario_cost_of_debt_addon": 0.010,
    },
    "base": {},
    "bull": {
        "scenario_erp_addon": -0.010,
        "scenario_cost_of_debt_addon": -0.005,
    },
}

VALUATION_MODEL_ORDER = (
    "relative_multiples",
    "reverse_dcf",
    "fcff_dcf",
    "fcfe_dcf",
    "ddm",
    "residual_income",
    "justified_multiples",
)

FINANCIAL_SECTOR_TOKENS = (
    "banque",
    "bank",
    "assurance",
    "insurance",
    "takaful",
    "financement",
    "leasing",
    "credit",
)
BANK_SECTOR_TOKENS = ("banque", "bank")
INSURANCE_SECTOR_TOKENS = ("assurance", "insurance", "takaful")
GENERAL_FINANCIAL_SECTOR_TOKENS = ("financement", "leasing", "credit")

# stock_master has a sector field but no industry field. The BVC labels identify
# mining and energy directly; the symbol registry disambiguates coarse BTP labels
# for cement, steel, and aluminium producers.
# Only genuine commodity *producers* whose realized margin swings with a
# commodity/BTP cycle qualify. The broad energie/energy/electricite/petrole/gaz
# tokens were dropped (brief 44 §3.1): they swept regulated utilities and fuel
# distributors (TQM contracted IPP on a long-term ONEE PPA, TMA/GAZ regulated fuel
# distribution) whose margins are contracted/regulated, not commodity-cyclical —
# mid-cycle normalization mis-applied to them was the single largest mispricing.
# BTP-materials producers carry coarse sector labels, so they are keyed by symbol
# in the registry rather than by a noisy sector token.
CYCLICAL_COMMODITY_SECTOR_TOKENS = (
    "mine",
    "mines",
    "mining",
)
CYCLICAL_COMMODITY_SYMBOL_REGISTRY: dict[str, str] = {
    "ALM": "aluminium producer in BTP sector",
    "CMA": "cement producer in BTP sector",
    "CMT": "mining company",
    "LHM": "cement producer in BTP sector",
    "MNG": "mining company",
    "REB": "mining holding",
    "SID": "steel producer in BTP sector",
    "SMI": "mining company",
    "ZDJ": "mining holding",
}

CONFIDENCE_TO_SCORE = {
    "high": 0.85,
    "medium": 0.60,
    "low": 0.35,
    "unavailable": 0.0,
}

RELATIVE_FAMILY_MODELS = {"relative_multiples", "justified_multiples"}
ENSEMBLE_INTRINSIC_METHOD_MODELS = {
    "fcff_dcf",
    "fcfe_dcf",
    "ddm",
    "residual_income",
    "justified_multiples",
}
ENSEMBLE_MARKET_METHOD_MODELS = {"relative_multiples"}
FCF_DCF_MODELS = {"fcff_dcf", "fcfe_dcf"}
JUSTIFIED_MULTIPLE_RATIO_BITS: tuple[tuple[str, int], ...] = (
    ("justified_pb", 1),
    ("justified_pe", 2),
)
RELATIVE_MULTIPLE_RATIO_BITS: tuple[tuple[str, int], ...] = (
    ("PER", 1),
    ("Price_to_Book", 2),
    ("Price_to_Sales", 4),
    ("EV_to_EBITDA", 8),
)
MAX_REASONABLE_DIVIDEND_YIELD = 0.25
MIN_REASONABLE_PRICE_TO_BOOK = 0.15
SEVERE_FCF_DCF_WARNINGS = {
    "missing_positive_fcf",
    "missing_positive_equity_cash_flow_proxy",
    "wacc_not_above_terminal_growth",
    "cost_of_equity_not_above_terminal_growth",
    "fcf_dcf_unavailable_nonpositive_equity_value",
}
SEVERE_FCF_DCF_WARNING_PREFIXES = ("fcf_model_unreliable_negative_",)
SEVERE_TERMINAL_VALUE_WARNINGS = {
    "terminal_value_above_75pct_ev",
    "terminal_value_above_75pct_equity_value",
}
# Terminal-value share thresholds (brief 44 §3.4). Derivation: 0.75 is the
# long-standing "terminal dominates" warn level; above 0.85 the explicit forecast
# window contributes <15% of value, so the DCF is a thinly-disguised perpetuity off
# a (often depressed) base and is not investment-grade. A DCF over the ceiling is
# excluded from the headline on its own; between warn and ceiling it stays but is
# reliability-down-weighted in the combiner.
TERMINAL_VALUE_WARN_SHARE = 0.75
TERMINAL_VALUE_EXCLUSION_SHARE = 0.85
TERMINAL_VALUE_CEILING_WARNINGS = {
    "terminal_value_above_85pct_ev",
    "terminal_value_above_85pct_equity_value",
}
NON_OBSERVED_INPUT_WARNING_TOKENS = (
    "proxy",
    "peer_median",
    "fallback",
    "assumption",
    "missing",
    "unavailable",
)
FCF_PROJECTION_UNAVAILABLE_WARNINGS = {
    "revenue_growth_unavailable_no_history_no_peer",
    "ebit_margin_unavailable_no_history_no_peer",
    "d_and_a_pct_unavailable_no_history_no_peer",
    "capex_pct_unavailable_no_history_no_peer",
    "working_capital_pct_unavailable_no_history_no_peer",
}
EQUITY_PROJECTION_UNAVAILABLE_WARNINGS = {
    *FCF_PROJECTION_UNAVAILABLE_WARNINGS,
    "payout_ratio_unavailable_no_history_no_peer",
    "bank_rbe_margin_unavailable_no_history_no_peer",
    "bank_cost_of_risk_unavailable_no_history_no_peer",
    "bank_pnb_unavailable_no_history_no_peer",
    "pnb_growth_unavailable_no_history_no_peer",
    "insurer_roe_unavailable_no_history_no_peer",
    "financial_roe_unavailable_no_history_no_peer",
}
STRICT_BANK_PROJECTION_UNAVAILABLE_WARNINGS = {
    "bank_rbe_margin_unavailable_no_history_no_peer",
    "bank_cost_of_risk_unavailable_no_history_no_peer",
    "pnb_growth_unavailable_no_history_no_peer",
}
SCENARIO_PROBABILITY_KEYS = {
    "bear": "scenario_probability_bear",
    "base": "scenario_probability_base",
    "bull": "scenario_probability_bull",
}
SCENARIO_PROBABILITY_RENORMALIZED_WARNING = "scenario_probabilities_renormalized"

EBITDA_ALIASES = ("EBITDA", "Excedent_brut_dexploitation")
REVENUE_ALIASES = ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires")
EBIT_ALIASES = ("EBIT", "Resultat_dexploitation")
NET_INCOME_ALIASES = ("NetIncome", "Net_Income", "Clean_Resultat_net", "Resultat_net")
GROUP_NET_INCOME_ALIASES = (
    "Resultat_net_part_du_groupe",
    "RNPG",
    "NetIncome_Group",
    "Net_Income_Group",
)
CAPEX_ALIASES = ("Capex", "Capital_Expenditures")
DANDA_ALIASES = ("Depreciation_Amortization", "DandA", "Dotations_dexploitation")
WORKING_CAPITAL_ALIASES = ("Working_Capital",)
CURRENT_ASSET_ALIASES = ("Current_Assets", "Actif_circulant")
CURRENT_LIABILITY_ALIASES = ("Current_Liabilities", "Passif_circulant")
DEBT_ALIASES = ("Total_Debt", "Debt_Total", "Dettes_de_financement")
EQUITY_ALIASES = (
    "Total_Equity",
    "Shareholders_Equity",
    "Total_Shareholders_Equity",
    "Stockholders_Equity",
    "Total_Stockholders_Equity",
    "Clean_Capitaux_propres",
    "Capitaux_propres",
    "Equity",
    "Total_Common_Equity",
    "Common_Equity",
)
GROUP_EQUITY_ALIASES = (
    "Equity_Group",
    "Total_Equity_Group",
    "Capitaux_propres_part_du_groupe",
    "Total_Common_Equity",
    "Common_Equity",
)
TOTAL_ASSET_ALIASES = ("Total_Assets", "Total_Actif")
TOTAL_LIABILITY_ALIASES = ("Total_Liabilities",)
DIVIDEND_ALIASES = ("Dividendes", "Dividends_Paid", "Clean_Dividendes")
FREE_CASH_FLOW_ALIASES = ("Free_Cash_Flow",)
MINORITY_INTEREST_ALIASES = ("Minority_Interest", "Interets_minoritaires")
ASSOCIATES_INVESTMENTS_ALIASES = (
    "Associates_Investments",
    "Investments_in_Associates",
    "Long_Term_Investments",
    "Investments",
)
PENSION_LEASE_ALIASES = (
    "Pension_Obligations",
    "Pension_Liabilities",
    "Lease_Obligations",
    "Lease_Liabilities",
    "Operating_Lease_Liabilities",
)
FINANCIAL_SUPPRESSED_METRICS = {
    "Capex",
    "Capital_Expenditures",
    "EBITDA",
    "EnterpriseValue",
    "Enterprise_Value",
    "EV_to_EBITDA",
    "EV_to_Sales",
    "FCF_Margin",
    "FCF_Yield",
    "Free_Cash_Flow",
    "Net_Debt",
    "Price_to_Sales",
}


def _finite_probability(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def scenario_probabilities_from_assumptions(assumptions: dict[str, Any]) -> dict[str, float]:
    """Return bear/base/bull probabilities from an already-normalized assumption dict."""

    return {
        scenario: float(assumptions.get(key, DEFAULT_ASSUMPTIONS[key]))
        for scenario, key in SCENARIO_PROBABILITY_KEYS.items()
    }


def normalize_scenario_probabilities(
    assumptions: dict[str, Any],
    provenance: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str] | None, list[str]]:
    """Clamp and renormalize scenario probabilities so they sum to one."""

    out: dict[str, Any] = dict(assumptions)
    provenance_out = dict(provenance) if provenance is not None else None
    raw: dict[str, float] = {}
    needs_renormalization = False
    for scenario, key in SCENARIO_PROBABILITY_KEYS.items():
        value = _finite_probability(out.get(key, DEFAULT_ASSUMPTIONS[key]))
        if value is None or value < 0.0:
            value = 0.0
            needs_renormalization = True
        raw[scenario] = value

    total = sum(raw.values())
    if total <= 0.0:
        raw = {
            scenario: float(DEFAULT_ASSUMPTIONS[key])
            for scenario, key in SCENARIO_PROBABILITY_KEYS.items()
        }
        total = sum(raw.values())
        needs_renormalization = True

    if abs(total - 1.0) > 1e-6:
        needs_renormalization = True

    normalized = {scenario: value / total for scenario, value in raw.items()}
    for scenario, probability in normalized.items():
        key = SCENARIO_PROBABILITY_KEYS[scenario]
        out[key] = probability
        if needs_renormalization and provenance_out is not None:
            provenance_out[key] = "computed"

    warnings = [SCENARIO_PROBABILITY_RENORMALIZED_WARNING] if needs_renormalization else []
    return out, provenance_out, warnings


def default_assumptions_for_scenario(scenario: str = "base") -> dict[str, float]:
    assumptions = dict(DEFAULT_ASSUMPTIONS)
    assumptions.update(SCENARIO_DEFAULT_OVERRIDES.get((scenario or "base").lower(), {}))
    assumptions, _provenance, _warnings = normalize_scenario_probabilities(assumptions)
    return assumptions


def resolve_assumptions(
    symbol: str,
    scenario: str,
    *,
    overrides_loader: Callable[[str, str], dict[str, float] | None] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Resolve default, scenario, and per-symbol assumption layers."""

    resolved = dict(DEFAULT_ASSUMPTIONS)
    provenance: dict[str, str] = {key: "default" for key in resolved}

    scenario_key = (scenario or "base").lower()
    for key, value in SCENARIO_DEFAULT_OVERRIDES.get(scenario_key, {}).items():
        resolved[key] = float(value)
        provenance[key] = "scenario"

    if overrides_loader is not None:
        symbol_overrides = overrides_loader(symbol.upper(), scenario_key) or {}
        for key, value in symbol_overrides.items():
            if key not in DEFAULT_ASSUMPTIONS:
                raise ValueError(f"unknown assumption key: {key}")
            resolved[key] = float(value)
            provenance[key] = "user_override"

    resolved, provenance, _warnings = normalize_scenario_probabilities(resolved, provenance)
    return resolved, provenance


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _ratio(value: Any) -> float | None:
    out = _num(value)
    if out is None:
        return None
    return out / 100.0 if abs(out) > 2.0 else out


def _dividend_yield_ratio(value: Any) -> float | None:
    out = _num(value)
    if out is None:
        return None
    # Dividend_Yield arrives from some import paths as percentage points
    # (1.52 means 1.52%), while older core fixtures use ratios (0.04 means 4%).
    return out / 100.0 if abs(out) > 0.25 else out


def _positive(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _growth(value: Any, cap: float | None = None) -> float:
    out = _ratio(value)
    if out is None:
        return 0.03
    if cap is None:
        return max(-0.05, out)
    return max(-0.05, min(cap, out))


def _snapshot_currency(snapshot: FundamentalSnapshot) -> str:
    raw = snapshot.source.get("currency") or snapshot.metrics.get("Currency") or DEFAULT_CURRENCY
    return str(raw or DEFAULT_CURRENCY).upper()


def _assumption_currency(assumptions: dict[str, Any] | None) -> str:
    raw = (assumptions or {}).get("currency", DEFAULT_CURRENCY)
    return str(raw or DEFAULT_CURRENCY).upper()


def _cost_of_capital_input(assumptions: dict[str, Any]) -> dict[str, Any]:
    build_up = assumptions.get("cost_of_capital_build_up")
    if isinstance(build_up, dict):
        out = {
            "cost_of_capital": build_up,
            "beta": build_up.get("beta"),
            "beta_source": build_up.get("beta_source"),
            "beta_method": build_up.get("beta_method"),
            "beta_as_of": build_up.get("beta_as_of"),
            "beta_liquidity_flag": build_up.get("beta_liquidity_flag"),
            "beta_proxy": build_up.get("market_proxy"),
            "risk_free_rate": build_up.get("risk_free_rate"),
            "cost_of_equity": build_up.get("cost_of_equity"),
            "cost_of_equity_floor": build_up.get("cost_of_equity_floor"),
            "cost_of_equity_unfloored": build_up.get("cost_of_equity_unfloored"),
            "wacc": build_up.get("wacc"),
        }
        return {key: value for key, value in out.items() if value is not None}
    out = {
        "beta": assumptions.get("beta"),
        "beta_source": "default_beta",
        "cost_of_equity": assumptions.get("cost_of_equity"),
        "cost_of_equity_floor": assumptions.get("cost_of_equity_floor"),
        "wacc": assumptions.get("wacc"),
    }
    return {key: value for key, value in out.items() if value is not None}


def _projection_from_assumptions(assumptions: dict[str, Any]) -> Projection | None:
    projection = assumptions.get("_projection")
    return projection if isinstance(projection, Projection) else None


def _projection_has_unavailable_driver(projection: Projection | None, required_warnings: set[str]) -> bool:
    if projection is None:
        return False
    warnings = set(str(warning) for warning in projection.warnings)
    return bool(warnings & required_warnings)


def _mid_year_discounting(assumptions: dict[str, Any]) -> bool:
    return bool(float(assumptions.get("mid_year_discounting", DEFAULT_ASSUMPTIONS["mid_year_discounting"])))


def _mid_year_terminal(assumptions: dict[str, Any]) -> bool:
    return bool(float(assumptions.get("mid_year_terminal", DEFAULT_ASSUMPTIONS["mid_year_terminal"])))


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_financial(sector: str | None) -> bool:
    normalized = _normalize_text(sector)
    return any(token in normalized for token in FINANCIAL_SECTOR_TOKENS)


def _financial_archetype(sector: str | None) -> str | None:
    normalized = _normalize_text(sector)
    if any(token in normalized for token in INSURANCE_SECTOR_TOKENS):
        return "insurance"
    if any(token in normalized for token in BANK_SECTOR_TOKENS):
        return "bank"
    if any(token in normalized for token in GENERAL_FINANCIAL_SECTOR_TOKENS):
        return "financial"
    return "financial" if _is_financial(sector) else None


def _sanitize_financial_snapshot(snapshot: FundamentalSnapshot, sector: str | None) -> FundamentalSnapshot:
    if not _is_financial(sector):
        return snapshot
    metrics = {key: value for key, value in snapshot.metrics.items() if key not in FINANCIAL_SUPPRESSED_METRICS}
    return replace(snapshot, metrics=metrics)


def _sanitize_financial_history(history: list[AnnualMetricRow], sector: str | None) -> list[AnnualMetricRow]:
    if not _is_financial(sector):
        return history
    return [row for row in history if row.metric_name not in FINANCIAL_SUPPRESSED_METRICS]


def _cyclical_commodity_source(symbol: str | None, sector: str | None) -> str | None:
    normalized_symbol = str(symbol or "").strip().upper()
    if normalized_symbol in CYCLICAL_COMMODITY_SYMBOL_REGISTRY:
        return f"symbol_registry:{CYCLICAL_COMMODITY_SYMBOL_REGISTRY[normalized_symbol]}"
    normalized_sector = _normalize_text(sector)
    if normalized_sector and any(token in normalized_sector for token in CYCLICAL_COMMODITY_SECTOR_TOKENS):
        return f"stock_master.sector:{sector}"
    return None


def is_cyclical_or_commodity(symbol: str | None, sector: str | None) -> bool:
    return _cyclical_commodity_source(symbol, sector) is not None


def _latest_metric(history: list[AnnualMetricRow], *metrics: str) -> float | None:
    by_year = _pick_best_row_per_year(history, metrics)
    if not by_year:
        return None
    row = by_year[max(by_year)]
    return row.metric_value if row.metric_value is not None else None


def _metric_series(history: list[AnnualMetricRow], metric: str) -> list[float]:
    by_year = _pick_best_row_per_year(history, (metric,))
    result: list[float] = []
    for _yr, row in sorted(by_year.items()):
        v = row.metric_value
        if v is not None and isfinite(float(v)):
            result.append(float(v))
    return result


def _metric_series_any(history: list[AnnualMetricRow], *metrics: str) -> list[float]:
    by_year = _pick_best_row_per_year(history, metrics)
    result: list[float] = []
    for _yr, row in sorted(by_year.items()):
        v = _num(row.metric_value)
        if v is not None:
            result.append(v)
    return result


def _metric_year_map(history: list[AnnualMetricRow], *metrics: str) -> dict[int, float]:
    by_year = _pick_best_row_per_year(history, metrics)
    return {yr: float(row.metric_value) for yr, row in by_year.items() if row.metric_value is not None}


def _ratio_year_map(
    history: list[AnnualMetricRow],
    numerator_aliases: Iterable[str],
    denominator_aliases: Iterable[str],
    *,
    absolute_numerator: bool = False,
) -> dict[int, float]:
    numerator = _metric_year_map(history, *numerator_aliases)
    denominator = _metric_year_map(history, *denominator_aliases)
    out: dict[int, float] = {}
    for year in sorted(set(numerator) & set(denominator)):
        den = denominator[year]
        if not den:
            continue
        num = abs(numerator[year]) if absolute_numerator else numerator[year]
        value = num / den
        if isfinite(value):
            out[year] = float(value)
    return out


def _roe_year_map(history: list[AnnualMetricRow]) -> dict[int, float]:
    out: dict[int, float] = {}
    for year, value in _metric_year_map(history, "ROE").items():
        ratio = _ratio(value)
        if ratio is not None and -1.0 < ratio < 1.0:
            out[year] = ratio
    net_income = _metric_year_map(history, *NET_INCOME_ALIASES)
    equity = _metric_year_map(history, *EQUITY_ALIASES)
    for year in sorted(set(net_income) & set(equity)):
        if year in out or not equity[year]:
            continue
        value = net_income[year] / equity[year]
        if isfinite(value) and -1.0 < value < 1.0:
            out[year] = float(value)
    return out


def _book_equity_total(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None) -> tuple[float | None, str | None]:
    observed = _latest_metric(history, *EQUITY_ALIASES)
    if observed is not None and observed > 0:
        return observed, "observed_equity"
    market_cap = _market_cap_for_multiple(snapshot, current_price)
    pb = _positive(snapshot.metrics.get("Price_to_Book"))
    if market_cap and pb:
        return market_cap / pb, "market_cap_over_price_to_book"
    return None, None


def _midcycle_earnings_basis(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    *,
    sector: str | None,
    current_price: float | None,
) -> dict[str, Any] | None:
    source = _cyclical_commodity_source(snapshot.symbol, sector)
    if source is None:
        return None
    ebit_margin_by_year = _ratio_year_map(history, EBIT_ALIASES, REVENUE_ALIASES)
    roe_by_year = _roe_year_map(history)
    common_years = sorted(set(ebit_margin_by_year) & set(roe_by_year))
    if len(common_years) < 3:
        # Fewer than 3 cycle years: a confident trough-based rating is not defensible
        # (brief 44 §3.3). Flag so the combiner routes the headline to review/NR rather
        # than shipping a confident trough SELL on a single bad year.
        return {
            "status": "unavailable",
            "reason": "cyclical_trough_unnormalized",
            "source": source,
            "required_years": 3,
            "available_years": len(common_years),
            "sector": sector,
        }
    thin_history = len(common_years) == 3
    ebitda_margin_by_year = _ratio_year_map(history, EBITDA_ALIASES, REVENUE_ALIASES)
    d_and_a_pct_by_year = _ratio_year_map(history, DANDA_ALIASES, REVENUE_ALIASES)
    median_margin = float(median([ebit_margin_by_year[year] for year in common_years]))
    median_roe = float(median([roe_by_year[year] for year in common_years]))
    ebitda_years = sorted(ebitda_margin_by_year)
    if len(ebitda_years) >= 4:
        median_ebitda_margin = float(median([ebitda_margin_by_year[year] for year in ebitda_years]))
        ebitda_source = "observed_ebitda_margin_median"
    else:
        d_and_a_years = sorted(d_and_a_pct_by_year)
        if len(d_and_a_years) >= 4:
            median_ebitda_margin = median_margin + float(median([d_and_a_pct_by_year[year] for year in d_and_a_years]))
            ebitda_source = "midcycle_ebit_margin_plus_observed_d_and_a_pct"
        else:
            median_ebitda_margin = None
            ebitda_source = "unavailable_insufficient_ebitda_or_d_and_a_history"
    current_revenue = _latest_metric(history, *REVENUE_ALIASES)
    if current_revenue is None:
        current_revenue = _num(snapshot.metrics.get("Revenue") or snapshot.metrics.get("Chiffre_daffaires"))
    book_equity, book_source = _book_equity_total(snapshot, history, current_price)
    shares = _shares(snapshot)
    normalized_ebit = current_revenue * median_margin if current_revenue is not None else None
    normalized_net_income = book_equity * median_roe if book_equity is not None else None
    normalized_ebitda = (
        current_revenue * median_ebitda_margin
        if current_revenue is not None and median_ebitda_margin is not None
        else None
    )
    latest_margin = ebit_margin_by_year[common_years[-1]]
    trailing_vs_midcycle_pct = (
        latest_margin / median_margin - 1.0
        if median_margin not in (0.0, None)
        else None
    )
    return {
        "status": "available",
        "thin_history": thin_history,
        "source": source,
        "sector": sector,
        "window": {"start": common_years[0], "end": common_years[-1], "count": len(common_years), "years": common_years},
        "median_margin": median_margin,
        "median_roe": median_roe,
        "median_ebitda_margin": median_ebitda_margin,
        "ebitda_source": ebitda_source,
        "current_revenue": current_revenue,
        "current_book_equity": book_equity,
        "book_equity_source": book_source,
        "shares": shares,
        "normalized_ebit": normalized_ebit,
        "normalized_net_income": normalized_net_income,
        "normalized_net_income_per_share": normalized_net_income / shares if normalized_net_income is not None and shares else None,
        "normalized_ebitda": normalized_ebitda,
        "trailing_vs_midcycle_pct": trailing_vs_midcycle_pct,
    }


def _midcycle_basis(assumptions: dict[str, Any]) -> dict[str, Any] | None:
    basis = assumptions.get("_midcycle_earnings_basis")
    return basis if isinstance(basis, dict) else None


def _midcycle_model_warning(assumptions: dict[str, Any]) -> str | None:
    if not assumptions.get("_cyclical_commodity"):
        return None
    basis = _midcycle_basis(assumptions)
    if not basis:
        return "midcycle_normalization_unavailable_no_basis"
    if basis.get("status") == "available":
        if basis.get("thin_history"):
            return "midcycle_normalization_thin_history"
        return "midcycle_normalization_applied"
    return str(basis.get("reason") or "midcycle_normalization_unavailable")


def _append_unique(warnings: list[str], warning: str | None) -> None:
    if warning and warning not in warnings:
        warnings.append(warning)


def _trailing_average(values: list[float], *, window: int = 3) -> float | None:
    cleaned = [value for value in values if isfinite(value)]
    if not cleaned:
        return None
    tail = cleaned[-max(1, window):]
    return sum(tail) / len(tail)


def _clamp_value(value: float, floor: float, ceiling: float) -> float:
    if ceiling < floor:
        ceiling = floor
    return max(floor, min(ceiling, value))


def _weighted_median(pairs: list[tuple[float, float]]) -> float | None:
    ordered = sorted((value, weight) for value, weight in pairs if weight > 0)
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return None
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= total / 2.0:
            return value
    return ordered[-1][0] if ordered else None


def _dispersion_stats(fair_values: list[float]) -> tuple[float | None, float]:
    vals = [value for value in fair_values if value > 0 and isfinite(value)]
    if len(vals) < 2:
        return None, 1.0
    center = float(median(vals))
    if center <= 0:
        return None, 1.0
    deviations = [abs(value - center) for value in vals]
    mad = float(median(deviations))
    robust_cv = 0.0 if mad <= 0 else (1.4826 * mad) / abs(center)
    agreement = max(0.0, 1.0 - min(1.0, robust_cv))
    return robust_cv, agreement


def _current_price(snapshot: FundamentalSnapshot) -> float | None:
    return _positive(snapshot.metrics.get("Current_Price"))


def _market_cap(snapshot: FundamentalSnapshot) -> float | None:
    return _positive(snapshot.metrics.get("MarketCap_Calc"))


def _shares(snapshot: FundamentalSnapshot) -> float | None:
    return _positive(snapshot.metrics.get("Shares_Outstanding"))


def _market_cap_for_multiple(snapshot: FundamentalSnapshot, current_price: float | None) -> float | None:
    market_cap = _market_cap(snapshot)
    if market_cap is not None:
        return market_cap
    shares = _shares(snapshot)
    if current_price is not None and shares is not None:
        return current_price * shares
    return None


def _group_basis_roe(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> tuple[float | None, str]:
    rows_by_year: dict[int, dict[str, Any]] = defaultdict(dict)
    for row in history:
        value = _num(row.metric_value)
        if value is None:
            continue
        rows_by_year[int(row.statement_year)][str(row.metric_name)] = value
    if not rows_by_year:
        return None, "missing_group_roe_components"
    target_year = snapshot.latest_statement_year
    if target_year is None or int(target_year) not in rows_by_year:
        target_year = sorted(rows_by_year)[-1]
    target_year = int(target_year)

    epsilon = float(DEFAULT_ASSUMPTIONS["minority_materiality_epsilon"])
    basis = resolve_minority_roe_basis(rows_by_year.get(target_year, {}), epsilon=epsilon)
    current_equity = basis.group_equity
    rnpg = basis.rnpg
    if not basis.is_material_minority:
        if current_equity is None or current_equity <= 0 or rnpg is None:
            return None, "missing_no_minority_roe_components"
        return rnpg / current_equity, basis.basis

    if current_equity is None or current_equity <= 0 or rnpg is None:
        return None, "missing_group_roe_components"
    group_equity_by_year = _metric_year_map(history, *GROUP_EQUITY_ALIASES)
    previous_years = [year for year, equity in group_equity_by_year.items() if year < target_year and equity > 0]
    previous_equity = group_equity_by_year[max(previous_years)] if previous_years else None
    if previous_equity is not None:
        scale_ratio = previous_equity / current_equity
        if scale_ratio < 0.20 or scale_ratio > 5.0:
            previous_equity = None
    denominator = (previous_equity + current_equity) / 2.0 if previous_equity is not None else current_equity
    if denominator <= 0:
        return None, "missing_group_roe_components"
    source = "group_roe_rnpg_over_avg_group_equity" if previous_equity is not None else "group_roe_rnpg_over_current_group_equity"
    return rnpg / denominator, source


def _normalized_roe(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, Any] | None = None,
) -> tuple[float | None, str]:
    return _roe_basis(snapshot, history, assumptions)


def _normalized_flow_multiple(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    metric: str,
    current_price: float | None,
    assumptions: dict[str, Any] | None = None,
) -> tuple[float | None, str]:
    if metric == "PER":
        assum = assumptions or {}
        forward_eps = _positive(assum.get("forward_eps"))
        if forward_eps is not None and current_price is not None and current_price > 0:
            # Forward P/E: price / forward EPS.  When peer P/E is then applied:
            #   fair_value = current_price × peer_PER / forward_PER = peer_PER × forward_EPS
            return current_price / forward_eps, "forward_eps_per"
        midcycle_basis = _midcycle_basis(assum)
        flow = (
            _num(midcycle_basis.get("normalized_net_income"))
            if midcycle_basis and midcycle_basis.get("status") == "available"
            else None
        )
        if flow is not None:
            basis = "market_cap_over_midcycle_net_income"
        else:
            flow = _trailing_average(_metric_series_any(history, *NET_INCOME_ALIASES), window=3)
            basis = "market_cap_over_3y_avg_net_income"
    elif metric == "Price_to_Sales":
        flow = _trailing_average(_metric_series_any(history, *REVENUE_ALIASES), window=3)
        basis = "market_cap_over_3y_avg_revenue"
    else:
        return _positive(snapshot.metrics.get(metric)), "spot"
    market_cap = _market_cap_for_multiple(snapshot, current_price)
    if market_cap is not None and flow is not None and flow > 0:
        return market_cap / flow, basis
    return _positive(snapshot.metrics.get(metric)), "spot_fallback"


def _upside(fair_value: float | None, current_price: float | None) -> float | None:
    if fair_value is None or current_price is None or current_price <= 0:
        return None
    return fair_value / current_price - 1.0


def _confidence(base: str, warnings: list[str], *, proxy: bool = False) -> str:
    if base == "unavailable":
        return "unavailable"
    if proxy and base == "high":
        base = "medium"
    if warnings and base == "high":
        return "medium"
    if len(warnings) >= 2:
        return "low"
    return base


def _data_quality(confidence: str, warnings: list[str], proxy: bool = False) -> float:
    score = CONFIDENCE_TO_SCORE.get(confidence, 0.0) * 100.0
    score -= min(30.0, len(warnings) * 7.5)
    if proxy:
        score = min(score, 60.0)
    return max(0.0, min(100.0, score))


def _cost_of_capital_warnings(assumptions: dict[str, Any]) -> list[str]:
    build_up = assumptions.get("cost_of_capital_build_up")
    if not isinstance(build_up, dict):
        return ["default_beta_for_cost_of_equity"]
    warnings: list[str] = []
    if str(build_up.get("beta_source") or "") == "default_beta":
        warnings.append("default_beta_for_cost_of_equity")
    if bool(build_up.get("beta_liquidity_flag")):
        warnings.append("beta_liquidity_flag_confidence_haircut")
    method = str(build_up.get("beta_method") or "")
    if method.startswith("peer_"):
        warnings.append("beta_proxy_confidence_haircut")
    proxy = str(build_up.get("market_proxy") or "MASI").upper()
    if proxy and proxy != "MASI":
        warnings.append("non_masi_beta_proxy_confidence_haircut")
    return warnings


def _with_cost_of_capital_context(results: list[ValuationResult], assumptions: dict[str, Any]) -> list[ValuationResult]:
    metadata = _cost_of_capital_input(assumptions)
    coc_warnings = _cost_of_capital_warnings(assumptions)
    if not metadata and not coc_warnings:
        return results
    adjusted: list[ValuationResult] = []
    for row in results:
        warnings = list(row.warnings)
        for warning in coc_warnings:
            if warning not in warnings:
                warnings.append(warning)
        confidence = row.confidence
        if confidence != "unavailable" and coc_warnings:
            confidence = _confidence(confidence, coc_warnings, proxy=row.is_proxy)
        data_quality_score = _data_quality(confidence, warnings, row.is_proxy)
        adjusted.append(
            replace(
                row,
                inputs={**metadata, **row.inputs},
                warnings=warnings,
                confidence=confidence,
                confidence_score=data_quality_score / 100.0,
                data_quality_score=data_quality_score,
            )
        )
    return adjusted


def _result(
    *,
    snapshot: FundamentalSnapshot,
    scenario: str,
    model: str,
    fair_value: float | None,
    current_price: float | None,
    confidence: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    methodology: str,
    family: str = "intrinsic",
    proxy: bool = False,
    currency: str | None = None,
) -> ValuationResult:
    warnings = warnings or []
    quality_score = _data_quality(confidence, warnings, proxy)
    confidence_score = quality_score / 100.0
    return ValuationResult(
        symbol=snapshot.symbol,
        scenario=scenario,
        model=model,
        fair_value=fair_value,
        current_price=current_price,
        upside_pct=_upside(fair_value, current_price),
        confidence=confidence,
        inputs=inputs,
        outputs=outputs or {},
        warnings=warnings,
        family=family,
        model_version=MODEL_VERSION,
        methodology=methodology,
        confidence_score=confidence_score,
        weight=None,
        is_proxy=proxy,
        data_quality_score=quality_score,
        currency=currency or _snapshot_currency(snapshot),
    )


def _peer_stats(
    snapshots: Iterable[FundamentalSnapshot],
    sectors: dict[str, str | None],
    target_symbol: str,
    peer_min_count: int,
) -> dict[str, dict[str, Any]]:
    target_sector = sectors.get(target_symbol)
    grouped: dict[str, list[float]] = defaultdict(list)
    fallback: dict[str, list[float]] = defaultdict(list)
    metric_aliases = {
        "PER": ("PER",),
        "Price_to_Book": ("Price_to_Book",),
        "Price_to_Sales": ("Price_to_Sales",),
        "EV_to_EBITDA": ("EV_to_EBITDA",),
        "Price_to_PNB": ("Price_to_PNB", "P_to_PNB"),
    }
    for row in snapshots:
        if row.symbol == target_symbol:
            continue
        for metric, aliases in metric_aliases.items():
            value = next((_positive(row.metrics.get(alias)) for alias in aliases if _positive(row.metrics.get(alias)) is not None), None)
            if value is None:
                continue
            fallback[metric].append(value)
            if target_sector and sectors.get(row.symbol) == target_sector:
                grouped[metric].append(value)
    out: dict[str, dict[str, Any]] = {}
    for metric in metric_aliases:
        sector_values = grouped[metric]
        market_values = fallback[metric]
        source = sector_values if len(sector_values) >= peer_min_count else market_values
        if source:
            out[metric] = {
                "median": float(median(source)),
                "count": len(source),
                "scope": "sector" if source is sector_values else "market",
            }
    return out


PEER_DRIVER_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue_growth": ("Revenue_Growth",),
    "ebit_margin": ("Operating_Margin", "EBIT_Margin"),
    "depreciation_amortization_pct": ("Depreciation_Amortization_Pct", "DandA_Pct", "DandA_to_Revenue"),
    "capex_pct": ("Capex_Pct", "Capex_to_Revenue"),
    "working_capital_pct": ("Working_Capital_Pct", "Working_Capital_to_Revenue"),
    "payout_ratio": ("Dividend_Payout",),
    "bank_pnb_growth": ("PNB_Growth",),
    "bank_rbe_margin": ("Marge_RBE", "RBE_Margin"),
    "bank_cost_of_risk_pct": ("Cost_of_Risk_Pct", "Cout_du_risque_to_Loans", "Cout_du_risque_to_PNB"),
    "insurer_roe": ("ROE", "Return_on_Equity"),
    "financial_roe": ("ROE", "Return_on_Equity"),
}


def _snapshot_ratio_metric(row: FundamentalSnapshot, aliases: Iterable[str]) -> float | None:
    for alias in aliases:
        value = _ratio(row.metrics.get(alias))
        if value is not None and isfinite(value):
            return float(value)
    return None


def _peer_driver_snapshot_value(row: FundamentalSnapshot, driver: str, aliases: tuple[str, ...]) -> float | None:
    value = _snapshot_ratio_metric(row, aliases)
    if value is not None:
        return value
    if driver == "bank_rbe_margin":
        rbe = _num(row.metrics.get("RBE") or row.metrics.get("Resultat_Brut_Exploitation"))
        pnb = _positive(row.metrics.get("PNB") or row.metrics.get("Produit_Net_Bancaire"))
        return rbe / pnb if rbe is not None and pnb else None
    if driver == "bank_cost_of_risk_pct":
        cost = _num(row.metrics.get("Cout_du_risque") or row.metrics.get("Cost_of_Risk") or row.metrics.get("Provision_for_Loan_Losses"))
        loans = _positive(row.metrics.get("Loans_Net") or row.metrics.get("Net_Loans"))
        pnb = _positive(row.metrics.get("PNB") or row.metrics.get("Produit_Net_Bancaire"))
        if cost is not None and loans:
            return abs(cost) / loans
        if cost is not None and pnb:
            return abs(cost) / pnb
    return None


def peer_driver_medians(
    snapshots: Iterable[FundamentalSnapshot],
    sectors: dict[str, str | None],
    target_symbol: str,
    peer_min_count: int,
) -> dict[str, dict[str, Any]]:
    target_sector = sectors.get(target_symbol)
    grouped: dict[str, list[float]] = defaultdict(list)
    fallback: dict[str, list[float]] = defaultdict(list)
    for row in snapshots:
        if row.symbol == target_symbol:
            continue
        for driver, aliases in PEER_DRIVER_METRIC_ALIASES.items():
            value = _peer_driver_snapshot_value(row, driver, aliases)
            if value is None or not isfinite(value):
                continue
            fallback[driver].append(float(value))
            if target_sector and sectors.get(row.symbol) == target_sector:
                grouped[driver].append(float(value))
    out: dict[str, dict[str, Any]] = {}
    for driver in PEER_DRIVER_METRIC_ALIASES:
        sector_values = grouped[driver]
        market_values = fallback[driver]
        source = sector_values if len(sector_values) >= peer_min_count else market_values
        if source:
            out[driver] = {
                "median": float(median(source)),
                "count": len(source),
                "scope": "sector" if source is sector_values else "market",
            }
    return out


def _has_dividend(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> bool:
    dividend_yield = _positive(_dividend_yield_ratio(snapshot.metrics.get("Dividend_Yield")))
    return dividend_yield is not None or (_latest_metric(history, "Dividendes", "Clean_Dividendes") or 0) > 0


def _eligible_models(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    sector: str | None,
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    financial = _is_financial(sector)
    positive_fcf = [value for value in _metric_series(history, "Free_Cash_Flow") if value > 0]
    has_projection_base = (
        _latest_metric(history, "Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires") is not None
        and _latest_metric(history, "EBIT", "Resultat_dexploitation") is not None
    )
    has_fcf_proxy = (
        _positive(snapshot.metrics.get("FCF_Yield")) is not None
        or _positive(snapshot.metrics.get("FCF_Margin")) is not None
        or bool(positive_fcf)
    )
    roe_for_eligibility, _roe_source = _roe_basis(snapshot, history, assumptions)
    has_book_roe = _positive(snapshot.metrics.get("Price_to_Book")) is not None and roe_for_eligibility is not None
    multiple_metrics = ("PER", "Price_to_Book", "Price_to_PNB", "P_to_PNB") if financial else ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA")
    multiple_count = sum(_positive(snapshot.metrics.get(metric)) is not None for metric in multiple_metrics)
    has_multiples = multiple_count > 0
    has_price_market = _current_price(snapshot) is not None and _market_cap(snapshot) is not None
    return {
        "fcff_dcf": {
            "eligible": bool(not financial and (has_fcf_proxy or has_projection_base)),
            "confidence": "high" if len(positive_fcf) >= 3 else ("medium" if has_fcf_proxy or has_projection_base else "unavailable"),
        },
        "fcfe_dcf": {
            "eligible": bool(not financial and (has_fcf_proxy or has_projection_base)),
            "confidence": "medium" if has_fcf_proxy or has_projection_base else "unavailable",
            "proxy_required": True,
        },
        "ddm": {
            "eligible": bool(_has_dividend(snapshot, history)),
            "confidence": "high" if _positive(_dividend_yield_ratio(snapshot.metrics.get("Dividend_Yield"))) else ("medium" if _has_dividend(snapshot, history) else "unavailable"),
        },
        "residual_income": {
            "eligible": bool(has_book_roe),
            "confidence": "medium" if has_book_roe else "unavailable",
        },
        "justified_multiples": {
            "eligible": bool(has_book_roe or _positive(snapshot.metrics.get("PER")) is not None),
            "confidence": "medium" if has_book_roe or _positive(snapshot.metrics.get("PER")) else "unavailable",
        },
        "relative_multiples": {
            "eligible": bool(has_multiples),
            "confidence": "high" if multiple_count >= 3 else ("medium" if multiple_count >= 2 else ("low" if has_multiples else "unavailable")),
        },
        "reverse_dcf": {
            "eligible": bool(not financial and has_price_market),
            "confidence": "medium" if not financial and has_price_market else "unavailable",
        },
        "is_financial": financial,
    }


def _cagr_from_positive_series(series: list[float]) -> float | None:
    """Return annualised CAGR when both endpoints are positive, else None."""
    if len(series) >= 2 and series[0] > 0 and series[-1] > 0:
        ratio = series[-1] / series[0]
        if ratio > 0:
            return ratio ** (1.0 / (len(series) - 1)) - 1.0
    return None


def _fcf_start(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> tuple[float | None, str | None]:
    market_cap = _market_cap(snapshot)
    revenue = _latest_metric(history, "Chiffre_daffaires", "Clean_Chiffre_daffaires")
    fcf = _latest_metric(history, "Free_Cash_Flow")
    if fcf is not None:
        return fcf, "reported_free_cash_flow"
    fcf_yield = _ratio(snapshot.metrics.get("FCF_Yield"))
    if market_cap and fcf_yield is not None:
        return market_cap * fcf_yield, "market_cap_times_fcf_yield"
    fcf_margin = _ratio(snapshot.metrics.get("FCF_Margin"))
    if revenue and fcf_margin is not None:
        return revenue * fcf_margin, "revenue_times_fcf_margin"
    return None, None


def _fcf_growth_input(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], assumptions: dict[str, float]) -> tuple[float | None, str, bool]:
    _GROWTH_CAP = 0.25  # prevent outlier CAGRs from dominating stage-1

    # Step 1: multi-year CAGR (robust anchor) — prefer FCF, fall back to revenue, then earnings
    cagr: float | None = None
    cagr_source: str = ""
    cagr_is_proxy: bool = True

    v = _cagr_from_positive_series(_metric_series(history, "Free_Cash_Flow"))
    if v is not None:
        cagr, cagr_source, cagr_is_proxy = v, "fcf_series_cagr", False
    else:
        v = _cagr_from_positive_series(_metric_series_any(history, "Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"))
        if v is not None:
            cagr, cagr_source, cagr_is_proxy = v, "revenue_series_cagr_proxy", True
        else:
            v = _cagr_from_positive_series(_metric_series_any(history, "NOPAT", "NetIncome", "Resultat_Net", "Clean_Resultat_Net"))
            if v is not None:
                cagr, cagr_source, cagr_is_proxy = v, "nopat_series_cagr_proxy", True

    # Step 2: single-year trailing metric from snapshot (nudge only; was the sole input before)
    trailing_1y: float | None = None
    trailing_source: str = ""
    trailing_is_proxy: bool = True
    for metric_name, source, is_proxy in (
        ("FCF_Growth", "reported_fcf_growth", False),
        ("OperatingCF_Growth", "reported_operating_cf_growth", False),
        ("NetIncome_Growth", "earnings_growth_proxy", True),
        ("Revenue_Growth", "revenue_growth_proxy", True),
    ):
        value = snapshot.metrics.get(metric_name)
        if value is not None:
            trailing_1y = _growth(value)
            trailing_source = source
            trailing_is_proxy = is_proxy
            break

    # Step 3: blend — CAGR is the 70% anchor, 1-year YoY is a 30% nudge
    if cagr is not None and trailing_1y is not None:
        blended = 0.7 * max(-0.05, min(_GROWTH_CAP, cagr)) + 0.3 * trailing_1y
        return max(-0.05, min(_GROWTH_CAP, blended)), f"{cagr_source}_blended_{trailing_source}", trailing_is_proxy
    if cagr is not None:
        return max(-0.05, min(_GROWTH_CAP, cagr)), cagr_source, cagr_is_proxy
    if trailing_1y is not None:
        return min(_GROWTH_CAP, trailing_1y), trailing_source, trailing_is_proxy
    return None, "fcf_growth_unavailable_no_history_no_peer", True


def _fcf_reliability_warnings(history: list[AnnualMetricRow]) -> list[str]:
    warnings: list[str] = []
    fcf_series = _metric_series(history, "Free_Cash_Flow")
    if fcf_series and fcf_series[-1] < 0:
        warnings.append("fcf_model_unreliable_negative_trailing_fcf")
    capex_series = _ratio_series_for_reliability(history, CAPEX_ALIASES, REVENUE_ALIASES, absolute_numerator=True)
    d_and_a_series = _ratio_series_for_reliability(history, DANDA_ALIASES, REVENUE_ALIASES)
    if capex_series:
        capex_pct = _median_or_latest(capex_series[-3:])
        d_and_a_pct = _median_or_latest(d_and_a_series[-3:]) if d_and_a_series else 0.0
        capex_hurdle = max(0.10, 2.0 * d_and_a_pct)
        if capex_pct > capex_hurdle:
            warnings.append("fcf_model_unreliable_capex_heavy")
    return warnings


def _ratio_series_for_reliability(
    history: list[AnnualMetricRow],
    numerator_aliases: Iterable[str],
    denominator_aliases: Iterable[str],
    *,
    absolute_numerator: bool = False,
) -> list[float]:
    numerator = _metric_year_map(history, *numerator_aliases)
    denominator = _metric_year_map(history, *denominator_aliases)
    out: list[float] = []
    for year in sorted(set(numerator) & set(denominator)):
        den = denominator[year]
        if den:
            num = abs(numerator[year]) if absolute_numerator else numerator[year]
            out.append(num / den)
    return [value for value in out if isfinite(value)]


def _median_or_latest(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _has_fcf_reliability_warning(result: ValuationResult) -> bool:
    return any(str(warning).startswith("fcf_model_unreliable_") for warning in result.warnings)


def _has_warning(result: ValuationResult, warnings: set[str], prefixes: tuple[str, ...] = ()) -> bool:
    for warning in result.warnings:
        text = str(warning)
        if text in warnings or any(text.startswith(prefix) for prefix in prefixes):
            return True
    return False


def _severe_valuation_exclusion_reason(result: ValuationResult) -> str | None:
    # A DCF/DDM whose terminal share exceeds the hard ceiling is low-information on
    # its own — it carries almost nothing from the explicit window (brief 44 §3.4).
    if result.model in {*FCF_DCF_MODELS, "ddm"} and _has_warning(result, TERMINAL_VALUE_CEILING_WARNINGS):
        return "terminal_value_dominates_dcf"
    if result.model in FCF_DCF_MODELS:
        if _has_warning(result, SEVERE_FCF_DCF_WARNINGS, SEVERE_FCF_DCF_WARNING_PREFIXES):
            return "severe_fcf_quality_warning"
        if _has_warning(result, SEVERE_TERMINAL_VALUE_WARNINGS) and _has_fcf_reliability_warning(result):
            return "severe_terminal_value_warning"
    if result.model == "ddm" and _has_warning(result, {"dividend_yield_above_plausible_range"}):
        return "severe_dividend_quality_warning"
    if result.model == "residual_income" and _has_warning(result, {"price_to_book_below_plausible_range"}):
        return "severe_book_value_quality_warning"
    return None


def _net_debt_bridge_detail(history: list[AnnualMetricRow]) -> dict[str, Any]:
    net_debt = _latest_metric(history, "NetDebt", "Net_Debt")
    debt = _latest_metric(history, *DEBT_ALIASES)
    cash = _latest_metric(history, "Cash_and_Equivalents", "Cash", "Tresorerie_Actif")
    warning = False
    if net_debt is not None:
        base_bridge = net_debt
        source = "reported_net_debt"
    elif debt is not None and cash is not None:
        base_bridge = debt - cash
        source = "computed_from_debt_minus_cash"
    elif debt is not None:
        base_bridge = debt
        source = "debt_only_cash_missing"
        warning = True
    else:
        base_bridge = 0.0
        source = "missing_net_debt_bridge"
        warning = True

    minority_interest = _latest_metric(history, *MINORITY_INTEREST_ALIASES)
    associates_investments = _latest_metric(history, *ASSOCIATES_INVESTMENTS_ALIASES)
    pension_lease_obligations = _latest_metric(history, *PENSION_LEASE_ALIASES)
    other_adjustments = {
        "minority_interest": minority_interest,
        "associates_investments": associates_investments,
        "pension_lease_obligations": pension_lease_obligations,
    }
    available_adjustments = any(value is not None for value in other_adjustments.values())
    adjusted_bridge = (
        base_bridge
        + (minority_interest or 0.0)
        + (pension_lease_obligations or 0.0)
        - (associates_investments or 0.0)
    )
    notes: list[str] = []
    if not available_adjustments:
        notes.append("bridge_simplified_net_debt_only")
    return {
        "net_debt": adjusted_bridge,
        "base_net_debt": base_bridge,
        "source": source if not available_adjustments else f"{source}_with_other_adjustments",
        "warning": warning,
        "other_adjustments": other_adjustments,
        "notes": notes,
    }


def _net_debt_bridge(history: list[AnnualMetricRow]) -> tuple[float, str, bool]:
    detail = _net_debt_bridge_detail(history)
    return float(detail["net_debt"]), str(detail["source"]), bool(detail["warning"])


def _working_capital_map(history: list[AnnualMetricRow]) -> dict[int, float]:
    wc = _metric_year_map(history, *WORKING_CAPITAL_ALIASES)
    if wc:
        return wc
    current_assets = _metric_year_map(history, *CURRENT_ASSET_ALIASES)
    current_liabilities = _metric_year_map(history, *CURRENT_LIABILITY_ALIASES)
    return {
        year: current_assets[year] - current_liabilities[year]
        for year in sorted(set(current_assets) & set(current_liabilities))
    }


def _payout_basis(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], assumptions: dict[str, Any]) -> tuple[float, str]:
    dividends = _metric_year_map(history, *DIVIDEND_ALIASES)
    net_income = _metric_year_map(history, *NET_INCOME_ALIASES)
    payout_values: list[float] = []
    for year in sorted(set(dividends) & set(net_income)):
        if net_income[year] > 0:
            payout_values.append(_clamp_value(abs(dividends[year]) / net_income[year], 0.0, 1.5))
    historical = _trailing_average(payout_values)
    if historical is not None:
        return historical, "historical_dividends_to_net_income"
    snapshot_payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if snapshot_payout is not None and 0.0 <= snapshot_payout <= 1.5:
        return snapshot_payout, "snapshot_dividend_payout"
    return float(assumptions.get("stable_payout_ratio", DEFAULT_ASSUMPTIONS["stable_payout_ratio"])), "stable_payout_assumption"


def _roe_basis(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, Any] | None = None,
) -> tuple[float | None, str]:
    group_roe, group_source = _group_basis_roe(snapshot, history)
    archetype = str((assumptions or {}).get("_financial_archetype") or "").lower()
    if archetype == "insurance" and group_roe is not None:
        # Insurers: normalize ROE to the through-cycle median so a single spike year
        # (e.g. one-off realized investment gains) cannot inflate the justified P/B and
        # drive an overshoot (brief 44 §3.7). Capped against the verified group basis so
        # the minority/group correction is preserved; never normalize a spike *upward*.
        roe_by_year = _roe_year_map(history)
        if len(roe_by_year) >= 3:
            median_roe = float(median([roe_by_year[year] for year in roe_by_year]))
            return min(group_roe, median_roe), "insurer_normalized_median_roe"
    if group_roe is not None:
        return group_roe, group_source
    if assumptions and bool(assumptions.get("_require_verified_group_roe")):
        return None, group_source

    roe_by_year = _roe_year_map(history)
    if roe_by_year:
        values = [roe_by_year[year] for year in sorted(roe_by_year)]
        trailing = _trailing_average(values, window=3)
        if trailing is not None:
            return trailing, "roe_3y_trailing" if len(values[-3:]) >= 2 else "roe_latest"

    snapshot_roe = _ratio(snapshot.metrics.get("ROE"))
    if snapshot_roe is not None and -1.0 <= snapshot_roe < 1.0:
        return snapshot_roe, "snapshot_roe"
    return None, group_source


def _terminal_growth_ceiling(assumptions: dict[str, Any]) -> tuple[float, str]:
    use_risk_free_ceiling = float(
        assumptions.get(
            "terminal_growth_ceiling_source",
            DEFAULT_ASSUMPTIONS["terminal_growth_ceiling_source"],
        )
        or 0.0
    ) >= 0.5
    if use_risk_free_ceiling:
        return float(assumptions.get("risk_free_rate", DEFAULT_ASSUMPTIONS["risk_free_rate"])), "risk_free_rate"
    return 1.0, "disabled"


def clamp_terminal_growth(
    raw_growth: float | None,
    assumptions: dict[str, Any],
    *,
    discount_rate: float | None,
) -> tuple[float, dict[str, Any]]:
    floor = float(assumptions.get("terminal_growth_floor", DEFAULT_ASSUMPTIONS["terminal_growth_floor"]))
    buffer = float(
        assumptions.get(
            "terminal_growth_discount_buffer",
            DEFAULT_ASSUMPTIONS["terminal_growth_discount_buffer"],
        )
    )
    ceiling, ceiling_source = _terminal_growth_ceiling(assumptions)
    cap = ceiling
    discount_cap = None
    if discount_rate is not None and discount_rate > 0:
        discount_cap = max(floor, discount_rate - max(0.0, buffer))
        cap = min(cap, discount_cap)
    candidate = floor if raw_growth is None or not isfinite(raw_growth) else raw_growth
    value = _clamp_value(candidate, floor, cap)
    if value == floor and candidate < floor:
        binding = "floor"
    elif discount_cap is not None and value == discount_cap and candidate > discount_cap:
        binding = "discount_buffer"
    elif value == ceiling and candidate > ceiling:
        binding = "ceiling"
    else:
        binding = "raw"
    return value, {
        "raw_growth": raw_growth,
        "floor": floor,
        "ceiling": ceiling,
        "ceiling_source": ceiling_source,
        "discount_rate": discount_rate,
        "discount_buffer": buffer,
        "discount_cap": discount_cap,
        "binding_constraint": binding,
    }


def sustainable_growth_equity(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    roe, roe_source = _roe_basis(snapshot, history, assumptions)
    payout, payout_source = _payout_basis(snapshot, history, assumptions)
    retention = _clamp_value(1.0 - payout, 0.0, 1.0)
    source = "retention_times_roe"
    if roe is None:
        raw_growth = _growth(
            snapshot.metrics.get("NetIncome_Growth") or snapshot.metrics.get("Revenue_Growth"),
        )
        source = "earnings_growth_proxy_missing_roe"
    else:
        raw_growth = roe * retention
    terminal_growth, clamp_basis = clamp_terminal_growth(
        raw_growth,
        assumptions,
        discount_rate=float(assumptions.get("cost_of_equity", DEFAULT_ASSUMPTIONS["cost_of_equity"])),
    )
    basis = {
        "path": "equity",
        "source": source,
        "roe": roe,
        "roe_source": roe_source,
        "payout": payout,
        "payout_source": payout_source,
        "retention": retention,
        "terminal_growth": terminal_growth,
        **clamp_basis,
    }
    return terminal_growth, basis


def _invested_capital_by_year(history: list[AnnualMetricRow]) -> dict[int, float]:
    debt = _metric_year_map(history, *DEBT_ALIASES)
    equity = _metric_year_map(history, *EQUITY_ALIASES)
    assets = _metric_year_map(history, *TOTAL_ASSET_ALIASES)
    liabilities = _metric_year_map(history, *TOTAL_LIABILITY_ALIASES)
    out: dict[int, float] = {}
    for year in sorted(set(debt) | set(equity) | set(assets) | set(liabilities)):
        book_equity = equity.get(year)
        if book_equity is None and year in assets and year in liabilities:
            book_equity = assets[year] - liabilities[year]
        if book_equity is None:
            continue
        out[year] = max(0.0, debt.get(year, 0.0)) + book_equity
    return out


def sustainable_growth_firm(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    tax_rate = float(assumptions.get("tax_rate", DEFAULT_ASSUMPTIONS["tax_rate"]))
    ebit = _metric_year_map(history, *EBIT_ALIASES)
    invested_capital = _invested_capital_by_year(history)
    roic_values: list[float] = []
    nopat_by_year: dict[int, float] = {}
    for year in sorted(set(ebit) & set(invested_capital)):
        nopat = ebit[year] * (1.0 - tax_rate)
        if nopat > 0 and invested_capital[year] > 0:
            roic_values.append(nopat / invested_capital[year])
            nopat_by_year[year] = nopat
    roic = _trailing_average(roic_values)
    capex = _metric_year_map(history, *CAPEX_ALIASES)
    d_and_a = _metric_year_map(history, *DANDA_ALIASES)
    working_capital = _working_capital_map(history)
    free_cash_flow = _metric_year_map(history, *FREE_CASH_FLOW_ALIASES)
    reinvestment_values: list[float] = []
    years = sorted(nopat_by_year)
    for year in years:
        nopat = nopat_by_year[year]
        if nopat <= 0:
            continue
        previous_wc_years = [candidate for candidate in working_capital if candidate < year]
        delta_wc = 0.0
        if year in working_capital and previous_wc_years:
            delta_wc = working_capital[year] - working_capital[max(previous_wc_years)]
        if year in capex or year in d_and_a or year in working_capital:
            reinvestment = abs(capex.get(year, 0.0)) - d_and_a.get(year, 0.0) + delta_wc
            reinvestment_values.append(_clamp_value(reinvestment / nopat, 0.0, 1.5))
        elif year in free_cash_flow:
            reinvestment_values.append(_clamp_value(1.0 - free_cash_flow[year] / nopat, 0.0, 1.5))
    reinvestment_rate = _trailing_average(reinvestment_values)
    if roic is None or reinvestment_rate is None:
        raw_growth = _growth(
            snapshot.metrics.get("Revenue_Growth") or snapshot.metrics.get("NetIncome_Growth"),
        )
        source = "revenue_growth_proxy_missing_roic_or_reinvestment"
    else:
        raw_growth = roic * reinvestment_rate
        source = "reinvestment_times_roic"
    terminal_growth, clamp_basis = clamp_terminal_growth(
        raw_growth,
        assumptions,
        discount_rate=float(assumptions.get("wacc", DEFAULT_ASSUMPTIONS["wacc"])),
    )
    basis = {
        "path": "firm",
        "source": source,
        "roic": roic,
        "reinvestment_rate": reinvestment_rate,
        "tax_rate": tax_rate,
        "terminal_growth": terminal_growth,
        **clamp_basis,
    }
    return terminal_growth, basis


def _terminal_key_is_explicit(assumptions: dict[str, Any], key: str, explicit_keys: set[str]) -> bool:
    if key in explicit_keys:
        return True
    value = _num(assumptions.get(key))
    default = DEFAULT_ASSUMPTIONS.get(key)
    return value is not None and default is not None and abs(value - float(default)) > 1e-12


def enrich_terminal_growth_assumptions(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, Any],
    *,
    scenario: str = "base",
    explicit_keys: set[str] | None = None,
    sector: str | None = None,
) -> dict[str, Any]:
    explicit_keys = set(explicit_keys or set())
    out = dict(assumptions)
    legacy_explicit = "terminal_growth" in explicit_keys or _terminal_key_is_explicit(out, "terminal_growth", explicit_keys)
    firm_explicit = _terminal_key_is_explicit(out, "terminal_growth_firm", explicit_keys)
    equity_explicit = _terminal_key_is_explicit(out, "terminal_growth_equity", explicit_keys)
    firm_basis: dict[str, Any]
    equity_basis: dict[str, Any]
    if firm_explicit:
        firm_growth = float(out.get("terminal_growth_firm", out.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth_firm"])))
        firm_basis = {"path": "firm", "source": "explicit_terminal_growth_firm", "terminal_growth": firm_growth}
    elif legacy_explicit:
        firm_growth = float(out.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth"]))
        firm_basis = {"path": "firm", "source": "legacy_terminal_growth_override", "terminal_growth": firm_growth}
    elif _is_financial(sector):
        firm_growth = float(out.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth"]))
        firm_basis = {"path": "firm", "source": "not_used_for_financials", "terminal_growth": firm_growth}
    else:
        firm_growth, firm_basis = sustainable_growth_firm(snapshot, history, out)

    if equity_explicit:
        equity_growth = float(out.get("terminal_growth_equity", out.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth_equity"])))
        equity_basis = {"path": "equity", "source": "explicit_terminal_growth_equity", "terminal_growth": equity_growth}
    elif legacy_explicit:
        equity_growth = float(out.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth"]))
        equity_basis = {"path": "equity", "source": "legacy_terminal_growth_override", "terminal_growth": equity_growth}
    else:
        equity_growth, equity_basis = sustainable_growth_equity(snapshot, history, out)

    out["terminal_growth_firm"] = firm_growth
    out["terminal_growth_equity"] = equity_growth
    out["terminal_growth_basis"] = {"firm": firm_basis, "equity": equity_basis}
    return out


def _terminal_growth_for_model(assumptions: dict[str, Any], path: str) -> float:
    key = "terminal_growth_firm" if path == "firm" else "terminal_growth_equity"
    return float(assumptions.get(key, assumptions.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth"])))


def _terminal_growth_input(assumptions: dict[str, Any], path: str) -> dict[str, Any]:
    key = "terminal_growth_firm" if path == "firm" else "terminal_growth_equity"
    basis = assumptions.get("terminal_growth_basis")
    path_basis = basis.get(path) if isinstance(basis, dict) and isinstance(basis.get(path), dict) else None
    value = _terminal_growth_for_model(assumptions, path)
    return {
        "terminal_growth": value,
        key: value,
        "terminal_growth_basis": path_basis,
    }


def _fcfe_start(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], assumptions: dict[str, float]) -> tuple[float | None, str | None, bool]:
    fcf, fcf_source = _fcf_start(snapshot, history)
    if fcf is None:
        return None, None, True
    tax_rate = float(assumptions.get("tax_rate", DEFAULT_ASSUMPTIONS["tax_rate"]))
    interest = abs(_latest_metric(history, "Interest_Expense", "Charges_Interets") or 0.0)
    issuance = _latest_metric(history, "Debt_Issuance", "Debt_Raised") or 0.0
    repayment = abs(_latest_metric(history, "Debt_Repayment", "Debt_Repaid") or 0.0)
    if interest == 0.0 and issuance == 0.0 and repayment == 0.0:
        return fcf, fcf_source, True
    fcfe = fcf - interest * (1.0 - tax_rate) + issuance - repayment
    return fcfe, f"{fcf_source}_adjusted_for_debt_flows" if fcf_source else "fcf_adjusted_for_debt_flows", False


def _sustainable_dividend_growth(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, float],
) -> tuple[float | None, str, list[str], float | None, str]:
    _GROWTH_CAP = 0.20  # dividend growth is inherently more stable; tighter cap
    warnings: list[str] = []
    roe, roe_source = _roe_basis(snapshot, history, assumptions)
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
        warnings.append("using_stable_payout_assumption")
    retention = max(0.0, min(1.0, 1.0 - payout))

    # Stage-1 anchor: multi-year earnings CAGR (historical growth actually delivered)
    earnings_cagr: float | None = None
    earnings_cagr_source: str = ""
    v = _cagr_from_positive_series(_metric_series_any(history, "NetIncome", "Resultat_Net", "Clean_Resultat_Net", "NOPAT"))
    if v is not None:
        earnings_cagr, earnings_cagr_source = v, "earnings_series_cagr"
    else:
        v = _cagr_from_positive_series(_metric_series_any(history, "Dividendes", "Clean_Dividendes"))
        if v is not None:
            earnings_cagr, earnings_cagr_source = v, "dividend_series_cagr"
        else:
            v = _cagr_from_positive_series(_metric_series_any(history, "Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"))
            if v is not None:
                earnings_cagr, earnings_cagr_source = v, "revenue_series_cagr_proxy"

    # Terminal anchor: sustainable growth = ROE × retention
    roe_retention: float | None = max(-0.05, roe * retention) if roe is not None else None

    if earnings_cagr is not None and roe_retention is not None:
        # 2-stage blend: 60% near-term CAGR + 40% sustainable ROE×retention
        blended = 0.6 * max(-0.05, min(_GROWTH_CAP, earnings_cagr)) + 0.4 * roe_retention
        return max(-0.05, min(_GROWTH_CAP, blended)), f"{earnings_cagr_source}_blended_roe_retention", warnings, roe, roe_source
    if earnings_cagr is not None:
        return max(-0.05, min(_GROWTH_CAP, earnings_cagr)), earnings_cagr_source, warnings, roe, roe_source
    if roe_retention is not None:
        growth_source = (
            "sustainable_growth_from_group_roe_retention"
            if roe_source.startswith("group_roe_")
            else "sustainable_growth_from_roe_retention"
        )
        return roe_retention, growth_source, warnings, roe, roe_source

    # Final fallback: single-year trailing proxy
    warnings.append("using_earnings_growth_proxy")
    raw_growth = snapshot.metrics.get("NetIncome_Growth") or snapshot.metrics.get("Revenue_Growth")
    if raw_growth is None:
        warnings.append("ddm_growth_unavailable_no_roe_no_growth")
        return None, "growth_unavailable", warnings, roe, roe_source
    return _growth(raw_growth), "earnings_growth_proxy", warnings, roe, roe_source


def _residual_income_base_confidence(
    *,
    book_value: float | None,
    roe: float | None,
    observed_book_value: bool,
    net_income_points: int,
    warnings: list[str],
    model_unavailable: bool,
) -> str:
    if model_unavailable or book_value is None:
        return "unavailable"
    if observed_book_value and net_income_points >= 3 and roe is not None and not warnings:
        return "high"
    if roe is not None or net_income_points > 0:
        return "medium"
    return "low"


def _justified_growth(sustainable_growth: float, terminal_growth: float, fade_years: int) -> float:
    if sustainable_growth <= terminal_growth:
        return sustainable_growth
    h_period = max(1, int(fade_years)) / 2.0
    return terminal_growth + h_period * (sustainable_growth - terminal_growth) / max(1, int(fade_years))


def _selected_ratio_keys(
    assumptions: dict[str, Any],
    assumption_key: str,
    ratio_bits: tuple[tuple[str, int], ...],
) -> set[str]:
    mask = _assumption_int_mask(assumptions, assumption_key)
    return {key for key, bit in ratio_bits if mask & bit}


def _assumption_int_mask(assumptions: dict[str, Any], assumption_key: str) -> int:
    default_mask = int(DEFAULT_ASSUMPTIONS[assumption_key])
    raw_mask = _num(assumptions.get(assumption_key))
    return max(0, int(raw_mask if raw_mask is not None else default_mask))


def _discount_period(step: int, *, mid_year: bool) -> float:
    return float(step) - 0.5 if mid_year else float(step)


def _discount_projected_cash_flows(
    cash_flows: list[float],
    terminal_growth: float,
    discount_rate: float,
    *,
    mid_year: bool,
    mid_year_terminal: bool = False,
    periods_per_year: int = 1,
) -> dict[str, Any]:
    periods = max(1, int(periods_per_year or 1))
    annual_discount_rate = float(discount_rate)
    annual_terminal_growth = float(terminal_growth)
    discount_rate = annual_rate_to_period_rate(annual_discount_rate, periods)
    terminal_growth = annual_rate_to_period_rate(annual_terminal_growth, periods)
    explicit_pv = 0.0
    discount_periods: list[float] = []
    for index, cash_flow in enumerate(cash_flows, start=1):
        period = _discount_period(index, mid_year=mid_year)
        discount_periods.append(period)
        explicit_pv += cash_flow / ((1.0 + discount_rate) ** period)
    terminal_value = None
    terminal_pv = None
    total_value = None
    terminal_value_pct = None
    terminal_period = None
    if cash_flows and discount_rate > terminal_growth:
        terminal_value = cash_flows[-1] * (1.0 + terminal_growth) / (discount_rate - terminal_growth)
        terminal_period = _discount_period(len(cash_flows), mid_year=mid_year_terminal)
        terminal_pv = terminal_value / ((1.0 + discount_rate) ** terminal_period)
        total_value = explicit_pv + terminal_pv
        terminal_value_pct = terminal_pv / total_value if total_value else None
    return {
        "cash_flows": cash_flows,
        "periods": discount_periods,
        "explicit_pv": explicit_pv,
        "terminal_value": terminal_value,
        "terminal_period": terminal_period,
        "terminal_pv": terminal_pv,
        "total_value": total_value,
        "terminal_value_pct": terminal_value_pct,
        "periods_per_year": periods,
        "annual_discount_rate": annual_discount_rate,
        "annual_terminal_growth": annual_terminal_growth,
        "discount_rate_period": discount_rate,
        "terminal_growth_period": terminal_growth,
    }


def _dcf_cash_flows(
    start: float,
    growth: float,
    terminal_growth: float,
    discount_rate: float,
    years: int,
    *,
    mid_year: bool = True,
    mid_year_terminal: bool = False,
) -> tuple[list[float], float | None]:
    projected: list[float] = []
    present_value = 0.0
    current = start
    for step in range(1, years + 1):
        fade = step / max(years, 1)
        step_growth = growth * (1.0 - fade) + terminal_growth * fade
        current *= 1.0 + step_growth
        projected.append(current)
        present_value += current / ((1.0 + discount_rate) ** _discount_period(step, mid_year=mid_year))
    if not projected or discount_rate <= terminal_growth:
        return projected, None
    terminal_value = projected[-1] * (1.0 + terminal_growth) / (discount_rate - terminal_growth)
    return projected, present_value + terminal_value / ((1.0 + discount_rate) ** _discount_period(years, mid_year=mid_year_terminal))


def _fcff_dcf(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    reliability_warnings = _fcf_reliability_warnings(history)
    warnings.extend(reliability_warnings)
    fcf, fcf_source = _fcf_start(snapshot, history)
    shares = _shares(snapshot)
    if fcf is None or fcf <= 0:
        warnings.append("missing_positive_fcf")
    if not shares:
        warnings.append("missing_shares")
    wacc = float(assumptions["wacc"])
    terminal_growth = _terminal_growth_for_model(assumptions, "firm")
    if wacc <= terminal_growth:
        warnings.append("wacc_not_above_terminal_growth")
    years = int(assumptions["forecast_years"])
    growth, growth_source, growth_is_proxy = _fcf_growth_input(snapshot, history, assumptions)
    if growth_is_proxy:
        warnings.append(growth_source)
    if growth is None:
        warnings.append("missing_fcf_growth_driver")
    net_debt_bridge = _net_debt_bridge_detail(history)
    net_debt = float(net_debt_bridge["net_debt"])
    net_debt_source = str(net_debt_bridge["source"])
    net_debt_warning = bool(net_debt_bridge["warning"])
    if net_debt_warning:
        warnings.append("missing_net_debt_bridge")
    fair = None
    projected: list[float] = []
    projection = _projection_from_assumptions(assumptions)
    projection_outputs: dict[str, Any] = {}
    projection_proxy = False
    model_unavailable = False
    projection_unavailable = _projection_has_unavailable_driver(projection, FCF_PROJECTION_UNAVAILABLE_WARNINGS)
    if projection_unavailable:
        model_unavailable = True
        warnings.append("fcff_dcf_projection_driver_unavailable")
    if not projection_unavailable and projection and projection.fcff and shares and wacc > terminal_growth:
        projected = list(projection.fcff)
        warnings.extend(item for item in projection.warnings if item not in warnings)
        projection_proxy = projection.fallback
        dcf = _discount_projected_cash_flows(
            projected,
            terminal_growth,
            wacc,
            mid_year=_mid_year_discounting(assumptions),
            mid_year_terminal=_mid_year_terminal(assumptions),
            periods_per_year=projection.periods_per_year,
        )
        enterprise_value = dcf["total_value"]
        if enterprise_value is not None:
            equity_value = enterprise_value - net_debt
            if equity_value <= 0:
                fair = None
                model_unavailable = True
                warnings.append("fcf_dcf_unavailable_nonpositive_equity_value")
            else:
                fair = equity_value / shares
        final_ebitda = None
        if projection.statements:
            final_ebitda = _positive(projection.statements[-1].get("ebitda"))
        exit_multiple = dcf["terminal_value"] / final_ebitda if dcf["terminal_value"] is not None and final_ebitda else None
        if dcf["terminal_value_pct"] is not None:
            if dcf["terminal_value_pct"] > TERMINAL_VALUE_WARN_SHARE:
                warnings.append("terminal_value_above_75pct_ev")
            if dcf["terminal_value_pct"] > TERMINAL_VALUE_EXCLUSION_SHARE:
                warnings.append("terminal_value_above_85pct_ev")
        projection_outputs = {
            "projection": projection.to_dict(),
            "dcf_bridge": dcf,
            "terminal_value_pct_ev": dcf["terminal_value_pct"],
            "implied_exit_ev_to_ebitda": exit_multiple,
        }
    elif not projection_unavailable and growth is not None and fcf and fcf > 0 and shares and wacc > terminal_growth:
        projected, enterprise_value = _dcf_cash_flows(
            fcf,
            growth,
            terminal_growth,
            wacc,
            years,
            mid_year=_mid_year_discounting(assumptions),
            mid_year_terminal=_mid_year_terminal(assumptions),
        )
        if enterprise_value is not None:
            equity_value = enterprise_value - net_debt
            if equity_value <= 0:
                fair = None
                model_unavailable = True
                warnings.append("fcf_dcf_unavailable_nonpositive_equity_value")
            else:
                fair = equity_value / shares
    base = "unavailable" if model_unavailable else ("high" if len([v for v in _metric_series(history, "Free_Cash_Flow") if v > 0]) >= 3 else "medium")
    confidence = _confidence(base, warnings, proxy=projection_proxy)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="fcff_dcf",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "fcf_start": fcf,
            "fcf_source": fcf_source,
            "growth": growth,
            "fcf_growth_source": growth_source,
            "wacc": wacc,
            **_terminal_growth_input(assumptions, "firm"),
            "mid_year_discounting": _mid_year_discounting(assumptions),
            "mid_year_terminal": _mid_year_terminal(assumptions),
            "net_debt": net_debt,
            "net_debt_source": net_debt_source,
            "net_debt_bridge": net_debt_bridge,
            **_cost_of_capital_input(assumptions),
        },
        outputs={"projected_fcf": projected, "projected_fcff": projected, **projection_outputs},
        warnings=warnings,
        methodology="FCFF discounted cash flow from the shared 3-statement projection, with mid-year discounting and a net-debt bridge to equity value.",
        proxy=projection_proxy,
    )


def _fcfe_dcf(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    reliability_warnings = _fcf_reliability_warnings(history)
    warnings.extend(reliability_warnings)
    fcfe, fcfe_source, is_proxy = _fcfe_start(snapshot, history, assumptions)
    if is_proxy:
        warnings.append("fcfe_proxy_from_free_cash_flow")
    shares = _shares(snapshot)
    if fcfe is None or fcfe <= 0:
        warnings.append("missing_positive_equity_cash_flow_proxy")
    if not shares:
        warnings.append("missing_shares")
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = _terminal_growth_for_model(assumptions, "equity")
    if cost <= terminal_growth:
        warnings.append("cost_of_equity_not_above_terminal_growth")
    years = int(assumptions["forecast_years"])
    growth, growth_source, growth_is_proxy = _fcf_growth_input(snapshot, history, assumptions)
    if growth_is_proxy:
        warnings.append(growth_source)
    if growth is None:
        warnings.append("missing_fcfe_growth_driver")
    fair = None
    projected: list[float] = []
    projection = _projection_from_assumptions(assumptions)
    projection_outputs: dict[str, Any] = {}
    model_unavailable = False
    projection_unavailable = _projection_has_unavailable_driver(projection, FCF_PROJECTION_UNAVAILABLE_WARNINGS)
    if projection_unavailable:
        model_unavailable = True
        warnings.append("fcfe_dcf_projection_driver_unavailable")
    if not projection_unavailable and projection and projection.fcfe and shares and cost > terminal_growth:
        projected = list(projection.fcfe)
        warnings.extend(item for item in projection.warnings if item not in warnings)
        is_proxy = bool(is_proxy or projection.fallback)
        dcf = _discount_projected_cash_flows(
            projected,
            terminal_growth,
            cost,
            mid_year=_mid_year_discounting(assumptions),
            mid_year_terminal=_mid_year_terminal(assumptions),
            periods_per_year=projection.periods_per_year,
        )
        equity_value = dcf["total_value"]
        if equity_value is not None:
            if equity_value <= 0:
                fair = None
                model_unavailable = True
                warnings.append("fcf_dcf_unavailable_nonpositive_equity_value")
            else:
                fair = equity_value / shares
        if dcf["terminal_value_pct"] is not None:
            if dcf["terminal_value_pct"] > TERMINAL_VALUE_WARN_SHARE:
                warnings.append("terminal_value_above_75pct_equity_value")
            if dcf["terminal_value_pct"] > TERMINAL_VALUE_EXCLUSION_SHARE:
                warnings.append("terminal_value_above_85pct_equity_value")
        projection_outputs = {
            "projection": projection.to_dict(),
            "dcf_bridge": dcf,
            "terminal_value_pct_equity_value": dcf["terminal_value_pct"],
        }
    elif not projection_unavailable and growth is not None and fcfe and fcfe > 0 and shares and cost > terminal_growth:
        projected, equity_value = _dcf_cash_flows(
            fcfe,
            growth,
            terminal_growth,
            cost,
            years,
            mid_year=_mid_year_discounting(assumptions),
            mid_year_terminal=_mid_year_terminal(assumptions),
        )
        if equity_value is not None:
            if equity_value <= 0:
                fair = None
                model_unavailable = True
                warnings.append("fcf_dcf_unavailable_nonpositive_equity_value")
            else:
                fair = equity_value / shares
    base = "unavailable" if model_unavailable else ("high" if not is_proxy and len([v for v in _metric_series(history, "Free_Cash_Flow") if v > 0]) >= 3 else "medium")
    confidence = _confidence(base, warnings, proxy=is_proxy)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="fcfe_dcf",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "fcfe_start": fcfe,
            "fcfe_source": fcfe_source,
            "growth": growth,
            "fcfe_growth_source": growth_source,
            "cost_of_equity": cost,
            **_terminal_growth_input(assumptions, "equity"),
            "mid_year_discounting": _mid_year_discounting(assumptions),
            "mid_year_terminal": _mid_year_terminal(assumptions),
            **_cost_of_capital_input(assumptions),
        },
        outputs={"projected_fcfe": projected, **projection_outputs},
        warnings=warnings,
        methodology="FCFE equity DCF from the shared 3-statement projection; fallback treats positive FCF as a capped-confidence proxy.",
        proxy=is_proxy,
    )


def _ddm(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    midcycle_basis = _midcycle_basis(assumptions)
    _append_unique(warnings, _midcycle_model_warning(assumptions))
    roe, roe_source = _roe_basis(snapshot, history, assumptions)
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = _terminal_growth_for_model(assumptions, "equity")
    fade_years = max(1, int(assumptions["fade_years"]))
    h_factor = fade_years / 2.0
    if cost <= terminal_growth:
        warnings.append("cost_of_equity_not_above_terminal_growth")
    latest_dividend_total = _latest_metric(history, "Dividendes", "Clean_Dividendes")
    shares = _shares(snapshot)
    dividend_source = None
    dividend = None
    if latest_dividend_total and shares:
        dividend = latest_dividend_total / shares
        dividend_source = "reported_dividends_per_share"
    dividend_yield = _dividend_yield_ratio(snapshot.metrics.get("Dividend_Yield"))
    if dividend is None and current_price and dividend_yield and dividend_yield > 0:
        dividend = current_price * dividend_yield
        dividend_source = "dividend_yield_times_price"
    implied_dividend_yield = dividend_yield
    if implied_dividend_yield is None and dividend is not None and current_price and current_price > 0:
        implied_dividend_yield = dividend / current_price
    if implied_dividend_yield is not None and implied_dividend_yield > MAX_REASONABLE_DIVIDEND_YIELD:
        warnings.append("dividend_yield_above_plausible_range")
    projection = _projection_from_assumptions(assumptions)
    projection_unavailable = _projection_has_unavailable_driver(projection, EQUITY_PROJECTION_UNAVAILABLE_WARNINGS)
    if projection_unavailable:
        warnings.append("ddm_projection_driver_unavailable")
    if not projection_unavailable and projection and projection.dividends and shares and cost > terminal_growth and any(value > 0 for value in projection.dividends):
        warnings.extend(item for item in projection.warnings if item not in warnings and item != "cash_flow_statement_missing_driver_fallback")
        projected_per_share = [value / shares for value in projection.dividends]
        dcf = _discount_projected_cash_flows(
            projected_per_share,
            terminal_growth,
            cost,
            mid_year=_mid_year_discounting(assumptions),
            mid_year_terminal=_mid_year_terminal(assumptions),
            periods_per_year=projection.periods_per_year,
        )
        fair = dcf["total_value"]
        model_unavailable = False
        if fair is None or fair <= 0:
            fair = None
            model_unavailable = True
            warnings.append("ddm_nonpositive_value_unavailable")
        if dcf["terminal_value_pct"] is not None:
            if dcf["terminal_value_pct"] > TERMINAL_VALUE_WARN_SHARE:
                warnings.append("terminal_value_above_75pct_equity_value")
            if dcf["terminal_value_pct"] > TERMINAL_VALUE_EXCLUSION_SHARE:
                warnings.append("terminal_value_above_85pct_equity_value")
        confidence = _confidence("unavailable" if model_unavailable else ("high" if latest_dividend_total and shares else "medium"), warnings)
        return _result(
            snapshot=snapshot,
            scenario=scenario,
            model="ddm",
            fair_value=fair,
            current_price=current_price,
            confidence=confidence,
            inputs={
                "dividend_per_share": dividend,
                "dividend_source": dividend_source or "shared_projection_dividends",
                "reported_dividend_total": latest_dividend_total,
                "shares": shares,
                "dividend_yield": dividend_yield,
                "roe": roe,
                "roe_source": roe_source,
                "normalized_earnings_basis": midcycle_basis,
                "cost_of_equity": cost,
                **_terminal_growth_input(assumptions, "equity"),
                "mid_year_discounting": _mid_year_discounting(assumptions),
                "mid_year_terminal": _mid_year_terminal(assumptions),
                **_cost_of_capital_input(assumptions),
            },
            outputs={
                "projected_dividends_per_share": projected_per_share,
                "projected_dividends": projection.dividends,
                "dcf_bridge": dcf,
                "terminal_value_pct_equity_value": dcf["terminal_value_pct"],
                "projection": projection.to_dict(),
                "normalized_earnings_basis": midcycle_basis,
            },
            warnings=warnings,
            methodology="Dividend discount model using projected dividends from the shared operating projection.",
        )
    if dividend is None or dividend <= 0:
        warnings.append("missing_positive_dividend")
    growth, growth_source, growth_warnings, roe, roe_source = _sustainable_dividend_growth(snapshot, history, assumptions)
    warnings.extend(item for item in growth_warnings if item not in warnings)
    if growth is None:
        warnings.append("ddm_growth_unavailable")
    elif growth < terminal_growth:
        warnings.append("ddm_growth_below_terminal")
    spread = max(0.0, growth - terminal_growth) if growth is not None else 0.0
    fair = (
        dividend * ((1.0 + terminal_growth) + h_factor * spread) / (cost - terminal_growth)
        if dividend and growth is not None and cost > terminal_growth
        else None
    )
    model_unavailable = False
    if fair is None or fair <= 0:
        fair = None
        model_unavailable = True
        warnings.append("ddm_nonpositive_value_unavailable")
    confidence = _confidence("unavailable" if model_unavailable else ("high" if latest_dividend_total and shares else "medium"), warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="ddm",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "dividend_per_share": dividend,
            "dividend_source": dividend_source,
            "reported_dividend_total": latest_dividend_total,
            "shares": shares,
            "dividend_yield": dividend_yield,
            "growth": growth,
            "growth_source": growth_source,
            "roe": roe,
            "roe_source": roe_source,
            "normalized_earnings_basis": midcycle_basis,
            "cost_of_equity": cost,
            **_terminal_growth_input(assumptions, "equity"),
            "fade_years": fade_years,
            "h_factor": h_factor,
            **_cost_of_capital_input(assumptions),
        },
        outputs={"normalized_earnings_basis": midcycle_basis} if midcycle_basis else {},
        warnings=warnings,
        methodology="H-model dividend discount model for dividend-paying stocks.",
    )


def _residual_income(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str, is_financial: bool) -> ValuationResult:
    warnings: list[str] = []
    midcycle_basis = _midcycle_basis(assumptions)
    _append_unique(warnings, _midcycle_model_warning(assumptions))
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = _terminal_growth_for_model(assumptions, "equity")
    fade_years = max(1, int(assumptions["fade_years"]))
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
        warnings.append("using_stable_payout_assumption")
    retention = max(0.0, min(1.0, 1.0 - payout))
    pb = _positive(snapshot.metrics.get("Price_to_Book"))
    if pb is not None and pb < MIN_REASONABLE_PRICE_TO_BOOK:
        warnings.append("price_to_book_below_plausible_range")
    roe, roe_source = _roe_basis(snapshot, history, assumptions)
    book_value = current_price / pb if current_price and pb else None
    if midcycle_basis and midcycle_basis.get("status") == "available":
        if book_value is None and midcycle_basis.get("current_book_equity") is not None and midcycle_basis.get("shares"):
            book_value = float(midcycle_basis["current_book_equity"]) / float(midcycle_basis["shares"])
    projection = _projection_from_assumptions(assumptions)
    shares = _shares(snapshot)
    observed_book_value = _latest_metric(history, *EQUITY_ALIASES) is not None
    net_income_points = len(_metric_series_any(history, *NET_INCOME_ALIASES))
    projection_unavailable = _projection_has_unavailable_driver(projection, EQUITY_PROJECTION_UNAVAILABLE_WARNINGS)
    if projection_unavailable:
        warnings.append("residual_income_projection_driver_unavailable")
    financial_archetype = str(assumptions.get("_financial_archetype") or "").lower()
    projection_warnings = set(str(warning) for warning in (projection.warnings if projection else []))
    if is_financial and financial_archetype == "bank" and projection_warnings & STRICT_BANK_PROJECTION_UNAVAILABLE_WARNINGS:
        strict_reason = sorted(projection_warnings & STRICT_BANK_PROJECTION_UNAVAILABLE_WARNINGS)[0]
        return _result(
            snapshot=snapshot,
            scenario=scenario,
            model="residual_income",
            fair_value=None,
            current_price=current_price,
            confidence="unavailable",
            inputs={
                "roe": roe,
                "roe_source": roe_source,
                "cost_of_equity": cost,
                **_terminal_growth_input(assumptions, "equity"),
                "financial_archetype": financial_archetype,
                **_cost_of_capital_input(assumptions),
            },
            outputs={"projection": projection.to_dict() if projection else None},
            warnings=[*warnings, strict_reason],
            methodology="Residual income unavailable because the bank projection is missing an observed or peer-derived required driver.",
        )
    if projection and projection.statements and projection.book_values and shares and cost > 0:
        warnings.extend(item for item in projection.warnings if item not in warnings and item != "cash_flow_statement_missing_driver_fallback")
        periods_per_year = max(1, int(projection.periods_per_year or 1))
        cost_period = annual_rate_to_period_rate(cost, periods_per_year)
        terminal_growth_period = annual_rate_to_period_rate(terminal_growth, periods_per_year)
        first = projection.statements[0]
        beginning_equity = (
            float(first.get("total_equity") or 0.0)
            - float(first.get("net_income") or 0.0)
            + float(first.get("dividends") or 0.0)
        )
        book_value = beginning_equity / shares if beginning_equity > 0 else book_value
        projected: list[dict[str, float]] = []
        pv_residual_income = 0.0
        previous_equity = beginning_equity
        for index, statement in enumerate(projection.statements, start=1):
            net_income = float(statement.get("net_income") or 0.0)
            residual_income = net_income - cost_period * previous_equity
            period = _discount_period(index, mid_year=_mid_year_discounting(assumptions))
            pv_residual_income += residual_income / ((1.0 + cost_period) ** period)
            ending_equity = float(statement.get("total_equity") or previous_equity)
            roe_path = net_income / previous_equity if previous_equity else 0.0
            projected.append(
                {
                    "year": float(statement.get("fiscal_year") or index),
                    "period_index": float(statement.get("period_index") or 0.0),
                    "roe": roe_path,
                    "book_value": ending_equity / shares,
                    "residual_income": residual_income / shares,
                }
            )
            previous_equity = ending_equity
        terminal_residual_pv = 0.0
        if projection.statements and cost_period > terminal_growth_period and previous_equity > 0:
            final = projection.statements[-1]
            final_roe = float(final.get("net_income") or 0.0) / max(previous_equity, 1.0)
            terminal_residual = previous_equity * (final_roe - cost_period) * (1.0 + terminal_growth_period) / (cost_period - terminal_growth_period)
            terminal_residual_pv = terminal_residual / ((1.0 + cost_period) ** _discount_period(len(projection.statements), mid_year=_mid_year_terminal(assumptions)))
        if book_value is not None:
            raw_fair = book_value + (pv_residual_income + terminal_residual_pv) / shares
            model_unavailable = projection_unavailable or raw_fair <= 0
            fair = None if model_unavailable else raw_fair
            if raw_fair <= 0:
                warnings.append("residual_income_nonpositive_value_unavailable")
            base_confidence = _residual_income_base_confidence(
                book_value=book_value,
                roe=None,
                observed_book_value=observed_book_value,
                net_income_points=net_income_points,
                warnings=warnings,
                model_unavailable=model_unavailable,
            )
            confidence = _confidence(base_confidence, warnings)
            return _result(
                snapshot=snapshot,
                scenario=scenario,
                model="residual_income",
                fair_value=fair,
                current_price=current_price,
                confidence=confidence,
                inputs={
                    "book_value_per_share": book_value,
                    "roe": roe,
                    "roe_source": roe_source,
                    "cost_of_equity": cost,
                    **_terminal_growth_input(assumptions, "equity"),
                    "periods_per_year": periods_per_year,
                    "cost_of_equity_period": cost_period,
                    "terminal_growth_period": terminal_growth_period,
                    "payout": payout,
                    "normalized_earnings_basis": midcycle_basis,
                    "mid_year_discounting": _mid_year_discounting(assumptions),
                    "mid_year_terminal": _mid_year_terminal(assumptions),
                    **_cost_of_capital_input(assumptions),
                },
                outputs={
                    "projected_residual_income": projected,
                    "terminal_residual_income_pv": terminal_residual_pv / shares,
                    "projection": projection.to_dict(),
                    "normalized_earnings_basis": midcycle_basis,
                },
                warnings=warnings,
                methodology="Residual income model using projected book value and net income from the shared operating projection.",
            )
    if book_value is None:
        warnings.append("missing_book_value_proxy")
    if roe is None:
        warnings.append("missing_roe")
    if is_financial and financial_archetype == "bank" and projection_unavailable and "bank_pnb_unavailable_no_history_no_peer" in projection_warnings:
        warnings.append("bank_projection_unavailable_using_pb_roe_fallback")
    fair = None
    projected: list[dict[str, float]] = []
    if book_value and roe is not None and cost > 0:
        book = book_value
        pv_residual_income = 0.0
        for year in range(1, fade_years + 2):
            fade = (year - 1) / fade_years
            year_roe = roe * (1.0 - fade) + cost * fade
            residual_income = book * (year_roe - cost)
            pv_residual_income += residual_income / ((1.0 + cost) ** year)
            projected.append({"year": float(year), "roe": year_roe, "book_value": book, "residual_income": residual_income})
            book *= 1.0 + year_roe * retention
        raw_fair = book_value + pv_residual_income
        if raw_fair <= 0:
            warnings.append("residual_income_nonpositive_value_unavailable")
        else:
            fair = raw_fair
    model_unavailable = fair is None and "residual_income_nonpositive_value_unavailable" in warnings
    base_confidence = _residual_income_base_confidence(
        book_value=book_value,
        roe=roe,
        observed_book_value=observed_book_value,
        net_income_points=net_income_points,
        warnings=warnings,
        model_unavailable=model_unavailable,
    )
    confidence = _confidence(base_confidence, warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="residual_income",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "book_value_per_share": book_value,
            "roe": roe,
            "roe_source": roe_source,
            "normalized_earnings_basis": midcycle_basis,
            "cost_of_equity": cost,
            **_terminal_growth_input(assumptions, "equity"),
            "fade_years": fade_years,
            "payout": payout,
            **_cost_of_capital_input(assumptions),
        },
        outputs={"projected_residual_income": projected, "normalized_earnings_basis": midcycle_basis},
        warnings=warnings,
        methodology="Residual income model with ROE spread fading linearly to cost of equity over the competitive erosion horizon.",
    )


def _justified_multiples(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    current_price: float | None,
    assumptions: dict[str, Any],
    scenario: str,
    is_financial: bool,
) -> ValuationResult:
    warnings: list[str] = []
    midcycle_basis = _midcycle_basis(assumptions)
    _append_unique(warnings, _midcycle_model_warning(assumptions))
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = _terminal_growth_for_model(assumptions, "equity")
    fade_years = int(assumptions["fade_years"])
    roe, roe_source = _normalized_roe(snapshot, history, assumptions)
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
        warnings.append("using_stable_payout_assumption")
    retention = max(0.0, min(1.0, 1.0 - payout))
    sustainable_growth = max(-0.05, (roe or 0.0) * retention)
    growth = _justified_growth(sustainable_growth, terminal_growth, fade_years)
    if cost <= growth:
        buffer = max(
            0.0,
            float(assumptions.get("terminal_growth_discount_buffer", DEFAULT_ASSUMPTIONS["terminal_growth_discount_buffer"])),
        )
        growth = max(terminal_growth, cost - buffer)
        warnings.append("justified_growth_capped_below_cost_of_equity")
    if cost <= growth:
        warnings.append("cost_of_equity_not_above_justified_growth")
    implied_prices: dict[str, float] = {}
    implied_prices_raw: dict[str, float] = {}
    justified_multiples: dict[str, float] = {}
    multiple_deltas: dict[str, float] = {}
    selected_ratio_keys = _selected_ratio_keys(assumptions, "justified_multiple_ratio_mask", JUSTIFIED_MULTIPLE_RATIO_BITS)
    if current_price and cost > growth:
        pb = _positive(snapshot.metrics.get("Price_to_Book"))
        if "justified_pb" in selected_ratio_keys and roe is not None and pb:
            justified_pb = max(0.0, (roe - growth) / (cost - growth))
            if justified_pb > 0:
                raw = current_price * justified_pb / pb
                implied_prices_raw["justified_pb"] = raw
                implied_prices["justified_pb"] = raw
                justified_multiples["implied_pb"] = justified_pb
                multiple_deltas["implied_pb_vs_current"] = justified_pb / pb - 1.0
        per = _positive(snapshot.metrics.get("PER"))
        if "justified_pe" in selected_ratio_keys and per and payout > 0:
            justified_pe = payout * (1.0 + growth) / (cost - growth)
            if justified_pe > 0:
                raw = current_price * justified_pe / per
                implied_prices_raw["justified_pe"] = raw
                implied_prices["justified_pe"] = raw
                justified_multiples["implied_pe"] = justified_pe
                multiple_deltas["implied_pe_vs_current"] = justified_pe / per - 1.0
    if not selected_ratio_keys:
        warnings.append("all_justified_multiples_excluded")
    if not implied_prices:
        warnings.append("no_usable_justified_multiple")
    fair = float(median(implied_prices.values())) if implied_prices else None
    base = "high" if len(implied_prices) >= 2 else ("medium" if implied_prices else "unavailable")
    confidence = _confidence(base, warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="justified_multiples",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "roe": roe,
            "roe_source": roe_source,
            "normalized_earnings_basis": midcycle_basis,
            "payout": payout,
            "sustainable_growth": sustainable_growth,
            "growth": growth,
            **_terminal_growth_input(assumptions, "equity"),
            "fade_years": fade_years,
            "cost_of_equity": cost,
            "selected_ratio_keys": sorted(selected_ratio_keys),
            "justified_multiple_ratio_mask": _assumption_int_mask(assumptions, "justified_multiple_ratio_mask"),
            **_cost_of_capital_input(assumptions),
        },
        outputs={
            "implied_prices": implied_prices,
            "implied_prices_raw": implied_prices_raw,
            "justified_multiples": justified_multiples,
            "multiple_deltas": multiple_deltas,
            "normalized_earnings_basis": midcycle_basis,
        },
        warnings=warnings,
        methodology="Justified P/B and P/E from ROE, payout, growth, and cost of equity.",
        family="relative",
    )


def _relative_multiples(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    current_price: float | None,
    peer_stats: dict[str, dict[str, Any]],
    assumptions: dict[str, Any],
    scenario: str,
    is_financial: bool = False,
) -> ValuationResult:
    warnings: list[str] = []
    midcycle_basis = _midcycle_basis(assumptions)
    cyclical_context = bool(assumptions.get("_cyclical_commodity"))
    _append_unique(warnings, _midcycle_model_warning(assumptions))
    implied: dict[str, float] = {}
    implied_raw: dict[str, float] = {}
    own_multiple_basis: dict[str, str] = {}
    own_multiples: dict[str, float | None] = {}
    ev_to_ebitda_bridge: dict[str, Any] = {}
    selected_ratio_keys = _selected_ratio_keys(assumptions, "relative_multiple_ratio_mask", RELATIVE_MULTIPLE_RATIO_BITS)
    if is_financial:
        selected_ratio_keys = {"PER", "Price_to_Book"}
        own_pnb_multiple = _positive(snapshot.metrics.get("Price_to_PNB")) or _positive(snapshot.metrics.get("P_to_PNB"))
        peer_pnb_multiple = _positive(peer_stats.get("Price_to_PNB", {}).get("median"))
        if own_pnb_multiple is not None and peer_pnb_multiple is not None:
            selected_ratio_keys.add("Price_to_PNB")
    capex_heavy_context = bool(_fcf_reliability_warnings(history))
    projection = _projection_from_assumptions(assumptions)
    if current_price is None:
        warnings.append("missing_current_price")
    else:
        flow_metrics = ("PER", "Price_to_Book") if is_financial else ("PER", "Price_to_Book", "Price_to_Sales")
        for metric in flow_metrics:
            if metric not in selected_ratio_keys:
                continue
            own, basis = _normalized_flow_multiple(snapshot, history, metric, current_price, assumptions)
            own_multiple_basis[metric] = basis
            own_multiples[metric] = own
            if basis == "spot_fallback" and "relative_own_multiple_spot_fallback" not in warnings:
                warnings.append("relative_own_multiple_spot_fallback")
            peer = _positive(peer_stats.get(metric, {}).get("median"))
            if own and peer:
                raw = current_price * peer / own
                implied_raw[metric] = raw
                implied[metric] = raw
        if is_financial and "Price_to_PNB" in selected_ratio_keys:
            own_pnb = _positive(snapshot.metrics.get("Price_to_PNB")) or _positive(snapshot.metrics.get("P_to_PNB"))
            peer_pnb = _positive(peer_stats.get("Price_to_PNB", {}).get("median"))
            own_multiples["Price_to_PNB"] = own_pnb
            own_multiple_basis["Price_to_PNB"] = "spot"
            if own_pnb and peer_pnb:
                raw = current_price * peer_pnb / own_pnb
                implied_raw["Price_to_PNB"] = raw
                implied["Price_to_PNB"] = raw
        if not is_financial and "EV_to_EBITDA" in selected_ratio_keys:
            peer_ev_ebitda = _positive(peer_stats.get("EV_to_EBITDA", {}).get("median"))
            own_ev_ebitda = _positive(snapshot.metrics.get("EV_to_EBITDA"))
            own_multiples["EV_to_EBITDA"] = own_ev_ebitda
            own_multiple_basis["EV_to_EBITDA"] = "spot"
            if peer_ev_ebitda and own_ev_ebitda:
                ebitda = _latest_metric(history, *EBITDA_ALIASES) or _positive(snapshot.metrics.get("EBITDA"))
                if (
                    cyclical_context
                    and midcycle_basis
                    and midcycle_basis.get("status") == "available"
                    and midcycle_basis.get("normalized_ebitda") is not None
                ):
                    ebitda = float(midcycle_basis["normalized_ebitda"])
                    warnings.append("ev_ebitda_uses_midcycle_ebitda")
                elif capex_heavy_context and projection is not None and projection.statements:
                    normalized_ebitda = _positive(projection.statements[-1].get("ebitda"))
                    if normalized_ebitda is not None:
                        ebitda = normalized_ebitda
                        warnings.append("ev_ebitda_uses_normalized_projection_ebitda")
                net_debt_bridge = _net_debt_bridge_detail(history)
                net_debt = float(net_debt_bridge["net_debt"])
                net_debt_warning = bool(net_debt_bridge["warning"])
                shares = _shares(snapshot)
                ev_to_ebitda_bridge = {
                    "ebitda": ebitda,
                    "net_debt": net_debt,
                    "net_debt_source": net_debt_bridge["source"],
                    "net_debt_bridge": net_debt_bridge,
                    "shares": shares,
                }
                if ebitda and shares and not net_debt_warning:
                    equity_value = peer_ev_ebitda * ebitda - net_debt
                    if equity_value <= 0:
                        warnings.append("ev_to_ebitda_nonpositive_value_unavailable")
                    else:
                        raw = equity_value / shares
                        implied_raw["EV_to_EBITDA"] = raw
                        implied["EV_to_EBITDA"] = raw
                else:
                    warnings.append("ev_multiple_skipped_missing_bridge")
        if not selected_ratio_keys:
            warnings.append("all_relative_multiples_excluded")
        if not implied:
            warnings.append("no_usable_peer_multiple")
        thin_sector_metrics = [m for m, s in peer_stats.items() if m in selected_ratio_keys and s.get("scope") == "market"]
        if thin_sector_metrics and "relative_peers_thin_sector_market_fallback" not in warnings:
            warnings.append("relative_peers_thin_sector_market_fallback")
        thin_count_metrics = [m for m, s in peer_stats.items() if m in selected_ratio_keys and (s.get("count") or 0) < 5]
        if thin_count_metrics and "relative_peers_count_below_5" not in warnings:
            warnings.append("relative_peers_count_below_5")
    fair = float(median(implied.values())) if implied else None
    confidence = "high" if len(implied) >= 3 else ("medium" if len(implied) >= 2 else ("low" if implied else "unavailable"))
    confidence = _confidence(confidence, warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="relative_multiples",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "peer_stats": peer_stats,
            "peer_scope": {m: s.get("scope") for m, s in peer_stats.items()},
            "peer_count": {m: s.get("count") for m, s in peer_stats.items()},
            "own_multiples": own_multiples or {m: snapshot.metrics.get(m) for m in peer_stats},
            "own_multiple_basis": own_multiple_basis,
            "ev_to_ebitda_bridge": ev_to_ebitda_bridge,
            "selected_ratio_keys": sorted(selected_ratio_keys),
            "relative_multiple_ratio_mask": _assumption_int_mask(assumptions, "relative_multiple_ratio_mask"),
            "financial_ratio_set": "P/B + P/E + P/PNB when observed peer data exists" if is_financial else None,
            "normalized_earnings_basis": midcycle_basis,
        },
        outputs={
            "implied_prices": implied,
            "implied_prices_raw": implied_raw,
            "normalized_earnings_basis": midcycle_basis,
        },
        warnings=warnings,
        methodology=(
            "Financial peer-relative valuation using P/B and P/E, plus P/PNB only when observed peer data exists."
            if is_financial
            else "Peer-relative valuation using sector medians when enough peers exist, otherwise market medians."
        ),
        family="relative",
    )


def _reverse_dcf(snapshot: FundamentalSnapshot, current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    market_cap = _market_cap(snapshot)
    fcf_yield = _ratio(snapshot.metrics.get("FCF_Yield"))
    implied = None
    if fcf_yield and fcf_yield > 0:
        implied = float(assumptions["wacc"]) - fcf_yield
    else:
        warnings.append("missing_fcf_yield_for_reverse_dcf")
    confidence = _confidence("medium" if market_cap and current_price else "unavailable", warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="reverse_dcf",
        fair_value=None,
        current_price=current_price,
        confidence=confidence,
        inputs={"market_cap": market_cap, "fcf_yield": fcf_yield, "wacc": assumptions["wacc"], **_cost_of_capital_input(assumptions)},
        outputs={
            "implied_perpetual_growth": implied,
            "interpretation": (
                f"Market implies {implied * 100:.1f}% perpetual FCF growth at WACC={float(assumptions['wacc']) * 100:.1f}%."
                if implied is not None
                else None
            ),
        },
        warnings=warnings,
        methodology="Reverse DCF diagnostic. fair_value is intentionally empty; primary output is implied_perpetual_growth.",
        family="diagnostic",
    )


def _unavailable(snapshot: FundamentalSnapshot, scenario: str, model: str, current_price: float | None, reason: str) -> ValuationResult:
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model=model,
        fair_value=None,
        current_price=current_price,
        confidence="unavailable",
        inputs={},
        outputs={},
        warnings=[reason],
        methodology="Model not run because eligibility rules were not satisfied.",
    )


def _integrity_warning(report: IntegrityReport) -> str | None:
    status = report.overall_status
    if status == "pass":
        return None
    failed = [
        check.name
        for check in report.checks
        if check.status in {"fail", "warn", "derived", "unavailable"}
    ]
    suffix = ",".join(failed) if failed else "all_checks_unavailable"
    if status == "fail":
        return f"integrity_fail: {suffix}"
    if status == "warn":
        return f"integrity_warn: {suffix}"
    if status == "derived":
        return f"integrity_derived_cash: {suffix}"
    return "integrity_unavailable"


def _apply_integrity_report(results: list[ValuationResult], report: IntegrityReport | None) -> list[ValuationResult]:
    if report is None or report.overall_status == "pass":
        return results
    haircut = max(0.0, min(0.5, float(report.confidence_haircut or 0.0)))
    warning = _integrity_warning(report)
    adjusted: list[ValuationResult] = []
    for row in results:
        confidence_score = row.confidence_score
        data_quality_score = row.data_quality_score
        if confidence_score is not None:
            confidence_score = max(0.0, confidence_score * (1.0 - haircut))
        if data_quality_score is not None:
            data_quality_score = max(0.0, data_quality_score * (1.0 - haircut))
        warnings = list(row.warnings)
        if warning and warning not in warnings:
            warnings.append(warning)
        adjusted.append(
            replace(
                row,
                warnings=warnings,
                confidence_score=confidence_score,
                data_quality_score=data_quality_score,
                is_proxy=True if report.overall_status == "fail" else row.is_proxy,
            )
        )
    return adjusted


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def _monte_carlo_band(
    usable: list[tuple[ValuationResult, float]],
    total_weight: float,
    *,
    seed: str,
    samples: int = 500,
    shock_correlation: float = MODEL_SHOCK_CORRELATION,
) -> tuple[float | None, float | None, float | None]:
    if not usable or total_weight <= 0:
        return None, None, None
    rng = Random(seed)
    rho = max(0.0, min(0.99, float(shock_correlation)))
    idio_scale = sqrt(max(0.0, 1.0 - rho * rho))
    draws: list[float] = []
    for _ in range(samples):
        common_z = rng.gauss(0.0, 1.0)
        fair = 0.0
        for row, weight in usable:
            if row.fair_value is None:
                continue
            confidence = row.confidence_score if row.confidence_score is not None else CONFIDENCE_TO_SCORE.get(row.confidence, 0.0)
            sigma = max(0.03, (1.0 - confidence) * 0.18)
            shock_z = rho * common_z + idio_scale * rng.gauss(0.0, 1.0)
            shocked = max(0.0, float(row.fair_value) * (1.0 + shock_z * sigma))
            fair += shocked * weight
        draws.append(fair / total_weight)
    return _percentile(draws, 0.05), _percentile(draws, 0.50), _percentile(draws, 0.95)


def _reject_cross_model_outliers(rows: list[ValuationResult]) -> tuple[list[ValuationResult], list[str]]:
    if not rows:
        return [], []
    warnings: list[str] = []

    def method_class(model: str) -> str:
        if model in ENSEMBLE_MARKET_METHOD_MODELS:
            return "market"
        if model in ENSEMBLE_INTRINSIC_METHOD_MODELS:
            return "intrinsic"
        return f"other:{model}"

    grouped: dict[str, list[ValuationResult]] = {}
    for row in rows:
        grouped.setdefault(method_class(row.model), []).append(row)

    survivors: list[ValuationResult] = []
    for class_rows in grouped.values():
        values = [
            float(row.fair_value)
            for row in class_rows
            if row.fair_value is not None and isfinite(float(row.fair_value))
        ]
        if len(values) < 3:
            survivors.extend(class_rows)
            continue
        center = float(median(values))
        if center <= 0:
            survivors.extend(class_rows)
            continue
        deviations = [abs(value - center) for value in values]
        mad = float(median(deviations))
        if mad <= 0:
            survivors.extend(class_rows)
            continue
        radius = float(DEFAULT_ASSUMPTIONS["ensemble_outlier_mad_k"]) * 1.4826 * mad
        lower = center - radius
        upper = center + radius
        for row in class_rows:
            value = float(row.fair_value) if row.fair_value is not None else None
            if value is None or not isfinite(value) or value < lower or value > upper:
                warnings.append(f"{row.model}_excluded_cross_model_outlier")
                continue
            survivors.append(row)
    return survivors, warnings


def _model_observed_input_fraction(row: ValuationResult) -> float:
    warnings = [str(warning).lower() for warning in row.warnings]
    penalty_count = sum(
        1
        for warning in warnings
        if any(token in warning for token in NON_OBSERVED_INPUT_WARNING_TOKENS)
    )
    fraction = max(0.0, 1.0 - min(0.80, 0.15 * penalty_count))
    if row.is_proxy:
        fraction = min(fraction, 0.50)
    return max(0.0, min(1.0, fraction))


# Structural low-information flags not captured by the generic NON_OBSERVED tokens
# (those catch proxy/peer_median/fallback/assumption/missing/unavailable). These are
# brief-44 mechanisms that depress a model without tripping a generic token.
RELIABILITY_STRUCTURAL_PENALTY_TOKENS = (
    "relative_peers_count_below_5",
    "terminal_value_above_75pct",
    "midcycle_normalization_thin_history",
    "cyclical_trough_unnormalized",
)
# Flags whose shared presence across a majority of usable models indicates the models
# agree only because they consumed the same low-information input — agreement that
# masks a shared bias rather than confirming the number (brief 44 RC-E).
SHARED_BIAS_FLAG_TOKENS = (
    "midcycle_",
    "_fallback",
    "earnings_growth_proxy",
    "relative_peers_",
    "terminal_value_above_75pct",
    "cyclical_trough_unnormalized",
)


def _model_reliability(row: ValuationResult) -> float:
    """Per-result reliability multiplier in [floor, 1].

    Starts from the observed-input fraction (generic non-observed tokens + proxy) and
    applies a multiplicative penalty per structural low-information flag. Floored so a
    low-information model is down-weighted, never silently zero-weighted — exclusion is
    reserved for the severe-warning gate (brief 44 §4).
    """
    reliability = _model_observed_input_fraction(row)
    warnings = [str(w).lower() for w in row.warnings]
    structural = sum(
        1
        for token in RELIABILITY_STRUCTURAL_PENALTY_TOKENS
        if any(token in warning for warning in warnings)
    )
    if structural:
        penalty = float(DEFAULT_ASSUMPTIONS["ensemble_reliability_structural_flag_penalty"])
        reliability *= penalty ** structural
    floor = float(DEFAULT_ASSUMPTIONS["ensemble_reliability_floor"])
    return max(floor, min(1.0, reliability))


def _shared_low_information_bias(rows: list[ValuationResult]) -> str | None:
    """Return the first low-information flag shared by a majority of *rows*, else None."""
    if not rows:
        return None
    majority = float(DEFAULT_ASSUMPTIONS["headline_review_shared_flag_majority"])
    total = len(rows)
    for token in SHARED_BIAS_FLAG_TOKENS:
        hits = sum(
            1 for row in rows if any(token in str(warning).lower() for warning in row.warnings)
        )
        if hits / total > majority:
            return token
    return None


def _reliability_weighted_value(pairs: list[tuple[float, float]]) -> float | None:
    """Weighted mean of (value, reliability) pairs; falls back to plain mean."""
    usable = [(value, weight) for value, weight in pairs if isfinite(value) and weight > 0]
    if not usable:
        return None
    total = sum(weight for _value, weight in usable)
    if total <= 0:
        return float(mean([value for value, _weight in usable]))
    return sum(value * weight for value, weight in usable) / total


def _confidence_weight(key: str, total: float) -> float:
    value = max(0.0, float(DEFAULT_ASSUMPTIONS[key]))
    return value / total if total > 0 else 0.0


def _ensemble_confidence_components(
    usable_rows: list[ValuationResult],
    values: list[float],
) -> tuple[float, float | None, float]:
    target_models = max(1.0, float(DEFAULT_ASSUMPTIONS["ensemble_confidence_target_models"]))
    coverage = min(1.0, len(usable_rows) / target_models)
    robust_cv, agreement = _dispersion_stats(values)
    data_quality = mean([_model_observed_input_fraction(row) for row in usable_rows]) if usable_rows else 0.0
    weight_total = (
        max(0.0, float(DEFAULT_ASSUMPTIONS["ensemble_confidence_weight_coverage"]))
        + max(0.0, float(DEFAULT_ASSUMPTIONS["ensemble_confidence_weight_agreement"]))
        + max(0.0, float(DEFAULT_ASSUMPTIONS["ensemble_confidence_weight_data_quality"]))
    )
    confidence = (
        _confidence_weight("ensemble_confidence_weight_coverage", weight_total) * coverage
        + _confidence_weight("ensemble_confidence_weight_agreement", weight_total) * agreement
        + _confidence_weight("ensemble_confidence_weight_data_quality", weight_total) * data_quality
    )
    return max(0.0, min(1.0, confidence)), robust_cv, agreement


ENSEMBLE_WEIGHT_OVERRIDE_PREFIX = "ensemble_weight_"


def _ensemble_weight_overrides_from_assumptions(assumptions: Any) -> dict[str, float] | None:
    """Extract user-defined per-model ensemble weights from an assumptions mapping.

    Accepts either an explicit ``_ensemble_weight_overrides`` dict or individual
    ``ensemble_weight_<model>`` scalar keys (which flow through the desk/per-symbol
    assumption-override system). Only positive weights are kept.
    """
    if not isinstance(assumptions, dict):
        return None
    overrides: dict[str, float] = {}
    explicit = assumptions.get("_ensemble_weight_overrides")
    if isinstance(explicit, dict):
        for model, weight in explicit.items():
            value = _num(weight)
            if value is not None and value > 0:
                overrides[str(model)] = float(value)
    for key, weight in assumptions.items():
        if isinstance(key, str) and key.startswith(ENSEMBLE_WEIGHT_OVERRIDE_PREFIX):
            value = _num(weight)
            if value is not None and value > 0:
                overrides[key[len(ENSEMBLE_WEIGHT_OVERRIDE_PREFIX):]] = float(value)
    return overrides or None


def compute_valuation_ensemble(
    symbol: str,
    scenario: str,
    valuations: list[ValuationResult],
    *,
    weight_overrides: dict[str, float] | None = None,
) -> EnsembleResult:
    candidates: list[ValuationResult] = []
    warnings: list[str] = []
    currencies = {row.currency for row in valuations if row.currency}
    currency = sorted(currencies)[0] if currencies else DEFAULT_CURRENCY
    integrity_failed = any(any(str(warning).startswith("integrity_fail") for warning in row.warnings) for row in valuations)
    if len(currencies) > 1:
        warnings.append("mixed_model_currencies")
    for result in valuations:
        if result.family == "diagnostic":
            continue
        if result.fair_value is None or result.current_price is None or result.confidence not in {"high", "medium", "low"}:
            continue
        severe_exclusion_reason = _severe_valuation_exclusion_reason(result)
        if severe_exclusion_reason is not None:
            warnings.append(f"{result.model}_{severe_exclusion_reason}")
            continue
        candidates.append(result)
    current_price = next((row.current_price for row in valuations if row.current_price), None)
    usable_rows, outlier_warnings = _reject_cross_model_outliers(candidates)
    warnings.extend(outlier_warnings)
    if not usable_rows:
        return EnsembleResult(
            symbol=symbol,
            scenario=scenario,
            fair_value_low=None,
            fair_value_base=None,
            fair_value_high=None,
            current_price=current_price,
            upside_pct=None,
            confidence_score=None,
            usable_model_count=0,
            excluded_model_count=len(valuations),
            model_weights={},
            warnings=[*warnings, "no_usable_valuation_models"],
            currency=currency,
            fair_value_mean=None,
            model_dispersion_cv=None,
            dispersion_factor=None,
        )
    values = sorted(float(row.fair_value) for row in usable_rows if row.fair_value is not None)
    # Per-result reliability (brief 44 §4): down-weights low-information models so a
    # thin comp or a normalization-flagged DCF cannot swing the headline. Keyed by id()
    # because ValuationResult is unhashable / equal rows are legitimately distinct.
    reliability_by_row = {id(row): _model_reliability(row) for row in usable_rows}
    class_pairs: dict[str, list[tuple[float, float]]] = {"intrinsic": [], "market": []}
    for row in usable_rows:
        if row.fair_value is None:
            continue
        pair = (float(row.fair_value), reliability_by_row[id(row)])
        if row.model in ENSEMBLE_MARKET_METHOD_MODELS:
            class_pairs["market"].append(pair)
        elif row.model in ENSEMBLE_INTRINSIC_METHOD_MODELS:
            class_pairs["intrinsic"].append(pair)
        else:
            class_pairs.setdefault(f"other:{row.model}", []).append(pair)
    class_representatives = [
        rep
        for key in [*("intrinsic", "market"), *sorted(k for k in class_pairs if k not in {"intrinsic", "market"})]
        if class_pairs.get(key) and (rep := _reliability_weighted_value(class_pairs[key])) is not None
    ]
    fair_mean = float(mean(values))

    # ── IC-shrunk ensemble weighting ──────────────────────────────────────────
    # Load pilot-estimated IC weights.  Fall back to equal-weight if:
    #   (a) no config file, or (b) no positive-IC model is available for this stock
    #   (coverage-preserving fallback so no symbol goes N/R).
    ic_cfg = _load_ic_weights()
    positive_ic_rows = [
        row for row in usable_rows
        if ic_cfg and ic_cfg.get(row.model, 0.0) > 0.0 and row.fair_value is not None
    ]
    _use_ic_weights = ic_cfg is not None and len(positive_ic_rows) > 0

    # User-defined weights take precedence over auto (IC / reliability) weighting — the
    # optimal model weighting is a desk judgment, not a provable constant. Overrides apply
    # only to the usable set (post data-quality exclusion), so a user cannot force a
    # severely-flagged or cross-model-outlier model back into the headline.
    manual_rows = (
        [
            (row, max(0.0, float(weight_overrides.get(row.model, 0.0))))
            for row in usable_rows
            if row.fair_value is not None
        ]
        if weight_overrides
        else []
    )
    positive_manual = [(row, weight) for row, weight in manual_rows if weight > 0]

    if positive_manual:
        raw_total = sum(weight for _row, weight in positive_manual)
        usable_manual = [(row, weight / raw_total) for row, weight in positive_manual]
        total_weight = sum(weight for _, weight in usable_manual)
        fair_base = (
            sum(float(row.fair_value) * weight for row, weight in usable_manual if row.fair_value is not None)
            / total_weight
        )
        model_weights = {row.model: 0.0 for row in candidates}
        for row, weight in usable_manual:
            model_weights[row.model] = round(weight, 6)
        usable = usable_manual
        warnings.append("ensemble_user_defined_weights")
        if len(positive_manual) < len([row for row in usable_rows if row.fair_value is not None]):
            warnings.append("ensemble_user_weights_partial_coverage")
    elif _use_ic_weights:
        assert ic_cfg is not None
        # IC weight encodes the *model's* learned predictive value; reliability discounts
        # *this result's* data quality. Their product is the effective weight (brief 44 §4):
        # a generally-predictive model built on fallback/proxy inputs for this name is
        # down-weighted, while clean-input names keep their pure-IC weighting unchanged.
        ic_reliability = [
            (row, ic_cfg.get(row.model, 0.0) * reliability_by_row[id(row)])
            for row in positive_ic_rows
        ]
        raw_total = sum(w for _row, w in ic_reliability)
        if raw_total <= 0:
            ic_reliability = [(row, 1.0) for row in positive_ic_rows]
            raw_total = float(len(positive_ic_rows))
        usable_ic = [(row, w / raw_total) for row, w in ic_reliability]
        total_weight = sum(w for _, w in usable_ic)
        fair_base = (
            sum(float(row.fair_value) * w for row, w in usable_ic if row.fair_value is not None)
            / total_weight
        )
        # model_weights: positive-IC models get normalised IC×reliability weight; rest get 0
        model_weights: dict[str, float] = {row.model: 0.0 for row in candidates}
        for row, w in usable_ic:
            model_weights[row.model] = round(w, 6)
        usable = usable_ic
        if len(positive_ic_rows) < len(usable_rows):
            warnings.append("ic_weight_fallback_for_uncovered_models")
    else:
        # Reliability-weighted fallback (no IC config or no coverage for this stock).
        # Headline = class-balanced median of the reliability-weighted class
        # representatives, so a thin comp can't swing the market-class voice.
        fair_base = float(median(class_representatives or values))
        rel_weights = [(row, reliability_by_row[id(row)]) for row in usable_rows]
        rel_total = sum(w for _row, w in rel_weights)
        if rel_total <= 0:
            rel_weights = [(row, 1.0) for row in usable_rows]
            rel_total = float(len(usable_rows))
        model_weights = {row.model: 0.0 for row in candidates}
        for row, w in rel_weights:
            model_weights[row.model] = round(w / rel_total, 6)
        usable = rel_weights
        total_weight = rel_total
        if ic_cfg is not None:
            # Config present but no positive-IC model available for this stock
            warnings.append("ic_weight_fallback_no_coverage")

    # ─────────────────────────────────────────────────────────────────────────
    if len(values) >= 4:
        fair_low = _percentile(values, 0.25) or values[0]
        fair_high = _percentile(values, 0.75) or values[-1]
    else:
        fair_low = values[0]
        fair_high = values[-1]
    confidence, dispersion_cv, dispersion_factor = _ensemble_confidence_components(usable_rows, values)
    target_models = max(1.0, float(DEFAULT_ASSUMPTIONS["ensemble_confidence_target_models"]))
    model_coverage = min(1.0, len(usable_rows) / target_models)
    _class_dispersion_cv, class_agreement = _dispersion_stats(class_representatives)
    mc_low, mc_base, mc_high = _monte_carlo_band(usable, total_weight, seed=f"{symbol}:{scenario}:{currency}")
    if mc_base is not None:
        shift = fair_base - mc_base
        mc_low = max(0.0, mc_low + shift) if mc_low is not None else None
        mc_base = fair_base
        mc_high = max(0.0, mc_high + shift) if mc_high is not None else None
    upside_pct = _upside(fair_base, current_price)
    # Shared low-information bias: when a majority of usable models carry the same
    # flagged input, their agreement masks a shared bias rather than confirming it.
    shared_bias_flag = _shared_low_information_bias(usable_rows)
    if shared_bias_flag is not None:
        warnings.append("headline_review_shared_input_bias")
    review_required = False
    if upside_pct is not None:
        upside_ceiling = float(DEFAULT_ASSUMPTIONS["headline_review_upside_ceiling"])
        downside_floor = float(DEFAULT_ASSUMPTIONS["headline_review_downside_floor"])
        confident_downside_band = float(DEFAULT_ASSUMPTIONS["headline_review_confident_downside_band"])
        min_coverage = float(DEFAULT_ASSUMPTIONS["headline_review_min_coverage"])
        min_class_agreement = float(DEFAULT_ASSUMPTIONS["headline_review_min_class_agreement"])
        extreme_upside = upside_pct > upside_ceiling
        extreme_downside = upside_pct < downside_floor
        weak_coverage = model_coverage < min_coverage
        weak_class_agreement = class_agreement < min_class_agreement
        # Shared bias substitutes for weak coverage/agreement: an extreme headline whose
        # models only agree because they share a flagged input must not be saved by that
        # (false) agreement (brief 44 RC-E).
        suspect_support = weak_coverage or weak_class_agreement or shared_bias_flag is not None
        if (extreme_upside or extreme_downside) and suspect_support:
            review_required = True
            warnings.append("headline_review_required_extreme_upside" if extreme_upside else "headline_review_required_extreme_downside")
            if weak_coverage:
                warnings.append("headline_review_weak_model_coverage")
            if weak_class_agreement:
                warnings.append("headline_review_weak_method_class_agreement")
        # A deeply negative headline built on low-information models must not ship as a
        # confident SELL even when it never reaches the -95% extreme floor (caught TQM
        # at -60% / AKT at -52% in the brief-44 evidence).
        if upside_pct < confident_downside_band and shared_bias_flag is not None:
            review_required = True
            warnings.append("headline_review_confident_downside_low_information")
    # Lone thin-comp headline (brief 44 — WAA defect): IC-weighting can collapse the
    # headline onto a single comp model (e.g. an insurer whose only positive-IC model is
    # relative_multiples) at effective weight ~1.0, where the reliability discount cancels
    # out because it is the sole survivor. A single thin comp must not justify an EXTREME
    # upside call on its own: when it drives the headline, prints an upside above the
    # lone-comp ceiling, AND is not corroborated by any nearby independent model, the
    # number is one low-information data point — route it to review. A well-populated comp
    # (no thin flag), a contained upside (e.g. OVR +67%, AAA +52%), or a nearby corroborator
    # all let the headline ship. User-pinned weights are an explicit desk choice and are
    # left untouched.
    if not positive_manual and len(usable_rows) >= 2 and upside_pct is not None:
        lone_share = float(DEFAULT_ASSUMPTIONS["headline_review_lone_driver_share"])
        lone_ceiling = float(DEFAULT_ASSUMPTIONS["headline_review_lone_thin_comp_upside_ceiling"])
        lone_divergence = float(DEFAULT_ASSUMPTIONS["headline_review_lone_comp_divergence"])
        dominant = max(usable_rows, key=lambda r: model_weights.get(r.model, 0.0))
        dominant_value = float(dominant.fair_value) if dominant.fair_value is not None else None
        if (
            dominant_value is not None
            and upside_pct > lone_ceiling
            and model_weights.get(dominant.model, 0.0) >= lone_share
            and dominant.model in ENSEMBLE_MARKET_METHOD_MODELS
            and any("relative_peers_count_below_5" in str(flag) for flag in dominant.warnings)
        ):
            # Corroboration is measured against the NEAREST independent model: a thin comp
            # that sits next to any one of the zero-weighted models is corroborated and may
            # ship even at extreme upside, while a comp far from every other model is a lone
            # bet on a single low-information data point and routes to review.
            corroborators = [
                float(row.fair_value)
                for row in usable_rows
                if row is not dominant
                and row.fair_value is not None
                and isfinite(float(row.fair_value))
                and float(row.fair_value) > 0
            ]
            corroborated = bool(corroborators) and min(
                abs(dominant_value - c) / c for c in corroborators
            ) <= lone_divergence
            if not corroborated:
                review_required = True
                warnings.append("headline_review_lone_thin_comp")
    if integrity_failed:
        warnings.append("integrity_fail_diagnostic")
    return EnsembleResult(
        symbol=symbol,
        scenario=scenario,
        fair_value_low=None if review_required else (mc_low if mc_low is not None else fair_low),
        fair_value_base=None if review_required else fair_base,
        fair_value_high=None if review_required else (mc_high if mc_high is not None else fair_high),
        current_price=current_price,
        upside_pct=None if review_required else upside_pct,
        confidence_score=confidence,
        usable_model_count=len(usable_rows),
        excluded_model_count=max(0, len([row for row in valuations if row.family != "diagnostic"]) - len(usable_rows)),
        model_weights=model_weights,
        warnings=warnings,
        currency=currency,
        model_dispersion_low=fair_low,
        model_dispersion_base=fair_base,
        model_dispersion_high=fair_high,
        monte_carlo_low=None if review_required else mc_low,
        monte_carlo_base=None if review_required else mc_base,
        monte_carlo_high=None if review_required else mc_high,
        fair_value_mean=fair_mean,
        model_dispersion_cv=dispersion_cv,
        dispersion_factor=dispersion_factor,
    )


def compute_symbol_valuations(
    *,
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    assumptions: dict[str, float] | None = None,
    scenario: str = "base",
    integrity: IntegrityReport | None = None,
) -> tuple[dict[str, Any], list[ValuationResult]]:
    """Route a stock through all relevant fundamental valuation models."""

    provided_assumption_keys = set((assumptions or {}).keys())
    merged_assumptions = {**default_assumptions_for_scenario(scenario), **(assumptions or {})}
    sector_map = sectors or {}
    sector = sector_map.get(snapshot.symbol)
    is_financial = _is_financial(sector)
    financial_archetype = _financial_archetype(sector)
    if is_financial:
        snapshot = _sanitize_financial_snapshot(snapshot, sector)
        history = _sanitize_financial_history(history, sector)
        peer_snapshots = [_sanitize_financial_snapshot(row, sector_map.get(row.symbol)) for row in peer_snapshots]
    current_price = _current_price(snapshot)
    snapshot_currency = _snapshot_currency(snapshot)
    assumption_currency = _assumption_currency(assumptions)
    if snapshot_currency != assumption_currency:
        results = [_unavailable(snapshot, scenario, model, current_price, "currency_mismatch") for model in VALUATION_MODEL_ORDER]
        eligibility = {
            model: {"eligible": False, "confidence": "unavailable", "reason": "currency_mismatch"}
            for model in VALUATION_MODEL_ORDER
        }
        eligibility["currency"] = {"snapshot": snapshot_currency, "assumptions": assumption_currency, "status": "mismatch"}
        ensemble = compute_valuation_ensemble(snapshot.symbol, scenario, results)
        eligibility["ensemble"] = {
            "usable_model_count": ensemble.usable_model_count,
            "excluded_model_count": ensemble.excluded_model_count,
            "confidence_score": ensemble.confidence_score,
            "model_weights": ensemble.model_weights,
            "warnings": ensemble.warnings,
            "currency": ensemble.currency,
            "fair_value_mean": ensemble.fair_value_mean,
            "model_dispersion_cv": ensemble.model_dispersion_cv,
            "dispersion_factor": ensemble.dispersion_factor,
        }
        return eligibility, results
    cyclical_commodity = is_cyclical_or_commodity(snapshot.symbol, sector)
    midcycle_basis = _midcycle_earnings_basis(
        snapshot,
        history,
        sector=sector,
        current_price=current_price,
    )
    merged_assumptions = {
        **merged_assumptions,
        "_cyclical_commodity": cyclical_commodity,
        "_financial_archetype": financial_archetype or "",
        "_midcycle_earnings_basis": midcycle_basis,
    }
    if not isinstance(merged_assumptions.get("terminal_growth_basis"), dict):
        merged_assumptions = enrich_terminal_growth_assumptions(
            snapshot,
            history,
            merged_assumptions,
            scenario=scenario,
            explicit_keys=provided_assumption_keys,
            sector=sector,
        )
    eligibility = _eligible_models(snapshot, history, sector, merged_assumptions)
    eligibility["financial_archetype"] = {
        "eligible": is_financial,
        "sector": sector,
        "class": financial_archetype,
        "suppressed_metrics": sorted(FINANCIAL_SUPPRESSED_METRICS) if is_financial else [],
    }
    eligibility["cyclical_commodity"] = {
        "eligible": cyclical_commodity,
        "sector": sector,
        "source": _cyclical_commodity_source(snapshot.symbol, sector),
        "normalized_earnings_basis": midcycle_basis,
    }
    peer_stats = _peer_stats(peer_snapshots, sector_map, snapshot.symbol, int(merged_assumptions["peer_min_count"]))
    driver_medians = peer_driver_medians(peer_snapshots, sector_map, snapshot.symbol, int(merged_assumptions["peer_min_count"]))
    merged_assumptions = {**merged_assumptions, "_peer_driver_medians": driver_medians}
    projection = _projection_from_assumptions(merged_assumptions)
    projection_terminal_growth = None
    projection_cyclical = None
    if projection is not None:
        projection_terminal_growth = _num(projection.growth_decomposition.get("terminal_growth"))
        projection_cyclical = bool(projection.growth_decomposition.get("cyclical", False))
    target_terminal_growth = _terminal_growth_for_model(merged_assumptions, "equity" if is_financial else "firm")
    if (
        projection is None
        or projection_terminal_growth is None
        or abs(projection_terminal_growth - target_terminal_growth) > 1e-12
        or projection_cyclical != cyclical_commodity
    ):
        projection = build_projection(snapshot, history, merged_assumptions, scenario=scenario, cyclical=cyclical_commodity)
        merged_assumptions = {**merged_assumptions, "_projection": projection}
    else:
        merged_assumptions = {**merged_assumptions, "_projection": projection}
    eligibility["projection"] = {
        "available": bool(projection.statements),
        "fallback": projection.fallback,
        "confidence_cap": projection.confidence_cap,
        "warnings": projection.warnings,
        "as_of": projection.as_of.isoformat() if projection.as_of else None,
    }
    eligibility["terminal_growth"] = merged_assumptions.get("terminal_growth_basis")

    results: list[ValuationResult] = [
        _relative_multiples(snapshot, history, current_price, peer_stats, merged_assumptions, scenario, is_financial=is_financial) if eligibility["relative_multiples"]["eligible"] else _unavailable(snapshot, scenario, "relative_multiples", current_price, "model_not_eligible"),
        _reverse_dcf(snapshot, current_price, merged_assumptions, scenario) if eligibility["reverse_dcf"]["eligible"] else _unavailable(snapshot, scenario, "reverse_dcf", current_price, "model_not_eligible"),
        _fcff_dcf(snapshot, history, current_price, merged_assumptions, scenario) if eligibility["fcff_dcf"]["eligible"] else _unavailable(snapshot, scenario, "fcff_dcf", current_price, "model_not_eligible"),
        _fcfe_dcf(snapshot, history, current_price, merged_assumptions, scenario) if eligibility["fcfe_dcf"]["eligible"] else _unavailable(snapshot, scenario, "fcfe_dcf", current_price, "model_not_eligible"),
        _ddm(snapshot, history, current_price, merged_assumptions, scenario) if eligibility["ddm"]["eligible"] else _unavailable(snapshot, scenario, "ddm", current_price, "model_not_eligible"),
        _residual_income(snapshot, history, current_price, merged_assumptions, scenario, is_financial) if eligibility["residual_income"]["eligible"] else _unavailable(snapshot, scenario, "residual_income", current_price, "model_not_eligible"),
        _justified_multiples(snapshot, history, current_price, merged_assumptions, scenario, is_financial) if eligibility["justified_multiples"]["eligible"] else _unavailable(snapshot, scenario, "justified_multiples", current_price, "model_not_eligible"),
    ]
    if financial_archetype == "insurance":
        # Our insurer valuation is equity-side (P/B-ROE, P/E, DDM) with no embedded /
        # appraisal value. Surface that caveat on the equity-side models so the headline is
        # read as a book-and-earnings proxy, not a life-EV valuation (brief 44 §3.7).
        for row in results:
            if (
                row.model in {"justified_multiples", "residual_income", "ddm", "relative_multiples"}
                and row.fair_value is not None
                and "insurer_no_embedded_value" not in row.warnings
            ):
                row.warnings.append("insurer_no_embedded_value")
    results = _with_cost_of_capital_context(results, merged_assumptions)
    results = _apply_integrity_report(results, integrity)
    ensemble = compute_valuation_ensemble(
        snapshot.symbol, scenario, results,
        weight_overrides=_ensemble_weight_overrides_from_assumptions(merged_assumptions),
    )
    for index, row in enumerate(results):
        weight = ensemble.model_weights.get(row.model)
        if weight is None and row.family == "diagnostic":
            weight = 0.0
        results[index] = ValuationResult(
            symbol=row.symbol,
            scenario=row.scenario,
            model=row.model,
            fair_value=row.fair_value,
            current_price=row.current_price,
            upside_pct=row.upside_pct,
            confidence=row.confidence,
            inputs=row.inputs,
            outputs=row.outputs,
            warnings=row.warnings,
            family=row.family,
            model_version=row.model_version,
            methodology=row.methodology,
            confidence_score=row.confidence_score,
            weight=weight,
            is_proxy=row.is_proxy,
            data_quality_score=row.data_quality_score,
            currency=row.currency,
        )
    eligibility["ensemble"] = {
        "usable_model_count": ensemble.usable_model_count,
        "excluded_model_count": ensemble.excluded_model_count,
        "confidence_score": ensemble.confidence_score,
        "model_weights": ensemble.model_weights,
        "warnings": ensemble.warnings,
        "currency": ensemble.currency,
        "model_dispersion": {
            "low": ensemble.model_dispersion_low,
            "base": ensemble.model_dispersion_base,
            "high": ensemble.model_dispersion_high,
            "cv": ensemble.model_dispersion_cv,
            "dispersion_factor": ensemble.dispersion_factor,
            "mean": ensemble.fair_value_mean,
        },
        "monte_carlo": {
            "low": ensemble.monte_carlo_low,
            "base": ensemble.monte_carlo_base,
            "high": ensemble.monte_carlo_high,
        },
    }
    if integrity is not None:
        eligibility["data_integrity"] = {
            "overall_status": integrity.overall_status,
            "confidence_haircut": integrity.confidence_haircut,
            "warnings": [_integrity_warning(integrity)] if _integrity_warning(integrity) else [],
        }
    return eligibility, results


def compute_sensitivity(
    *,
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    base_assumptions: dict[str, float] | None = None,
    scenario: str = "base",
    axis_x: str = "wacc",
    axis_y: str = "terminal_growth",
    range_x: tuple[float, float] = (0.07, 0.13),
    range_y: tuple[float, float] = (0.01, 0.05),
    steps: int = 5,
    integrity: IntegrityReport | None = None,
) -> dict[str, Any]:
    allowed = {"wacc", "terminal_growth", "cost_of_equity"}
    if axis_x not in allowed or axis_y not in allowed:
        raise ValueError(f"Sensitivity axes must be one of {sorted(allowed)}")
    if steps < 2 or steps > 11:
        raise ValueError("Sensitivity steps must be between 2 and 11")

    def linspace(bounds: tuple[float, float]) -> list[float]:
        start, end = bounds
        return [start + (end - start) * index / (steps - 1) for index in range(steps)]

    xs = linspace(range_x)
    ys = linspace(range_y)
    base = {**default_assumptions_for_scenario(scenario), **(base_assumptions or {})}
    base.pop("_projection", None)
    matrix: list[list[float | None]] = []
    upside_matrix: list[list[float | None]] = []
    confidence_matrix: list[list[float | None]] = []
    model_cells: dict[str, dict[tuple[int, int], ValuationResult]] = {}
    for row_index, y_value in enumerate(ys):
        row_values: list[float | None] = []
        row_upside: list[float | None] = []
        row_confidence: list[float | None] = []
        for col_index, x_value in enumerate(xs):
            assumptions = {**base, axis_x: float(x_value), axis_y: float(y_value)}
            _, valuations = compute_symbol_valuations(
                snapshot=snapshot,
                history=history,
                peer_snapshots=peer_snapshots,
                sectors=sectors,
                assumptions=assumptions,
                scenario=scenario,
                integrity=integrity,
            )
            ensemble = compute_valuation_ensemble(snapshot.symbol, scenario, valuations)
            for valuation in valuations:
                model_cells.setdefault(valuation.model, {})[(row_index, col_index)] = valuation
            row_values.append(ensemble.fair_value_base)
            row_upside.append(ensemble.upside_pct)
            row_confidence.append(ensemble.confidence_score)
        matrix.append(row_values)
        upside_matrix.append(row_upside)
        confidence_matrix.append(row_confidence)

    model_grids: dict[str, Any] = {}
    for model, cells in sorted(model_cells.items()):
        fair_value_grid: list[list[float | None]] = []
        upside_grid: list[list[float | None]] = []
        confidence_grid: list[list[float | None]] = []
        for row_index in range(len(ys)):
            fair_value_row: list[float | None] = []
            upside_row: list[float | None] = []
            confidence_row: list[float | None] = []
            for col_index in range(len(xs)):
                valuation = cells.get((row_index, col_index))
                fair_value_row.append(valuation.fair_value if valuation else None)
                upside_row.append(valuation.upside_pct if valuation else None)
                confidence_row.append(valuation.confidence_score if valuation else None)
            fair_value_grid.append(fair_value_row)
            upside_grid.append(upside_row)
            confidence_grid.append(confidence_row)
        model_grids[model] = {
            "symbol": snapshot.symbol,
            "scenario": scenario,
            "model": model,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "xs": xs,
            "ys": ys,
            "matrix": fair_value_grid,
            "fair_value_base": fair_value_grid,
            "upside_pct": upside_grid,
            "confidence_score": confidence_grid,
        }
    return {
        "symbol": snapshot.symbol,
        "scenario": scenario,
        "axis_x": axis_x,
        "axis_y": axis_y,
        "xs": xs,
        "ys": ys,
        "matrix": matrix,
        "axis_x_meta": {"key": axis_x, "values": xs},
        "axis_y_meta": {"key": axis_y, "values": ys},
        "fair_value_base": matrix,
        "upside_pct": upside_matrix,
        "confidence_score": confidence_matrix,
        "model_grids": model_grids,
    }


def compute_default_sensitivity_grids(
    *,
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    base_assumptions: dict[str, float] | None = None,
    scenario: str = "base",
    integrity: IntegrityReport | None = None,
) -> dict[str, Any]:
    base = {**default_assumptions_for_scenario(scenario), **(base_assumptions or {})}
    wacc = float(base.get("wacc", DEFAULT_ASSUMPTIONS["wacc"]))
    terminal_growth = float(base.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth"]))
    cost_of_equity = float(base.get("cost_of_equity", DEFAULT_ASSUMPTIONS["cost_of_equity"]))
    wacc_step = float(base.get("sensitivity_wacc_step", DEFAULT_ASSUMPTIONS["sensitivity_wacc_step"]))
    terminal_step = float(base.get("sensitivity_terminal_growth_step", DEFAULT_ASSUMPTIONS["sensitivity_terminal_growth_step"]))
    offsets = (-2, -1, 0, 1, 2)

    def bounds(center: float, step: float) -> tuple[float, float]:
        return center + offsets[0] * step, center + offsets[-1] * step

    return {
        "wacc_x_terminal_growth": compute_sensitivity(
            snapshot=snapshot,
            history=history,
            peer_snapshots=peer_snapshots,
            sectors=sectors,
            base_assumptions=base,
            scenario=scenario,
            axis_x="wacc",
            axis_y="terminal_growth",
            range_x=bounds(wacc, wacc_step),
            range_y=bounds(terminal_growth, terminal_step),
            steps=5,
            integrity=integrity,
        ),
        "cost_of_equity_x_terminal_growth": compute_sensitivity(
            snapshot=snapshot,
            history=history,
            peer_snapshots=peer_snapshots,
            sectors=sectors,
            base_assumptions=base,
            scenario=scenario,
            axis_x="cost_of_equity",
            axis_y="terminal_growth",
            range_x=bounds(cost_of_equity, wacc_step),
            range_y=bounds(terminal_growth, terminal_step),
            steps=5,
            integrity=integrity,
        ),
    }
