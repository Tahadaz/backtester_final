import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

const metrics = [
  {
    id: "cagr",
    title: "CAGR (Compound Annual Growth Rate)",
    content: [
      "The annualized growth rate of your investment over the backtest period. It represents the constant yearly rate that would yield the same total return.",
      "Formula: CAGR = (Ending Value / Starting Value)^(1 / Years) - 1",
      "A CAGR of 15% means your portfolio would grow by 15% per year on average. This is the most important metric for comparing long-term strategy performance.",
    ],
  },
  {
    id: "total-return",
    title: "Total Return",
    content: [
      "The cumulative percentage return over the entire backtest period.",
      "Formula: Total Return = (Ending Equity / Starting Equity) - 1",
      "A total return of 150% means your initial investment increased by 150%, so 100,000 became 250,000.",
    ],
  },
  {
    id: "pnl",
    title: "PnL (Profit and Loss)",
    content: [
      "The absolute dollar amount gained or lost over the backtest period. This is simply the difference between ending equity and starting equity.",
      "While useful for understanding absolute gains, PnL doesn't account for risk or the time value of money, so CAGR and Sharpe are better for strategy comparison.",
    ],
  },
  {
    id: "max-drawdown",
    title: "Max Drawdown (MDD)",
    content: [
      "The largest peak-to-trough decline in equity during the backtest period. This measures the worst loss you would have experienced from a previous high point.",
      "A max drawdown of -25% means at one point, your portfolio declined 25% from its highest value. Lower drawdowns indicate more stable strategies.",
      "Drawdown tests your risk tolerance. A strategy with 50% annual returns but -60% drawdown might be psychologically unbearable.",
    ],
  },
  {
    id: "sharpe",
    title: "Sharpe Ratio",
    content: [
      "A risk-adjusted return metric that measures excess return per unit of risk (volatility).",
      "Formula: Sharpe = (Mean Return - Risk-Free Rate) / Std Dev of Returns",
      "Sharpe < 1.0: Poor | 1.0-2.0: Good | 2.0-3.0: Very good | > 3.0: Exceptional",
    ],
  },
  {
    id: "trades",
    title: "# Trades",
    content: [
      "The total number of round-trip trades (buy and sell pairs) executed during the backtest period.",
      "More trades mean higher transaction costs. A strategy with 500 trades vs. 50 trades needs to generate enough extra return to justify the additional costs.",
    ],
  },
  {
    id: "win-rate",
    title: "Win % (Win Rate)",
    content: [
      "The percentage of trades that were profitable.",
      "Formula: Win Rate = (Winning Trades / Total Trades) x 100",
      "Win rate alone is misleading. A strategy with 90% win rate but small wins and large losses can still lose money. Always consider win rate alongside average win/loss size.",
    ],
  },
]

const signals = [
  {
    id: "signal",
    title: "Signal (-1, 0, +1)",
    content: [
      "+1 (BUY): Strategy indicates a long position should be taken.",
      "0 (HOLD): Strategy indicates holding current position or staying in cash.",
      "-1 (SELL): Strategy indicates closing positions or taking a short position.",
      "The final stock signal is computed by combining individual strategy signals using either majority vote or weighted vote (typically CAGR-weighted).",
    ],
  },
  {
    id: "cooldown-bars",
    title: "Cooldown Bars",
    content: [
      "The minimum number of time periods (bars) that must pass between consecutive trades. Prevents overtrading and reduces transaction costs.",
      "With cooldown_bars=5 on daily data, after selling a position, the strategy must wait at least 5 days before buying again.",
    ],
  },
]

const strategies = [
  {
    id: "rsi",
    title: "RSI (Relative Strength Index)",
    content: [
      "A momentum oscillator ranging 0-100. RSI > 70: overbought (sell). RSI < 30: oversold (buy).",
      "Parameters: rsi_window (14), rsi_overbought (70), rsi_oversold (30).",
    ],
  },
  {
    id: "macd",
    title: "MACD (Moving Average Convergence Divergence)",
    content: [
      "Trend-following momentum indicator. Buy when MACD line crosses above signal line; sell when it crosses below.",
      "Parameters: macd_fast_window (12), macd_slow_window (26), macd_signal_window (9).",
    ],
  },
  {
    id: "bollinger",
    title: "Bollinger Bands",
    content: [
      "Volatility bands above and below a moving average. Price at lower band = oversold. Price at upper band = overbought.",
      "Parameters: bb_window (20), bb_k (2.0 standard deviations).",
    ],
  },
  {
    id: "sma",
    title: "SMA (Simple Moving Average)",
    content: [
      "Average price over N periods. Price > SMA = bullish. Price < SMA = bearish.",
      "Parameters: window (50 or 200 commonly).",
    ],
  },
  {
    id: "ichimoku",
    title: "Ichimoku Cloud",
    content: [
      "Multi-line trend system with support/resistance cloud. Signals based on Tenkan/Kijun crosses and cloud position.",
      "Parameters: tenkan (9), kijun (26), senkou_b (52), shift (26).",
    ],
  },
]

const portfolio = [
  {
    id: "buy_pct_cash",
    title: "buy_pct_cash",
    content: ["Percentage of available cash to use when buying (1.0 = 100%, 0.5 = 50%)."],
  },
  {
    id: "sell_pct_shares",
    title: "sell_pct_shares",
    content: ["Percentage of held shares to sell when selling (1.0 = 100%, 0.25 = 25%)."],
  },
  {
    id: "min_return_before_sell",
    title: "min_return_before_sell",
    content: ["Minimum return threshold before allowing a sell (prevents premature exits)."],
  },
]

function GlossarySection({
  title,
  items,
}: {
  title: string
  items: { id: string; title: string; content: string[] }[]
}) {
  return (
    <div>
      <h2 className="mb-4 text-lg font-bold text-foreground">{title}</h2>
      <div className="space-y-4">
        {items.map((item) => (
          <div
            key={item.id}
            id={item.id}
            className="rounded-lg border border-border bg-card p-4"
          >
            <h3 className="font-semibold text-foreground">{item.title}</h3>
            <div className="mt-2 space-y-1.5">
              {item.content.map((line, idx) => (
                <p key={idx} className="text-sm text-muted-foreground leading-relaxed">
                  {line}
                </p>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function GlossaryPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground text-balance">
          Metrics & Parameters Glossary
        </h1>
        <p className="text-sm text-muted-foreground">
          Definitions for all performance metrics, signals, and strategy parameters
        </p>
      </div>

      <Card>
        <CardContent className="space-y-8 p-6">
          <GlossarySection title="Performance Metrics" items={metrics} />
          <Separator />
          <GlossarySection title="Signals & Trading" items={signals} />
          <Separator />
          <GlossarySection title="Strategy Indicators" items={strategies} />
          <Separator />
          <GlossarySection title="Portfolio Parameters" items={portfolio} />

          <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
            <p className="text-sm text-foreground">
              <strong>Need more information?</strong> These metrics and parameters are industry-standard tools for quantitative trading. For deeper understanding, we recommend &ldquo;Quantitative Trading&rdquo; by Ernest Chan or &ldquo;Evidence-Based Technical Analysis&rdquo; by David Aronson.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
