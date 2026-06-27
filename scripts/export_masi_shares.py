"""Scrape MASI share counts and export them to Excel.

Uses the same BDCSessionAdapter as the daily Bourse market-data refresh.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import text


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.quant_core.data import BDCSessionAdapter  # noqa: E402
from services.api.app.db import _ensure_session_factory  # noqa: E402
from services.api.app.masi_tickers import all_masi_tickers, get_masi_info, is_masi_ticker  # noqa: E402


def _positive_int(value: object) -> int | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not pd.notna(number) or number <= 0:
        return None
    return int(round(number))


def _parse_french_int(value: str) -> int | None:
    normalized = (
        str(value or "")
        .replace("\u00a0", "")
        .replace("Â ", "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )
    return _positive_int(normalized)


def _parse_session_date(html: str) -> dt.date | None:
    date_match = re.search(
        r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
        r"\s+(\d{1,2})\s+"
        r"(janvier|f[eÃ©]vrier|mars|avril|mai|juin|juillet|ao[uÃ»]t"
        r"|septembre|octobre|novembre|d[eÃ©]cembre)\s+(\d{4})",
        html,
        re.IGNORECASE,
    )
    if not date_match:
        return None
    month = BDCSessionAdapter._MONTH_MAP.get(date_match.group(2).lower())
    if month is None:
        return None
    return dt.date(int(date_match.group(3)), month, int(date_match.group(1)))


def _scrape_share_count_direct(symbol: str) -> tuple[int | None, dt.date | None]:
    """Share-only fallback for instruments where the session volume row is absent."""
    url = BDCSessionAdapter._BASE_URL.format(symbol=symbol)
    response = requests.get(
        url,
        timeout=30,
        verify=False,
        headers={"User-Agent": BDCSessionAdapter._USER_AGENT},
    )
    response.raise_for_status()
    html = response.text
    match = re.search(
        r"<th[^>]*>\s*Nombre de titres[^<]*</th>\s*<td[^>]*>.*?"
        r"<span\s+dir=[\"']ltr[\"']>([^<]+)</span>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None, _parse_session_date(html)
    return _parse_french_int(match.group(1)), _parse_session_date(html)


def _load_symbols_from_db() -> list[dict[str, str]]:
    try:
        session_factory = _ensure_session_factory()
        db = session_factory()
    except Exception:
        return all_masi_tickers()

    try:
        rows = db.execute(
            text(
                """
                SELECT symbol, display_name
                FROM stock_master
                WHERE is_active = true
                ORDER BY symbol
                """
            )
        ).mappings().all()
    except Exception:
        return all_masi_tickers()
    finally:
        db.close()

    out: list[dict[str, str]] = []
    for row in rows:
        symbol = str(row["symbol"] or "").strip().upper()
        if not symbol or not is_masi_ticker(symbol):
            continue
        masi_info = get_masi_info(symbol) or {}
        out.append(
            {
                "symbol": symbol,
                "display_name": str(row["display_name"] or masi_info.get("display_name") or ""),
            }
        )
    return out or all_masi_tickers()


def _scrape_share_count(adapter: BDCSessionAdapter, symbol: str) -> tuple[int | None, dt.date | None]:
    try:
        market_data = adapter.load([symbol], interval="1d")
        frame = market_data.bars.get(symbol)
        if frame is not None and not frame.empty and "NombreTitres" in frame.columns:
            values = frame["NombreTitres"].dropna()
            if not values.empty:
                shares = _positive_int(values.iloc[-1])
                as_of = values.index[-1].date() if hasattr(values.index[-1], "date") else None
                return shares, as_of
    except Exception:
        pass
    return _scrape_share_count_direct(symbol)


def _coerce_date_for_db(value: object) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _update_db(rows: list[dict[str, object]]) -> int:
    successful = [row for row in rows if row.get("shares_outstanding") is not None]
    if not successful:
        return 0
    try:
        session_factory = _ensure_session_factory()
        db = session_factory()
    except Exception:
        return 0

    updated = 0
    try:
        for row in successful:
            result = db.execute(
                text(
                    """
                    UPDATE stock_master
                    SET
                      shares_outstanding = :shares_outstanding,
                      shares_source = 'bourse_direct',
                      shares_as_of = :shares_as_of,
                      shares_updated_at = now(),
                      updated_at = now()
                    WHERE symbol = :symbol
                    """
                ),
                {
                    "symbol": row["symbol"],
                    "shares_outstanding": row["shares_outstanding"],
                    "shares_as_of": _coerce_date_for_db(row["shares_as_of"]),
                },
            )
            updated += int(result.rowcount or 0)
        db.commit()
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "masi_stock_shares.xlsx",
        help="Excel output path.",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated symbol list. Defaults to active MASI stocks in the app.",
    )
    parser.add_argument("--no-db-update", action="store_true")
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args()

    if args.symbols.strip():
        requested_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        symbols = [
            {"symbol": symbol, "display_name": (get_masi_info(symbol) or {}).get("display_name", "")}
            for symbol in requested_symbols
        ]
    else:
        symbols = _load_symbols_from_db()

    adapter = BDCSessionAdapter(timezone="UTC", use_cache=False)
    rows: list[dict[str, object]] = []
    failures: list[str] = []

    for index, item in enumerate(symbols, start=1):
        symbol = item["symbol"]
        try:
            shares, as_of = _scrape_share_count(adapter, symbol)
            if shares is None:
                failures.append(f"{symbol}: missing NombreTitres")
            rows.append(
                {
                    "symbol": symbol,
                    "display_name": item.get("display_name") or (get_masi_info(symbol) or {}).get("display_name"),
                    "shares_outstanding": shares,
                    "shares_as_of": as_of.isoformat() if as_of else None,
                }
            )
            print(f"[{index}/{len(symbols)}] {symbol}: {shares if shares is not None else 'missing'}")
        except Exception as exc:
            failures.append(f"{symbol}: {type(exc).__name__}: {exc}")
            rows.append(
                {
                    "symbol": symbol,
                    "display_name": item.get("display_name") or (get_masi_info(symbol) or {}).get("display_name"),
                    "shares_outstanding": None,
                    "shares_as_of": None,
                }
            )
            print(f"[{index}/{len(symbols)}] {symbol}: error")
        if args.delay > 0:
            time.sleep(args.delay)

    output = args.output
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame(rows)[["symbol", "display_name", "shares_outstanding"]]
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="shares")

    updated = 0 if args.no_db_update else _update_db(rows)
    print(f"Wrote {output}")
    print(f"Rows: {len(rows)}; scraped: {sum(row.get('shares_outstanding') is not None for row in rows)}; db_updated: {updated}")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"  {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
