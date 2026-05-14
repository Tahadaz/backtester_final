import type {
  DashboardCustomIndexComponent,
  DashboardCustomIndexDefinition,
} from "@/lib/dashboard-types"

export const MASI20_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "AKT", shares: 7_079_604 },
  { symbol: "ADI", shares: 8_831_435 },
  { symbol: "CMG", shares: 8_500_005 },
  { symbol: "SID", shares: 1_365_000 },
  { symbol: "ATW", shares: 55_299_801 },
  { symbol: "BOA", shares: 55_070_470 },
  { symbol: "BCP", shares: 30_496_871 },
  { symbol: "CDM", shares: 2_720_304 },
  { symbol: "CFG", shares: 29_756_766 },
  { symbol: "CMA", shares: 5_052_601 },
  { symbol: "CSR", shares: 28_346_143 },
  { symbol: "ADH", shares: 140_892_939 },
  { symbol: "IAM", shares: 175_819_068 },
  { symbol: "JET", shares: 1_211_809 },
  { symbol: "LBV", shares: 1_302_281 },
  { symbol: "LHM", shares: 8_200_934 },
  { symbol: "RDS", shares: 11_793_983 },
  { symbol: "MSA", shares: 25_688_460 },
  { symbol: "TQM", shares: 3_538_281 },
  { symbol: "TGC", shares: 13_869_733 },
]

// The supplied rows included SID twice; component indices are ticker-keyed, so SID is stored once.
const MASI20_FLOATING_SHARE_MAP = Object.fromEntries(
  MASI20_FLOATING_SHARE_COMPONENTS.map((component) => [component.symbol, component.shares]),
)

export const MASI20_FLOATING_SHARE_INDEX: DashboardCustomIndexDefinition = {
  id: "builtin-masi20-floating-shares",
  name: "MASI20 - actions flottantes",
  symbols: MASI20_FLOATING_SHARE_COMPONENTS.map((component) => component.symbol),
  component_shares: MASI20_FLOATING_SHARE_MAP,
  components: MASI20_FLOATING_SHARE_COMPONENTS,
  is_weighted_complete: true,
  editable: false,
}
