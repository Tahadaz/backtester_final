# Final 4 Days — Day-One Readiness Sprint

**Written:** 2026-08-12 (Wednesday) · **Day one:** Monday 2026-08-17
**Seat:** offshore cross-asset desk — eurobonds, FX, commodities
**Desk stack:** Python + VBA (no AI allowed, weak locked-down machines)

## Why this file exists

`00`–`09` are a 12-week program written 2026-07-19. It was not executed: the
only blotter file is a blank template. Twelve weeks of material does not
compress into four days, so this file replaces the program for the sprint and
selects only what pays off in week one.

## The organising constraint

The stated fear is **"being asked something basic and not knowing the answer"** —
not failing a hard problem. That is the correct fear for a day-one junior and it
is the cheapest one to fix. Everything below is built around it.

Consequence: the flagship deliverable of these four days is not a build. It is
`11-basics-battery.md` — the question bank a senior could plausibly ask in the
first two weeks, with tight answers, drilled to reflex and **printed on paper**,
because there will be no AI and no Stack Overflow at the desk.

## What this sprint is not

- Not "learn to code". Four days cannot do it. The coding target is a *floor*
  plus the right **task shape** (below).
- Not the 12-week syllabus, the build track, or the interview prep (`06`).
- Not French reps — the user rates French as adequate; deprioritised.

## Coding: the realistic target

Nobody hands a day-one junior an algorithm. They hand you:

- "reconcile these two files, they don't match"
- "clean this export and give me a pivot"
- "why doesn't this column sum to the total"
- "pull these levels into a sheet every morning"

That is the shape to train: **messy input → clean output → a number someone
trusts**. In Python that is pandas read/clean/join/group/pivot plus `sqlite3`.
In VBA that is ranges, loops, a function, and recording-then-editing a macro.
Both are on the desk stack; VBA gets real time because it was named explicitly.

The Iron Rule from `08` holds all sprint: **you write the code, I review after.**
No generated code, no debugging-for-you mid-task.

## The four days

### Day 1 — Wed 12 Aug: measure, then plug
1. **Diagnostic battery** — market conventions across all three assets, mental
   math, then a keyboard coding diagnostic. Graded here. Output = the real hole
   list, replacing guesswork.
2. **Conventions bootcamp part 1** — FX and commodities quoting: which way the
   pair goes, base/quote, pips, T+2, forward points and their sign, futures
   contract specs, contango/backwardation, roll.
3. **Blotter #1**, live data, real levels, written to `blotter/2026-08.md`.

### Day 2 — Thu 13 Aug: rates and eurobonds
1. Price–yield, clean vs dirty, accrued, day-count conventions, duration/DV01,
   spread language (G-spread, Z-spread, ASW), primary vs secondary, settlement.
2. **Mental math to speed** — bp-to-money, DV01 approximations, cross rates,
   forward points, timed.
3. **Python kata 1**, hand-written, graded by me.
4. **Blotter #2**.

### Day 3 — Fri 14 Aug: the desk toolchain
1. **Excel/VBA block** — XLOOKUP/INDEX-MATCH, absolute refs, pivots, fast chart;
   then record a macro, open the editor, rewrite it properly.
2. **Python desk-task block** — the messy-input→trusted-number shape, end to end.
3. **Blotter #3**.

### Day 4 — Sat 15 Aug: rehearsal and the paper kit
1. Full dress rehearsal: morning brief delivered aloud, timed math under
   pressure, one realistic desk task start to finish.
2. Assemble and print the **day-one kit**:
   - one-page conventions card
   - `11-basics-battery.md` with answers
   - day-one protocol (below)
   - a blank question log for week one
3. Portable context primer for the Claude mobile app (this repo will not be
   with you at the desk).

### Sunday 16 Aug — light
Reread the kit, blotter #4, stop early.

## Day-one protocol (the part that actually prevents humiliation)

Knowledge is not what saves a junior in week one; posture is.

- **Never bluff a number.** "Je vérifie et je reviens vers toi" — then actually
  come back, same day, unprompted.
- **Repeat every instruction back** before acting on it. Every time. Seniors
  read this as competence, not weakness.
- **Write everything down.** One notebook, timestamped. The question you were
  too embarrassed to ask goes in it and gets asked at a calm moment, batched.
- **Ask once, properly.** "I looked at X, I think it's Y, am I reading this
  right?" beats both silence and a naked "how does this work?".
- **Say the number and the unit.** Ambiguity about bp vs %, base vs quote, lots
  vs notional is how juniors lose money mechanically.

## Progress

- [ ] Day 1 diagnostic
- [ ] Conventions bootcamp part 1
- [ ] Blotter #1
- [ ] Day 2 rates block
- [ ] Python kata 1
- [ ] Day 3 Excel/VBA block
- [ ] Day 3 Python desk task
- [ ] Day 4 rehearsal
- [ ] Paper kit printed
