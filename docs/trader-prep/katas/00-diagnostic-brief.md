# Coding Diagnostic — "These two files disagree"

**Timebox: 90 minutes total.** Stop where you stop — where you stop *is* the
measurement. Finishing Part 1 only is a perfectly informative result.

## The Iron Rule for this task

No AI. No copying from elsewhere in this repo. No Stack Overflow. You may use
**offline references only**: `help()`, `dir()`, `python -m pydoc pandas`, and
docstrings. This mirrors the bank machine exactly.

**Keep a look-up log** at the bottom of your file — every single thing you had
to check. That log is more valuable to me than your working code, because it is
the precise list of what to drill Thursday and Friday.

## The scenario

You are handed two files and a sentence: *"The positions blotter doesn't match
the risk system. Can you have a look before the close?"*

- `data/trades.csv` — the day's trade capture, exported by someone else's system
- `data/marks.csv` — end-of-day closing marks

Both are dirty in the ways real exports are dirty. Finding the dirt is part of
the task; nobody will list it for you on the desk.

## Part 1 — stdlib only (`solution_part1.py`)

**No pandas.** Use the `csv` module. This is the version that runs on a locked
bank machine with no packages.

Read `trades.csv` and print the **net position per symbol** — signed, buys
positive, sells negative.

Handle whatever you find. Think about what a "trade capture export" does wrong.

## Part 2 — pandas (`solution_part2.py`)

Same data, now with `marks.csv` joined in. Produce one table, one row per
symbol:

| symbol | net_position | avg_entry_price | latest_mark | unrealised_pnl |

- `avg_entry_price` — average price paid across that symbol's trades
- `latest_mark` — the most recent close available for that symbol
- `unrealised_pnl` — `net_position × (latest_mark − avg_entry_price)`

**Then answer the question that was actually asked:** print an explicit warning
listing any symbol that could not be fully reconciled, and say why. A number
handed over without its caveats is worse than no number.

## Part 3 — SQL (`solution_part3.py`)

Load both files into an in-memory `sqlite3` database and reproduce the Part 2
table as **a single SQL query**. Aggregation, a join, and a window function or
correlated subquery to pick the latest mark per symbol.

## Bonus (only if the first three are done)

Real P&L needs contract multipliers — 1,000 barrels per crude contract, 100 oz
per gold contract, 1 for a cash equity, and a bond quoted per 100 of face.
Apply them. See `../11-conventions-card.md`.

## When you're done

Say so and I'll run all three against the data and review them properly: what
works, what breaks on input you didn't anticipate, and what you'd be asked to
change in a real code review. Paste your look-up log with it.
