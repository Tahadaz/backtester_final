"""Part 1 reference — net position per symbol, standard library only.

This is the version that runs on a locked-down bank machine: no pandas, no pip,
just what ships with Python. Comments explain WHY, not what -- the what is
readable from the code.

The shape of every desk data task is the same three phases:

    1. PARSE   -- turn untrusted text into typed values, rejecting what you
                  cannot understand instead of guessing.
    2. AGGREGATE -- do the arithmetic, in the correct units.
    3. REPORT  -- print the answer AND everything that qualifies it.

Phase 3 is the one juniors skip, and it is the one that gets you trusted.
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import csv

# Resolve paths relative to THIS FILE, never the current working directory.
# Your first run crashed on FileNotFoundError precisely because "trades.csv"
# was interpreted relative to wherever you happened to launch python from.
DATA = Path(__file__).resolve().parent / "data"

# An explicit whitelist, not an if/else. Anything not in here is unknown input,
# and unknown input must raise -- see parse_side.
SIDE_SIGN = {"BUY": 1, "B": 1, "BOT": 1, "SELL": -1, "S": -1, "SLD": -1}

# Real exports carry mixed date formats because different upstream systems
# wrote them. Try each; refuse to guess beyond the list.
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y")


# --------------------------------------------------------------------------
# 1. PARSE
# --------------------------------------------------------------------------

def parse_number(raw):
    """'1,000' -> 1000.0   '2 415.50' -> 2415.5   ' 98.40 ' -> 98.4

    Thousands separators arrive as commas, ordinary spaces, and non-breaking
    spaces (\\xa0) -- the last one comes from anything that passed through
    Excel or a web page and is invisible in a text editor, which makes it a
    classic afternoon-losing bug. Strip all three.
    """
    cleaned = raw.strip().replace(",", "").replace(" ", "").replace("\xa0", "")
    if not cleaned:
        raise ValueError("empty number")
    return float(cleaned)          # float() raises on junk. Let it.


def parse_side(raw):
    """' BUY ' -> +1, 'sell' -> -1, anything unrecognised -> ValueError.

    THE IMPORTANT LINE IN THIS FILE. The tempting version is

        return 1 if raw == "buy" else -1

    which silently turns every value you did not anticipate into a SELL. A
    trailing space, a new side code, a typo -- silently short, discovered days
    later on the risk report. Unknown input raises. Always.
    """
    key = raw.strip().upper()
    if key not in SIDE_SIGN:
        raise ValueError(f"unknown side {raw!r}")
    return SIDE_SIGN[key]


def parse_date(raw):
    """Accept any format in DATE_FORMATS; refuse the rest.

    Note 03/08/2026 is ambiguous -- 3 August or 8 March? We assume day-first
    because the desk is European. That is an ASSUMPTION, so it is written down
    here rather than buried. On a real desk you would ask, once, and then know.
    """
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date {raw!r}")


def normalise_symbol(raw):
    """'brent_sep26' and 'BRENT_SEP26' are the same instrument.

    Without this, one position splits into two rows and the join to marks
    silently misses. Pick one canonical form -- upper -- and apply it at the
    boundary, so that everything downstream can assume it.
    """
    return raw.strip().upper()


def load_trades(path):
    """Return (trades, problems).

    Two return values because a loader that only returns clean data throws
    away the answer to "why don't these two systems match?". The problems list
    IS the deliverable for that question.
    """
    trades = {}                      # trade_id -> parsed record
    problems = []

    with open(path, newline="", encoding="utf-8") as fh:
        # newline="" is required by the csv module on Windows; without it,
        # quoted fields containing newlines get mangled.
        reader = csv.DictReader(fh)

        # start=2 because line 1 is the header, so lineno matches what you
        # see in a text editor. Being able to say "line 7 is bad" instead of
        # "a line is bad" is the difference between a useful and useless report.
        for lineno, row in enumerate(reader, start=2):
            try:
                record = {
                    "trade_date": parse_date(row["trade_date"]),
                    "symbol": normalise_symbol(row["symbol"]),
                    "signed_qty": parse_side(row["side"]) * parse_number(row["quantity"]),
                    "price": parse_number(row["price"]),
                }
            except (ValueError, KeyError, TypeError) as exc:
                # Catch the row, record it, keep going. One bad row must not
                # kill the report -- but it must never vanish either.
                problems.append(f"line {lineno}: rejected ({exc})")
                continue

            trade_id = row["trade_id"].strip()

            if trade_id in trades:
                # A repeated trade_id means the export ran twice OR somebody
                # re-used an id. You cannot tell which, so you do NOT silently
                # pick one. You keep the first, and you flag it loudly.
                problems.append(
                    f"line {lineno}: duplicate trade_id {trade_id} -- "
                    f"ignored, verify with ops"
                )
                continue

            trades[trade_id] = record

    return trades, problems


# --------------------------------------------------------------------------
# 2. AGGREGATE
# --------------------------------------------------------------------------

def net_positions(trades):
    """symbol -> net signed quantity.

    UNITS: signed_qty is a COUNT (barrels, ounces, shares, face value). It is
    NOT quantity x price -- that would be a cash notional, and a position is
    not a cash amount. Say the unit out loud when you name the variable and
    this class of bug disappears.
    """
    positions = defaultdict(float)
    for record in trades.values():
        positions[record["symbol"]] += record["signed_qty"]
    return dict(positions)


# --------------------------------------------------------------------------
# 3. REPORT
# --------------------------------------------------------------------------

def main():
    trades, problems = load_trades(DATA / "trades.csv")

    print(f"{'symbol':<16}{'net position':>16}")
    print("-" * 32)
    for symbol, qty in sorted(net_positions(trades).items()):
        # +,.0f -> always show the sign, group thousands. A position of -400
        # and one of 400 must never be confusable at a glance.
        print(f"{symbol:<16}{qty:>+16,.0f}")

    print(f"\n{len(trades)} trades accepted")

    # The caveats are not an appendix. They are the answer to the question
    # that was actually asked.
    if problems:
        print(f"\nDATA QUALITY -- {len(problems)} issue(s):")
        for problem in problems:
            print(f"  ! {problem}")


if __name__ == "__main__":
    # This guard means the file can be imported (by a test, or by tomorrow's
    # bigger script) without executing anything. Free habit, always worth it.
    main()
