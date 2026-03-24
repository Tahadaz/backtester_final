from __future__ import annotations

import pandas as pd

from services.api.app.market_data_formats import (
    build_upload_format_reference,
    detect_upload_format,
    parse_datetime_series,
    parse_numeric_series,
    rename_columns_for_upload,
)


def test_investing_aliases_are_detected_and_renamed() -> None:
    frame = pd.DataFrame(
        columns=[" Date ", "Dernier", "Ouv.", "Plus Haut", "Plus Bas", "Vol.", "Change %"]
    )

    renamed, detected_format, matched_aliases = rename_columns_for_upload(frame)

    assert detected_format == "investing"
    assert list(renamed.columns[:6]) == ["Date", "Close", "Open", "High", "Low", "Volume"]
    assert matched_aliases["Close"]["input_column"] == "Dernier"
    assert matched_aliases["Open"]["input_column"] == "Ouv."


def test_bmce_new_aliases_are_case_and_space_tolerant() -> None:
    frame = pd.DataFrame(
        columns=[
            " seance ",
            "ouverture",
            " +haut du jour ",
            " +bas du jour ",
            "dernier cours",
            "nombre de titres echanges",
        ]
    )

    spec = detect_upload_format([str(column) for column in frame.columns])
    renamed, detected_format, _matched_aliases = rename_columns_for_upload(frame)

    assert spec is not None
    assert spec.format_id == "bmce_new"
    assert detected_format == "bmce_new"
    assert list(renamed.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]


def test_english_numeric_parsing_handles_thousands_and_suffixes() -> None:
    values = pd.Series(["1,745.00", "2,100.00", "980.00", "5.60K", "1.2M"])
    parsed = parse_numeric_series(values, number_style="english", allow_suffixes=True)

    assert parsed.tolist() == [1745.0, 2100.0, 980.0, 5600.0, 1_200_000.0]


def test_french_numeric_parsing_handles_spaces_and_decimal_comma() -> None:
    values = pd.Series(["1 052,00", "5 249", "982", "-", ""])
    parsed = parse_numeric_series(values, number_style="french", allow_suffixes=False)

    assert parsed.iloc[0] == 1052.0
    assert parsed.iloc[1] == 5249.0
    assert parsed.iloc[2] == 982.0
    assert pd.isna(parsed.iloc[3])
    assert pd.isna(parsed.iloc[4])


def test_datetime_parsing_respects_day_first() -> None:
    values = pd.Series(["03/04/2026", "18/03/2026"])
    parsed = parse_datetime_series(values, day_first=True)

    assert parsed.dt.strftime("%Y-%m-%d").tolist() == ["2026-04-03", "2026-03-18"]


def test_investing_format_uses_day_first_dates() -> None:
    spec = detect_upload_format(["Date", "Dernier", "Ouv.", "Plus Haut", "Plus Bas", "Vol."])

    assert spec is not None
    assert spec.format_id == "investing"
    assert spec.day_first is False


def test_investing_string_dates_are_parsed_month_first() -> None:
    values = pd.Series(["03/12/2026", "03/11/2026"])

    parsed = parse_datetime_series(values, day_first=False, format_id="investing")

    assert parsed.dt.strftime("%Y-%m-%d").tolist() == ["2026-03-12", "2026-03-11"]


def test_investing_date_parser_handles_mixed_strings_and_excel_datetimes() -> None:
    values = pd.Series([
        "03/18/2026",
        "03/17/2026",
        pd.Timestamp("2026-12-03"),
        pd.Timestamp("2026-11-03"),
    ])

    parsed = parse_datetime_series(values, day_first=True, format_id="investing")

    assert parsed.dt.strftime("%Y-%m-%d").tolist() == [
        "2026-03-18",
        "2026-03-17",
        "2026-03-12",
        "2026-03-11",
    ]


def test_investing_date_parser_drops_future_dates_after_resolution() -> None:
    values = pd.Series(["03/18/2026", pd.Timestamp("2026-12-25")])

    parsed = parse_datetime_series(values, day_first=False, format_id="investing")

    assert parsed.iloc[0].strftime("%Y-%m-%d") == "2026-03-18"
    assert pd.isna(parsed.iloc[1])


def test_upload_format_reference_includes_required_validation_note() -> None:
    reference = build_upload_format_reference()

    assert "Date" in reference["canonical_fields"]
    assert "Volume" in reference["validation"]["required_fields"]
    assert "Extra columns are ignored" in reference["validation"]["note"]
