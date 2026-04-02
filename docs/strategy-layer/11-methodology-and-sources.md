# Strategy Layer — Methodology and Sources

## Purpose

This document centralizes the sources that support the design choices of the Strategy page. The goal is not to artificially "scientize" every pixel, but to show that the chosen business rules have an identifiable logical or empirical basis.

The previous chapters use these sources as **design justification**, not as absolute truth. The references support the chosen direction; they do not remove the need for OOS validation in our own market universe.

## 1. Signals Are Not Strategies

The separation between the signal engine and the strategy layer rests on a simple idea:

- detecting a predictive pattern is not the same thing as defining a full trading system

This aligns with the literature on:

- overfitting
- data snooping
- separating feature discovery from portfolio construction

Useful references:

- Bailey, Borwein, López de Prado, Zhu (2014), *Pseudo-Mathematics and Financial Charlatanism*
- Harvey, Liu, Zhu (2016), *... and the Cross-Section of Expected Returns*
- López de Prado (2018), *Advances in Financial Machine Learning*
- Pardo (2008), *The Evaluation and Optimization of Trading Strategies*

## 2. Regime-Aware Signal Conditioning (Signal Layer)

The regime-aware conditioning methodology is built on the idea that the usefulness of technical indicators depends on market context. This methodology is owned by the **signal layer** — see [../signal-generation/11-regime-aware-conditioning.md](../signal-generation/11-regime-aware-conditioning.md) for full details.

Primary reference:

- Neely, Rapach, Tu, Zhou (2014), *Forecasting the Equity Risk Premium: The Role of Technical Indicators*, Management Science

Why this matters:

- it supports the idea that technical information is not uniformly useful
- it justifies an architecture that conditions signal usage on market state

Supporting references:

- Hong & Stein (1999), which supports the theoretical distinction between momentum / trend-following behavior and overreaction / mean-reversion behavior, directly informing the separation between trend and oscillation families
- Han, Yang, & Zhou (2013), which supports the idea that technical-analysis profitability varies across market conditions and information uncertainty, reinforcing why regime-conditional evaluation is useful
- Hamilton (1989), which provides the foundational regime-switching framework underlying the architecture of conditional market-state modeling
- Ang & Timmermann (2012), which supports regime-dependent strategy selection and conditional behavior in financial markets
- Kaufman (1995), which supports the use of the Efficiency Ratio as a regime candidate
- Stein (2024), which supports the idea that technical-indicator predictability can vary by regime and frequency, reinforcing regime-conditional weighting

## 3. Support / Resistance and Execution Geometry

The Execution layer rests on two broad ideas:

1. price levels matter
2. normal volatility must be respected when placing stops

References:

- Osler (2003), *Currency Orders and Exchange-Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis*, Journal of Finance
- Wilder (1978), *New Concepts in Technical Trading Systems*

Why they matter:

- Osler supports the practical idea that meaningful order clustering happens around salient levels
- Wilder provides the foundation for ATR / ADX as measures of noise and directionality

This does not prove that every swing level will hold. It justifies an execution architecture that respects:

- price structure
- current volatility
- reward / risk geometry

These choices also sit inside a broader walk-forward validation framework supported by Pardo (2008), which is relevant across all layers that depend on out-of-sample evaluation rather than in-sample intuition.

## 4. Fractional Kelly and Risk Sizing

Primary reference:

- Thorp (2006), *The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market*

Why this matters:

- Kelly provides a rational sizing framework under assumptions of measurable edge and measurable unit risk
- real usage often prefers fractional Kelly because parameter estimates are uncertain

That supports:

- Full Kelly as a theoretical ceiling
- Half Kelly as the recommended default
- Quarter Kelly as a more conservative mode

Ang & Timmermann (2012) is also relevant here because regime-dependent market behavior supports the broader idea that sizing and allocation decisions may need to respond to conditional market structure rather than assume one static environment.

## 5. Equal Weight as a Serious Baseline

Primary reference:

- DeMiguel, Garlappi, Uppal (2009), *Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?*

Why this matters:

- it reminds us that simple `equal weight` is often a more robust benchmark than a fragile optimizer

That justifies treating `Equal Weight` as a real v1 allocation method, not as an embarrassing fallback.

## 6. Signal Families, Technical Analysis, and Allocation Logic

Several sources support the decision to keep technical-analysis families explicit rather than collapse them into one undifferentiated signal block.

- Hong & Stein (1999) supports the idea that momentum-type behavior and overreaction / reversal behavior arise from different mechanisms, which maps naturally to the distinction between trend and oscillation families in the Signal layer
- Zhu & Zhou (2009) supports the formal use of moving-average signals in an allocation context, strengthening the rationale for keeping moving-average-based signals central in the Signal layer
- Han, Yang, & Zhou (2013) supports the idea that technical-analysis profitability varies across the cross section and with information uncertainty, which reinforces why the pipeline tests multiple windows and why regime-conditional logic is justified

## 7. Why Casablanca Specifically

The Casablanca Stock Exchange is not just a generic market setting. It has characteristics that make this architecture especially relevant:

- lower liquidity than large developed exchanges
- fewer analysts and less institutional coverage
- higher information asymmetry
- a greater chance that technical information remains useful because prices adjust less perfectly and less instantly

Hung & Lai (2022) is directly relevant here: their result supports the idea that technical analysis can be more profitable in markets with greater information asymmetry. Han, Yang, & Zhou (2013) also matters because they connect technical-analysis profitability to information uncertainty, which is exactly the type of condition that can be more pronounced in smaller and less heavily covered equity markets.

This does not guarantee that technical analysis will work on every Casablanca stock. It just strengthens the strategic logic for building a disciplined, OOS-validated technical framework in this market rather than assuming that developed-market efficiency arguments transfer automatically.

Hung & Lai (2022) also supports the Universe layer rationale for enforcing liquidity discipline: if the market contains informational inefficiencies but also substantial trading frictions, any strategy that ignores the execution reality of low-volume names risks turning a theoretically interesting edge into a practically untradeable one.

## 8. Future Allocation Methods

These methods are not implemented in v1, but they are included as plausible architectural extensions.

### Hierarchical Risk Parity

- López de Prado (2016), *Building Diversified Portfolios that Outperform Out of Sample*

Interest:

- addresses some fragilities of classical optimization
- still requires a reliable correlation matrix

### Mean-Variance Optimization

- Markowitz (1952), *Portfolio Selection*

Interest:

- historical foundation of modern allocation theory

Practical limitation:

- highly sensitive to expected return and covariance assumptions

## 9. How These Sources Should Be Used

The sources above should not be treated as magic authority that removes the need for our own tests. Their role in this documentation is to justify structural choices:

- separating signal and strategy
- conditioning signals on market regime (upstream in signal layer)
- imposing trade geometry
- capping size with Kelly
- keeping a simple, robust baseline allocation
- matching the design to the specific conditions of the Casablanca market

## Bibliography

- Ang, A., & Timmermann, A. (2012). *Regime Changes and Financial Markets*. Annual Review of Financial Economics.
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). *Pseudo-Mathematics and Financial Charlatanism*. Notices of the AMS.
- DeMiguel, V., Garlappi, L., Uppal, R. (2009). *Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?* Review of Financial Studies.
- Hamilton, J.D. (1989). *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*. Econometrica.
- Han, Y., Yang, K., & Zhou, G. (2013). *A New Anomaly: The Cross-Sectional Profitability of Technical Analysis*. Journal of Financial and Quantitative Analysis.
- Harvey, C.R., Liu, Y., Zhu, H. (2016). *... and the Cross-Section of Expected Returns*. Review of Financial Studies.
- Hong, H., & Stein, J.C. (1999). *A Unified Theory of Underreaction, Momentum Trading, and Overreaction*. Journal of Finance.
- Hung, C., & Lai, H. (2022). *Information Asymmetry and the Profitability of Technical Analysis*. Journal of Banking & Finance.
- Kaufman, P.J. (1995). *Trading Systems and Methods*.
- López de Prado, M. (2016). *Building Diversified Portfolios that Outperform Out of Sample*.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Markowitz, H. (1952). *Portfolio Selection*. Journal of Finance.
- Neely, C.J., Rapach, D.E., Tu, J., Zhou, G. (2014). *Forecasting the Equity Risk Premium: The Role of Technical Indicators*. Management Science.
- Osler, C.L. (2003). *Currency Orders and Exchange-Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis*. Journal of Finance.
- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley.
- Stein, T. (2024). *Forecasting the Equity Premium with Frequency-Decomposed Technical Indicators*. International Journal of Forecasting.
- Thorp, E.O. (2006). *The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market*.
- Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*.
- Zhu, Y., & Zhou, G. (2009). *Technical Analysis: An Asset Allocation Perspective on the Use of Moving Averages*. Journal of Financial Economics.

## Cross-Links

- Regime-aware conditioning methodology: [../signal-generation/11-regime-aware-conditioning.md](../signal-generation/11-regime-aware-conditioning.md)
- Execution justifications are applied in [06-execution-layer.md](./06-execution-layer.md)
- Sizing justifications are applied in [07-position-sizing-layer.md](./07-position-sizing-layer.md)
