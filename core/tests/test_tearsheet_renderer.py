from __future__ import annotations

from html.parser import HTMLParser

from quant_core.fundamentals.tearsheet import render_tearsheet


def test_renders_with_full_context() -> None:
    html = render_tearsheet(
        {
            "symbol": "AAA",
            "company_name": "Alpha",
            "scores": {"overall": 72, "quality": 80},
            "ensemble": {"fair_value_base": 120, "upside_pct": 0.2, "confidence_score": 0.7, "currency": "MAD"},
            "thesis": {"core_thesis": "Strong quality compounder with clear valuation support."},
            "integrity": {"overall_status": "pass", "confidence_haircut": 0.0},
            "catalysts": [{"event_date": "2026-06-01", "title": "Earnings"}],
            "comps_table": {"peers": [{"symbol": "BBB"}]},
        }
    )
    assert 'id="section-valuation"' in html
    assert 'id="section-thesis"' in html
    HTMLParser().feed(html)


def test_renders_with_missing_optional_sections() -> None:
    html = render_tearsheet({"symbol": "AAA", "ensemble": {"fair_value_base": 1}})
    assert "donnees indisponibles" in html


def test_language_toggle_changes_labels() -> None:
    assert "Investment Thesis" in render_tearsheet({"symbol": "AAA", "ensemble": {}}, lang="en")
    assert "These d&#x27;investissement" in render_tearsheet({"symbol": "AAA", "ensemble": {}}, lang="fr")
