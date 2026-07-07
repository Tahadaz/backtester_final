from __future__ import annotations

import re
from pathlib import Path

from quant_core.fundamentals.cross_section.masi_float_shares import MASI_FLOAT_SHARES


def _parse_masi_components_from_ts() -> dict[str, int]:
    root = Path(__file__).resolve().parents[2]
    source = (root / "frontend" / "lib" / "builtin-dashboard-indices.ts").read_text(encoding="utf-8")
    match = re.search(
        r'const MASI_FLOATING_SHARE_COMPONENTS: DashboardCustomIndexComponent\[\] = \[([\s\S]*?)\n\]',
        source,
    )
    assert match is not None, "missing MASI_FLOATING_SHARE_COMPONENTS in builtin-dashboard-indices.ts"
    return {
        item.group(1): int(item.group(2).replace("_", ""))
        for item in re.finditer(r'symbol: "([^"]+)", shares: ([0-9_]+)', match.group(1))
    }


def test_python_masi_float_shares_match_frontend_source() -> None:
    ts_components = _parse_masi_components_from_ts()
    assert MASI_FLOAT_SHARES == ts_components
    assert MASI_FLOAT_SHARES["ATW"] == 64_542_252
    assert MASI_FLOAT_SHARES["IAM"] == 175_819_068
    assert MASI_FLOAT_SHARES["BCP"] == 30_496_871
