// Builds the market-implied vs house-model earnings-growth comparison used by
// ImpliedGrowthCard (Signal page, Fondamental > Valorisation). Plain-JS sibling
// of fundamental-valuation-story-utils.js — same local-helper conventions, no TS.

function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {}
}

function fmtPctText(value, digits = 1) {
  const numberValue = asNumber(value)
  return numberValue == null ? "-" : `${(numberValue * 100).toFixed(digits)}%`
}

function fmtPtsText(value, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-"
}

const MAX_ROWS = 8

// horizon literals match FundamentalHorizon ("quarter" | "semester" | "year") in
// frontend/components/strategy/fundamental/lib/types.ts.
const HORIZON_CONFIG = {
  year: { subPeriods: 1, exponent: 1, label: (year) => `${year}E` },
  semester: { subPeriods: 2, exponent: 1 / 2, label: (year, sub) => `S${sub} ${year}E` },
  quarter: { subPeriods: 4, exponent: 1 / 4, label: (year, sub) => `T${sub} ${year}E` },
}

function subAnnualRate(annualRate, exponent) {
  if (annualRate == null) return null
  return (1 + annualRate) ** exponent - 1
}

// Historical net-income aliases, mirrors ESTIMATION_HISTORICAL_ALIASES.net_income
// in frontend/components/strategy/fundamental/lib/constants.ts.
const NET_INCOME_ALIASES = ["Clean_Resultat_net", "Resultat_net", "NetIncome", "Net_Income", "IS_Net_Income"]

function firstAlias(metrics, aliases) {
  for (const name of aliases) {
    const value = asNumber(metrics[name])
    if (value != null) return value
  }
  return null
}

function lastActualNetIncome(detail, beforeYear) {
  const rows = Array.isArray(detail?.annual) ? detail.annual : []
  const candidates = rows
    .map((row) => asRecord(row))
    .map((row) => ({ year: asNumber(row.statement_year), metrics: asRecord(row.metrics) }))
    .filter((row) => row.year != null && (beforeYear == null || row.year < beforeYear))
    .sort((a, b) => b.year - a.year)
  if (!candidates.length) return null
  return firstAlias(candidates[0].metrics, NET_INCOME_ALIASES)
}

function orderedProjectedNetIncome(projection) {
  const statements = Array.isArray(projection?.statements) ? projection.statements : []
  return statements
    .map((item) => asRecord(item))
    .map((item) => ({ year: asNumber(item.fiscal_year), netIncome: asNumber(item.net_income) }))
    .filter((item) => item.year != null)
    .sort((a, b) => a.year - b.year)
}

export function buildGrowthComparisonTable(row, detail, projection, horizon) {
  const inputs = asRecord(row?.inputs)
  const outputs = asRecord(row?.outputs)
  const marketOutputs = asRecord(outputs.market_implied_growth_path)
  const marketPathRaw = Array.isArray(marketOutputs.path) ? marketOutputs.path : []
  const gStart = asNumber(marketOutputs.g_start)
  const gTerminal = asNumber(marketOutputs.g_terminal)
  const fadeYears = asNumber(marketOutputs.fade_years)
  const reason = typeof marketOutputs.reason === "string" ? marketOutputs.reason : null
  const exceedsKe = marketOutputs.g_start_exceeds_cost_of_equity === true
  const ke = asNumber(inputs.cost_of_equity)
  const payout = asNumber(inputs.payout)

  const marketByOffset = new Map()
  for (const item of marketPathRaw) {
    const record = asRecord(item)
    const offset = asNumber(record.year_offset)
    const growth = asNumber(record.growth)
    if (offset != null) marketByOffset.set(offset, growth)
  }
  const maxMarketOffset = marketByOffset.size ? Math.max(...marketByOffset.keys()) : 0

  const orderedStatements = orderedProjectedNetIncome(projection)
  const firstProjectedYear = orderedStatements.length ? orderedStatements[0].year : null
  const lastActual = lastActualNetIncome(detail, firstProjectedYear)

  const houseByOffset = new Map()
  orderedStatements.forEach((item, index) => {
    const previous = index === 0 ? lastActual : orderedStatements[index - 1].netIncome
    const growth = previous != null && previous > 0 && item.netIncome != null ? item.netIncome / previous - 1 : null
    houseByOffset.set(index + 1, growth)
  })
  const maxHouseOffset = orderedStatements.length
  const houseFirstYear = houseByOffset.get(1) ?? null

  const annualOffsets = Math.max(maxMarketOffset, maxHouseOffset)
  const config = HORIZON_CONFIG[horizon] ?? HORIZON_CONFIG.year

  const periods = []
  for (let offset = 1; offset <= annualOffsets && periods.length < MAX_ROWS; offset += 1) {
    const yearLabel = firstProjectedYear != null ? firstProjectedYear + (offset - 1) : offset
    const marketAnnual = marketByOffset.has(offset)
      ? marketByOffset.get(offset)
      : offset > maxMarketOffset && maxMarketOffset > 0
        ? gTerminal
        : null
    const houseAnnual = houseByOffset.has(offset) ? houseByOffset.get(offset) : null
    for (let sub = 1; sub <= config.subPeriods && periods.length < MAX_ROWS; sub += 1) {
      const interpolated = config.subPeriods > 1
      const market = interpolated ? subAnnualRate(marketAnnual, config.exponent) : marketAnnual
      const house = interpolated ? subAnnualRate(houseAnnual, config.exponent) : houseAnnual
      const delta = market != null && house != null ? market - house : null
      periods.push({
        label: config.label(yearLabel, sub),
        market,
        house,
        delta,
        interpolated,
      })
    }
  }

  const terminalYear = firstProjectedYear != null && fadeYears != null ? firstProjectedYear + fadeYears - 1 : null

  return {
    periods,
    meta: { gStart, gTerminal, ke, payout, reason, exceedsKe, houseFirstYear, terminalYear },
  }
}

const REASON_SENTENCES = {
  eps_unavailable: "Bénéfices négatifs ou indisponibles : impossible d'inverser une croissance exigée depuis le PER.",
  payout_unavailable: "Taux de distribution indisponible : impossible de reconstruire le dividende implicite nécessaire au modèle H.",
  ke_below_terminal_growth: "Le coût des fonds propres ne dépasse pas la croissance terminale : le modèle H ne peut pas être inversé dans ces conditions.",
  price_unavailable: "Cours de marché indisponible : impossible de calculer la croissance implicite dans le cours.",
}

const DELTA_TOLERANCE = 0.005

export function buildImpliedGrowthSentences(row, table) {
  const meta = table?.meta ?? {}
  const sentences = []

  if (meta.reason && REASON_SENTENCES[meta.reason]) {
    sentences.push(REASON_SENTENCES[meta.reason])
    return sentences
  }

  if (meta.gStart == null) {
    sentences.push("Croissance implicite dans le cours indisponible pour ce titre.")
    return sentences
  }

  const gStartPct = fmtPctText(meta.gStart)
  const gTerminalPct = fmtPctText(meta.gTerminal)
  const horizonYear = meta.terminalYear != null ? String(meta.terminalYear) : "long terme"
  const kePct = fmtPctText(meta.ke)
  const payoutPct = fmtPctText(meta.payout)
  sentences.push(
    `Au cours actuel, le marché exige une croissance des bénéfices d'environ ${gStartPct}/an l'an prochain, décroissant vers ${gTerminalPct} à l'horizon ${horizonYear} (modèle H, Ke ${kePct}, payout ${payoutPct}).`,
  )

  if (meta.houseFirstYear != null) {
    const houseFirstPct = fmtPctText(meta.houseFirstYear)
    const deltaPts = (meta.gStart - meta.houseFirstYear) * 100
    if (deltaPts > DELTA_TOLERANCE * 100) {
      sentences.push(`Le modèle maison prévoit ${houseFirstPct} : le cours intègre des attentes supérieures de ${fmtPtsText(deltaPts)} pts.`)
    } else if (deltaPts < -DELTA_TOLERANCE * 100) {
      sentences.push(`Le modèle maison prévoit ${houseFirstPct} : le cours intègre des attentes inférieures de ${fmtPtsText(Math.abs(deltaPts))} pts.`)
    } else {
      sentences.push(`Le modèle maison prévoit ${houseFirstPct} : le cours intègre des attentes cohérentes avec le modèle maison.`)
    }
  } else {
    sentences.push("Modèle maison : croissance de la première année non disponible pour comparaison directe.")
  }

  if (meta.exceedsKe) {
    sentences.push("Le cours implique une croissance initiale supérieure au coût des fonds propres — attentes non soutenables au sens du modèle de Gordon.")
  }

  return sentences
}
