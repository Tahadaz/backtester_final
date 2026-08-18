# Junior Trader Prep — Eurobonds, FX & Commodities

**Created:** 2026-07-19 · **Audience:** you, first job out of school, targeting a junior
trader seat covering eurobonds, FX and commodities (offshore/international desk).
**Companion plans:** `docs/offshore-lab/` (bond pricer + curve lab), `docs/ai/cross-asset-lab-slice1.md` (FX carry/TSM build).

## The thesis

Your repo already proves you can build research infrastructure. What a first-year
trader is actually judged on is different:

1. **Conventions fluency** — day counts, settlement, quotation conventions, accrued
   interest, forward points. Getting these wrong loses money mechanically.
2. **Mental pricing math at speed** — duration/DV01 approximations, forward points
   from rate differentials, roll P&L, cross rates. Tested live in interviews and
   used all day on a desk.
3. **Market narrative** — knowing what moved overnight, why, and what you'd expect
   next. Built only by daily repetition, not by reading.
4. **Conduct & market structure** — FX Global Code, how the eurobond primary/secondary
   market works, who the players are. Standard interview territory post-2013.
5. **One flagship research artifact** — a backtest you built and can defend line by
   line. This is where your existing skills become a differentiator instead of a
   distraction.

This folder is the program that covers all five.

## The files

| File | What it is | Cadence |
|---|---|---|
| `01-syllabus-12-weeks.md` | Knowledge track: 12-week study plan mapped to the ACI Dealing Certificate, ICMA FIC topics, and CME courses | ~1h/day |
| `02-daily-blotter.md` | The daily macro blotter method: instruments, sources, template, weekly review | 20–30 min every market morning |
| `03-mental-math-drills.md` | Drill sets with worked examples and target speeds | 10 min/day |
| `04-build-track.md` | The three builds (bond pricer → FX carry slice → curve lab), what each teaches, acceptance criteria | weeks 1–8 alongside study |
| `05-market-structure-and-conduct.md` | Eurobond market mechanics, FX market structure, commodities futures mechanics, FX Global Code | read weeks 1–6, revisit before interviews |
| `06-interview-prep.md` | First-job interview formats, question banks, how to present your platform, the Morocco angle | backup only — see `07` |
| `07-first-90-days.md` | **Primary since 2026-07-19** (verbal yes from internship manager, awaiting HR): onboarding plan, the social playbook for the floor, French reps, months 1–3 | daily reps + read now |
| `08-coding-readiness.md` | Hand-coding without AI (bank forbids it, weak machines): Iron Rule for builds, daily katas, retrieval drills vs own repo, desk-scale system design, Excel/VBA | daily kata + weekly reps |
| `09-daily-loop-mobile.md` | How the program runs day to day: the 07:00/21:00/23:00 cloud routines, the `TRADER PREP LOG` Google Doc, and the phrases to use in the Claude mobile app | read once, then daily |

## Weekly rhythm (the whole program on one line each)

- **Every market day:** blotter (20–30 min) + one drill set (10 min) + one
  coding kata (30 min, `08`).
- **Mon–Fri:** one syllabus session (~1h) from `01`.
- **2–3 sessions/week:** build track from `04` — **hand-coded, no AI** (`08`
  Iron Rule).
- **Weekly:** 2 retrieval drills, 1 system-design rep, 1 Excel/VBA hour (`08`).
- **Saturday:** weekly review — reread the week's blotter entries, grade your calls,
  one page of notes on what you got wrong and why.
- **Sunday:** off, or catch-up.

Total ≈ 10–12 h/week for 12 weeks. Front-load the builds (weeks 1–6) so the last
weeks are free for interview drilling.

## Sequencing (agreed 2026-07-19)

1. **Today:** start the blotter (`02`) and drills (`03`) — habits compound, start
   before you feel ready.
2. **Week 1–2:** un-shelve and build the Phase 1 bond calculator
   (`docs/ai/offshore-lab-phase1-fixed-income.md`) as a *learning build*.
3. **Week 2–6:** cross-asset lab Slice 1, **FX sleeve only** (G10 carry + TSM) —
   the flagship interview artifact.
4. **Week 6–8:** curve lab (offshore-lab Phase 3) — feeds the blotter and eurobond
   interview depth.
5. **Deferred until after the job hunt:** paper-trading desk, US equity port.

## Rules of engagement

- The blotter and drills are **non-negotiable daily**; everything else flexes.
- Builds are for *learning*, not product polish: notebook-grade output beats a
  frontend. If a build stops teaching you market content, stop building.
- Every study session ends with one question written down that you can't yet
  answer. Saturday's job is to close them.
- When in doubt, choose the activity closest to "what would the desk ask me at
  7:30am" — that is the test you are actually training for.
