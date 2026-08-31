# 75 — CGNC archetype mapping

CGNC mapping is organized by statement archetype instead of forcing every issuer through an industrial chart of accounts.

- `industrial`: revenue, EBITDA/EBIT, working capital, cash flow, capex and leverage.
- `bank`: PNB, net interest and commission income, RBE, loans, deposits, regulatory capital, NPL and cost-to-income/loan-to-deposit derivations.
- `insurance`: premiums, claims, acquisition costs, technical provisions/result, reinsurance, solvency, loss/expense/combined ratios.
- `insurance_broker`: explicitly retains industrial operating metrics. AFM and AGM are classified here; an insurance-sector label alone must not erase broker EBITDA/cash-flow economics.

Resolution order is explicit symbol override, supplied sector/archetype, then field evidence. Financial archetypes suppress industrial-only enterprise-value and cash-flow metrics instead of inventing substitutes. Derived ratios require their actual component lines; missing inputs stay missing. ROA uses average assets when two periods exist, and archetype-specific growth uses PNB for banks and premiums for insurers.

When a new issuer is added, assign its business model explicitly where the exchange sector label is ambiguous, add raw CGNC labels to the relevant alias group, and cover the mapping with a fixture using real statement labels. Never map a line solely because its wording resembles another archetype.
