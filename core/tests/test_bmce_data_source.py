from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant_core.data import BMCEDataSource  # noqa: E402


def test_bmce_loader_accepts_french_header_variants(tmp_path: Path) -> None:
    path = tmp_path / "bmce_variant_headers.csv"
    path.write_text(
        "\n".join(
            [
                "Date,Ouverture,+haut,+bas,Close,Volue",
                "2024-01-02,100,110,90,105,1000",
                "2024-01-03,101,111,91,106,1100",
            ]
        ),
        encoding="utf-8",
    )

    ds = BMCEDataSource(timezone="UTC")
    md = ds.load(
        symbols=["ATW"],
        start="2024-01-01",
        end="2024-01-31",
        interval="1d",
        paths=str(path),
    )

    bars = md.bars["ATW"]
    assert list(bars.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert str(bars.index.tz) == "UTC"
    assert float(bars.iloc[0]["Open"]) == 100.0
    assert float(bars.iloc[0]["High"]) == 110.0
    assert float(bars.iloc[0]["Low"]) == 90.0
    assert float(bars.iloc[0]["Close"]) == 105.0
    assert float(bars.iloc[0]["Volume"]) == 1000.0
