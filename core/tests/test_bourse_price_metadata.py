from __future__ import annotations

from quant_core.data import BDCSessionAdapter, BMCECapitalLiveAdapter, BourseDirectAdapter


def test_bourse_adapters_do_not_label_raw_close_as_adjusted_close() -> None:
    assert BDCSessionAdapter().fill_adj_close is False
    assert BMCECapitalLiveAdapter().fill_adj_close is False
    assert BourseDirectAdapter(url_template="https://example.invalid/{symbol}").fill_adj_close is False
