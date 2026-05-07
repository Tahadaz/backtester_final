from __future__ import annotations

from io import BytesIO

import pandas as pd

from services.api.app import models
from services.api.app import market_data_loader as loader_mod


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeS3:
    def __init__(self, payload_by_key: dict[str, bytes]) -> None:
        self._payload_by_key = payload_by_key

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, _FakeBody]:
        _ = Bucket
        return {"Body": _FakeBody(self._payload_by_key[Key])}


def test_load_close_series_from_store_treats_zero_as_missing(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "Close": [100.0, 0.0, 101.5],
        },
        index=pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"], utc=True),
    )
    buffer = BytesIO()
    frame.to_parquet(buffer, index=True)

    fake_s3 = _FakeS3({"market_data/AFI/1D.parquet": buffer.getvalue()})
    monkeypatch.setattr(loader_mod, "s3_client", lambda: fake_s3)

    close = loader_mod.load_close_series_from_store(object_key="market_data/AFI/1D.parquet")

    assert close.index.strftime("%Y-%m-%d").tolist() == ["2026-04-01", "2026-04-03"]
    assert close.tolist() == [100.0, 101.5]


def test_load_close_series_from_dataset_treats_zero_as_missing(monkeypatch) -> None:
    csv_payload = "\n".join(
        [
            "Date,Close",
            "2026-04-01,100",
            "2026-04-02,0",
            "2026-04-03,103.2",
        ]
    ).encode("utf-8")
    fake_s3 = _FakeS3({"datasets/hash/afi.csv": csv_payload})
    monkeypatch.setattr(loader_mod, "s3_client", lambda: fake_s3)

    dataset_row = models.Dataset(
        source="uploaded_file",
        symbol="afi.csv",
        timeframe="1D",
        data_hash="hash",
        filename="afi.csv",
        object_key="datasets/hash/afi.csv",
    )

    close = loader_mod.load_close_series_from_dataset(dataset_row=dataset_row, symbol="AFI")

    assert close.index.strftime("%Y-%m-%d").tolist() == ["2026-04-01", "2026-04-03"]
    assert close.tolist() == [100.0, 103.2]
