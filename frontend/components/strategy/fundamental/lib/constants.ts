import {
  type FundamentalAssumptionMeta,
} from "@/lib/api"
import { DetailTab, FinancialStatementTab, FundamentalHorizon, MultipleRatioDefinition, Scenario, ValuationFormulaMeta } from "../lib/types"

export const SCENARIOS: Scenario[] = ["bear", "base", "bull"]


export const FUNDAMENTAL_HORIZONS: Array<{ value: FundamentalHorizon; label: string; periodType: "quarterly" | "semiannual" | "annual" }> = [
  { value: "quarter", label: "Trimestre", periodType: "quarterly" },
  { value: "semester", label: "Semestre", periodType: "semiannual" },
  { value: "year", label: "Annee", periodType: "annual" },
]


export const FUND_TABS: Array<{ value: DetailTab; label: string }> = [
  { value: "synthese", label: "Synthèse" },
  { value: "valuation", label: "Valorisation" },
  { value: "estimates", label: "Estimations & Hypothèses" },
  { value: "quality", label: "Comparables & Qualité" },
  { value: "strategie", label: "Stratégie de valeur" },
]

export const FUND_TAB_PURPOSE: Record<DetailTab, string> = {
  synthese: "L'essentiel : la recommandation, ce qui la soutient, et ce qui pourrait la changer.",
  valuation: "Ce que valent les modèles par rapport au prix de marché, et comment la cible est construite.",
  estimates: "D'où viennent les prévisions, et les hypothèses que vous pouvez ajuster.",
  quality: "Le titre face à ses pairs, et la solidité de ses fondamentaux.",
  strategie: "L'état actuel et la performance backtestée de la stratégie systématique B/M + CF/P (recherche, pas un historique live).",
}


export const MODEL_ORDER = ["fcff_dcf", "fcfe_dcf", "ddm", "residual_income", "justified_multiples", "relative_multiples", "reverse_dcf"]


export const VALUATION_EXCLUSIONS_STORAGE_KEY = "fundamental_valuation_exclusions_by_symbol"

export const DEFAULT_COMPARATOR_STORAGE_KEY = "fundamental_default_comparator_id"


export const FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD = 500_000


export const JUSTIFIED_MULTIPLE_RATIO_MASK_KEY = "justified_multiple_ratio_mask"


export const RELATIVE_MULTIPLE_RATIO_MASK_KEY = "relative_multiple_ratio_mask"


export const JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK = 3


export const RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK = 15


export const EXTREME_VALUATION_FAIR_VALUE_MULTIPLE = 20


export const SEVERE_VALUATION_WARNINGS = new Set([
  "missing_positive_fcf",
  "missing_positive_equity_cash_flow_proxy",
  "wacc_not_above_terminal_growth",
  "cost_of_equity_not_above_terminal_growth",
  "fcf_dcf_unavailable_nonpositive_equity_value",
  "dividend_yield_above_plausible_range",
  "price_to_book_below_plausible_range",
])


export const SEVERE_FCF_WARNING_PREFIXES = ["fcf_model_unreliable_negative_"]


// FR labels for SEVERE_VALUATION_WARNINGS, used wherever these warnings surface
// in trader-facing copy (Synthese risks list, and future Valorisation/Qualite chips).
export const SEVERE_VALUATION_WARNING_LABELS_FR: Record<string, string> = {
  missing_positive_fcf: "FCF projeté non positif",
  missing_positive_equity_cash_flow_proxy: "Proxy de cash-flow actionnaire non positif",
  wacc_not_above_terminal_growth: "WACC ne dépasse pas la croissance terminale",
  cost_of_equity_not_above_terminal_growth: "Coût des fonds propres ne dépasse pas la croissance terminale",
  fcf_dcf_unavailable_nonpositive_equity_value: "Valeur des fonds propres DCF non positive",
  dividend_yield_above_plausible_range: "Rendement du dividende hors plage plausible",
  price_to_book_below_plausible_range: "P/B impliqué sous la plage plausible",
}

export const VALUATION_WARNING_LABELS_FR: Record<string, string> = {
  ...SEVERE_VALUATION_WARNING_LABELS_FR,
  capex_pct_from_peer_median: "Capex : proxy médiane secteur",
  capex_pct_unavailable_no_history_no_peer: "Capex : historique et proxy secteur indisponibles",
  cash_flow_statement_missing_driver_fallback: "Cash-flow : proxy faute de tableau de flux",
  d_and_a_pct_from_peer_median: "D&A : proxy médiane secteur",
  direct_driver_fcff_fallback: "FCFF : proxy direct faute de drivers",
  earnings_growth_proxy: "Croissance : proxy bénéfices",
  ebit_margin_from_peer_median: "Marge EBIT : proxy médiane secteur",
  fcfe_proxy_from_free_cash_flow: "FCFE : proxy depuis free cash-flow",
  fcff_dcf_projection_driver_unavailable: "FCFF DCF : drivers projetés incomplets",
  fcfe_dcf_projection_driver_unavailable: "FCFE DCF : drivers projetés incomplets",
  midcycle_ebit_margin_applied: "Marge EBIT : proxy milieu de cycle",
  midcycle_maintenance_capex_applied: "Capex : proxy milieu de cycle",
  midcycle_maintenance_capex_unavailable_registry_assumption: "Capex : proxy 4 % CA (défaut)",
  missing_book_value_proxy: "Book value : proxy requis",
  missing_fcf_growth_driver: "Croissance : proxy faute de driver FCF",
  missing_fcfe_growth_driver: "Croissance : proxy faute de driver FCFE",
  missing_net_debt_bridge: "Dette nette : bridge incomplet",
  payout_ratio_from_peer_median: "Payout : proxy médiane secteur",
  revenue_growth_from_peer_median: "Croissance : proxy secteur",
  roe_from_peer_median: "ROE : proxy médiane secteur",
  stable_payout_assumption: "Payout : hypothèse stable",
  using_stable_payout_assumption: "Payout : hypothèse stable",
  working_capital_pct_from_peer_median: "BFR : proxy médiane secteur",
}


export function valuationWarningLabel(warning: string): string {
  return VALUATION_WARNING_LABELS_FR[warning] ?? warning
}


// Per-model glossary entry ids for GlossaryTerm wiring (football field legend,
// valuation model rail...). Falls back to the general "dcf" entry when a model
// has no dedicated glossary entry.
export const MODEL_GLOSSARY_IDS: Record<string, string> = {
  fcff_dcf: "fcff",
  fcfe_dcf: "fcfe",
  ddm: "ddm",
  residual_income: "residual-income",
  justified_multiples: "justified-multiples",
  relative_multiples: "relative-multiples",
  reverse_dcf: "reverse-dcf",
}


export const JUSTIFIED_MULTIPLE_RATIOS: MultipleRatioDefinition[] = [
  { key: "justified_pb", label: "P/B", bit: 1 },
  { key: "justified_pe", label: "P/E", bit: 2 },
]


export const RELATIVE_MULTIPLE_RATIOS: MultipleRatioDefinition[] = [
  { key: "PER", label: "P/E", bit: 1 },
  { key: "Price_to_Book", label: "P/B", bit: 2 },
  { key: "Price_to_Sales", label: "P/S", bit: 4 },
  { key: "EV_to_EBITDA", label: "EV/EBITDA", bit: 8 },
]


export const MODEL_LABELS: Record<string, string> = {
  fcff_dcf: "DCF FCFF",
  fcfe_dcf: "DCF FCFE",
  ddm: "DDM",
  residual_income: "Revenu residuel",
  justified_multiples: "Multiples justifies",
  relative_multiples: "Comparables",
  reverse_dcf: "Reverse DCF",
}


export const MODEL_FORMULA_META: Record<string, ValuationFormulaMeta> = {
  fcff_dcf: {
    formula: "FV/share = (PV(FCFF_1..n) + TV - Net Debt) / Shares",
    secondaryFormula: "TV = FCFF_n x (1 + g_terminal) / (WACC - g_terminal)",
    explanation: "Values the operating business from free cash flow to the firm, then bridges enterprise value to equity value.",
    assumptionKeys: ["wacc", "terminal_growth_firm", "default_debt_weight", "default_equity_weight", "use_balance_sheet_capital_weights", "cost_of_debt", "forecast_years", "growth_cap", "tax_rate"],
    technicalInputKeys: ["fcf_start", "fcf_source", "fcf_growth_source", "net_debt", "net_debt_source"],
    statementKeys: {
      income: ["revenue", "ebitda", "ebit", "net_income"],
      balance: ["cash", "total_debt", "net_debt", "total_equity"],
      cashflow: ["operating_cf", "capex", "free_cash_flow"],
    },
  },
  fcfe_dcf: {
    formula: "FV/share = (PV(FCFE_1..n) + TV) / Shares",
    secondaryFormula: "FCFE = FCF - Interest x (1 - tax) + Debt issuance - Debt repayment",
    explanation: "Discounts cash flow available to equity holders directly, so no net-debt bridge is applied after discounting.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "cost_of_debt", "forecast_years", "growth_cap", "tax_rate"],
    technicalInputKeys: ["fcfe_start", "fcfe_source"],
    statementKeys: {
      income: ["revenue", "ebitda", "net_income"],
      balance: ["total_debt", "net_debt", "total_equity"],
      cashflow: ["operating_cf", "financing_cf", "free_cash_flow"],
    },
  },
  ddm: {
    formula: "FV/share = DPS_1 / (Cost of Equity - g)",
    secondaryFormula: "DPS_1 = Dividend per share x (1 + sustainable growth)",
    explanation: "Uses the Gordon dividend model when the stock has an observable dividend base.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "stable_payout_ratio", "growth_cap"],
    technicalInputKeys: ["dividend_per_share", "growth_source"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["total_equity"],
      cashflow: ["dividends_paid", "free_cash_flow"],
    },
  },
  residual_income: {
    formula: "FV/share = BVPS_0 + sum((ROE_t - Cost of Equity) x BVPS_{t-1}) / (1 + Cost of Equity)^t",
    secondaryFormula: "BVPS_t grows with retained earnings while ROE fades toward Cost of Equity.",
    explanation: "Starts from book value and adds the discounted value created above the required return on equity.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "fade_years", "stable_payout_ratio"],
    technicalInputKeys: ["book_value_per_share", "roe"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["total_equity", "retained_earnings"],
      cashflow: ["dividends_paid", "free_cash_flow"],
    },
  },
  justified_multiples: {
    formula: "FV/share = median(Current Price x Justified Multiple / Current Multiple)",
    secondaryFormula: "Justified P/B = (ROE - g) / (Cost of Equity - g), Justified P/E = payout x (1 + g) / (Cost of Equity - g)",
    explanation: "Translates ROE, payout and growth into internally justified P/B and P/E multiples.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "stable_payout_ratio", "growth_cap", "fade_years", JUSTIFIED_MULTIPLE_RATIO_MASK_KEY],
    technicalInputKeys: ["roe"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["total_equity"],
      cashflow: ["dividends_paid", "free_cash_flow"],
    },
  },
  relative_multiples: {
    formula: "FV/share = median(Current Price x Peer Median Multiple / Own Multiple)",
    secondaryFormula: "Applied to P/E, P/B, P/S and EV/EBITDA when each own and peer multiple is usable.",
    explanation: "Benchmarks the stock against sector peers first, then the market when the sector sample is too thin.",
    assumptionKeys: ["peer_min_count", RELATIVE_MULTIPLE_RATIO_MASK_KEY],
    technicalInputKeys: ["own_multiples", "peer_stats"],
    statementKeys: {
      income: ["revenue", "ebitda", "net_income"],
      balance: ["total_equity", "net_debt"],
      cashflow: ["free_cash_flow"],
    },
  },
  reverse_dcf: {
    formula: "Implied g = WACC - FCF Yield",
    secondaryFormula: "Diagnostic only: the result is an implied growth assumption, not a price target.",
    explanation: "Does not produce a fair value. It explains what perpetual-growth assumption the current market price already embeds.",
    assumptionKeys: ["wacc"],
    technicalInputKeys: ["market_cap", "fcf_yield"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["net_debt", "total_equity"],
      cashflow: ["free_cash_flow"],
    },
  },
}


export const DEFAULT_VALUATION_FORMULA: ValuationFormulaMeta = {
  formula: "FV/share = model output / Shares",
  explanation: "Model-specific details are available through persisted inputs and outputs.",
  assumptionKeys: [],
  technicalInputKeys: [],
  statementKeys: {
    income: ["revenue", "ebitda", "net_income"],
    balance: ["total_equity", "net_debt"],
    cashflow: ["free_cash_flow", "dividends_paid"],
  },
}


export const STATEMENT_TITLES: Record<FinancialStatementTab, string> = {
  income: "Compte de resultat",
  balance: "Bilan",
  cashflow: "Cash-flow",
}


export const VALUE_LABELS: Record<string, string> = {
  cost_of_equity: "Cost of equity",
  dividend_per_share: "Dividend / share",
  fade_years: "Fade years",
  fcf_growth_source: "FCF growth source",
  fcf_source: "FCF source",
  fcf_start: "Starting FCF",
  fcfe_source: "FCFE source",
  fcfe_start: "Starting FCFE",
  fcf_yield: "FCF yield",
  forecast_years: "Forecast years",
  growth: "Growth",
  growth_cap: "Growth cap",
  growth_source: "Growth source",
  justified_multiple_ratio_mask: "Selected justified ratios",
  market_cap: "Market cap",
  net_debt: "Net debt",
  net_debt_source: "Net debt source",
  own_multiples: "Own multiples",
  payout: "Payout",
  peer_min_count: "Peer minimum",
  peer_stats: "Peer medians",
  relative_multiple_ratio_mask: "Selected relative ratios",
  roe: "ROE",
  stable_payout_ratio: "Stable payout",
  sustainable_growth: "Sustainable growth",
  tax_rate: "Tax rate",
  terminal_growth: "Terminal growth",
  terminal_growth_firm: "Terminal growth firm",
  terminal_growth_equity: "Terminal growth equity",
  terminal_growth_basis: "Terminal growth basis",
  wacc: "WACC",
}


export const ASSUMPTION_FIELDS = [
  ["risk_free_rate", "Taux sans risque"],
  ["equity_risk_premium", "Prime actions"],
  ["beta", "Beta"],
  ["cost_of_equity_floor", "Plancher Ke"],
  ["terminal_growth_firm", "g firm"],
  ["terminal_growth_equity", "g equity"],
  ["cost_of_debt", "Cout dette"],
  ["tax_rate", "Taux IS"],
  ["default_debt_weight", "Poids dette"],
] as const


export const SCORE_SCOPE_LABELS = [
  ["value", "Valeur"],
  ["quality", "Qualite"],
] as const


export const ESTIMATION_ASSUMPTION_KEYS = [
  "forecast_years",
  "growth_cap",
  "terminal_growth_firm",
  "tax_rate",
  "stable_payout_ratio",
] as const


export const ESTIMATION_ASSUMPTION_KEY_SET = new Set<string>(ESTIMATION_ASSUMPTION_KEYS)


export const ESTIMATION_ASSUMPTION_FALLBACK_META: Record<(typeof ESTIMATION_ASSUMPTION_KEYS)[number], FundamentalAssumptionMeta> = {
  forecast_years: {
    value: 5,
    label: "Horizon explicite",
    unit: "years",
    group: "projection",
    derivation: "Nombre d'annees explicites avant la valeur terminale.",
    source: "Valuation engine",
    plausible_range: [3, 7],
    scope: "desk",
    editable: true,
  },
  growth_cap: {
    value: 0.08,
    label: "Cap de croissance",
    unit: "percent",
    group: "projection",
    derivation: "Borne haute appliquee aux proxys de croissance.",
    source: "Valuation engine",
    plausible_range: [0.03, 0.15],
    scope: "desk",
    editable: true,
  },
  terminal_growth_firm: {
    value: 0.025,
    label: "Croissance terminale firm",
    unit: "percent",
    group: "projection",
    derivation: "Point d'arrivee de la trajectoire de croissance operationnelle.",
    source: "ROIC et reinvestissement historiques",
    plausible_range: [0, 0.055],
    scope: "symbol",
    editable: true,
  },
  tax_rate: {
    value: 0.35,
    label: "Taux IS",
    unit: "percent",
    group: "projection",
    derivation: "Taux d'impot applique a l'EBIT pour construire le NOPAT.",
    source: "Valuation engine",
    plausible_range: [0.20, 0.40],
    scope: "desk",
    editable: true,
  },
  stable_payout_ratio: {
    value: 0.55,
    label: "Payout stable",
    unit: "percent",
    group: "projection",
    derivation: "Fallback de distribution lorsque le payout historique est incomplet.",
    source: "Valuation engine",
    plausible_range: [0, 0.90],
    scope: "desk",
    editable: true,
  },
}


export const ESTIMATION_STATEMENT_KEYS = new Set([
  "revenue",
  "ebit",
  "nopat",
  "capex",
  "delta_working_capital",
  "fcff",
  "fcfe",
  "net_income",
  "dividends",
])


export const ESTIMATION_HISTORICAL_ALIASES: Record<string, string[]> = {
  revenue: ["Clean_Chiffre_daffaires", "Chiffre_daffaires", "Revenue", "Total_Revenue", "Total_Revenues", "TotalRevenue"],
  ebit: ["EBIT", "Operating_Income", "OperatingIncome", "Resultat_dexploitation", "Resultat_Exploitation"],
  nopat: ["NOPAT"],
  capex: ["Capex", "CAPEX", "Capital_Expenditure", "Capital_Expenditures"],
  delta_working_capital: ["Delta_Working_Capital", "Change_in_Working_Capital", "Variation_BFR"],
  fcff: ["FCFF", "Free_Cash_Flow", "Levered_Free_Cash_Flow"],
  fcfe: ["FCFE", "Free_Cash_Flow_to_Equity"],
  net_income: ["Clean_Resultat_net", "Resultat_net", "NetIncome", "Net_Income", "IS_Net_Income"],
  dividends: ["Clean_Dividendes", "Dividendes", "Dividends_Paid", "Cash_Dividends_Paid"],
}


export const WORKING_CAPITAL_HISTORICAL_ALIASES = ["Working_Capital", "BFR"]


export const HISTORICAL_TAX_ALIASES = ["Income_Tax_Expense", "Impots_sur_les_resultats"]


export const HISTORICAL_TAX_RATE_ALIASES = ["Tax_Rate", "Effective_Tax_Rate"]


export const HISTORICAL_REVENUE_GROWTH_ALIASES = ["Revenue_Growth"]


export const HISTORICAL_DEPRECIATION_AMORTIZATION_ALIASES = ["Depreciation_Amortization", "DandA", "Dotations_dexploitation"]


export const HISTORICAL_PAYOUT_ALIASES = ["Dividend_Payout", "Payout_Ratio"]


export const COMPARABLE_METRICS = [
  "PER",
  "EV_to_EBITDA",
  "Price_to_Book",
  "Price_to_Sales",
  "ROE",
  "Dividend_Yield",
  "Revenue_Growth",
] as const


export const VALUATION_COMPARABLE_METRICS = ["PER", "EV_to_EBITDA", "Price_to_Book", "Price_to_Sales"] as const


export const COMPARABLE_METRIC_LABELS: Record<string, string> = {
  PER: "P/E",
  EV_to_EBITDA: "EV/EBITDA",
  Price_to_Book: "P/B",
  Price_to_Sales: "P/S",
  ROE: "ROE",
  Dividend_Yield: "Div Yield",
  Revenue_Growth: "g CA",
}


export const COMPARABLE_PERCENT_METRICS = new Set(["ROE", "Dividend_Yield", "Revenue_Growth"])


export const LOWER_BETTER_COMPARABLE_METRICS = new Set(["PER", "EV_to_EBITDA", "Price_to_Book", "Price_to_Sales"])


// Glossary ids for comparable/peer metric headers (brief 57 §4.4 / §6.2). Metrics with no
// glossary entry (e.g. Revenue_Growth, FCF_Yield) are intentionally absent - left plain.
export const COMPARABLE_METRIC_GLOSSARY_IDS: Record<string, string> = {
  PER: "per",
  EV_to_EBITDA: "ev-ebitda",
  Price_to_Book: "price-to-book",
  Price_to_Sales: "price-to-sales",
  ROE: "roe",
  Dividend_Yield: "dividend-yield",
}


export const DEFAULT_FORWARD_GROWTH = 0.03


export const DEFAULT_STABLE_PAYOUT = 0.55
