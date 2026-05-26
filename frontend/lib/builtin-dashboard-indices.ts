// Generated from C:/Users/taha/Downloads/Compo_All_Indices.xlsx (session 2026-05-25).
import type {
  DashboardCustomIndexComponent,
  DashboardCustomIndexDefinition,
} from "@/lib/dashboard-types"

function componentMap(components: DashboardCustomIndexComponent[]): Record<string, number> {
  return Object.fromEntries(components.map((component) => [component.symbol, component.shares]))
}

function builtinIndex(
  id: string,
  name: string,
  components: DashboardCustomIndexComponent[],
): DashboardCustomIndexDefinition {
  return {
    id,
    name,
    symbols: components.map((component) => component.symbol),
    component_shares: componentMap(components),
    components,
    is_weighted_complete: true,
    editable: false,
  }
}

const MASI_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "ATW", shares: 64_542_252 },
  { symbol: "MNG", shares: 1_779_701 },
  { symbol: "MSA", shares: 25_688_460 },
  { symbol: "IAM", shares: 175_819_068 },
  { symbol: "LHM", shares: 8_200_934 },
  { symbol: "BOA", shares: 55_070_470 },
  { symbol: "TGC", shares: 13_869_733 },
  { symbol: "GTM", shares: 12_000_000 },
  { symbol: "CMA", shares: 5_052_601 },
  { symbol: "AKT", shares: 7_079_604 },
  { symbol: "BCP", shares: 30_496_871 },
  { symbol: "TQM", shares: 3_538_281 },
  { symbol: "CFG", shares: 29_756_766 },
  { symbol: "CSR", shares: 28_346_143 },
  { symbol: "WAA", shares: 875_000 },
  { symbol: "LBV", shares: 1_302_281 },
  { symbol: "ADH", shares: 140_892_939 },
  { symbol: "CMT", shares: 840_617 },
  { symbol: "GAZ", shares: 1_031_250 },
  { symbol: "ADI", shares: 8_831_435 },
  { symbol: "ARD", shares: 7_540_878 },
  { symbol: "CIH", shares: 8_901_406 },
  { symbol: "CMG", shares: 8_500_450 },
  { symbol: "HPS", shares: 4_814_024 },
  { symbol: "SID", shares: 1_365_000 },
  { symbol: "CDM", shares: 2_720_304 },
  { symbol: "JET", shares: 1_211_809 },
  { symbol: "LES", shares: 6_907_878 },
  { symbol: "SMI", shares: 246_764 },
  { symbol: "SOT", shares: 5_746_425 },
  { symbol: "TMA", shares: 1_344_000 },
  { symbol: "RDS", shares: 11_793_983 },
  { symbol: "MUT", shares: 7_397_390 },
  { symbol: "VCN", shares: 4_103_540 },
  { symbol: "BCI", shares: 2_655_857 },
  { symbol: "ATL", shares: 12_056_719 },
  { symbol: "DHO", shares: 26_280_000 },
  { symbol: "CAP", shares: 4_910_618 },
  { symbol: "SBM", shares: 565_931 },
  { symbol: "SAH", shares: 411_687 },
  { symbol: "RIS", shares: 3_202_426 },
  { symbol: "ATH", shares: 10_058_906 },
  { symbol: "MIC", shares: 756_000 },
  { symbol: "IMO", shares: 6_304_900 },
  { symbol: "DWY", shares: 660_017 },
  { symbol: "AFM", shares: 400_000 },
  { symbol: "AGM", shares: 70_000 },
  { symbol: "EQD", shares: 334_050 },
  { symbol: "SLF", shares: 937_236 },
  { symbol: "COL", shares: 5_641_164 },
  { symbol: "UMR", shares: 2_282_776 },
  { symbol: "DRI", shares: 89_513 },
  { symbol: "OUL", shares: 297_000 },
  { symbol: "SNP", shares: 960_000 },
  { symbol: "ALM", shares: 139_786 },
  { symbol: "DYT", shares: 698_677 },
  { symbol: "NKL", shares: 4_500_000 },
  { symbol: "NEJ", shares: 51_163 },
  { symbol: "CTM", shares: 245_196 },
  { symbol: "MAB", shares: 207_627 },
  { symbol: "FBR", shares: 503_644 },
  { symbol: "SNA", shares: 1_769_515 },
  { symbol: "S2M", shares: 243_621 },
  { symbol: "PRO", shares: 100_000 },
  { symbol: "MLE", shares: 277_677 },
  { symbol: "M2M", shares: 226_722 },
  { symbol: "BAL", shares: 348_800 },
  { symbol: "STR", shares: 374_555 },
  { symbol: "AFI", shares: 145_750 },
  { symbol: "MOX", shares: 121_875 },
  { symbol: "CRS", shares: 1_316_250 },
  { symbol: "SRM", shares: 64_000 },
  { symbol: "MDP", shares: 1_195_956 },
  { symbol: "INV", shares: 133_951 },
  { symbol: "DLM", shares: 350_000 },
  { symbol: "ZDJ", shares: 57_285 },
  { symbol: "IBC", shares: 187_869 },
  { symbol: "REB", shares: 35_291 },
]

export const MASI20_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "ATW", shares: 55_299_801 },
  { symbol: "MSA", shares: 25_688_460 },
  { symbol: "IAM", shares: 175_819_068 },
  { symbol: "LHM", shares: 8_200_934 },
  { symbol: "BOA", shares: 55_070_470 },
  { symbol: "TGC", shares: 13_869_733 },
  { symbol: "CMA", shares: 5_052_601 },
  { symbol: "AKT", shares: 7_079_604 },
  { symbol: "BCP", shares: 30_496_871 },
  { symbol: "TQM", shares: 3_538_281 },
  { symbol: "CFG", shares: 29_756_766 },
  { symbol: "CSR", shares: 28_346_143 },
  { symbol: "LBV", shares: 1_302_281 },
  { symbol: "ADH", shares: 140_892_939 },
  { symbol: "ADI", shares: 8_831_435 },
  { symbol: "CMG", shares: 8_500_450 },
  { symbol: "SID", shares: 1_365_000 },
  { symbol: "CDM", shares: 2_720_304 },
  { symbol: "JET", shares: 1_211_809 },
  { symbol: "RDS", shares: 11_793_983 },
]

const MASI_ESG_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "MNG", shares: 536_283 },
  { symbol: "ATW", shares: 8_723_137 },
  { symbol: "IAM", shares: 41_053_752 },
  { symbol: "MSA", shares: 3_236_746 },
  { symbol: "BOA", shares: 12_578_095 },
  { symbol: "TQM", shares: 1_087_432 },
  { symbol: "LHM", shares: 1_016_916 },
  { symbol: "CMA", shares: 629_410 },
  { symbol: "CSR", shares: 5_395_216 },
  { symbol: "AKT", shares: 613_094 },
  { symbol: "CDM", shares: 643_080 },
  { symbol: "CIH", shares: 1_637_859 },
  { symbol: "LES", shares: 1_450_654 },
  { symbol: "BCI", shares: 847_218 },
  { symbol: "SID", shares: 209_430 },
  { symbol: "ATL", shares: 2_598_223 },
  { symbol: "SBM", shares: 124_505 },
  { symbol: "HPS", shares: 457_703 },
  { symbol: "ARD", shares: 627_150 },
  { symbol: "ATH", shares: 2_147_576 },
]

const MASI_MID_SMALL_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "CMT", shares: 840_617 },
  { symbol: "CFG", shares: 17_886_792 },
  { symbol: "ARD", shares: 7_540_878 },
  { symbol: "CMG", shares: 8_500_450 },
  { symbol: "HPS", shares: 4_814_024 },
  { symbol: "SID", shares: 1_365_000 },
  { symbol: "JET", shares: 1_211_809 },
  { symbol: "LES", shares: 6_907_878 },
  { symbol: "SMI", shares: 246_764 },
  { symbol: "RDS", shares: 11_793_983 },
  { symbol: "MUT", shares: 7_397_390 },
  { symbol: "VCN", shares: 4_103_540 },
  { symbol: "BCI", shares: 2_655_857 },
  { symbol: "ATL", shares: 12_056_719 },
  { symbol: "DHO", shares: 26_280_000 },
  { symbol: "SBM", shares: 565_931 },
  { symbol: "SAH", shares: 411_687 },
  { symbol: "RIS", shares: 3_202_426 },
  { symbol: "ATH", shares: 10_058_906 },
  { symbol: "MIC", shares: 756_000 },
  { symbol: "DWY", shares: 660_017 },
  { symbol: "AFM", shares: 400_000 },
  { symbol: "EQD", shares: 334_050 },
  { symbol: "SLF", shares: 937_236 },
  { symbol: "COL", shares: 5_641_164 },
  { symbol: "SNP", shares: 960_000 },
  { symbol: "NKL", shares: 4_500_000 },
  { symbol: "CTM", shares: 245_196 },
  { symbol: "SNA", shares: 1_769_515 },
  { symbol: "PRO", shares: 100_000 },
]

const SECTOR_AGRO_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "CSR", shares: 28_346_143 },
  { symbol: "LES", shares: 6_907_878 },
  { symbol: "MUT", shares: 7_397_390 },
  { symbol: "UMR", shares: 2_282_776 },
  { symbol: "DRI", shares: 89_513 },
  { symbol: "CRS", shares: 1_316_250 },
]

const SECTOR_ASSUR_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "WAA", shares: 875_000 },
  { symbol: "ATL", shares: 12_056_719 },
  { symbol: "SAH", shares: 411_687 },
  { symbol: "AFM", shares: 400_000 },
  { symbol: "AGM", shares: 70_000 },
]

const SECTOR_BANK_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "ATW", shares: 64_542_252 },
  { symbol: "BOA", shares: 55_070_470 },
  { symbol: "BCP", shares: 30_496_871 },
  { symbol: "CFG", shares: 29_756_766 },
  { symbol: "CIH", shares: 8_901_406 },
  { symbol: "CDM", shares: 2_720_304 },
  { symbol: "BCI", shares: 2_655_857 },
]

const SECTOR_B_MC_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "LHM", shares: 8_200_934 },
  { symbol: "TGC", shares: 13_869_733 },
  { symbol: "GTM", shares: 12_000_000 },
  { symbol: "CMA", shares: 5_052_601 },
  { symbol: "SID", shares: 1_365_000 },
  { symbol: "JET", shares: 1_211_809 },
  { symbol: "COL", shares: 5_641_164 },
  { symbol: "ALM", shares: 139_786 },
  { symbol: "AFI", shares: 145_750 },
]

const SECTOR_BOISS_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "SBM", shares: 565_931 },
  { symbol: "OUL", shares: 297_000 },
]

const SECTOR_CHIM_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "SNP", shares: 960_000 },
  { symbol: "MOX", shares: 121_875 },
]

const SECTOR_DISTR_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "LBV", shares: 1_302_281 },
  { symbol: "ATH", shares: 10_058_906 },
  { symbol: "NKL", shares: 4_500_000 },
  { symbol: "NEJ", shares: 51_163 },
  { symbol: "FBR", shares: 503_644 },
  { symbol: "SNA", shares: 1_769_515 },
  { symbol: "SRM", shares: 64_000 },
]

const SECTOR_ELEC_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "TQM", shares: 3_538_281 },
]

const SECTOR_IAG_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "CMG", shares: 8_500_450 },
]

const SECTOR_I_BEI_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "STR", shares: 374_555 },
  { symbol: "DLM", shares: 350_000 },
]

const SECTOR_IMMOB_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "ADH", shares: 140_892_939 },
  { symbol: "ADI", shares: 8_831_435 },
  { symbol: "RDS", shares: 11_793_983 },
]

const SECTOR_L_H_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "RIS", shares: 3_202_426 },
]

const SECTOR_L_SI_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "HPS", shares: 4_814_024 },
  { symbol: "MIC", shares: 756_000 },
  { symbol: "DWY", shares: 660_017 },
  { symbol: "DYT", shares: 698_677 },
  { symbol: "S2M", shares: 243_621 },
  { symbol: "M2M", shares: 226_722 },
  { symbol: "INV", shares: 133_951 },
  { symbol: "IBC", shares: 187_869 },
]

const SECTOR_MINES_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "MNG", shares: 1_779_701 },
  { symbol: "CMT", shares: 840_617 },
  { symbol: "SMI", shares: 246_764 },
  { symbol: "REB", shares: 35_291 },
]

const SECTOR_P_G_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "GAZ", shares: 1_031_250 },
  { symbol: "TMA", shares: 1_344_000 },
]

const SECTOR_PHARM_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "SOT", shares: 5_746_425 },
  { symbol: "PRO", shares: 100_000 },
]

const SECTOR_SANTE_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "AKT", shares: 7_079_604 },
  { symbol: "VCN", shares: 4_103_540 },
]

const SECTOR_SDT_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "MSA", shares: 25_688_460 },
]

const SECTOR_SF_AF_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "CAP", shares: 4_910_618 },
  { symbol: "EQD", shares: 334_050 },
  { symbol: "SLF", shares: 937_236 },
  { symbol: "MAB", shares: 207_627 },
  { symbol: "MLE", shares: 277_677 },
]

const SECTOR_S_P_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "MDP", shares: 1_195_956 },
]

const SECTOR_SP_H_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "DHO", shares: 26_280_000 },
  { symbol: "ZDJ", shares: 57_285 },
]

const SECTOR_SPI_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "ARD", shares: 7_540_878 },
  { symbol: "IMO", shares: 6_304_900 },
  { symbol: "BAL", shares: 348_800 },
]

const SECTOR_TCOM_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "IAM", shares: 175_819_068 },
]

const SECTOR_TRANS_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent[] = [
  { symbol: "CTM", shares: 245_196 },
]

export const BUILTIN_WEIGHTED_MASI_INDEX = builtinIndex(
  "builtin-masi-floating-shares",
  "MASI",
  MASI_FLOATING_SHARE_COMPONENTS,
)

export const MASI20_FLOATING_SHARE_INDEX = builtinIndex(
  "builtin-masi20-floating-shares",
  "MASI20 - actions flottantes",
  MASI20_FLOATING_SHARE_COMPONENTS,
)

export const MASI_ESG_FLOATING_SHARE_INDEX = builtinIndex(
  "builtin-masi-esg-floating-shares",
  "MASI ESG",
  MASI_ESG_FLOATING_SHARE_COMPONENTS,
)

export const MASI_MID_SMALL_FLOATING_SHARE_INDEX = builtinIndex(
  "builtin-masi-mid-small-floating-shares",
  "MASI Mid and Small Cap",
  MASI_MID_SMALL_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_AGRO_INDEX = builtinIndex(
  "builtin-masi-sector-agro-floating-shares",
  "MASI AGROALIMENTAIRE / PRODUCTION",
  SECTOR_AGRO_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_ASSUR_INDEX = builtinIndex(
  "builtin-masi-sector-assur-floating-shares",
  "MASI ASSURANCES",
  SECTOR_ASSUR_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_BANK_INDEX = builtinIndex(
  "builtin-masi-sector-bank-floating-shares",
  "MASI BANQUES",
  SECTOR_BANK_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_B_MC_INDEX = builtinIndex(
  "builtin-masi-sector-b-mc-floating-shares",
  "MASI BATIMENT ET MATERIAUX DE CONSTRUCTION",
  SECTOR_B_MC_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_BOISS_INDEX = builtinIndex(
  "builtin-masi-sector-boiss-floating-shares",
  "MASI BOISSONS",
  SECTOR_BOISS_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_CHIM_INDEX = builtinIndex(
  "builtin-masi-sector-chim-floating-shares",
  "MASI CHIMIE",
  SECTOR_CHIM_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_DISTR_INDEX = builtinIndex(
  "builtin-masi-sector-distr-floating-shares",
  "MASI DISTRIBUTEURS",
  SECTOR_DISTR_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_ELEC_INDEX = builtinIndex(
  "builtin-masi-sector-elec-floating-shares",
  "MASI ELECTRICITE",
  SECTOR_ELEC_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_IAG_INDEX = builtinIndex(
  "builtin-masi-sector-iag-floating-shares",
  "MASI INDUSTRIE AGRICOLE",
  SECTOR_IAG_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_I_BEI_INDEX = builtinIndex(
  "builtin-masi-sector-i-bei-floating-shares",
  "MASI INGENIERIES ET BIENS DEQUIPEMENT INDUSTRIELS",
  SECTOR_I_BEI_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_IMMOB_INDEX = builtinIndex(
  "builtin-masi-sector-immob-floating-shares",
  "MASI PARTICIPATION ET PROMOTION IMMOBILIERES",
  SECTOR_IMMOB_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_L_H_INDEX = builtinIndex(
  "builtin-masi-sector-l-h-floating-shares",
  "MASI LOISIRS ET HOTELS",
  SECTOR_L_H_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_L_SI_INDEX = builtinIndex(
  "builtin-masi-sector-l-si-floating-shares",
  "MASI MATERIELS,LOGICIELS ET SERVICES INFORMATIQUES",
  SECTOR_L_SI_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_MINES_INDEX = builtinIndex(
  "builtin-masi-sector-mines-floating-shares",
  "MASI MINES",
  SECTOR_MINES_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_P_G_INDEX = builtinIndex(
  "builtin-masi-sector-p-g-floating-shares",
  "MASI PETROLE ET GAZ",
  SECTOR_P_G_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_PHARM_INDEX = builtinIndex(
  "builtin-masi-sector-pharm-floating-shares",
  "MASI INDUSTRIE PHARMACEUTIQUE",
  SECTOR_PHARM_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_SANTE_INDEX = builtinIndex(
  "builtin-masi-sector-sante-floating-shares",
  "MASI SANTE",
  SECTOR_SANTE_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_SDT_INDEX = builtinIndex(
  "builtin-masi-sector-sdt-floating-shares",
  "MASI SERVICES DE TRANSPORT",
  SECTOR_SDT_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_SF_AF_INDEX = builtinIndex(
  "builtin-masi-sector-sf-af-floating-shares",
  "MASI SOCIETE DE FINANCEMENT ET AUTRES ACTIVITES FINANCIERES",
  SECTOR_SF_AF_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_S_P_INDEX = builtinIndex(
  "builtin-masi-sector-s-p-floating-shares",
  "MASI SYLVICULTURE ET PAPIER",
  SECTOR_S_P_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_SP_H_INDEX = builtinIndex(
  "builtin-masi-sector-sp-h-floating-shares",
  "MASI SOCIETES DE PORTEFEUILLES - HOLDINGS",
  SECTOR_SP_H_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_SPI_INDEX = builtinIndex(
  "builtin-masi-sector-spi-floating-shares",
  "MASI SOCIETES DE PLACEMENT IMMOBILIER",
  SECTOR_SPI_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_TCOM_INDEX = builtinIndex(
  "builtin-masi-sector-tcom-floating-shares",
  "MASI TELECOMMUNICATIONS",
  SECTOR_TCOM_FLOATING_SHARE_COMPONENTS,
)

export const MASI_SECTOR_TRANS_INDEX = builtinIndex(
  "builtin-masi-sector-trans-floating-shares",
  "MASI TRANSPORT",
  SECTOR_TRANS_FLOATING_SHARE_COMPONENTS,
)

export const BUILTIN_CUSTOM_DASHBOARD_INDICES: DashboardCustomIndexDefinition[] = [
  MASI20_FLOATING_SHARE_INDEX,
  MASI_ESG_FLOATING_SHARE_INDEX,
  MASI_MID_SMALL_FLOATING_SHARE_INDEX,
  MASI_SECTOR_AGRO_INDEX,
  MASI_SECTOR_ASSUR_INDEX,
  MASI_SECTOR_BANK_INDEX,
  MASI_SECTOR_B_MC_INDEX,
  MASI_SECTOR_BOISS_INDEX,
  MASI_SECTOR_CHIM_INDEX,
  MASI_SECTOR_DISTR_INDEX,
  MASI_SECTOR_ELEC_INDEX,
  MASI_SECTOR_IAG_INDEX,
  MASI_SECTOR_I_BEI_INDEX,
  MASI_SECTOR_IMMOB_INDEX,
  MASI_SECTOR_L_H_INDEX,
  MASI_SECTOR_L_SI_INDEX,
  MASI_SECTOR_MINES_INDEX,
  MASI_SECTOR_P_G_INDEX,
  MASI_SECTOR_PHARM_INDEX,
  MASI_SECTOR_SANTE_INDEX,
  MASI_SECTOR_SDT_INDEX,
  MASI_SECTOR_SF_AF_INDEX,
  MASI_SECTOR_S_P_INDEX,
  MASI_SECTOR_SP_H_INDEX,
  MASI_SECTOR_SPI_INDEX,
  MASI_SECTOR_TCOM_INDEX,
  MASI_SECTOR_TRANS_INDEX,
]

export const BUILTIN_DASHBOARD_INDEX_DEFINITIONS: DashboardCustomIndexDefinition[] = [
  BUILTIN_WEIGHTED_MASI_INDEX,
  ...BUILTIN_CUSTOM_DASHBOARD_INDICES,
]
