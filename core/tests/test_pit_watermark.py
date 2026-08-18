from __future__ import annotations

from datetime import date, datetime, timezone
import math

from core.quant_core.pit_watermark import canonical_json, source_watermark_v1


def test_canonical_watermark_is_order_unicode_and_timezone_stable() -> None:
    composed = "é"
    decomposed = "e\u0301"
    first = [
        ("scores", [decomposed, date(2024, 1, 1)], {"z": -0.0, "a": None}),
        ("calendar", [1], datetime(2024, 1, 1, 1, tzinfo=timezone.utc)),
    ]
    second = [
        ("calendar", [1], datetime.fromisoformat("2024-01-01T02:00:00+01:00")),
        ("scores", [composed, date(2024, 1, 1)], {"a": None, "z": -0.0}),
    ]
    assert source_watermark_v1(first) == source_watermark_v1(second)
    assert canonical_json(-0.0) == '{"$float":"-0x0.0p+0"}'


def test_each_input_family_and_special_float_changes_digest() -> None:
    base = [("universe", ["IAM"], True), ("price", ["IAM", "2024-01-01"], 1.0)]
    original = source_watermark_v1(base)
    assert source_watermark_v1([*base, ("score", [1], math.nan)]) != original
    assert source_watermark_v1([*base, ("oos", [1], math.inf)]) != original
    assert source_watermark_v1([*base, ("methodology", [1], "v5")]) != original
