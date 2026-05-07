from __future__ import annotations

from datetime import date

from services.api.app.market_holidays import get_holiday_info


def test_confirms_user_provided_bridge_day() -> None:
    holiday = get_holiday_info(date(2024, 4, 12))

    assert holiday is not None
    assert holiday["certainty"] == "confirmed"
    assert holiday["name"] == "Pont"


def test_confirms_hijri_new_year_2023() -> None:
    holiday = get_holiday_info(date(2023, 7, 19))

    assert holiday is not None
    assert holiday["certainty"] == "confirmed"
    assert holiday["name"] == "Islamic New Year"


def test_amazigh_new_year_exists_from_2025_onward() -> None:
    for year in range(2025, 2027):
        holiday = get_holiday_info(date(year, 1, 14))
        assert holiday is not None
        assert holiday["certainty"] == "confirmed"
        assert holiday["name"] == "Amazigh New Year"


def test_amazigh_new_year_absent_before_2025() -> None:
    for year in range(2020, 2025):
        assert get_holiday_info(date(year, 1, 14)) is None


def test_user_corrected_closure_dates_are_present() -> None:
    expected = {
        date(2025, 6, 9): "Eid al-Adha",
        date(2023, 4, 24): "Eid al-Fitr",
        date(2023, 9, 28): {"Aïd Al-Mawlid Annabawi", "Mawlid al-Nabi"},
        date(2023, 9, 29): {"Aïd Al-Mawlid Annabawi", "Mawlid al-Nabi"},
        date(2022, 5, 2): "Eid al-Fitr",
        date(2022, 5, 3): "Eid al-Fitr",
        date(2021, 7, 21): "Eid al-Adha",
        date(2021, 7, 22): "Eid al-Adha",
        date(2021, 10, 19): {"Aïd Al-Mawlid Annabawi", "Mawlid al-Nabi"},
        date(2021, 10, 20): {"Aïd Al-Mawlid Annabawi", "Mawlid al-Nabi"},
    }

    for day, names in expected.items():
        holiday = get_holiday_info(day)
        assert holiday is not None
        assert holiday["certainty"] == "confirmed"
        if isinstance(names, set):
            assert holiday["name"] in names
        else:
            assert holiday["name"] == names


def test_symbol_specific_holiday_applies_only_to_iam() -> None:
    holiday = get_holiday_info(date(2025, 3, 27), symbol="IAM")

    assert holiday is not None
    assert holiday["certainty"] == "confirmed"
    assert holiday["name"] == "Suspension de la cotation (changement de direction)"
    assert holiday["symbols"] == ["IAM"]
    assert get_holiday_info(date(2025, 3, 27), symbol="BCP") is None
    assert get_holiday_info(date(2025, 3, 27)) is None


def test_boa_dividend_suspensions_apply_only_to_boa() -> None:
    expected_dates = [
        date(2023, 7, 27),
        date(2023, 8, 25),
        date(2024, 6, 24),
        date(2024, 9, 6),
    ]

    for day in expected_dates:
        holiday = get_holiday_info(day, symbol="BOA")

        assert holiday is not None
        assert holiday["certainty"] == "confirmed"
        assert holiday["name"] == "Suspension de la cotation (detachement dividendes)"
        assert holiday["symbols"] == ["BOA"]
        assert get_holiday_info(day, symbol="BCP") is None
        assert get_holiday_info(day) is None
