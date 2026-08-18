# Coding Readiness — Hand-Coding Without AI

**The problem, stated honestly:** this app was built AI-assisted. The bank
forbids AI, the machines are weak and locked down, and there will be no
autocomplete, no Stack Overflow reflex, possibly no pip. The gap to close is
not "learn to code" — it is **removing the assistance layer** from skills you
already exercise daily. That is done by deliberate withdrawal + reps, and it
fits in the weeks available. "Mastery" does not; the target below does.

## Target level (what "ready" means)

By start date you can, on a weak Windows machine with no internet help:
1. Write a clean 200–400-line Python module (functions, a class or two, tests)
   from a blank file, first try mostly working, debugging via traceback + print
   + pdb only.
2. Do any everyday pandas/numpy transformation without looking anything up
   (load, clean, join, resample, group, pivot, rolling).
3. Write intermediate SQL cold (joins, aggregation, window functions).
4. Explain and justify every architectural choice in this app as if you made
   it alone — because by then, you effectively will have.
5. Survive in Excel/VBA at desk level (lookups, pivots, record-and-edit a macro).

## The Iron Rule (starts today)

**All build-track code (`04`) is now written by hand, no AI, no copy-paste from
old repo code.** Editor + offline docs only. AI is allowed in exactly one role:
**reviewer after the fact** — at the end of a build week you may ask for a
code review of what you wrote, read the critique, apply fixes yourself. Never
generation, never debugging-for-you, never "how do I…" mid-task. (This mirrors
the bank exactly: there, the senior reviews you; the skill of *receiving*
review transfers, the habit of *asking mid-keystroke* does not.)

Second rule: **work like the bank machine.** For build sessions: no
autocomplete-heavy IDE assistance (turn Copilot-type features off), keep a
plain editor + terminal workflow, and get comfortable with offline references:
`help()`, `dir()`, `python -m pydoc`, and an offline docs app (devdocs.io
offline mode / Zeal) for Python, pandas, SQL.

## Rep 1 — Daily kata (30 min, replaces nothing, adds to the dailies)

One small exercise from a blank file, timed, no references until finished.
Rotate three flavors:

- **Core Python (2×/wk):** dict/list gymnastics, parsing a messy CSV with
  stdlib only, a small class with `__repr__`/equality, a generator, datetime
  arithmetic with day-count flavor. Sources: Advent of Code back-catalog,
  LeetCode easy/medium (don't grind hard problems — banks don't ask them for
  desk roles; fluency beats puzzles).
- **Pandas/numpy (2×/wk), always market-flavored:** compute rolling 20d vol
  from OHLCV; resample daily→monthly returns; align two series on different
  calendars and forward-fill with a staleness cap; group trades by symbol and
  compute VWAP; build a 2s10s series from two yield columns. (You have real
  data in the app's stores — export a few CSVs now as kata fixtures.)
- **SQL (1×/wk):** against a local SQLite with a few exported tables:
  positions × prices join for P&L, window function for rolling NAV, dedup on
  latest-timestamp-per-key. Know `sqlite3` from Python stdlib cold — it may be
  the only database you're allowed.

Log every kata: minutes, what you had to look up. The look-up log is your
weakness list; next week's katas come from it.

## Rep 2 — Retrieval drills against your own repo (2×/wk, 45 min)

The highest-value drill for your specific situation. Pick a core function
"you" built with AI; read it for 10 minutes; close it; **re-implement it from
memory in a scratch file; then diff.** The diff shows exactly what you never
actually owned. Priority queue (most desk-relevant first):

1. `risk.py` — block bootstrap, Monte-Carlo equity paths, Kelly.
2. `backtest_mc.py` core loop — the lagged-execution + cost accounting.
3. `wfo/engine.py` — the window loop.
4. The robustness stats — deflated Sharpe, PSR (also re-derivable from `01`
   week-12 reading).
5. Your new hand-written fixed-income modules (as revision, week 2+).

When the diff is embarrassing, that's the drill working. Repeat that module
next session.

## Rep 3 — System design, desk-scale (1×/wk, 45 min, spoken aloud)

Bank system design is not FAANG design. Nobody will ask you to shard a
distributed cache; they will need: a nightly batch that never silently fails, a
data pipeline someone else can maintain, an idempotent job that can be re-run
after a crash. Two exercises, alternating weeks:

- **Defend your own app.** Pick one subsystem (RQ job queue + status rows;
  Parquet-in-MinIO store with denormalized freshness; Alembic migration
  discipline; the run/artifact reproducibility spine; the scheduler dispatch).
  Whiteboard it from memory, then answer aloud: why this over the obvious
  alternative? what breaks first under load? how would I build it with *only*
  stdlib + SQLite + cron (the bank-machine version)? That last question is the
  important one — translating your architecture down to poor tooling is
  precisely the job.
- **Design fresh, out loud, 30 min, paper only:** a daily P&L recon between
  two systems that disagree; a market-data cache with staleness rules; a limit
  monitor that alerts on breach; an end-of-day report generator with an audit
  trail; a trade blotter with corrections (never deletions). Pattern
  vocabulary to be fluent in: idempotency, checkpoint/restart, config-vs-code,
  append-only logs, reconciliation, PIT correctness (you know this one better
  than most seniors — say it in French too: "données point-in-time").

## Rep 4 — Excel/VBA (1×/wk, 1h — do not skip this one)

Whatever the tech stack promises, the desk runs on Excel, and weak machines
guarantee it. Minimum: XLOOKUP / INDEX-MATCH cold; pivot tables; conditional
formatting for a monitor sheet; data → chart in under a minute; then record a
macro, open the VBA editor, and clean it up (loops, ranges, a function). Final
session: rebuild one blotter-board day entirely in Excel with formulas — that
artifact is plausibly your actual day-one job.

## Weekly rhythm (revised totals)

- Daily: blotter (20–30m) + math drill (10m) + **kata (30m)**.
- 2–3×/wk: build sessions (now hand-coded — same slots as before).
- 2×/wk: retrieval drill (45m). 1×/wk: system design (45m). 1×/wk: Excel (1h).
- Saturday review now also covers: look-up log, worst diff of the week, one
  design question you couldn't answer.

Total ≈ 15–16 h/wk. If that breaks, cut in this order: system design to
biweekly, one pandas kata, one retrieval drill. Never cut: blotter, the Iron
Rule, Excel.

## What NOT to spend these weeks on

- LeetCode hard / competitive programming — wrong game entirely.
- New languages, frameworks, k8s, microservices — the bank machine can't run
  them and the desk doesn't want them.
- Polishing this app's frontend — no transfer.
- Reading architecture books cover-to-cover — you have a working architecture
  to interrogate; Rep 3 on your own system beats a book in the time available.
  (One exception if time allows: skim *The Pragmatic Programmer* — it's about
  exactly the unassisted-craftsman habits this file trains.)
