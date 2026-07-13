// Static, prospectus-sourced data for the T2S Group Holding IPO card.
//
// Source: AMMC-visaed prospectus "Note d'operation - Introduction en Bourse de
// T2S Group Holding", visa VI/EM/021/2026 du 06/07/2026 (document de reference
// EN/EM/010/2026). All figures are the issuer/advisor's own; nothing here is
// produced by the live valuation engine. This is editorial reference data only.
//
// Numbers are transcribed verbatim from the note d'operation. Do not recompute
// them from the live fundamentals pipeline - T2S is not yet listed and has no
// price history, so the engine cannot value it.

export const IPO_SENTINEL_SYMBOL = "T2S:IPO"

export type IpoMethodValuation = {
  key: string
  label: string
  fairValue: number // MAD / share
  detail: string
}

export type IpoPeer = {
  name: string
  country: string
  marketCapMusd: number
  evEbe2026e: number | null
  evEbe2027p: number | null
  pe2026e: number | null
  pe2027p: number | null
  isLocal?: boolean
  note?: string
  category?: "prospectus" | "local_anchor" | "custom"
}

export type IpoPeerStats = {
  mean: { evEbe2026e: number | null; evEbe2027p: number | null; pe2026e: number | null; pe2027p: number | null }
  median: { evEbe2026e: number | null; evEbe2027p: number | null; pe2026e: number | null; pe2027p: number | null }
}

export type IpoBpRow = {
  key: string
  label: string
  format: "money" | "pct"
  // 2023, 2024, 2025, 2026e, 2027p, 2028p, 2029p, 2030p
  values: Array<number | null>
}

export type IpoDcfFlowRow = {
  key: string
  label: string
  // 2026e, 2027p, 2028p, 2029p, 2030p, normatif
  values: Array<number | null>
}

export type IpoWaccRow = { label: string; value: string }

export type IpoBridgeStep = {
  label: string
  value: number | null // MMAD unless noted
  kind: "add" | "subtract" | "total" | "result"
  note?: string
}

export type IpoBaseRateRow = {
  ipo: string
  year: number
  oversubscription: string
  satisfaction: string
  j1Return: number | null
  j5Return: number | null
  j10Return: number | null
  j1Reserved?: boolean
  performanceNote?: string
  note?: string
  source: string
  estimated?: boolean // true when the row (or a figure within it, e.g. a derived satisfaction) is not a directly published number
}

export const IPO_T2S = {
  meta: {
    name: "T2S Group Holding",
    ticker: "T2S",
    sector: "Distribution d'equipements & dispositifs medicaux",
    subSectors: "RADONCO - ORAS - Dispositifs medicaux - IVD - Radiopharma - Systemes digitaux - SAV",
    market: "Bourse de Casablanca - Marche principal",
    offerPrice: 223, // MAD / share (prime d'emission incluse)
    nominal: 50, // MAD (reduit de 100 a 50 a compter de la 1ere cotation)
    subscriptionOpen: "13/07/2026",
    subscriptionClose: "17/07/2026 15h30",
    firstQuote: "27/07/2026",
    // Structure de l'operation
    newShares: 1_569_506, // augmentation de capital
    capitalIncreaseMad: 349_999_838, // prime d'emission incluse
    securedShares: 3_363_228, // cession
    secondaryMad: 749_999_844,
    totalDealMad: 1_099_999_682,
    // Valorisation induite au prix de 223 MAD
    postMoneyEquityMmad: 4_508,
    sharesOutstanding: 20_215_247, // = postMoneyEquity / offerPrice (approx.)
    netDebt2025Mmad: 222,
    prospectusRef: "AMMC - visa VI/EM/021/2026 du 06/07/2026",
    referenceDoc: "Document de reference EN/EM/010/2026",
    trancheInstitutionalShares: 3_139_013,
    trancheRetailShares: 1_793_721,
    trancheInstitutionalMinShares: 13_452,
    retailBlockSize: 100,
    defaultBlockedDays: 12,
    subscriptionCapShares: 493_273, // 10% de l'offre, plafond par investisseur, les deux types
  },

  // Methodes de valorisation retenues (note d'operation, synthese p.38)
  methods: [
    { key: "dcf", label: "DCF (FCFF)", fairValue: 301, detail: "CMPC 10,28% - g 2,0% - actualisation mi-annee" },
    { key: "ev_ebe", label: "Comparables EV/EBE", fairValue: 295, detail: "Moyenne 2026e-2027p (14,3x / 11,5x)" },
    { key: "pe", label: "Comparables P/E", fairValue: 318, detail: "Moyenne 2026e-2027p (25,9x / 21,2x)" },
  ] as IpoMethodValuation[],

  // Multiples induits par le prix de 223 MAD (equity post-money 4 508 MMAD)
  inducedMultiples: {
    evEbe: { y2025: 12.4, y2026e: 11.1, y2027p: 8.7, avg2627: 9.9 },
    pe: { y2025: 22.0, y2026e: 18.7, y2027p: 14.5, avg2627: 16.6 },
  },

  // Echantillon de comparables boursiers (Capital IQ, 3 mois au 25/06/2026)
  peers: [
    {
      name: "Vicenne",
      country: "Maroc",
      marketCapMusd: 449,
      evEbe2026e: 14.4,
      evEbe2027p: 13.0,
      pe2026e: 28.3,
      pe2027p: 27.6,
      isLocal: true,
      note: "Comp directe; IPO 07/2025 a 236 DH, +40% premiere semaine, satisfaction retail 1,56%.",
      category: "prospectus",
    },
    { name: "Entero Healthcare Solutions", country: "Inde", marketCapMusd: 552, evEbe2026e: 19.9, evEbe2027p: 11.1, pe2026e: 34.9, pe2027p: 19.6, category: "prospectus" },
    { name: "AddLife AB", country: "Suede", marketCapMusd: 1_978, evEbe2026e: 12.8, evEbe2027p: 11.7, pe2026e: 24.5, pe2027p: 21.4, category: "prospectus" },
    { name: "Asker Healthcare Group", country: "Suede", marketCapMusd: 3_131, evEbe2026e: 14.3, evEbe2027p: 12.8, pe2026e: 25.3, pe2027p: 21.8, category: "prospectus" },
    { name: "Uniphar plc", country: "Irlande", marketCapMusd: 1_308, evEbe2026e: 10.0, evEbe2027p: 9.0, pe2026e: 16.7, pe2027p: 15.4, category: "prospectus" },
  ] as IpoPeer[],
  localAnchorPeers: [
    {
      name: "Akdital",
      country: "Maroc",
      marketCapMusd: 1_650,
      evEbe2026e: null,
      evEbe2027p: null,
      pe2026e: null,
      pe2027p: null,
      isLocal: true,
      note: "Ancre locale de sentiment healthcare; operateur, pas distributeur.",
      category: "local_anchor",
    },
  ] as IpoPeer[],
  peerStats: {
    mean: { evEbe2026e: 14.3, evEbe2027p: 11.5, pe2026e: 25.9, pe2027p: 21.2 },
    median: { evEbe2026e: 14.3, evEbe2027p: 11.7, pe2026e: 25.3, pe2027p: 21.4 },
  } as IpoPeerStats,

  casablancaBaseRates: [
    {
      ipo: "TGCC",
      year: 2021,
      oversubscription: "n.d.",
      satisfaction: "n.d.",
      j1Return: null,
      j5Return: null,
      j10Return: null,
      performanceNote: "Historique OHLC de l'app disponible seulement depuis 2023.",
      note: "+553% depuis l'IPO (long terme, presse 2025)",
      source: "FNH",
      estimated: true,
    },
    {
      ipo: "Akdital",
      year: 2022,
      oversubscription: "3,77x",
      satisfaction: "~26% (dérivé ≈1/3,77)",
      j1Return: 302 / 300 - 1,
      j5Return: 300 / 300 - 1,
      j10Return: 284 / 300 - 1,
      performanceNote: "Cours de clôture OHLC de l'app vs prix d'offre de 300 MAD.",
      note: "8 225 souscripteurs; marché froid 2022; +340% depuis (long terme)",
      source: "Médias24 14/12/2022",
      estimated: false,
    },
    {
      ipo: "CMGP",
      year: 2024,
      oversubscription: "37x",
      satisfaction: "~2,7% (dérivé ≈1/37)",
      j1Return: 219.95 / 200 - 1,
      j5Return: 277.4 / 200 - 1,
      j10Return: 277.4 / 200 - 1,
      performanceNote: "Cours de clôture OHLC de l'app vs prix d'offre de 200 MAD.",
      note: "33 700 souscripteurs",
      source: "presse (FNH)",
      estimated: true,
    },
    {
      ipo: "Vicenne",
      year: 2025,
      oversubscription: "64x",
      satisfaction: "1,56% moy. / 2,29% retail",
      j1Return: 259.55 / 236 - 1,
      j5Return: 379.85 / 236 - 1,
      j10Return: 485 / 236 - 1,
      j1Reserved: true,
      performanceNote: "J1 réservé à la hausse; observations OHLC post-offre vs 236 MAD.",
      note: "37 674 souscripteurs; comp directe medtech",
      source: "Médias24/Boursenews 07/2025",
      estimated: false,
    },
    {
      ipo: "Cash Plus",
      year: 2025,
      oversubscription: "64x",
      satisfaction: "~1,6% (dérivé)",
      j1Return: 219.95 / 200 - 1,
      j5Return: 321.9 / 200 - 1,
      j10Return: 318 / 200 - 1,
      performanceNote: "Observations OHLC post-offre de l'app vs 200 MAD.",
      note: "81 466 souscripteurs",
      source: "Morocco World News/african-markets 12/2025",
      estimated: true,
    },
    {
      ipo: "SGTM",
      year: 2025,
      oversubscription: "34x",
      satisfaction: "2,94% moy.",
      j1Return: 461.95 / 420 - 1,
      j5Return: 676.1 / 420 - 1,
      j10Return: 760 / 420 - 1,
      j1Reserved: true,
      performanceNote: "J1 réservé à la hausse; observations OHLC post-offre vs 420 MAD.",
      note: "171 377 souscripteurs (168k particuliers); record",
      source: "Médias24/Le Desk 12/2025",
      estimated: false,
    },
  ] as IpoBaseRateRow[],

  // Principaux agregats du business plan pre-money (MMAD)
  bpYears: ["2023", "2024", "2025", "2026e", "2027p", "2028p", "2029p", "2030p"],
  bp: [
    { key: "revenue", label: "Chiffre d'affaires", format: "money", values: [1_374, 1_508, 1_763, 2_144, 2_589, 3_029, 3_526, 4_168] },
    { key: "gross_margin", label: "Marge brute", format: "money", values: [470, 546, 683, 765, 936, 1_110, 1_312, 1_570] },
    { key: "gross_margin_pct", label: "Marge brute (%)", format: "pct", values: [0.342, 0.362, 0.387, 0.357, 0.362, 0.366, 0.372, 0.377] },
    { key: "ebe", label: "EBE", format: "money", values: [246, 276, 388, 434, 555, 675, 814, 1_007] },
    { key: "rnpg", label: "Resultat net part du groupe", format: "money", values: [null, null, null, 241, 312, null, null, null] },
  ] as IpoBpRow[],
  bpCagr: { revenue2630: 0.181, ebe2630: 0.232 }, // TCAM 26e-30p (CA depuis note; EBE derive)

  // Calcul du CMPC (note d'operation p.33-34)
  wacc: [
    { label: "Taux sans risque (BDT 10 ans, 29/06/2026)", value: "3,22%" },
    { label: "Prime de risque marche actions", value: "6,07%" },
    { label: "Beta desendette", value: "1,29" },
    { label: "Beta endette", value: "1,65" },
    { label: "Gearing cible (D/E)", value: "40,0%" },
    { label: "Cout des fonds propres", value: "13,22%" },
    { label: "Cout de la dette (avant IS)", value: "4,20%" },
    { label: "Cout de la dette (net d'IS)", value: "2,92%" },
    { label: "Taux d'IS", value: "30,44%" },
    { label: "CMPC retenu", value: "10,28%" },
    { label: "Croissance a l'infini (g)", value: "2,0%" },
  ] as IpoWaccRow[],

  // Resultats DCF - flux de tresorerie disponibles (MMAD, note d'operation p.34)
  dcfFlowYears: ["2026e", "2027p", "2028p", "2029p", "2030p", "Normatif"],
  dcfFlows: [
    { key: "ebe", label: "EBE", values: [434, 555, 675, 814, 1_007, 1_028] },
    { key: "tax", label: "IS theorique sur le REX", values: [-107, -151, -185, -224, -279, -299] },
    { key: "wc", label: "Variation du BFR", values: [-175, -91, -89, -117, -139, -22] },
    { key: "capex", label: "Investissements", values: [-84, -134, -33, -39, -46, -47] },
    { key: "fcff", label: "Flux de tresorerie disponibles", values: [68, 179, 368, 433, 544, 660] },
    { key: "fcff_pv", label: "FCFF actualises", values: [65, 155, 288, 308, 350, 5_137] },
  ] as IpoDcfFlowRow[],

  // Passage valeur d'entreprise -> valeur des fonds propres (MMAD)
  bridge: [
    { label: "Somme des FCFF actualises 2026e-2030p", value: 1_165, kind: "add" },
    { label: "Valeur terminale actualisee", value: 5_137, kind: "add" },
    { label: "Valeur d'entreprise", value: 6_302, kind: "total" },
    { label: "Dette nette au 31.12.2025", value: -222, kind: "subtract" },
    { label: "Valeur des fonds propres", value: 6_080, kind: "result", note: "= 301 MAD / action" },
  ] as IpoBridgeStep[],

  // Upsides non integres au business plan pre-money (note d'operation, definitions + p.28)
  upsides: [
    "Nouveaux partenariats et commercialisation de nouveaux equipements / dispositifs medicaux",
    "Operations de croissance externe potentielles",
    "Acquisition de 45,5% de Cyclopharma (radiopharma) - 102 MMAD 2026e-2027p",
    "Unite de production de cyclotron a Fes (mise en service 2028) - doublement capacite traceurs PET",
    "Distribution GE Healthcare : presence dans plus de 20 pays d'Afrique subsaharienne francophone",
  ],

  // Facteurs de risque (note d'operation p.39 + lecture desk)
  risks: [
    "Liquidite du titre post-IPO (flottant et volumes)",
    "Volatilite du cours et risque de perte en capital",
    "Execution du business plan : TCAM CA +18,1% 2026e-2030p a realiser",
    "BFR eleve : delai de rotation clients ~169 j de CA en 2026e",
    "Concentration sur partenariats OEM et expansion Afrique",
  ],
} as const

// Derived helpers (kept out of the component to keep it presentational).
export function ipoMethodMeanFairValue(): number {
  const vals = IPO_T2S.methods.map((m) => m.fairValue)
  return vals.reduce((a, b) => a + b, 0) / vals.length
}

export function ipoBandLowHigh(): { low: number; high: number } {
  const vals = IPO_T2S.methods.map((m) => m.fairValue)
  return { low: Math.min(...vals), high: Math.max(...vals) }
}

// Investor upside from the offer price to a given fair value (fairValue / offer - 1).
export function ipoUpsideFromOffer(fairValue: number): number {
  return fairValue / IPO_T2S.meta.offerPrice - 1
}

// Prospectus "decote" of the offer price vs a fair value (1 - offer / fairValue).
export function ipoOfferDecote(fairValue: number): number {
  return 1 - IPO_T2S.meta.offerPrice / fairValue
}
