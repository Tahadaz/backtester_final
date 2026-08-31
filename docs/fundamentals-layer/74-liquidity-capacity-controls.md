# 74 — Liquidity and capacity controls

The strategy now fails closed on point-in-time liquidity and exposes every limit in the UI/API. Defaults are research calibration, not desk-approved limits: MAD 10m NAV, MAD 100k minimum order, MAD 500k minimum 20-session ADTV, 20% maximum ADTV participation, and a one-session execution horizon. Each rule can be disabled or edited.

At formation date `t`, ADTV uses exactly the preceding 20 observations (`date < t`), so formation-day volume cannot leak into eligibility or fills. An order below the minimum ticket is rejected; an order above `ADTV × participation × horizon` is partially filled. The same cap applies to buys and sells. Unfilled notional stays in cash or in the existing position and is never redistributed. Transaction cost is 33 bps per filled side, including initial deployment.

The 20% convention is anchored to institutional liquidity practice, including MSCI IndexMetrics' default trading limit and the SEC's 20%-of-ADV liquidation convention. The 20-session window follows the SEC convention. The MAD 500k universe floor and MAD 100k ticket are transparent Casablanca calibration choices derived from the locally observed universe distribution; they require desk approval before capital deployment. Casablanca orders remain subject to exchange order and trading-mode rules.

Sources:

- AMMC, *Le marché des capitaux en chiffres 2025*: https://www.ammc.ma/sites/default/files/LE%20MARCHE%20DES%20CAPITAUX%20EN%20CHIFFRES%202025%20VFR.pdf
- Bourse de Casablanca, trading modes: https://www.casablanca-bourse.com/market-data/modes-cotation-comptant
- SEC proposed liquidity rule (20% ADV; preceding 20 business days): https://www.sec.gov/files/rules/proposed/2022/33-11130.pdf
- MSCI IndexMetrics methodology (20% default trading limit): https://www.msci.com/documents/10199/402635a5-fd5d-498e-985a-1bec8ff8d8b1

Known limitation: monthly targets are still formed and executed at the same as-of close. Production must introduce an explicit next-session execution lag and verify exchange calendar, auction, limit, suspension, and order-size behavior. Therefore this remains research/backtest infrastructure, not a live-capital approval.
