export const STRAT_PARAM_KEYS: Record<string, string[]> = {
  sma_price: ["strategy.sma_window", "strategy.signal_mode"],
  ma_cross: ["strategy.sma_fast_window", "strategy.sma_slow_window"],
  rsi: ["strategy.rsi_window", "strategy.rsi_oversold", "strategy.rsi_overbought"],
  macd: ["strategy.macd_fast_window", "strategy.macd_slow_window", "strategy.macd_signal_window"],
  bollinger: ["strategy.bb_window", "strategy.bb_k"],
  obv: ["strategy.obv_span"],
  stoch_vwap: ["strategy.k_window", "strategy.d_window", "strategy.smooth_k", "strategy.vwap_window"],
  ichimoku: ["strategy.tenkan", "strategy.kijun", "strategy.senkou_b", "strategy.shift"],
}

export const PORTF_KEYS = [
  "portfolio.cooldown_bars",
  "portfolio.buy_pct_cash",
  "portfolio.sell_pct_shares",
]
