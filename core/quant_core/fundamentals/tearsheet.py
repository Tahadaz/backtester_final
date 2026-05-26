from __future__ import annotations

import html
from typing import Any


LABELS = {
    "fr": {
        "thesis": "These d'investissement",
        "valuation": "Valorisation",
        "quality": "Qualite",
        "catalysts": "Catalyseurs",
        "comparables": "Comparables",
        "integrity": "Integrite des donnees",
        "missing": "donnees indisponibles",
        "morning": "Note du matin",
        "ic": "Memo IC",
    },
    "en": {
        "thesis": "Investment Thesis",
        "valuation": "Valuation",
        "quality": "Quality",
        "catalysts": "Catalysts",
        "comparables": "Comparables",
        "integrity": "Data Integrity",
        "missing": "data unavailable",
        "morning": "Morning Note",
        "ic": "IC Memo",
    },
}


def _labels(lang: str) -> dict[str, str]:
    return LABELS.get((lang or "fr").lower(), LABELS["fr"])


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def format_money(value: Any, currency: str | None = None) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    suffix = f" {currency}" if currency else ""
    return f"{number:,.2f}{suffix}"


def format_pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number * 100:.1f}%"


def _section(section_id: str, title: str, body: str) -> str:
    return f'<section id="{_esc(section_id)}"><h2>{_esc(title)}</h2>{body}</section>'


def _missing(items: list[str], labels: dict[str, str]) -> str:
    if not items:
        return ""
    body = ", ".join(_esc(item) for item in items)
    return f'<div class="missing">{_esc(labels["missing"])}: {body}</div>'


def render_tearsheet(context: dict[str, Any], *, lang: str = "fr", artefact: str = "tearsheet") -> str:
    labels = _labels(lang)
    symbol = context.get("symbol") or "-"
    company_name = context.get("company_name") or symbol
    ensemble = context.get("ensemble") or {}
    thesis = context.get("thesis") or {}
    integrity = context.get("integrity") or {}
    catalysts = context.get("catalysts") or []
    comps_table = context.get("comps_table") or context.get("comparables") or {}
    scores = context.get("scores") or {}
    currency = ensemble.get("currency") or context.get("currency")
    missing_required = []
    if not context.get("symbol"):
        missing_required.append("symbol")
    if not ensemble:
        missing_required.append("ensemble")
    if artefact == "ic-memo" and not thesis:
        missing_required.append("thesis")

    valuation_body = (
        "<dl>"
        f"<dt>Fair value</dt><dd>{_esc(format_money(ensemble.get('fair_value_base'), currency))}</dd>"
        f"<dt>Upside</dt><dd>{_esc(format_pct(ensemble.get('upside_pct')))}</dd>"
        f"<dt>Confidence</dt><dd>{_esc(ensemble.get('confidence_score'))}</dd>"
        "</dl>"
    )
    thesis_body = (
        f"<p>{_esc(thesis.get('core_thesis') or labels['missing'])}</p>"
        if thesis
        else f"<p>- {labels['missing']}</p>"
    )
    quality_body = "<ul>" + "".join(
        f"<li>{_esc(key)}: {_esc(value)}</li>"
        for key, value in scores.items()
        if key in {"overall", "value", "quality", "growth", "risk", "cash_flow", "health"}
    ) + "</ul>"
    integrity_body = (
        f"<p>{_esc(integrity.get('overall_status'))} ({_esc(integrity.get('confidence_haircut'))})</p>"
        if integrity
        else f"<p>- {labels['missing']}</p>"
    )
    catalyst_body = (
        "<ul>"
        + "".join(
            f"<li>{_esc(item.get('event_date'))} - {_esc(item.get('title'))}</li>"
            for item in catalysts[:10]
            if isinstance(item, dict)
        )
        + "</ul>"
        if catalysts
        else f"<p>- {labels['missing']}</p>"
    )
    comps_body = (
        f"<p>{len(comps_table.get('peers') or comps_table.get('rows') or [])} peers</p>"
        if comps_table
        else f"<p>- {labels['missing']}</p>"
    )
    body = "\n".join(
        [
            _missing(missing_required, labels),
            _section("section-thesis", labels["thesis"], thesis_body),
            _section("section-valuation", labels["valuation"], valuation_body),
            _section("section-quality", labels["quality"], quality_body or f"<p>- {labels['missing']}</p>"),
            _section("section-integrity", labels["integrity"], integrity_body),
            _section("section-catalysts", labels["catalysts"], catalyst_body),
            _section("section-comparables", labels["comparables"], comps_body),
        ]
    )
    title = labels["ic"] if artefact == "ic-memo" else f"{symbol} - {company_name}"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{_esc(title)}</title>"
        "<style>body{font-family:Arial,sans-serif;margin:32px;color:#151515}"
        "section{border-top:1px solid #ddd;padding:14px 0}.missing{background:#fff3cd;padding:10px;margin-bottom:14px}"
        "h1{margin-bottom:4px}h2{font-size:16px}</style></head><body>"
        f"<h1>{_esc(symbol)} - {_esc(company_name)}</h1>{body}</body></html>"
    )


def render_morning_note(context: dict[str, Any], *, lang: str = "fr") -> str:
    labels = _labels(lang)
    date = context.get("date") or ""
    rows = context.get("rows") or []
    catalysts = context.get("catalysts") or []
    body_rows = "".join(
        f"<li>{_esc(row.get('symbol'))}: {_esc(format_pct(row.get('upside_pct')))} / {_esc(row.get('recommendation'))}</li>"
        for row in rows
        if isinstance(row, dict)
    )
    body_catalysts = "".join(
        f"<li>{_esc(item.get('symbol'))} - {_esc(item.get('title'))}</li>"
        for item in catalysts
        if isinstance(item, dict)
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{_esc(labels['morning'])}</title></head><body>"
        f"<h1>{_esc(labels['morning'])} - {_esc(date)}</h1>"
        f"{_section('section-symbols', 'Coverage', '<ul>' + body_rows + '</ul>')}"
        f"{_section('section-catalysts', labels['catalysts'], '<ul>' + body_catalysts + '</ul>')}"
        "</body></html>"
    )
