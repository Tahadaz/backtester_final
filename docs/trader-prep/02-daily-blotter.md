# Daily Macro Blotter — Method

The single highest-value habit in this program. 20–30 minutes every market
morning. Its equity ancestor is `docs/DAILY_BLOTTER_METHOD.md`; this is the
macro version. Keep entries in one running file or notebook —
`docs/trader-prep/blotter/YYYY-MM.md`, one dated section per day.

## What you track (the board)

Same instruments every day, so changes become visible. All free sources.

| Group | Instruments | Source |
|---|---|---|
| Rates US | 2y, 10y, 30y UST yields; 2s10s | FRED `DGS2/DGS10/DGS30`, CNBC/Investing for intraday |
| Rates EUR | 10y Bund, 10y BTP–Bund spread | Investing.com, ECB |
| Real yield | US 10y TIPS | FRED `DFII10` |
| FX majors | EUR/USD, USD/JPY, GBP/USD, DXY | any live source |
| FX carry pairs | AUD/JPY (risk proxy), USD/MXN or USD/TRY (EM carry) | any |
| Morocco | USD/MAD, EUR/MAD, BAM reference curve, Morocco USD eurobond yield/G-spread | BAM, bourse/Boerse-Frankfurt marks |
| Energy | Brent front, WTI front, Brent–WTI, front–second spread (curve shape) | CME/ICE delayed, Investing |
| Metals | Gold, copper | any |
| Risk tone | S&P 500 future, VIX | any |

First session: build this as a one-page template so filling it is mechanical.
(Optionally later, wire it into the app via the macro-ingestion pipeline — but
do NOT let building the dashboard replace doing the blotter by hand for the
first month. Hand-filling is the point: it forces you to look at every number.)

## The three questions (the actual work)

After filling the numbers, write **3–6 lines** answering:

1. **What moved?** The 1–2 biggest standardized moves on the board (in bp, %,
   or vs recent range — not just "up").
2. **Why?** Attach the move to a cause: data release, central bank speaker,
   auction, OPEC, geopolitics, positioning squeeze. If you can't find a cause,
   write "no obvious driver" — that is itself information (flow-driven).
3. **What next?** One falsifiable expectation with a horizon. "If tomorrow's US
   CPI prints above 3.4% y/y, 2s10s bear-flattens further; below 3.2%, front
   end rallies hard." Bad: "market may be volatile."

## The event calendar (fill Sunday for the week)

FOMC/ECB/BoE/BoJ dates and speakers · US CPI, NFP, PCE · euro-area flash CPI,
PMIs · UST auction schedule (3y/10y/30y refunding weeks) · EIA crude inventories
(Wed) · OPEC+ meetings · BAM policy dates. Before each event write one line:
consensus, your lean, what would surprise. After: what printed, how the board
reacted vs your expectation.

## Weekly review (Saturday, ~30 min)

- Reread the week's entries. Grade every "what next" call: right / wrong /
  unresolved, and — more important — *right for the right reason?*
- One page: the week's dominant narrative in your own words, your worst call
  and its lesson, one open question to chase in next week's study sessions.
- Monthly: reread the four weekly pages. This is the compounding step — after
  8–12 weeks you can narrate the whole quarter, which is exactly the "talk to
  me about markets" interview question.

## Standards

- **Never skip the "why" hunt** — the habit of attaching moves to causes is the
  skill; the numbers are just the prompt.
- Standardize moves: yields in bp, FX in % or pips, always vs the prior close
  you recorded (your own board is the source of truth).
- Keep opinions falsifiable and dated. You are building a track record of
  judgment, and the honest misses teach more than the hits.
- If short on time: numbers + question 1 only. An incomplete entry beats a
  skipped day; the streak is what compounds.
