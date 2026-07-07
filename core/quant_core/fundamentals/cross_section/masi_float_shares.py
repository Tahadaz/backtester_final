"""Generated MASI all-share floating-share snapshot for Python consumers.

Generated from ``frontend/lib/builtin-dashboard-indices.ts`` which was itself
generated from ``Compo_All_Indices.xlsx`` (snapshot 2026-05-25).

Keep this module in sync with ``BUILTIN_WEIGHTED_MASI_INDEX`` in the frontend.
The backtest uses this as a latest-known float-share snapshot across history:
exact for live construction, approximate for historical benchmark weights.
"""

from __future__ import annotations

MASI_FLOAT_SHARES_SNAPSHOT_DATE = "2026-05-25"

MASI_FLOAT_SHARES: dict[str, int] = {
    "ATW": 64542252,
    "MNG": 1779701,
    "MSA": 25688460,
    "IAM": 175819068,
    "LHM": 8200934,
    "BOA": 55070470,
    "TGC": 13869733,
    "GTM": 12000000,
    "CMA": 5052601,
    "AKT": 7079604,
    "BCP": 30496871,
    "TQM": 3538281,
    "CFG": 29756766,
    "CSR": 28346143,
    "WAA": 875000,
    "LBV": 1302281,
    "ADH": 140892939,
    "CMT": 840617,
    "GAZ": 1031250,
    "ADI": 8831435,
    "ARD": 7540878,
    "CIH": 8901406,
    "CMG": 8500450,
    "HPS": 4814024,
    "SID": 1365000,
    "CDM": 2720304,
    "JET": 1211809,
    "LES": 6907878,
    "SMI": 246764,
    "SOT": 5746425,
    "TMA": 1344000,
    "RDS": 11793983,
    "MUT": 7397390,
    "VCN": 4103540,
    "BCI": 2655857,
    "ATL": 12056719,
    "DHO": 26280000,
    "CAP": 4910618,
    "SBM": 565931,
    "SAH": 411687,
    "RIS": 3202426,
    "ATH": 10058906,
    "MIC": 756000,
    "IMO": 6304900,
    "DWY": 660017,
    "AFM": 400000,
    "AGM": 70000,
    "EQD": 334050,
    "SLF": 937236,
    "COL": 5641164,
    "UMR": 2282776,
    "DRI": 89513,
    "OUL": 297000,
    "SNP": 960000,
    "ALM": 139786,
    "DYT": 698677,
    "NKL": 4500000,
    "NEJ": 51163,
    "CTM": 245196,
    "MAB": 207627,
    "FBR": 503644,
    "SNA": 1769515,
    "S2M": 243621,
    "PRO": 100000,
    "MLE": 277677,
    "M2M": 226722,
    "BAL": 348800,
    "STR": 374555,
    "AFI": 145750,
    "MOX": 121875,
    "CRS": 1316250,
    "SRM": 64000,
    "MDP": 1195956,
    "INV": 133951,
    "DLM": 350000,
    "ZDJ": 57285,
    "IBC": 187869,
    "REB": 35291,
}


def masi_float_shares() -> dict[str, int]:
    return dict(MASI_FLOAT_SHARES)


__all__ = ["MASI_FLOAT_SHARES", "MASI_FLOAT_SHARES_SNAPSHOT_DATE", "masi_float_shares"]
