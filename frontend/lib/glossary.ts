export type GlossaryLanguage = "fr" | "en"

export type LocalizedText = Record<GlossaryLanguage, string>

export type GlossaryLink = {
  label: LocalizedText
  href: string
}

export type GlossaryCategory = {
  id: string
  label: LocalizedText
  description: LocalizedText
}

export type GlossaryEntry = {
  id: string
  categoryId: string
  title: LocalizedText
  plain: LocalizedText
  details?: LocalizedText[]
  example?: LocalizedText
  formula?: string
  aliases?: string[]
  tags?: string[]
  appLinks?: GlossaryLink[]
}

export const glossaryCategories: GlossaryCategory[] = [
  {
    id: "app",
    label: { fr: "Navigation de l'app", en: "App navigation" },
    description: {
      fr: "Où aller dans l'application et quoi lire sur chaque page.",
      en: "Where to go in the application and what each page means.",
    },
  },
  {
    id: "scores",
    label: { fr: "Scores et signaux", en: "Scores and signals" },
    description: {
      fr: "Lecture des scores, badges et familles du Signal Engine.",
      en: "How to read Signal Engine scores, badges, and families.",
    },
  },
  {
    id: "indicators",
    label: { fr: "Indicateurs techniques", en: "Technical indicators" },
    description: {
      fr: "Les 20 indicateurs utilisés par les familles Tendance, Momentum, Oscillation et Volume.",
      en: "The 20 indicators used by the Trend, Momentum, Oscillation, and Volume families.",
    },
  },
  {
    id: "edge",
    label: { fr: "Edge et décision", en: "Edge and decision" },
    description: {
      fr: "Preuve statistique, rendement attendu, gates et ticket de décision.",
      en: "Statistical proof, expected return, gates, and decision ticket.",
    },
  },
  {
    id: "analytics",
    label: { fr: "Analytics", en: "Analytics" },
    description: {
      fr: "IC, hit rate, buckets, méthodes OOS et facteurs macro.",
      en: "IC, hit rate, buckets, OOS methods, and macro factors.",
    },
  },
  {
    id: "fundamentals",
    label: { fr: "Valorisation fondamentale", en: "Fundamental valuation" },
    description: {
      fr: "DCF, flux de trésorerie, taux d'actualisation, valeur terminale, multiples et combinaison des modèles utilisés dans le mode fondamental.",
      en: "DCF, cash flows, discount rate, terminal value, multiples, and the model ensemble used in fundamental mode.",
    },
  },
  {
    id: "backtest",
    label: { fr: "Backtest et résultats", en: "Backtest and results" },
    description: {
      fr: "Métriques de performance, WFO, Monte Carlo et ledger de trades.",
      en: "Performance metrics, WFO, Monte Carlo, and trade ledger.",
    },
  },
  {
    id: "data",
    label: { fr: "Données", en: "Data" },
    description: {
      fr: "Catalogue marché, liquidité, prix et champs visibles dans les tables.",
      en: "Market catalog, liquidity, prices, and fields shown in tables.",
    },
  },
  {
    id: "quality-screens",
    label: { fr: "Qualité & écrans", en: "Quality & screens" },
    description: {
      fr: "Ratios de qualité, écrans de risque et multiples de marché utilisés dans les onglets Comparables et Synthèse.",
      en: "Quality ratios, risk screens, and market multiples used in the Comparables and Synthèse tabs.",
    },
  },
]

export const quickGlossaryLinks: GlossaryLink[] = [
  { label: { fr: "Tableau de Bord", en: "Dashboard" }, href: "#dashboard" },
  { label: { fr: "Figures", en: "Figures" }, href: "#figures-explication" },
  { label: { fr: "Score global", en: "Global score" }, href: "#score-composite" },
  { label: { fr: "Méthode scoring", en: "Scoring method" }, href: "#scoring-methodology" },
  { label: { fr: "Expected return", en: "Expected return" }, href: "#expected-return" },
  { label: { fr: "Score composite", en: "Composite score" }, href: "#score-composite" },
  { label: { fr: "Signal Engine", en: "Signal Engine" }, href: "#signal-engine" },
  { label: { fr: "DCF", en: "DCF" }, href: "#dcf" },
  { label: { fr: "Valeur terminale", en: "Terminal value" }, href: "#terminal-value" },
  { label: { fr: "WFO", en: "WFO" }, href: "#wfo" },
  { label: { fr: "Edge", en: "Edge" }, href: "#edge" },
  { label: { fr: "IC", en: "IC" }, href: "#ic" },
  { label: { fr: "Hit rate", en: "Hit rate" }, href: "#hit-rate" },
  { label: { fr: "ADV20", en: "ADV20" }, href: "#adv20" },
  { label: { fr: "Blotter", en: "Blotter" }, href: "#daily-blotter" },
  { label: { fr: "CAGR", en: "CAGR" }, href: "#cagr" },
  { label: { fr: "Sharpe", en: "Sharpe" }, href: "#sharpe" },
  { label: { fr: "Max drawdown", en: "Max drawdown" }, href: "#max-drawdown" },
]

const dashboardLink: GlossaryLink = {
  label: { fr: "Voir le Tableau de Bord", en: "Open Dashboard" },
  href: "/dashboard",
}

const dataLink: GlossaryLink = {
  label: { fr: "Voir Data", en: "Open Data" },
  href: "/data",
}

const signalsLink: GlossaryLink = {
  label: { fr: "Voir Signals", en: "Open Signals" },
  href: "/signals",
}

const strategyLink: GlossaryLink = {
  label: { fr: "Voir Strategy", en: "Open Strategy" },
  href: "/strategy",
}

const backtestLink: GlossaryLink = {
  label: { fr: "Voir Backtest", en: "Open Backtest" },
  href: "/backtest",
}

const analyticsLink: GlossaryLink = {
  label: { fr: "Voir Analytics", en: "Open Analytics" },
  href: "/analytics",
}

const fundamentalsLink: GlossaryLink = {
  label: { fr: "Voir le mode fondamental", en: "Open fundamental mode" },
  href: "/signals?mode=fundamental",
}

export const glossaryEntries: GlossaryEntry[] = [
  {
    id: "dashboard",
    categoryId: "app",
    title: { fr: "Tableau de Bord", en: "Dashboard" },
    plain: {
      fr: "La page de pilotage rapide. Elle classe les titres, montre les scores par famille, le signal final, le meilleur edge disponible et le ticket de portefeuille.",
      en: "The fast decision page. It ranks stocks and shows family scores, the final signal, the best available edge, and the portfolio ticket.",
    },
    details: [
      {
        fr: "Commence ici quand tu veux savoir quoi regarder aujourd'hui: filtre le marché, choisis l'horizon, puis ouvre le détail d'un titre si le signal semble intéressant.",
        en: "Start here when you want to know what to review today: filter the market, choose the horizon, then open a stock detail when a signal looks interesting.",
      },
    ],
    aliases: ["home", "v1", "tableau"],
    appLinks: [dashboardLink],
  },
  {
    id: "data",
    categoryId: "app",
    title: { fr: "Data", en: "Data" },
    plain: {
      fr: "La page qui vérifie si les instruments ont des prix exploitables. Elle sert à contrôler le catalogue, la fraîcheur des données et la couverture par marché.",
      en: "The page that checks whether instruments have usable prices. It controls the catalog, data freshness, and market coverage.",
    },
    aliases: ["donnees", "catalogue"],
    appLinks: [dataLink],
  },
  {
    id: "signals",
    categoryId: "app",
    title: { fr: "Signals", en: "Signals" },
    plain: {
      fr: "La page d'analyse par titre. Elle explique pourquoi le Signal Engine, WFO ou Factor x TA donne un score, avec graphiques, représentants, évidence WFO et backtest MC.",
      en: "The per-stock analysis page. It explains why Signal Engine, WFO, or Factor x TA produced a score, with charts, representatives, WFO evidence, and MC backtest.",
    },
    aliases: ["signaux", "detail titre"],
    appLinks: [signalsLink],
  },
  {
    id: "strategy",
    categoryId: "app",
    title: { fr: "Strategy", en: "Strategy" },
    plain: {
      fr: "Le constructeur de stratégie. Tu choisis l'univers, l'allocation, le type de stratégie, les signaux, les règles d'entrée, les sorties et le risque.",
      en: "The strategy builder. You choose the universe, allocation, strategy type, signals, entry rules, exits, and risk.",
    },
    aliases: ["constructeur", "rules", "strategie"],
    appLinks: [strategyLink],
  },
  {
    id: "backtest",
    categoryId: "app",
    title: { fr: "Backtest", en: "Backtest" },
    plain: {
      fr: "La page qui teste une stratégie sur l'historique. Le mode Direct applique les règles actuelles; le mode WFO optimise sur des fenêtres passées puis teste sur des périodes non vues.",
      en: "The page that tests a strategy on history. Direct mode applies current rules; WFO mode optimizes on past windows and tests on unseen periods.",
    },
    aliases: ["test", "runner", "wfo run"],
    appLinks: [backtestLink],
  },
  {
    id: "analytics",
    categoryId: "app",
    title: { fr: "Analytics", en: "Analytics" },
    plain: {
      fr: "La page qui mesure si les signaux ont vraiment prédit les rendements futurs. C'est ici qu'on lit l'IC, le hit rate, les buckets et les facteurs macro.",
      en: "The page that measures whether signals really predicted future returns. This is where IC, hit rate, buckets, and macro factors are read.",
    },
    aliases: ["ic", "predictive ability", "capacite predictive"],
    appLinks: [analyticsLink],
  },
  {
    id: "score-composite",
    categoryId: "scores",
    title: { fr: "Score composite", en: "Composite score" },
    plain: {
      fr: "Un chiffre entre -100 et +100 qui résume la conviction directionnelle d'un titre. Positif signifie plutôt achat; négatif signifie plutôt vente; proche de zéro signifie pas de signal clair.",
      en: "A number from -100 to +100 summarizing directional conviction for a stock. Positive means more buy-like, negative means more sell-like, near zero means no clear signal.",
    },
    details: [
      {
        fr: "Le score agrège les familles Tendance, Momentum, Oscillation et Volume. Il ne doit pas être lu seul: il faut vérifier l'edge, la liquidité et le contexte.",
        en: "The score aggregates Trend, Momentum, Oscillation, and Volume families. It should not be read alone: check edge, liquidity, and context.",
      },
      {
        fr: "Lecture pratique: le score global dit la direction et la force du signal maintenant. L'edge et l'expected return disent si ce type de signal a historiquement produit un résultat exploitable.",
        en: "Practical read: the global score tells current signal direction and strength. Edge and expected return tell whether this kind of signal historically produced something usable.",
      },
    ],
    formula: "Score global = somme(score famille x poids famille), borne entre -100 et +100",
    example: {
      fr: "+62 peut devenir Achat fort; -34 peut devenir Vente; +4 reste Neutre.",
      en: "+62 may become Strong Buy; -34 may become Sell; +4 remains Neutral.",
    },
    aliases: ["aggregate_score_pct", "score", "global score", "consensus score"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "scoring-methodology",
    categoryId: "scores",
    title: { fr: "Méthode de scoring", en: "Scoring methodology" },
    plain: {
      fr: "La méthode qui transforme plusieurs indicateurs techniques en un score global lisible. L'app calcule d'abord des scores par indicateur, les regroupe par famille, puis combine les familles dans un score final.",
      en: "The method that turns several technical indicators into one readable global score. The app first computes indicator scores, groups them by family, then combines the families into the final score.",
    },
    details: [
      {
        fr: "Chaque indicateur vote dans son langage: tendance, accélération, excès ou confirmation par volume. Le score de famille résume ces votes avant que le score global les combine.",
        en: "Each indicator votes in its own language: trend, acceleration, excess, or volume confirmation. The family score summarizes those votes before the global score combines them.",
      },
      {
        fr: "Le scoring est une lecture de marché, pas une preuve statistique. Pour décider si le signal est exploitable, l'app compare ensuite ce score avec l'edge, les gates et l'expected return.",
        en: "Scoring is a market read, not statistical proof. To decide whether the signal is usable, the app then compares this score with edge, gates, and expected return.",
      },
    ],
    formula: "Indicateurs -> scores de famille -> score global -> badge signal -> validation edge",
    example: {
      fr: "Tendance +70, Momentum +40, Oscillation -10, Volume +30 donnent un score global positif, mais l'app vérifie encore l'edge avant de proposer un ticket.",
      en: "Trend +70, Momentum +40, Oscillation -10, Volume +30 produce a positive global score, but the app still checks edge before proposing a ticket.",
    },
    aliases: ["methodology", "global scoring", "score methodology", "scoring"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "signal-badge",
    categoryId: "scores",
    title: { fr: "Badge signal", en: "Signal badge" },
    plain: {
      fr: "La traduction lisible du score. Exemple: Achat fort, Achat, Neutre, Vente ou Vente forte pour le signal final.",
      en: "The readable translation of a score. Example: Strong Buy, Buy, Neutral, Sell, or Strong Sell for the final signal.",
    },
    details: [
      {
        fr: "Attention: les familles n'utilisent pas toutes les mêmes mots. Oscillation parle de Survendu/Suracheté, Volume parle d'Accumulation/Distribution.",
        en: "Careful: families do not all use the same wording. Oscillation uses Oversold/Overbought, Volume uses Accumulation/Distribution.",
      },
    ],
    aliases: ["aggregate_signal_label", "label", "badge"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "signal-engine",
    categoryId: "scores",
    title: { fr: "Signal Engine", en: "Signal Engine" },
    plain: {
      fr: "Le moteur qui calcule les scores techniques avec des paramètres fixes et explicables. Il sert de référence rapide avant de regarder WFO ou l'edge statistique.",
      en: "The engine that computes technical scores with fixed, explainable parameters. It is the fast reference before checking WFO or statistical edge.",
    },
    details: [
      {
        fr: "Dans l'app, Signal Engine peut être comparé à WFO. Si les deux vont dans le même sens, la lecture est plus confortable; s'ils divergent, il faut ouvrir le détail.",
        en: "In the app, Signal Engine can be compared with WFO. If both point the same way, the read is more comfortable; if they diverge, open the detail.",
      },
    ],
    aliases: ["engine", "A-G", "A->G", "score source"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "wfo",
    categoryId: "scores",
    title: { fr: "WFO - Walk-Forward Optimization", en: "WFO - Walk-Forward Optimization" },
    plain: {
      fr: "Une méthode qui optimise les paramètres sur une fenêtre passée, puis les teste sur une fenêtre future non vue. Elle imite mieux une décision prise dans le temps.",
      en: "A method that optimizes parameters on a past window, then tests them on a future unseen window. It better imitates decisions made through time.",
    },
    details: [
      {
        fr: "WFO aide à réduire le surapprentissage: une configuration brillante dans le passé mais mauvaise hors échantillon sera pénalisée.",
        en: "WFO helps reduce overfitting: a configuration that is brilliant in-sample but poor out-of-sample is penalized.",
      },
    ],
    aliases: ["walk forward", "walk-forward", "optimization", "optimise"],
    appLinks: [signalsLink, backtestLink],
  },
  {
    id: "score-source",
    categoryId: "scores",
    title: { fr: "Source du score", en: "Score source" },
    plain: {
      fr: "Le choix entre Signal Engine, WFO ou Both. Il détermine quel score est affiché dans la table et quel signal sert de base à certains tris.",
      en: "The choice between Signal Engine, WFO, or Both. It determines which score appears in the table and which signal drives some sorting.",
    },
    aliases: ["both", "source", "wfo vs engine"],
    appLinks: [dashboardLink],
  },
  {
    id: "familles-indicateurs",
    categoryId: "scores",
    title: { fr: "Familles d'indicateurs", en: "Indicator families" },
    plain: {
      fr: "Les quatre blocs qui composent le score: Tendance, Momentum, Oscillation et Volume. Chaque famille lit un aspect différent du marché.",
      en: "The four blocks behind the score: Trend, Momentum, Oscillation, and Volume. Each family reads a different market dimension.",
    },
    aliases: ["families", "per_family"],
    appLinks: [dashboardLink, signalsLink, strategyLink],
  },
  {
    id: "tendance",
    categoryId: "scores",
    title: { fr: "Tendance", en: "Trend" },
    plain: {
      fr: "La famille qui regarde la direction générale du prix. Un score positif indique que le prix confirme plutôt une tendance haussière.",
      en: "The family that reads the general price direction. A positive score means price action is more consistent with an uptrend.",
    },
    details: [
      {
        fr: "Indicateurs inclus: SMA, EMA, EMA Cross, Ichimoku et PSAR.",
        en: "Included indicators: SMA, EMA, EMA Cross, Ichimoku, and PSAR.",
      },
    ],
    aliases: ["trend", "trend_score"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "momentum",
    categoryId: "scores",
    title: { fr: "Momentum", en: "Momentum" },
    plain: {
      fr: "La famille qui mesure la vitesse du mouvement. Un score positif veut dire que l'élan actuel soutient plutôt une hausse.",
      en: "The family that measures movement speed. A positive score means current momentum supports an upward move.",
    },
    details: [
      {
        fr: "Indicateurs inclus: MACD, ROC, TRIX, ADX et TSI.",
        en: "Included indicators: MACD, ROC, TRIX, ADX, and TSI.",
      },
    ],
    aliases: ["momentum_score"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "oscillation",
    categoryId: "scores",
    title: { fr: "Oscillation", en: "Oscillation" },
    plain: {
      fr: "La famille qui lit les zones de surachat et de survente. Elle sert souvent à détecter un excès qui peut se normaliser.",
      en: "The family that reads overbought and oversold zones. It often detects an excess that may normalize.",
    },
    details: [
      {
        fr: "Indicateurs inclus: RSI, Stochastic, CCI, MFI et Ultimate Oscillator.",
        en: "Included indicators: RSI, Stochastic, CCI, MFI, and Ultimate Oscillator.",
      },
    ],
    aliases: ["oscillator", "oscillation_score"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "volume",
    categoryId: "scores",
    title: { fr: "Volume", en: "Volume" },
    plain: {
      fr: "La famille qui regarde si les volumes confirment l'achat ou la vente. Accumulation signifie pression acheteuse; distribution signifie pression vendeuse.",
      en: "The family that checks whether volume confirms buying or selling. Accumulation means buying pressure; distribution means selling pressure.",
    },
    details: [
      {
        fr: "Indicateurs inclus: OBV, CMF, A/D Line, VWAP et Force Index.",
        en: "Included indicators: OBV, CMF, A/D Line, VWAP, and Force Index.",
      },
    ],
    aliases: ["volume_score", "accumulation", "distribution"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "sma",
    categoryId: "indicators",
    title: { fr: "SMA - Simple Moving Average", en: "SMA - Simple Moving Average" },
    plain: {
      fr: "Moyenne simple du prix sur une période. Prix au-dessus de la SMA: tendance plus positive; prix en dessous: tendance plus négative.",
      en: "Simple average of price over a period. Price above SMA is more positive; price below SMA is more negative.",
    },
    aliases: ["simple moving average", "moyenne mobile simple"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "ema",
    categoryId: "indicators",
    title: { fr: "EMA - Exponential Moving Average", en: "EMA - Exponential Moving Average" },
    plain: {
      fr: "Moyenne mobile qui donne plus de poids aux prix récents. Elle réagit plus vite que la SMA.",
      en: "Moving average that gives more weight to recent prices. It reacts faster than SMA.",
    },
    aliases: ["exponential moving average", "moyenne exponentielle"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "ema-cross",
    categoryId: "indicators",
    title: { fr: "EMA Cross", en: "EMA Cross" },
    plain: {
      fr: "Compare une EMA rapide et une EMA lente. Quand la rapide passe au-dessus, le signal devient plus haussier; l'inverse devient plus baissier.",
      en: "Compares a fast EMA and a slow EMA. When the fast line crosses above, the signal turns more bullish; the reverse is more bearish.",
    },
    aliases: ["ema_cross", "croisement ema"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "ichimoku",
    categoryId: "indicators",
    title: { fr: "Ichimoku", en: "Ichimoku" },
    plain: {
      fr: "Système de tendance àvec plusieurs lignes et un nuage. Il aide à lire tendance, support, résistance et équilibre du prix.",
      en: "Trend system with several lines and a cloud. It helps read trend, support, resistance, and price balance.",
    },
    aliases: ["cloud", "nuage ichimoku"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "psar",
    categoryId: "indicators",
    title: { fr: "PSAR - Parabolic SAR", en: "PSAR - Parabolic SAR" },
    plain: {
      fr: "Points de suivi de tendance. Quand les points changent de cote par rapport au prix, cela signale souvent un retournement.",
      en: "Trend-following dots. When dots switch side relative to price, it often signals a reversal.",
    },
    aliases: ["parabolic sar"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "macd",
    categoryId: "indicators",
    title: { fr: "MACD", en: "MACD" },
    plain: {
      fr: "Indicateur de momentum basé sur deux moyennes exponentielles. Il lit l'accélération et les croisements de tendance.",
      en: "Momentum indicator based on two exponential averages. It reads acceleration and trend crosses.",
    },
    aliases: ["moving average convergence divergence"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "roc",
    categoryId: "indicators",
    title: { fr: "ROC - Rate of Change", en: "ROC - Rate of Change" },
    plain: {
      fr: "Variation du prix sur N périodes. Un ROC positif indique que le prix est au-dessus de son niveau passé.",
      en: "Price change over N periods. A positive ROC means price is above its past level.",
    },
    aliases: ["rate of change"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "trix",
    categoryId: "indicators",
    title: { fr: "TRIX", en: "TRIX" },
    plain: {
      fr: "Momentum lisse à partir d'une triple EMA. Il filtre une partie du bruit court terme.",
      en: "Smoothed momentum built from a triple EMA. It filters part of short-term noise.",
    },
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "adx",
    categoryId: "indicators",
    title: { fr: "ADX", en: "ADX" },
    plain: {
      fr: "Mesure la force de la tendance, pas seulement sa direction. Un ADX élevé veut dire que le mouvement est plus structuré.",
      en: "Measures trend strength, not only direction. A high ADX means the move is more structured.",
    },
    aliases: ["average directional index"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "tsi",
    categoryId: "indicators",
    title: { fr: "TSI - True Strength Index", en: "TSI - True Strength Index" },
    plain: {
      fr: "Momentum doublement lisse autour de zéro. Il aide à lire la force et la direction de l'élan.",
      en: "Double-smoothed momentum around zero. It helps read the strength and direction of momentum.",
    },
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "rsi",
    categoryId: "indicators",
    title: { fr: "RSI - Relative Strength Index", en: "RSI - Relative Strength Index" },
    plain: {
      fr: "Oscillateur entre 0 et 100. Haut = risque de surachat; bas = risque de survente.",
      en: "Oscillator from 0 to 100. High means overbought risk; low means oversold risk.",
    },
    aliases: ["relative strength index"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "stochastic",
    categoryId: "indicators",
    title: { fr: "Stochastic", en: "Stochastic" },
    plain: {
      fr: "Mesure où se situe le prix dans son range récent. Proche du haut: pression haussière déjà avancée; proche du bas: titre potentiellement survendu.",
      en: "Measures where price sits within its recent range. Near the top: advanced bullish pressure; near the bottom: potentially oversold.",
    },
    aliases: ["stoch", "%K", "%D"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "cci",
    categoryId: "indicators",
    title: { fr: "CCI - Commodity Channel Index", en: "CCI - Commodity Channel Index" },
    plain: {
      fr: "Mesure l'écart du prix typique par rapport à sa moyenne. Il détecte les excès au-dessus ou en dessous du régime récent.",
      en: "Measures the typical price deviation from its average. It detects excess above or below the recent regime.",
    },
    aliases: ["commodity channel index"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "mfi",
    categoryId: "indicators",
    title: { fr: "MFI - Money Flow Index", en: "MFI - Money Flow Index" },
    plain: {
      fr: "RSI enrichi par le volume. Il cherche les zones de surachat/survente avec la pression de flux.",
      en: "RSI enriched with volume. It looks for overbought/oversold zones using flow pressure.",
    },
    aliases: ["money flow index"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "uo",
    categoryId: "indicators",
    title: { fr: "Ultimate Oscillator", en: "Ultimate Oscillator" },
    plain: {
      fr: "Oscillateur qui combine plusieurs horizons. Il évite de juger le titre sur une seule fenêtre trop courte.",
      en: "Oscillator combining several horizons. It avoids judging a stock from only one short window.",
    },
    aliases: ["ultimate oscillator"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "obv",
    categoryId: "indicators",
    title: { fr: "OBV - On-Balance Volume", en: "OBV - On-Balance Volume" },
    plain: {
      fr: "Cumule le volume en fonction des jours de hausse ou de baisse. Il cherche si le volume accompagne le mouvement.",
      en: "Cumulated volume based on up or down days. It checks whether volume supports the move.",
    },
    aliases: ["on balance volume"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "cmf",
    categoryId: "indicators",
    title: { fr: "CMF - Chaikin Money Flow", en: "CMF - Chaikin Money Flow" },
    plain: {
      fr: "Mesure si les clôtures se font plutôt près des hauts ou des bas, pondérées par le volume.",
      en: "Measures whether closes happen nearer highs or lows, weighted by volume.",
    },
    aliases: ["chaikin money flow"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "ad-line",
    categoryId: "indicators",
    title: { fr: "A/D Line - Accumulation/Distribution", en: "A/D Line - Accumulation/Distribution" },
    plain: {
      fr: "Ligne qui cumule l'accumulation ou la distribution estimée par prix et volume. Elle aide à voir si les flux confirment le prix.",
      en: "Line that cumulates estimated accumulation or distribution from price and volume. It helps see whether flows confirm price.",
    },
    aliases: ["ad", "a/d", "accumulation distribution"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "vwap",
    categoryId: "indicators",
    title: { fr: "VWAP", en: "VWAP" },
    plain: {
      fr: "Prix moyen pondéré par le volume. Dans l'app, il sert à voir si le prix est cher ou bon marché par rapport aux volumes récents.",
      en: "Volume-weighted average price. In the app, it helps see whether price is expensive or cheap relative to recent volume.",
    },
    aliases: ["volume weighted average price"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "force-index",
    categoryId: "indicators",
    title: { fr: "Force Index", en: "Force Index" },
    plain: {
      fr: "Combine variation de prix et volume. Il cherche si un mouvement a une vraie force derrière lui.",
      en: "Combines price change and volume. It checks whether a move has real force behind it.",
    },
    aliases: ["fi"],
    appLinks: [signalsLink, strategyLink],
  },
  {
    id: "edge",
    categoryId: "edge",
    title: { fr: "Edge", en: "Edge" },
    plain: {
      fr: "Avantage statistique mesuré sur l'historique hors échantillon. Un signal a de l'edge quand les observations passées montrent un rendement attendu positif et robuste.",
      en: "Statistical advantage measured on out-of-sample history. A signal has edge when past observations show positive and robust expected return.",
    },
    details: [
      {
        fr: "Dans le Tableau de Bord, Edge ne veut pas dire garantie. Cela veut dire: les tests disponibles sont assez bons pour classer l'idée comme exploitable ou à surveiller.",
        en: "In the Dashboard, Edge does not mean guarantee. It means available tests are good enough to classify the idea as usable or watch-worthy.",
      },
    ],
    aliases: ["proven edge", "best edge", "edge ratio"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "best-signal",
    categoryId: "edge",
    title: { fr: "Meilleure méthode auto", en: "Best automatic method" },
    plain: {
      fr: "La méthode que l'app choisit comme meilleure candidate pour ce titre et cet horizon, selon l'edge net, la taille d'échantillon et les gates.",
      en: "The method the app selects as the best candidate for this stock and horizon, based on net edge, sample size, and gates.",
    },
    aliases: ["best_signal", "methode auto"],
    appLinks: [dashboardLink],
  },
  {
    id: "edge-selection",
    categoryId: "edge",
    title: { fr: "Sélection de l'edge", en: "Edge selection" },
    plain: {
      fr: "La logique qui choisit quel edge mettre en avant. L'app compare les méthodes candidates, retire celles qui manquent d'observations ou échouent les gates, puis privilégie le meilleur rendement attendu net robuste.",
      en: "The logic that chooses which edge to highlight. The app compares candidate methods, removes those with too few observations or failed gates, then favors the best robust net expected return.",
    },
    details: [
      {
        fr: "Un edge peut être écarté même avec un bon rendement moyen si l'échantillon est trop petit, si le test Monte Carlo ressemble au hasard, ou si la borne Wilson rend le hit rate trop incertain.",
        en: "An edge can be rejected even with a good average return if the sample is too small, if Monte Carlo looks like luck, or if the Wilson bound makes hit rate too uncertain.",
      },
      {
        fr: "La meilleure méthode auto n'est donc pas seulement le plus grand chiffre: c'est le meilleur compromis entre rendement attendu, robustesse, couverture et sens de l'action.",
        en: "The best automatic method is therefore not just the largest number: it is the best tradeoff between expected return, robustness, coverage, and action side.",
      },
    ],
    formula: "Choix edge = max(E[R] net robuste) parmi les méthodes qui passent les gates",
    aliases: ["edge choice", "edge ranking", "best edge selection"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "expected-return",
    categoryId: "edge",
    title: { fr: "Expected return - E[R]", en: "Expected return - E[R]" },
    plain: {
      fr: "Rendement moyen attendu d'une action ou d'un signal sur l'horizon choisi. Il répond à: si on reprend ce type de signal dans des conditions similaires, combien peut-on attendre en moyenne?",
      en: "Average expected return of an action or signal over the selected horizon. It answers: if we repeat this kind of signal in similar conditions, what can we expect on average?",
    },
    details: [
      {
        fr: "L'app distingue Stock E[R] et Action E[R]. Stock E[R] lit le rendement futur du titre. Action E[R] remet ce rendement dans le sens de la décision: long, short ou no trade.",
        en: "The app separates Stock E[R] and Action E[R]. Stock E[R] reads the stock's future return. Action E[R] converts that return into the decision side: long, short, or no trade.",
      },
      {
        fr: "En mode net, l'expected return retire les coûts estimés. C'est ce chiffre net qui doit guider le ranking, car un signal profitable brut peut devenir inutile après coûts.",
        en: "In net mode, expected return subtracts estimated costs. This net value should drive ranking because a profitable gross signal can become useless after costs.",
      },
    ],
    formula: "E[R] net = P(gain) x gain moyen - P(perte) x perte moyenne - coûts",
    example: {
      fr: "Si le signal gagne 55% du temps avec +2.0% moyen, perd 45% du temps avec -1.2% moyen, et coûte 0.2%, E[R] net = 0.55x2.0 - 0.45x1.2 - 0.2 = +0.36%.",
      en: "If the signal wins 55% of the time with +2.0% average win, loses 45% with -1.2% average loss, and costs 0.2%, net E[R] = 0.55x2.0 - 0.45x1.2 - 0.2 = +0.36%.",
    },
    aliases: ["E[R]", "ER", "expected value", "net expected return", "action er", "stock er"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "action-er",
    categoryId: "edge",
    title: { fr: "Action E[R]", en: "Action E[R]" },
    plain: {
      fr: "Rendement attendu de l'action recommandée: long, short ou no trade. En mode net, les coûts sont déjà retirés.",
      en: "Expected return of the recommended action: long, short, or no trade. In net mode, costs are already deducted.",
    },
    details: [
      {
        fr: "Pour un signal long, Action E[R] suit le rendement du titre. Pour un signal short, il inverse le signe: une baisse du titre devient positive pour l'action short.",
        en: "For a long signal, Action E[R] follows the stock return. For a short signal, it flips the sign: a stock drop becomes positive for the short action.",
      },
    ],
    formula: "Action E[R] = moyenne des rendements futurs dans le sens de l'action, après coûts si mode net",
    aliases: ["expected return", "action_expected_return_net", "best er"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "stock-er",
    categoryId: "edge",
    title: { fr: "Stock E[R]", en: "Stock E[R]" },
    plain: {
      fr: "Rendement moyen futur du titre lui-même, avant inversion long/short. Il répond à la question: le titre a-t-il monté ou baissé après ce type de signal?",
      en: "Average future return of the stock itself, before long/short direction adjustment. It asks: did the stock rise or fall after this signal type?",
    },
    details: [
      {
        fr: "Stock E[R] est utile pour comprendre le comportement du titre. Action E[R] est plus utile pour prendre une décision de portefeuille.",
        en: "Stock E[R] is useful for understanding the stock behavior. Action E[R] is more useful for making a portfolio decision.",
      },
    ],
    aliases: ["stock_expected_return"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "proven-edge",
    categoryId: "edge",
    title: { fr: "Edge prouvé", en: "Proven edge" },
    plain: {
      fr: "Statut positif quand l'échantillon est suffisant et que les tests de robustesse acceptent le signal.",
      en: "Positive status when sample size is sufficient and robustness tests accept the signal.",
    },
    details: [
      {
        fr: "Si le badge dit À surveiller, cela peut rester intéressant, mais l'évidence statistique n'est pas encore assez forte.",
        en: "If the badge says Watch, it may still be interesting, but statistical evidence is not strong enough yet.",
      },
    ],
    aliases: ["proven_edge_net", "Prouve", "A surveiller"],
    appLinks: [dashboardLink],
  },
  {
    id: "edge-gates",
    categoryId: "edge",
    title: { fr: "Gates d'edge", en: "Edge gates" },
    plain: {
      fr: "Les contrôles que le signal doit passer avant d'être marqué comme edge prouvé: taille d'échantillon, Monte Carlo, label shuffle et borne Wilson.",
      en: "The checks a signal must pass before being marked as proven edge: sample size, Monte Carlo, label shuffle, and Wilson lower bound.",
    },
    aliases: ["gates", "mc gate", "wilson"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "mc-test",
    categoryId: "edge",
    title: { fr: "Test de chance MC", en: "MC luck test" },
    plain: {
      fr: "Test Monte Carlo qui estime si le résultat peut venir du hasard. Une p-value basse soutient l'idée que le signal contient de l'information.",
      en: "Monte Carlo test estimating whether the result may come from luck. A low p-value supports the idea that the signal contains information.",
    },
    aliases: ["mc_luck_pvalue", "monte carlo gate"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "label-shuffle",
    categoryId: "edge",
    title: { fr: "Label shuffle", en: "Label shuffle" },
    plain: {
      fr: "Test qui mélange les labels de signal. Si le signal original reste meilleur que les versions mélangées, il est moins probable que le résultat soit accidentel.",
      en: "Test that shuffles signal labels. If the original signal remains better than shuffled versions, the result is less likely to be accidental.",
    },
    aliases: ["shuffle", "label_shuffle_pvalue"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "wilson-lower-bound",
    categoryId: "edge",
    title: { fr: "Borne basse Wilson", en: "Wilson lower bound" },
    plain: {
      fr: "Borne prudente du hit rate. Elle évite de trop faire confiance à un taux de réussite élevé calculé sur trop peu d'observations.",
      en: "Conservative lower bound for hit rate. It prevents overtrusting a high win rate computed on too few observations.",
    },
    aliases: ["wilson", "hit_ci_lower"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "profit-factor",
    categoryId: "edge",
    title: { fr: "Profit factor", en: "Profit factor" },
    plain: {
      fr: "Rapport entre gains bruts et pertes brutes. Au-dessus de 1, les gains dépassent les pertes; en dessous de 1, les pertes dominent.",
      en: "Ratio between gross gains and gross losses. Above 1, gains exceed losses; below 1, losses dominate.",
    },
    formula: "Profit factor = gains bruts / pertes brutes absolues",
    aliases: ["PF", "profit_factor_net", "profit_factor_gross"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "expectancy",
    categoryId: "edge",
    title: { fr: "Expectance", en: "Expectancy" },
    plain: {
      fr: "Gain moyen attendu par trade en combinant probabilité de gain, gain moyen, probabilité de perte et perte moyenne.",
      en: "Average expected gain per trade combining win probability, average win, loss probability, and average loss.",
    },
    formula: "Expectance = P(gain) x gain moyen - P(perte) x perte moyenne",
    aliases: ["expectancy", "EV", "expected value"],
    appLinks: [dashboardLink, signalsLink],
  },
  {
    id: "side-policy",
    categoryId: "edge",
    title: { fr: "Side policy", en: "Side policy" },
    plain: {
      fr: "Règle qui dit si le système peut seulement acheter en long, ou aussi profiter des signaux baissiers en long/short.",
      en: "Rule defining whether the system can only buy long, or can also use bearish signals in long/short mode.",
    },
    aliases: ["long_only", "long_short", "sens"],
    appLinks: [dashboardLink, backtestLink],
  },
  {
    id: "ticket",
    categoryId: "edge",
    title: { fr: "Ticket portefeuille", en: "Portfolio ticket" },
    plain: {
      fr: "Proposition de quantités cibles à partir du capital, du cash buffer, des limites par titre/secteur et de l'edge.",
      en: "Proposed target quantities based on capital, cash buffer, per-stock/sector limits, and edge.",
    },
    aliases: ["portfolio ticket", "target_qty", "delta_qty"],
    appLinks: [dashboardLink],
  },
  {
    id: "daily-blotter",
    categoryId: "edge",
    title: { fr: "Daily blotter", en: "Daily blotter" },
    plain: {
      fr: "Liste opérationnelle des actions à faire: acheter, réduire, sortir, attendre ou revoir. C'est la traduction pratique du ticket.",
      en: "Operational list of actions to take: buy, reduce, exit, wait, or review. It is the practical translation of the ticket.",
    },
    aliases: ["blotter", "BUY", "REDUCE", "WATCH", "REVIEW"],
    appLinks: [dashboardLink],
  },
  {
    id: "kelly-fraction",
    categoryId: "edge",
    title: { fr: "Fraction Kelly", en: "Kelly fraction" },
    plain: {
      fr: "Règle de dimensionnement qui ajuste la taille selon l'avantage estimé. L'app l'utilise de façon fractionnée pour rester prudente.",
      en: "Sizing rule that adjusts size based on estimated advantage. The app uses it fractionally to stay conservative.",
    },
    aliases: ["kelly", "kelly_pct"],
    appLinks: [dashboardLink, strategyLink],
  },
  {
    id: "entry-zone",
    categoryId: "edge",
    title: { fr: "Zone d'entrée", en: "Entry zone" },
    plain: {
      fr: "Fourchette de prix où l'entrée est considérée acceptable. Si le prix est hors zone, l'app peut recommander d'attendre.",
      en: "Price range where entry is considered acceptable. If price is outside the zone, the app may recommend waiting.",
    },
    aliases: ["entry_zone", "entry_reference_price", "wait_for_pullback"],
    appLinks: [dashboardLink],
  },
  {
    id: "stop-loss",
    categoryId: "edge",
    title: { fr: "Stop loss", en: "Stop loss" },
    plain: {
      fr: "Niveau de sortie défensive si le scénario devient invalide. Il limite la perte au lieu d'attendre que le signal se dégrade.",
      en: "Defensive exit level if the scenario becomes invalid. It limits loss instead of waiting for the signal to deteriorate.",
    },
    aliases: ["SL", "stop"],
    appLinks: [dashboardLink, strategyLink, backtestLink],
  },
  {
    id: "take-profit",
    categoryId: "edge",
    title: { fr: "Take profit", en: "Take profit" },
    plain: {
      fr: "Niveau où une partie ou toute la position peut être vendue pour sécuriser le gain.",
      en: "Level where part or all of a position may be sold to lock in gains.",
    },
    aliases: ["TP", "target", "target_1"],
    appLinks: [dashboardLink, strategyLink, backtestLink],
  },
  {
    id: "ic",
    categoryId: "analytics",
    title: { fr: "IC - Information Coefficient", en: "IC - Information Coefficient" },
    plain: {
      fr: "Corrélation entre le rang du signal aujourd'hui et le rang du rendement futur. Si l'IC est positif, les meilleurs signaux ont eu tendance à être suivis de meilleurs rendements.",
      en: "Correlation between today's signal rank and future return rank. If IC is positive, better signals tended to be followed by better returns.",
    },
    formula: "IC = correlation de Spearman(signal_t, rendement futur_t+h)",
    aliases: ["information coefficient", "spearman_ic", "ic_h1", "mean_ic"],
    appLinks: [analyticsLink],
  },
  {
    id: "t-stat",
    categoryId: "analytics",
    title: { fr: "t-stat", en: "t-stat" },
    plain: {
      fr: "Mesure si un IC ou un résultat est assez loin de zéro pour être difficile à expliquer par le hasard.",
      en: "Measures whether an IC or result is far enough from zero to be hard to explain by chance.",
    },
    aliases: ["t_stat", "ic_t_stat"],
    appLinks: [analyticsLink],
  },
  {
    id: "fdr",
    categoryId: "analytics",
    title: { fr: "FDR pass", en: "FDR pass" },
    plain: {
      fr: "Contrôle statistique utilisé quand on teste beaucoup de signaux. Il réduit le risque de croire à un faux positif trouvé par hasard.",
      en: "Statistical control used when many signals are tested. It reduces the risk of believing a false positive found by chance.",
    },
    aliases: ["false discovery rate", "fdr_pass"],
    appLinks: [analyticsLink],
  },
  {
    id: "hit-rate",
    categoryId: "analytics",
    title: { fr: "Hit rate", en: "Hit rate" },
    plain: {
      fr: "Pourcentage de cas où le signal a donné la bonne direction. 50% ressemble à pile ou face; au-dessus de 50%, le signal commence à montrer une utilité.",
      en: "Percentage of cases where the signal got direction right. 50% looks like a coin flip; above 50%, the signal starts to show usefulness.",
    },
    formula: "Hit rate = trades corrects / trades testes",
    aliases: ["hit%", "win rate direction", "hit_ci_lower"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "bucket",
    categoryId: "analytics",
    title: { fr: "Bucket de signal", en: "Signal bucket" },
    plain: {
      fr: "Classe discrète du signal: strong_buy, buy, hold, sell ou strong_sell. Les matrices Analytics comparent les rendements futurs par bucket.",
      en: "Discrete signal class: strong_buy, buy, hold, sell, or strong_sell. Analytics matrices compare future returns by bucket.",
    },
    aliases: ["strong_buy", "buy", "hold", "sell", "strong_sell"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "forward-return",
    categoryId: "analytics",
    title: { fr: "Forward return", en: "Forward return" },
    plain: {
      fr: "Rendement réalisé après la date du signal. Exemple: forward 21j = rendement entre aujourd'hui et environ 21 séances plus tard.",
      en: "Return realized after the signal date. Example: 21d forward return = return from today to about 21 sessions later.",
    },
    aliases: ["fwd_h", "future return", "rendement futur"],
    appLinks: [analyticsLink],
  },
  {
    id: "methodes-retour-oos",
    categoryId: "analytics",
    title: { fr: "Méthodes de retour OOS", en: "OOS return methods" },
    plain: {
      fr: "Façons de mesurer le rendement futur hors échantillon: close-to-close, close-to-open, open-to-open et open-to-close.",
      en: "Ways to measure future out-of-sample return: close-to-close, close-to-open, open-to-open, and open-to-close.",
    },
    aliases: ["return_calc_method", "OOS method", "C-C", "C-O", "O-O", "O-C"],
    appLinks: [analyticsLink],
  },
  {
    id: "close-to-close",
    categoryId: "analytics",
    title: { fr: "C-C - Close to Close", en: "C-C - Close to Close" },
    plain: {
      fr: "Rendement entre une clôture et une clôture future. Lecture standard quand on raisonne en prix de clôture.",
      en: "Return from one close to a future close. Standard read when reasoning with closing prices.",
    },
    aliases: ["close_to_close"],
    appLinks: [analyticsLink],
  },
  {
    id: "close-to-open",
    categoryId: "analytics",
    title: { fr: "C-O - Close to Open", en: "C-O - Close to Open" },
    plain: {
      fr: "Rendement entre la clôture et l'ouverture suivante ou future. Utile pour lire l'effet overnight.",
      en: "Return from close to next or future open. Useful for reading overnight effect.",
    },
    aliases: ["close_to_open"],
    appLinks: [analyticsLink],
  },
  {
    id: "open-to-open",
    categoryId: "analytics",
    title: { fr: "O-O - Open to Open", en: "O-O - Open to Open" },
    plain: {
      fr: "Rendement entre deux ouvertures. C'est souvent cohérent avec une exécution à l'ouverture.",
      en: "Return between two opens. Often consistent with execution at the open.",
    },
    aliases: ["open_to_open", "O/O"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "open-to-close",
    categoryId: "analytics",
    title: { fr: "O-C - Open to Close", en: "O-C - Open to Close" },
    plain: {
      fr: "Rendement entre ouverture et clôture. Il lit plutôt une logique intraday ou une exposition limitée à la séance.",
      en: "Return from open to close. It reads a more intraday-like exposure limited to the session.",
    },
    aliases: ["open_to_close"],
    appLinks: [analyticsLink],
  },
  {
    id: "method-evaluation",
    categoryId: "analytics",
    title: { fr: "Évaluation des méthodes", en: "Method evaluation" },
    plain: {
      fr: "Table qui décide si une méthode doit être gardée, surveillée ou écartée selon couverture, IC médian, Sharpe, hit rate, nombre d'observations et score de preuve.",
      en: "Table deciding whether a method should be kept, watched, or discarded based on coverage, median IC, Sharpe, hit rate, observations, and evidence score.",
    },
    aliases: ["verdict", "keep", "watch", "discard", "evidence_score"],
    appLinks: [analyticsLink],
  },
  {
    id: "macro-factor",
    categoryId: "analytics",
    title: { fr: "Facteur macro", en: "Macro factor" },
    plain: {
      fr: "Série externe comme VIX, Brent, DXY, S&P 500 ou taux US10Y. Elle sert à tester si le contexte macro aide ou dégrade un signal.",
      en: "External series such as VIX, Brent, DXY, S&P 500, or US10Y yield. It tests whether macro context helps or hurts a signal.",
    },
    aliases: ["macro", "factor", "VIX", "Brent", "DXY"],
    appLinks: [analyticsLink],
  },
  {
    id: "factor-relevance",
    categoryId: "analytics",
    title: { fr: "Pertinence factorielle", en: "Factor relevance" },
    plain: {
      fr: "Score qui indique si un facteur macro a une relation utile avec une action ou un signal sur l'horizon choisi.",
      en: "Score indicating whether a macro factor has a useful relationship with a stock or signal for the selected horizon.",
    },
    aliases: ["relevance_score", "factor relevance"],
    appLinks: [analyticsLink],
  },
  {
    id: "cagr",
    categoryId: "backtest",
    title: { fr: "CAGR", en: "CAGR" },
    plain: {
      fr: "Rendement annualisé. Il transforme la performance totale en rythme annuel comparable entre stratégies.",
      en: "Annualized return. It converts total performance into a yearly pace comparable across strategies.",
    },
    formula: "CAGR = (valeur finale / valeur initiale)^(1 / années) - 1",
    aliases: ["compound annual growth rate"],
    appLinks: [backtestLink],
  },
  {
    id: "total-return",
    categoryId: "backtest",
    title: { fr: "Total return", en: "Total return" },
    plain: {
      fr: "Performance cumulée sur toute la période. Il dit combien le capital a gagné ou perdu au total.",
      en: "Cumulative performance over the full period. It says how much capital gained or lost in total.",
    },
    formula: "Total return = valeur finale / valeur initiale - 1",
    aliases: ["return", "retour total"],
    appLinks: [backtestLink],
  },
  {
    id: "pnl",
    categoryId: "backtest",
    title: { fr: "PnL", en: "PnL" },
    plain: {
      fr: "Profit and Loss: gain ou perte en monnaie. Contrairement au pourcentage, il dépend du capital engagé.",
      en: "Profit and Loss: monetary gain or loss. Unlike a percentage, it depends on deployed capital.",
    },
    aliases: ["profit and loss", "net pnl"],
    appLinks: [backtestLink],
  },
  {
    id: "sharpe",
    categoryId: "backtest",
    title: { fr: "Sharpe ratio", en: "Sharpe ratio" },
    plain: {
      fr: "Rendement ajusté du risque. Plus il est élevé, plus la stratégie a produit de rendement par unité de volatilité.",
      en: "Risk-adjusted return. The higher it is, the more return the strategy produced per unit of volatility.",
    },
    formula: "Sharpe = rendement excédentaire moyen / volatilité des rendements",
    aliases: ["sharpe ratio", "oos_sharpe"],
    appLinks: [backtestLink, analyticsLink],
  },
  {
    id: "max-drawdown",
    categoryId: "backtest",
    title: { fr: "Max drawdown", en: "Max drawdown" },
    plain: {
      fr: "Pire baisse entre un sommet et un creux de la courbe d'équité. C'est une mesure très concrète de douleur de portefeuille.",
      en: "Worst drop from a peak to a trough in the equity curve. It is a very concrete measure of portfolio pain.",
    },
    aliases: ["MDD", "max dd", "drawdown"],
    appLinks: [backtestLink],
  },
  {
    id: "win-rate",
    categoryId: "backtest",
    title: { fr: "Win rate", en: "Win rate" },
    plain: {
      fr: "Pourcentage de trades gagnants. Il doit être lu avec le gain moyen et la perte moyenne; seul, il peut être trompeur.",
      en: "Percentage of winning trades. It must be read with average win and average loss; alone, it can be misleading.",
    },
    aliases: ["win%", "win_pct"],
    appLinks: [backtestLink],
  },
  {
    id: "trades",
    categoryId: "backtest",
    title: { fr: "Nombre de trades", en: "Number of trades" },
    plain: {
      fr: "Nombre d'opérations réalisées. Beaucoup de trades augmente les coûts et exige une preuve plus solide.",
      en: "Number of executed trades. Many trades increase costs and require stronger evidence.",
    },
    aliases: ["n_trades", "number_of_trades", "fills"],
    appLinks: [backtestLink],
  },
  {
    id: "monte-carlo",
    categoryId: "backtest",
    title: { fr: "Monte Carlo", en: "Monte Carlo" },
    plain: {
      fr: "Simulation de nombreux chemins alternatifs pour voir si la performance dépend trop d'un ordre chanceux des trades ou des rendements.",
      en: "Simulation of many alternative paths to see whether performance depends too much on lucky ordering of trades or returns.",
    },
    aliases: ["MC", "fan chart"],
    appLinks: [signalsLink, backtestLink],
  },
  {
    id: "block-bootstrap",
    categoryId: "backtest",
    title: { fr: "Block bootstrap", en: "Block bootstrap" },
    plain: {
      fr: "Monte Carlo qui rééchantillonne des blocs de temps. Il garde une partie de la structure temporelle du marché.",
      en: "Monte Carlo that resamples time blocks. It keeps part of market time structure.",
    },
    aliases: ["block_bootstrap"],
    appLinks: [signalsLink],
  },
  {
    id: "trade-bootstrap",
    categoryId: "backtest",
    title: { fr: "Trade bootstrap", en: "Trade bootstrap" },
    plain: {
      fr: "Monte Carlo qui rééchantillonne les trades. Il teste si la distribution des trades reste acceptable dans d'autres ordres possibles.",
      en: "Monte Carlo that resamples trades. It tests whether the trade distribution remains acceptable in other possible orders.",
    },
    aliases: ["trade_bootstrap"],
    appLinks: [signalsLink],
  },
  {
    id: "equity-curve",
    categoryId: "backtest",
    title: { fr: "Courbe d'équité", en: "Equity curve" },
    plain: {
      fr: "Evolution du capital au fil du temps. Elle montre si la stratégie gagne de façon régulière ou par quelques périodes isolées.",
      en: "Capital evolution through time. It shows whether the strategy wins regularly or through a few isolated periods.",
    },
    aliases: ["equity", "cumreturn_vs_benchmark"],
    appLinks: [backtestLink],
  },
  {
    id: "trade-ledger",
    categoryId: "backtest",
    title: { fr: "Trade ledger", en: "Trade ledger" },
    plain: {
      fr: "Journal détaillé des trades: date, sens, prix, quantité, règle déclenchée, PnL réalisé et latent.",
      en: "Detailed trade journal: date, side, price, quantity, triggered rule, realized PnL, and latent PnL.",
    },
    aliases: ["ledger", "fills", "CMP"],
    appLinks: [signalsLink, backtestLink],
  },
  {
    id: "wfo-window",
    categoryId: "backtest",
    title: { fr: "Fenêtre WFO", en: "WFO window" },
    plain: {
      fr: "Bloc composé d'une période d'apprentissage et d'une période OOS. Les paramètres sont choisis dans la première puis contrôlés dans la seconde.",
      en: "Block made of a training period and an OOS period. Parameters are chosen in the first and checked in the second.",
    },
    aliases: ["window", "fold", "walk forward"],
    appLinks: [backtestLink, signalsLink],
  },
  {
    id: "held-out-test",
    categoryId: "backtest",
    title: { fr: "Held-out test", en: "Held-out test" },
    plain: {
      fr: "Test final sur une période gardée à part. Elle sert à éviter de juger la stratégie sur les mêmes données que l'optimisation.",
      en: "Final test on a period kept aside. It avoids judging the strategy on the same data used for optimization.",
    },
    aliases: ["test_period", "OOS final"],
    appLinks: [backtestLink],
  },
  {
    id: "wfe",
    categoryId: "backtest",
    title: { fr: "WFE - Walk-Forward Efficiency", en: "WFE - Walk-Forward Efficiency" },
    plain: {
      fr: "Compare la performance OOS à la performance in-sample. Une WFE faible signale que l'optimisation ne se transfère pas bien.",
      en: "Compares OOS performance with in-sample performance. A low WFE signals optimization does not transfer well.",
    },
    aliases: ["walk-forward efficiency"],
    appLinks: [backtestLink],
  },
  {
    id: "robustness-ratio",
    categoryId: "backtest",
    title: { fr: "Robustness ratio", en: "Robustness ratio" },
    plain: {
      fr: "Mesure de stabilité d'une configuration entre fenêtres. Plus elle est haute, moins la performance semble dépendre d'un cas unique.",
      en: "Stability measure for a configuration across windows. Higher means performance depends less on one isolated case.",
    },
    aliases: ["robustness"],
    appLinks: [backtestLink],
  },
  {
    id: "adv20",
    categoryId: "data",
    title: { fr: "ADV20", en: "ADV20" },
    plain: {
      fr: "Average Daily Value sur 20 jours: moyenne de la valeur échangée, calculée comme prix de clôture x nombre de titres échangés. Elle mesure la liquidité récente en MAD.",
      en: "Average Daily Value over 20 days: average traded value, computed as close price x number of shares traded. It measures recent liquidity in MAD.",
    },
    aliases: ["average daily value", "average daily volume", "liquidite", "volume moyen", "valeur echangee"],
    appLinks: [dashboardLink, dataLink, strategyLink],
  },
  {
    id: "liquidity-filter",
    categoryId: "data",
    title: { fr: "Filtre liquidité", en: "Liquidity filter" },
    plain: {
      fr: "Filtre qui retire les titres trop peu traités. Dans l'app, le seuil courant le plus visible est ADV20 >= 1 000 000 MAD.",
      en: "Filter that removes thinly traded stocks. In the app, the most visible current threshold is ADV20 >= 1,000,000 MAD.",
    },
    aliases: ["ADV20 >= 1000000 MAD", "ADV >= 1000", "liquid_masi"],
    appLinks: [dashboardLink, analyticsLink],
  },
  {
    id: "market-catalog",
    categoryId: "data",
    title: { fr: "Catalogue marché", en: "Market catalog" },
    plain: {
      fr: "Liste des instruments connus par l'app, avec type d'actif, région, nom affiché et disponibilité des données.",
      en: "List of instruments known by the app, with asset type, region, display name, and data availability.",
    },
    aliases: ["catalog", "instruments"],
    appLinks: [dataLink],
  },
  {
    id: "canonical-data",
    categoryId: "data",
    title: { fr: "Données canoniques", en: "Canonical data" },
    plain: {
      fr: "Série de prix officielle que l'app utilise pour les calculs. Si un instrument n'a pas de données canoniques, les scores ne sont pas fiables ou indisponibles.",
      en: "Official price series used by the app for calculations. If an instrument has no canonical data, scores are unreliable or unavailable.",
    },
    aliases: ["has_canonical_data", "canonical"],
    appLinks: [dataLink],
  },
  {
    id: "ohlcv",
    categoryId: "data",
    title: { fr: "OHLCV", en: "OHLCV" },
    plain: {
      fr: "Open, High, Low, Close, Volume: ouverture, plus haut, plus bas, clôture et volume d'une séance.",
      en: "Open, High, Low, Close, Volume: opening, high, low, closing price, and volume for a session.",
    },
    aliases: ["open", "high", "low", "close", "volume"],
    appLinks: [dataLink, signalsLink],
  },
  {
    id: "last-price",
    categoryId: "data",
    title: { fr: "Dernier prix", en: "Last price" },
    plain: {
      fr: "Dernier prix disponible pour l'instrument. Il sert à afficher le niveau courant et à situer les signaux techniques.",
      en: "Latest available price for the instrument. It displays the current level and positions technical signals.",
    },
    aliases: ["last_price", "close_used", "prix"],
    appLinks: [dashboardLink, dataLink],
  },
  {
    id: "var1j",
    categoryId: "data",
    title: { fr: "Variation 1j", en: "1-day change" },
    plain: {
      fr: "Variation du prix sur la dernière séance disponible. Elle donne le mouvement très court terme, pas une preuve de signal.",
      en: "Price change over the latest available session. It gives very short-term movement, not signal proof.",
    },
    aliases: ["var1j_pct", "1d change"],
    appLinks: [dashboardLink],
  },
  {
    id: "masi",
    categoryId: "data",
    title: { fr: "MASI", en: "MASI" },
    plain: {
      fr: "Indice principal de la Bourse de Casablanca. Dans l'app, MASI designe souvent l'univers marocain prioritaire.",
      en: "Main index of the Casablanca Stock Exchange. In the app, MASI often means the priority Moroccan universe.",
    },
    aliases: ["Moroccan All Shares Index", "Maroc"],
    appLinks: [dashboardLink, dataLink],
  },
  {
    id: "asset-type",
    categoryId: "data",
    title: { fr: "Type d'actif", en: "Asset type" },
    plain: {
      fr: "Classe d'instrument: action, matière première, obligation, devise ou indice. Elle sert aux filtres et à l'organisation du catalogue.",
      en: "Instrument class: equity, commodity, bond, currency, or index. It is used for filters and catalog organization.",
    },
    aliases: ["asset_type", "equity", "commodity", "bond"],
    appLinks: [dataLink],
  },
  {
    id: "market-region",
    categoryId: "data",
    title: { fr: "Région marché", en: "Market region" },
    plain: {
      fr: "Zone géographique ou groupe de marché: MASI, US, Europe, Asie, etc. Elle sert à filtrer l'univers complet.",
      en: "Geographic zone or market group: MASI, US, Europe, Asia, and so on. It filters the full universe.",
    },
    aliases: ["market_region", "region"],
    appLinks: [dataLink, dashboardLink],
  },
  {
    id: "dcf",
    categoryId: "fundamentals",
    title: { fr: "DCF - Discounted Cash Flow", en: "DCF - Discounted Cash Flow" },
    plain: {
      fr: "Méthode qui dit qu'une entreprise vaut la somme de ses flux de trésorerie futurs, ramenés à aujourd'hui. Un euro reçu dans 5 ans vaut moins qu'un euro aujourd'hui: on l'actualise donc avec un taux qui reflète le risque et le temps.",
      en: "A method stating that a company is worth the sum of its future cash flows, brought back to today. A euro received in 5 years is worth less than a euro today, so each flow is discounted with a rate reflecting risk and time.",
    },
    details: [
      {
        fr: "Trois ingrédients suffisent: (1) les flux futurs projetés, (2) le taux d'actualisation r, (3) une valeur terminale qui capture la vie de l'entreprise au-delà de l'horizon explicite. Le DCF de l'app existe en deux versions: FCFF (actualisé au WACC) et FCFE (actualisé au coût des fonds propres).",
        en: "Three ingredients are enough: (1) projected future flows, (2) the discount rate r, (3) a terminal value capturing the life of the firm beyond the explicit horizon. The app's DCF comes in two flavors: FCFF (discounted at WACC) and FCFE (discounted at cost of equity).",
      },
    ],
    formula: "Valeur = Σ CF_t / (1 + r)^t + Valeur terminale / (1 + r)^n",
    example: {
      fr: "Avec r = 10%, un flux de 100 dans 1 an vaut 100/1.10 = 90.9 aujourd'hui; le même flux dans 3 ans vaut 100/1.10^3 = 75.1.",
      en: "With r = 10%, a flow of 100 in 1 year is worth 100/1.10 = 90.9 today; the same flow in 3 years is worth 100/1.10^3 = 75.1.",
    },
    aliases: ["discounted cash flow", "fcff_dcf", "fcfe_dcf", "actualisation des flux"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "fcff",
    categoryId: "fundamentals",
    title: { fr: "FCFF - Flux de trésorerie disponible pour la firme", en: "FCFF - Free Cash Flow to the Firm" },
    plain: {
      fr: "Le cash généré par l'exploitation et disponible pour TOUS les apporteurs de capital (actionnaires et créanciers), avant le service de la dette. C'est le flux actualisé dans le DCF FCFF, au WACC.",
      en: "The cash generated by operations and available to ALL capital providers (shareholders and lenders), before debt service. It is the flow discounted in the FCFF DCF, at the WACC.",
    },
    formula: "FCFF = NOPAT + amortissements - variation du BFR - investissements (capex)",
    example: {
      fr: "NOPAT 120, amortissements 30, hausse du BFR 10, capex 50 -> FCFF = 120 + 30 - 10 - 50 = 90.",
      en: "NOPAT 120, D&A 30, working-capital increase 10, capex 50 -> FCFF = 120 + 30 - 10 - 50 = 90.",
    },
    aliases: ["free cash flow to firm", "Free_Cash_Flow", "flux firme"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "fcfe",
    categoryId: "fundamentals",
    title: { fr: "FCFE - Flux de trésorerie disponible pour l'actionnaire", en: "FCFE - Free Cash Flow to Equity" },
    plain: {
      fr: "Le cash qui revient aux seuls actionnaires, après le service de la dette (intérêts et remboursements nets). Comme il est déjà net de dette, on l'actualise au coût des fonds propres et il n'y a pas de pont dette nette à la fin.",
      en: "The cash that belongs to shareholders only, after debt service (interest and net repayments). Because it is already net of debt, it is discounted at the cost of equity and needs no net-debt bridge at the end.",
    },
    formula: "FCFE = FCFF - intérêts x (1 - taux d'impôt) + variation nette de la dette",
    aliases: ["free cash flow to equity", "Free_Cash_Flow_to_Equity", "flux actionnaire"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "wacc",
    categoryId: "fundamentals",
    title: { fr: "WACC - Coût moyen pondéré du capital", en: "WACC - Weighted Average Cost of Capital" },
    plain: {
      fr: "Le taux d'actualisation utilisé pour le FCFF. C'est le rendement moyen exigé par l'ensemble des financeurs, en pondérant le coût des fonds propres et le coût de la dette (après impôt) par leur poids respectif.",
      en: "The discount rate used for FCFF. It is the average return required by all financiers, weighting the cost of equity and the after-tax cost of debt by their respective shares.",
    },
    formula: "WACC = poids fonds propres x Ke + poids dette x Kd x (1 - taux d'impôt)",
    example: {
      fr: "70% fonds propres à Ke = 12%, 30% dette à Kd = 6% et impôt 30% -> WACC = 0.7x12% + 0.3x6%x0.7 = 8.4% + 1.26% = 9.66%.",
      en: "70% equity at Ke = 12%, 30% debt at Kd = 6% and 30% tax -> WACC = 0.7x12% + 0.3x6%x0.7 = 8.4% + 1.26% = 9.66%.",
    },
    aliases: ["weighted average cost of capital", "cout du capital", "taux d'actualisation firme"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "cost-of-equity",
    categoryId: "fundamentals",
    title: { fr: "Ke - Coût des fonds propres", en: "Ke - Cost of equity" },
    plain: {
      fr: "Le rendement exigé par les actionnaires pour le risque pris. Il sert de taux d'actualisation pour le FCFE et le DDM. L'app l'estime souvent via le MEDAF (CAPM): taux sans risque + bêta x prime de risque actions.",
      en: "The return shareholders require for the risk taken. It is the discount rate for FCFE and DDM. The app typically estimates it via CAPM: risk-free rate + beta x equity risk premium.",
    },
    formula: "Ke = taux sans risque + bêta x prime de risque actions",
    example: {
      fr: "Taux sans risque 3%, bêta 1.1, prime 6% -> Ke = 3% + 1.1x6% = 9.6%.",
      en: "Risk-free 3%, beta 1.1, premium 6% -> Ke = 3% + 1.1x6% = 9.6%.",
    },
    aliases: ["cost of equity", "Ke", "MEDAF", "CAPM", "cout des fonds propres"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "discount-period",
    categoryId: "fundamentals",
    title: { fr: "t - Période d'actualisation", en: "t - Discount period" },
    plain: {
      fr: "Le nombre d'années qui sépare aujourd'hui du flux. Plus t est grand, plus le flux est lointain et plus il est actualisé. Dans la table DCF, t = 1 pour le flux de l'an prochain, t = 2 pour l'année suivante, etc.",
      en: "The number of years between today and the flow. The larger t, the further away the flow and the more it is discounted. In the DCF table, t = 1 is next year's flow, t = 2 the year after, and so on.",
    },
    details: [
      {
        fr: "L'app peut utiliser une convention de mi-année (mid-year): le flux est supposé tomber au milieu de l'année, donc t = 0.5, 1.5, 2.5... ce qui réduit légèrement l'actualisation.",
        en: "The app may use a mid-year convention: the flow is assumed to arrive mid-year, so t = 0.5, 1.5, 2.5... which slightly reduces discounting.",
      },
    ],
    aliases: ["t", "periode", "mid-year", "convention mi-annee"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "discount-factor",
    categoryId: "fundamentals",
    title: { fr: "Facteur d'actualisation", en: "Discount factor" },
    plain: {
      fr: "Le multiplicateur qui transforme un flux futur en valeur d'aujourd'hui. Il vaut toujours entre 0 et 1: plus la période t est lointaine, plus le facteur est petit. La colonne \"Facteur\" de la table DCF affiche exactement ce nombre.",
      en: "The multiplier that turns a future flow into today's value. It is always between 0 and 1: the further the period t, the smaller the factor. The \"Facteur\" column of the DCF table shows exactly this number.",
    },
    formula: "Facteur = 1 / (1 + r)^t",
    example: {
      fr: "Avec r = 10%: facteur an 1 = 1/1.10 = 0.909; an 3 = 1/1.10^3 = 0.751; an 5 = 0.621.",
      en: "With r = 10%: factor year 1 = 1/1.10 = 0.909; year 3 = 1/1.10^3 = 0.751; year 5 = 0.621.",
    },
    aliases: ["facteur", "facteur d'actualisation", "discount factor"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "present-value",
    categoryId: "fundamentals",
    title: { fr: "PV - Valeur actuelle", en: "PV - Present value" },
    plain: {
      fr: "La valeur d'aujourd'hui d'un flux futur, une fois actualisé. C'est simplement le flux multiplié par son facteur d'actualisation. La colonne \"PV\" de la table DCF montre ce que chaque année rapporte en valeur d'aujourd'hui.",
      en: "Today's value of a future flow once discounted. It is simply the flow multiplied by its discount factor. The \"PV\" column of the DCF table shows what each year contributes in today's value.",
    },
    formula: "PV = flux x facteur = CF_t / (1 + r)^t",
    example: {
      fr: "Un FCFF de 90 en année 3 avec r = 10% -> PV = 90 x 0.751 = 67.6.",
      en: "An FCFF of 90 in year 3 with r = 10% -> PV = 90 x 0.751 = 67.6.",
    },
    aliases: ["pv", "valeur actuelle", "present value", "flux actualise"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "terminal-value",
    categoryId: "fundamentals",
    title: { fr: "Valeur terminale", en: "Terminal value" },
    plain: {
      fr: "La valeur de tous les flux situés au-delà de l'horizon de projection explicite, résumée en un seul chiffre. On l'estime par une perpétuité de Gordon: le dernier flux croît à l'infini à un taux g modeste. Elle pèse souvent la majorité de la valeur, d'où l'attention portée aux hypothèses.",
      en: "The value of all flows beyond the explicit projection horizon, summarized in a single number. It is estimated with a Gordon perpetuity: the last flow grows forever at a modest rate g. It often makes up the majority of value, hence the focus on its assumptions.",
    },
    formula: "Valeur terminale = CF_n x (1 + g) / (r - g), puis actualisée par 1/(1+r)^n",
    example: {
      fr: "CF_n = 100, g = 2%, r = 10% -> VT = 100x1.02/(0.10-0.02) = 1275, à actualiser ensuite.",
      en: "CF_n = 100, g = 2%, r = 10% -> TV = 100x1.02/(0.10-0.02) = 1275, then discounted.",
    },
    aliases: ["terminal value", "valeur terminale", "Gordon", "perpetuite"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "terminal-growth",
    categoryId: "fundamentals",
    title: { fr: "g - Croissance terminale", en: "g - Terminal growth" },
    plain: {
      fr: "Le taux auquel le dernier flux est supposé croître à l'infini dans la valeur terminale. Il doit rester inférieur au taux d'actualisation r et raisonnablement proche de la croissance de long terme de l'économie. Un g trop élevé fait exploser la valeur.",
      en: "The rate at which the last flow is assumed to grow forever in the terminal value. It must stay below the discount rate r and be reasonably close to the long-run growth of the economy. A g that is too high makes value explode.",
    },
    details: [
      {
        fr: "L'app ne fixe pas g au hasard: pour le FCFF, g = taux de réinvestissement x ROIC; pour le FCFE, g = taux de rétention x ROE, le tout borné par un plancher et un plafond.",
        en: "The app does not set g arbitrarily: for FCFF, g = reinvestment rate x ROIC; for FCFE, g = retention rate x ROE, all bounded by a floor and a ceiling.",
      },
    ],
    formula: "g_firme = réinvestissement x ROIC ; g_equity = rétention x ROE",
    aliases: ["g", "terminal growth", "croissance perpetuelle", "terminal_growth_firm", "terminal_growth_equity"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "net-debt-bridge",
    categoryId: "fundamentals",
    title: { fr: "Pont dette nette (EV -> capitaux propres)", en: "Net-debt bridge (EV -> equity)" },
    plain: {
      fr: "L'étape qui transforme la valeur d'entreprise (EV, issue du DCF FCFF) en valeur des capitaux propres, puis en prix par action. On retire la dette nette (dette - trésorerie) puis on divise par le nombre d'actions.",
      en: "The step that turns enterprise value (EV, from the FCFF DCF) into equity value, then into a per-share price. Net debt (debt - cash) is subtracted, then the result is divided by the share count.",
    },
    formula: "Capitaux propres = EV - dette nette ; Juste valeur/action = capitaux propres / nombre d'actions",
    example: {
      fr: "EV = 1000, dette nette = 200, 100 actions -> capitaux propres = 800, juste valeur = 8 par action.",
      en: "EV = 1000, net debt = 200, 100 shares -> equity = 800, fair value = 8 per share.",
    },
    aliases: ["net debt", "dette nette", "enterprise value", "EV", "pont"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "ddm",
    categoryId: "fundamentals",
    title: { fr: "DDM - Modèle d'actualisation des dividendes", en: "DDM - Dividend Discount Model" },
    plain: {
      fr: "Une variante du DCF qui actualise directement les dividendes futurs au coût des fonds propres. Utile pour les sociétés matures qui versent une part stable de leur résultat, comme les banques et les assurances.",
      en: "A DCF variant that discounts future dividends directly at the cost of equity. Useful for mature companies paying out a stable share of earnings, such as banks and insurers.",
    },
    formula: "Valeur = Σ dividende_t / (1 + Ke)^t + valeur terminale des dividendes",
    aliases: ["dividend discount model", "ddm", "modele de Gordon"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "residual-income",
    categoryId: "fundamentals",
    title: { fr: "Résultat résiduel (Residual income)", en: "Residual income" },
    plain: {
      fr: "Modèle qui part de la valeur comptable des capitaux propres et y ajoute la valeur créée au-dessus du rendement exigé. Il récompense les entreprises qui gagnent plus que leur coût des fonds propres (ROE > Ke).",
      en: "A model that starts from the book value of equity and adds the value created above the required return. It rewards firms earning more than their cost of equity (ROE > Ke).",
    },
    formula: "Valeur = valeur comptable + Σ (ROE - Ke) x capitaux propres_t / (1 + Ke)^t",
    aliases: ["residual income", "resultat residuel", "RI"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "justified-multiples",
    categoryId: "fundamentals",
    title: { fr: "Multiples justifiés", en: "Justified multiples" },
    plain: {
      fr: "Multiples (PER, P/B) calculés à partir des fondamentaux de l'entreprise elle-même, et non des pairs. Par exemple, un P/B justifié dépend du ROE, du coût des fonds propres et de la croissance. Ils donnent un prix \"mérité\" indépendant du marché.",
      en: "Multiples (P/E, P/B) derived from the company's own fundamentals rather than peers. For instance, a justified P/B depends on ROE, cost of equity, and growth. They give a \"deserved\" price independent of the market.",
    },
    formula: "P/B justifié = (ROE - g) / (Ke - g)",
    aliases: ["justified multiples", "multiples justifies", "justified_pb", "justified_pe"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "relative-multiples",
    categoryId: "fundamentals",
    title: { fr: "Multiples relatifs (comparables)", en: "Relative multiples (comparables)" },
    plain: {
      fr: "Valorisation par comparaison: on applique au titre le multiple médian d'un groupe de pairs (PER, EV/EBITDA, P/B, P/S). Le prix obtenu reflète ce que le marché paie aujourd'hui pour des sociétés similaires.",
      en: "Valuation by comparison: the median multiple of a peer group (P/E, EV/EBITDA, P/B, P/S) is applied to the stock. The resulting price reflects what the market currently pays for similar companies.",
    },
    details: [
      {
        fr: "L'app pondère les pairs par leur flottant ou capitalisation et permet de choisir les pairs (indice, secteur) et les ratios retenus.",
        en: "The app weights peers by free float or market cap and lets you choose the peer set (index, sector) and which ratios are used.",
      },
    ],
    aliases: ["relative multiples", "comparables", "comps", "peers", "multiples relatifs"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "reverse-dcf",
    categoryId: "fundamentals",
    title: { fr: "Reverse DCF", en: "Reverse DCF" },
    plain: {
      fr: "On inverse le DCF: au lieu de calculer un prix, on part du prix de marché actuel et on déduit la croissance que le marché doit anticiper pour le justifier. Le résultat est un taux de croissance implicite, pas un prix.",
      en: "The DCF run backwards: instead of computing a price, you start from the current market price and infer the growth the market must be expecting to justify it. The output is an implied growth rate, not a price.",
    },
    details: [
      {
        fr: "Lecture: si la croissance implicite dépasse largement la croissance du modèle, le titre paraît cher (le marché attend beaucoup); l'inverse suggère une attente prudente.",
        en: "Reading: if implied growth far exceeds the model's growth, the stock looks expensive (the market expects a lot); the reverse suggests cautious expectations.",
      },
    ],
    aliases: ["reverse dcf", "croissance implicite", "implied growth"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "valuation-ensemble",
    categoryId: "fundamentals",
    title: { fr: "Ensemble de valorisation", en: "Valuation ensemble" },
    plain: {
      fr: "La cible finale n'est pas un seul modèle mais une combinaison de plusieurs (DCF FCFF/FCFE, DDM, résultat résiduel, multiples). On agrège leurs justes valeurs en une fourchette et une cible, ce qui réduit la dépendance à une seule hypothèse.",
      en: "The final target is not a single model but a blend of several (FCFF/FCFE DCF, DDM, residual income, multiples). Their fair values are aggregated into a range and a target, reducing reliance on any single assumption.",
    },
    details: [
      {
        fr: "Dans l'onglet Valorisation, tu peux inclure ou exclure chaque modèle et choisir la méthode de pondération (égale ou par IC).",
        en: "In the Valuation tab, you can include or exclude each model and choose the weighting method (equal or IC-based).",
      },
    ],
    aliases: ["ensemble", "football field", "fourchette de valorisation", "fair value base"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "ic-weighting",
    categoryId: "fundamentals",
    title: { fr: "Pondération par IC vs égale", en: "IC vs equal weighting" },
    plain: {
      fr: "Deux façons de combiner les modèles. Égale: chaque modèle retenu compte autant (1/N). Par IC: chaque modèle est pondéré par sa capacité historique à prédire les rendements (son Information Coefficient), si bien que les méthodes les plus fiables pèsent plus.",
      en: "Two ways to combine models. Equal: each retained model counts the same (1/N). IC-based: each model is weighted by its historical ability to predict returns (its Information Coefficient), so the most reliable methods carry more weight.",
    },
    details: [
      {
        fr: "Par défaut l'app utilise les poids IC validés par le backend quand ils existent, et retombe sur l'égale pondération sinon. L'onglet Valorisation laisse forcer l'une ou l'autre.",
        en: "By default the app uses backend-validated IC weights when available, and falls back to equal weighting otherwise. The Valuation tab lets you force either one.",
      },
    ],
    formula: "Cible = Σ juste valeur_modèle x poids_modèle, avec Σ poids = 1",
    aliases: ["ic weighting", "equal weighting", "ponderation", "ic_ensemble", "model weights"],
    appLinks: [fundamentalsLink, analyticsLink],
  },
  {
    id: "altman-z",
    categoryId: "quality-screens",
    title: { fr: "Z-score d'Altman", en: "Altman Z-score" },
    plain: {
      fr: "Un score qui combine cinq ratios du bilan pour estimer le risque de faillite : au-dessus de ~3 la société est en zone saine, en dessous de ~1,8 en zone de fragilité, entre les deux c'est la zone grise.",
      en: "A score combining five balance-sheet ratios to estimate bankruptcy risk: above ~3 the company is in a safe zone, below ~1.8 it is in a distress zone, and in between it is the grey zone.",
    },
    aliases: ["altman z", "z-score", "zone de fragilité", "bankruptcy score"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "eva",
    categoryId: "quality-screens",
    title: { fr: "EVA - Valeur économique ajoutée", en: "EVA - Economic Value Added" },
    plain: {
      fr: "Mesure si l'entreprise crée vraiment de la valeur : elle compare le rendement de son capital investi (ROIC) au coût de ce capital (WACC). Si ROIC dépasse le WACC, chaque dirham investi rapporte plus qu'il ne coûte.",
      en: "Measures whether the company genuinely creates value by comparing the return on invested capital (ROIC) to the cost of that capital (WACC). If ROIC exceeds WACC, every dirham invested earns more than it costs.",
    },
    formula: "EVA = (ROIC - WACC) x Capital investi",
    aliases: ["economic value added", "creation de valeur", "value creation"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "roic",
    categoryId: "quality-screens",
    title: { fr: "ROIC - Rentabilité du capital investi", en: "ROIC - Return on Invested Capital" },
    plain: {
      fr: "Combien l'entreprise gagne, en pourcentage, pour chaque dirham de capital (dette + fonds propres) mis au travail dans l'exploitation. Comparé au WACC, il dit si l'activité crée ou détruit de la valeur.",
      en: "How much the company earns, in percent, for each dirham of capital (debt + equity) put to work in operations. Compared to the WACC, it tells whether the business creates or destroys value.",
    },
    formula: "ROIC = NOPAT / Capital investi",
    aliases: ["return on invested capital", "rentabilite du capital"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "roe",
    categoryId: "quality-screens",
    title: { fr: "ROE - Rentabilité des fonds propres", en: "ROE - Return on Equity" },
    plain: {
      fr: "Le bénéfice net rapporté aux fonds propres : combien l'entreprise gagne pour chaque dirham que les actionnaires ont investi. Il sert de base au DuPont et aux multiples justifiés.",
      en: "Net income relative to shareholders' equity: how much the company earns for every dirham shareholders have invested. It underpins the DuPont breakdown and the justified multiples.",
    },
    formula: "ROE = Résultat net / Fonds propres",
    aliases: ["return on equity", "rentabilite des fonds propres"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "dupont",
    categoryId: "quality-screens",
    title: { fr: "Décomposition de DuPont", en: "DuPont decomposition" },
    plain: {
      fr: "Casse le ROE en trois morceaux pour comprendre d'où vient la rentabilité : la marge nette (combien reste du chiffre d'affaires), la rotation de l'actif (combien de ventes par dirham d'actif) et le levier financier (combien de dette par rapport aux fonds propres).",
      en: "Breaks ROE into three pieces to explain where profitability comes from: net margin (how much of revenue is kept), asset turnover (sales generated per dirham of assets), and financial leverage (how much debt relative to equity).",
    },
    formula: "ROE = Marge nette x Rotation de l'actif x Levier financier",
    aliases: ["dupont analysis", "decomposition roe"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "peg",
    categoryId: "quality-screens",
    title: { fr: "PEG - P/E rapporté à la croissance", en: "PEG - P/E to growth" },
    plain: {
      fr: "Le P/E divisé par le taux de croissance attendu des bénéfices. Il permet de comparer des sociétés qui ont des P/E différents parce qu'elles grandissent à des rythmes différents : un PEG proche de 1 est souvent jugé raisonnable.",
      en: "The P/E divided by the expected earnings growth rate. It lets you compare companies with different P/E ratios because they grow at different paces: a PEG near 1 is often considered reasonable.",
    },
    formula: "PEG = P/E / Croissance attendue des bénéfices (%)",
    aliases: ["price earnings to growth", "peg ratio"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "magic-formula",
    categoryId: "quality-screens",
    title: { fr: "Formule magique (Magic Formula)", en: "Magic Formula" },
    plain: {
      fr: "Un écran qui classe les sociétés en combinant deux idées simples : est-ce que l'entreprise est rentable (rendement du capital élevé) et est-ce qu'elle est bon marché (rendement des bénéfices élevé). Les mieux classées sur les deux critères ressortent en tête.",
      en: "A screen that ranks companies by combining two simple ideas: is the business profitable (high return on capital) and is it cheap (high earnings yield). Companies ranking well on both come out on top.",
    },
    aliases: ["magic formula investing", "greenblatt"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "payout-ratio",
    categoryId: "quality-screens",
    title: { fr: "Taux de distribution (payout)", en: "Payout ratio" },
    plain: {
      fr: "La part du bénéfice net que l'entreprise reverse en dividendes plutôt que de la garder pour réinvestir. Un payout élevé laisse peu de marge pour financer la croissance sans dette ou émission d'actions.",
      en: "The share of net income the company pays out as dividends rather than keeping to reinvest. A high payout leaves little room to fund growth without debt or new share issuance.",
    },
    formula: "Payout = Dividendes / Résultat net",
    aliases: ["dividend payout", "taux de distribution"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "free-float",
    categoryId: "quality-screens",
    title: { fr: "Free float", en: "Free float" },
    plain: {
      fr: "La part du capital réellement disponible à l'achat et à la vente en bourse, hors actionnaires stables (État, famille fondatrice, participations croisées). Un free float faible veut dire moins de titres disponibles et souvent moins de liquidité.",
      en: "The share of capital actually available for trading, excluding stable holders (the state, founding families, cross-holdings). A low free float means fewer shares available and often less liquidity.",
    },
    aliases: ["flottant", "free float pct"],
    appLinks: [fundamentalsLink, dataLink],
  },
  {
    id: "beta",
    categoryId: "quality-screens",
    title: { fr: "Bêta", en: "Beta" },
    plain: {
      fr: "Mesure la sensibilité du titre aux mouvements du marché. Un bêta de 1,2 veut dire que le titre bouge en moyenne 20% de plus que le marché, dans les deux sens. Il sert à calculer le coût des fonds propres.",
      en: "Measures how sensitive the stock is to market moves. A beta of 1.2 means the stock moves on average 20% more than the market, in both directions. It feeds into the cost-of-equity calculation.",
    },
    formula: "Ke = Taux sans risque + Bêta x Prime de risque actions",
    aliases: ["beta coefficient", "sensibilite marche"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "per",
    categoryId: "quality-screens",
    title: { fr: "P/E - Price to Earnings", en: "P/E - Price to Earnings" },
    plain: {
      fr: "Le prix de l'action divisé par le bénéfice par action. Il dit combien d'années de bénéfices actuels il faut pour \"payer\" le prix du titre. Plus il est élevé, plus le marché paie cher chaque dirham de bénéfice.",
      en: "The share price divided by earnings per share. It shows how many years of current earnings it takes to 'pay back' the share price. The higher it is, the more the market pays for each dirham of earnings.",
    },
    formula: "P/E = Cours / Bénéfice par action",
    aliases: ["price to earnings", "PER", "multiple de resultat"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "price-to-book",
    categoryId: "quality-screens",
    title: { fr: "P/B - Price to Book", en: "P/B - Price to Book" },
    plain: {
      fr: "Le prix de l'action divisé par la valeur comptable par action (les fonds propres par action). Un P/B au-dessus de 1 veut dire que le marché valorise l'entreprise au-delà de ce que ses livres comptables indiquent.",
      en: "The share price divided by book value per share (equity per share). A P/B above 1 means the market values the company above what its accounting books show.",
    },
    formula: "P/B = Cours / Valeur comptable par action",
    aliases: ["price to book", "price_to_book"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "price-to-sales",
    categoryId: "quality-screens",
    title: { fr: "P/S - Price to Sales", en: "P/S - Price to Sales" },
    plain: {
      fr: "Le prix de l'action divisé par le chiffre d'affaires par action. Utile pour comparer des sociétés qui ne sont pas encore ou plus rentables, là où le P/E ne fonctionne pas.",
      en: "The share price divided by revenue per share. Useful for comparing companies that are not yet, or no longer, profitable, where the P/E does not work.",
    },
    formula: "P/S = Cours / Chiffre d'affaires par action",
    aliases: ["price to sales", "price_to_sales"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "ev-ebitda",
    categoryId: "quality-screens",
    title: { fr: "EV/EBITDA", en: "EV/EBITDA" },
    plain: {
      fr: "La valeur d'entreprise (capitalisation + dette nette) divisée par l'EBITDA. Contrairement au P/E, il n'est pas déformé par la structure de dette ou les éléments non-récurrents, ce qui facilite la comparaison entre sociétés inégalement endettées.",
      en: "Enterprise value (market cap + net debt) divided by EBITDA. Unlike the P/E, it is not distorted by capital structure or one-off items, making it easier to compare companies with different debt levels.",
    },
    formula: "EV/EBITDA = (Capitalisation + Dette nette) / EBITDA",
    aliases: ["ev to ebitda", "ev_to_ebitda"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "dividend-yield",
    categoryId: "quality-screens",
    title: { fr: "Rendement du dividende", en: "Dividend yield" },
    plain: {
      fr: "Le dividende annuel par action rapporté au cours actuel. Il dit quel pourcentage du prix payé revient chaque année sous forme de dividende, sans compter une éventuelle plus-value.",
      en: "The annual dividend per share relative to the current price. It shows what percentage of the price paid comes back each year as a dividend, excluding any capital gain.",
    },
    formula: "Rendement = Dividende par action / Cours",
    aliases: ["dividend yield", "rendement dividende"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "sensitivity-grid",
    categoryId: "quality-screens",
    title: { fr: "Grille de sensibilité", en: "Sensitivity grid" },
    plain: {
      fr: "Un tableau qui montre comment la juste valeur change quand on fait varier deux hypothèses en même temps (par exemple le WACC et la croissance terminale). Il aide à voir si la cible est fragile ou robuste face à des erreurs d'hypothèses.",
      en: "A table showing how fair value changes as two assumptions move together (for example the WACC and terminal growth). It helps show whether the target is fragile or robust to assumption errors.",
    },
    aliases: ["sensitivity matrix", "sensitivity heatmap", "matrice de sensibilite"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "scenario-bear-base-bull",
    categoryId: "quality-screens",
    title: { fr: "Scénarios bear / base / bull", en: "Bear / base / bull scenarios" },
    plain: {
      fr: "Trois versions de la thèse : bear (pessimiste), base (le scénario central retenu) et bull (optimiste). Chacune a ses propres hypothèses et donc sa propre juste valeur, ce qui donne une fourchette plutôt qu'un chiffre unique.",
      en: "Three versions of the thesis: bear (pessimistic), base (the central scenario used), and bull (optimistic). Each has its own assumptions and therefore its own fair value, giving a range rather than a single number.",
    },
    aliases: ["bear case", "bull case", "base case", "scenarios"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "conviction",
    categoryId: "quality-screens",
    title: { fr: "Conviction", en: "Conviction" },
    plain: {
      fr: "Un score de 1 à 5 qui dit à quel point la recommandation est bien étayée par les données disponibles (couverture des modèles, cohérence entre eux, qualité des données). Ce n'est pas une prédiction de performance, juste un niveau de confiance dans l'analyse.",
      en: "A score from 1 to 5 indicating how well-supported the recommendation is by available data (model coverage, agreement between models, data quality). It is not a performance forecast, just a confidence level in the analysis.",
    },
    aliases: ["conviction score", "niveau de confiance"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "upside",
    categoryId: "quality-screens",
    title: { fr: "Upside / Downside", en: "Upside / downside" },
    plain: {
      fr: "L'écart en pourcentage entre la juste valeur (ou le prix cible) et le cours actuel. Positif (upside), le titre est jugé décoté ; négatif (downside), il est jugé cher par rapport à l'estimation.",
      en: "The percentage gap between fair value (or the target price) and the current price. Positive (upside) means the stock looks undervalued; negative (downside) means it looks expensive relative to the estimate.",
    },
    formula: "Upside = (Juste valeur / Cours actuel) - 1",
    aliases: ["potentiel de hausse", "potentiel de baisse", "downside"],
    appLinks: [fundamentalsLink],
  },
  {
    id: "football-field",
    categoryId: "quality-screens",
    title: { fr: "Football field (fourchettes de valorisation)", en: "Football field (valuation ranges)" },
    plain: {
      fr: "Un graphique qui montre, modèle par modèle, la fourchette de juste valeur obtenue (basse à haute), avec une ligne verticale pour le cours actuel. Il permet de voir d'un coup d'oeil où se situe le prix de marché par rapport à chaque méthode.",
      en: "A chart showing, model by model, the fair-value range obtained (low to high), with a vertical line for the current price. It lets you see at a glance where the market price sits relative to each method.",
    },
    aliases: ["football field chart", "fourchette de valorisation"],
    appLinks: [fundamentalsLink],
  },
]
