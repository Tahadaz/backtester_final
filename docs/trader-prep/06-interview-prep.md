# Interview Prep — First Job Out of School

Start from week 6; drill hard in the final two weeks. A junior trader interview
tests four things: do you follow markets, can you think in prices under
pressure, do you understand risk, and would the desk enjoy sitting next to you
at 7am. Your builds are a bonus round — deployed correctly.

## Round anatomy (typical bank S&T / trading-desk process)

1. **Fit/HR:** why trading, why this desk, why you. Have a tight 90-second
   story: engineering/quant background → built a research platform → discovered
   the questions you care about are desk questions (pricing, carry, risk) →
   this seat. Practice it aloud until it doesn't sound rehearsed.
2. **Markets round:** "talk to me about markets" — your blotter IS the answer.
   Narrate the current macro picture in 2 minutes: Fed/ECB stance, where the
   curves are, dollar trend, oil/gold, one thing you're watching this week.
   Then be ready for "why?" three levels deep on any of it.
3. **Technical/mental-math round:** live versions of `03` drills + concept
   questions from `01`. Speed matters less than composure: state the
   approximation, compute, sanity-check the sign out loud.
4. **Trade idea / game round:** pitch a trade (below); market-making games
   ("make me a market on X"); sizing/odds games. They watch process: bid-offer
   discipline, adjusting on new information, knowing your out.

## Question bank (drill aloud; write model answers for the starred ones)

**Markets & macro**
- ★ Walk me through what's driving rates/FX/oil right now. What's your highest-
  conviction view and what kills it?
- The Fed surprises with a 50bp cut tomorrow — what happens to 2s10s, EUR/USD,
  gold, and an EM eurobond spread, in order of confidence?
- ★ Why is the curve inverted/steep right now and what would re-steepen/flatten it?

**Bonds/eurobonds**
- ★ Define duration to a non-finance friend, then to a trader (DV01). Why does
  convexity always help the long?
- Clean vs dirty price; why do we quote clean?
- G-spread vs Z-spread — when do they disagree?
- ★ Morocco wants to issue a 10y USD eurobond — walk me through the process and
  how it gets priced. (Your `05` §1 + Morocco case study; this is your home-turf
  question — own it.)
- You're long a 10y EM sovereign and UST sells off 30bp — what happened to your
  position and what were you actually paid to take?

**FX**
- ★ Spot 1.09, USD rates above EUR — is the EUR/USD forward above or below
  spot, and why (CIP, no "supply and demand" hand-waving)?
- What is carry, why does it work, why does it crash? (Your Build 2 gives you a
  personal, data-backed answer nobody else in the pipeline has.)
- What is last look? Pre-hedging — when is it acceptable? (Code fluency, `05` §4.)

**Commodities**
- ★ WTI curve backwardated, you're long the front and roll monthly — P&L
  decomposition? What's the theory-of-storage story?
- Tell me the April 2020 negative-WTI story and what it teaches about delivery
  mechanics.

**Risk & judgment**
- ★ When would you cut a winning position? A losing one? (Answer with process:
  pre-set invalidation, sizing rules — echo your own kill-switch design.)
- You're down 2% on the month with no obvious bug in the view — what do you do?
- Make me a market on [population of Morocco / cups of coffee sold in Casablanca
  daily]. (Process: anchor, width for uncertainty, tighten as they trade you.)

**Behavioral (first-job specific)**
- ★ A time you were wrong and what you changed. (Use a real blotter miss or the
  look-ahead bug you quantified in Build 2 — concrete beats generic.)
- Why trading and not quant research / software, given your background? (Answer
  honestly: you built the research stack and found you care most about the
  decision under uncertainty, not the pipeline. Then prove it with the blotter.)

## Deploying your builds (the differentiator, used correctly)

Rules: **market conclusions first, engineering second.** Lead with "I ran G10
carry and momentum on genuine excess returns — carry's Sharpe collapses once
you account for its crash episodes and costs; here's what survived," not with
FastAPI and Postgres. Have the five-page Build 2 writeup printable; mention the
platform only as the thing that made the study honest (PIT discipline, deflated
Sharpe, no look-ahead — say those three phrases, they signal maturity). Be
ready for hostile follow-ups: "why should I believe any backtest?" — answer
with your own multiple-testing and cost-sensitivity results.

The Morocco angle is the same play: BAM curve, basket mechanics, CIP on
USD/MAD, the sovereign's eurobond curve — local knowledge international
candidates won't have. One crisp paragraph on each, ready to go.

## Questions to ask them (have five; these signal desk-awareness)

- How is the book split between franchise/client flow and risk positions?
- What does a good first year look like in this seat — what do juniors own by
  month 6?
- How does the desk source and manage its eurobond hedges (govvies vs futures vs
  swaps)?
- What's the desk's biggest structural constraint right now — balance sheet,
  liquidity, data?
- Who on the desk should I learn pricing conventions from, and how do you
  onboard someone into the risk system?

## Final-week checklist

- [ ] 2-minute markets narrative refreshed the morning of (from the blotter).
- [ ] 20-minute mixed drill session (`03`) same morning.
- [ ] Model answers to all ★ questions rehearsed aloud once.
- [ ] Build 2 writeup printed / linkable; 60-second version rehearsed.
- [ ] Morocco paragraph set (BAM, basket, eurobond curve) fresh.
- [ ] Five questions for them chosen for the specific desk.
- [ ] Sleep. Composure beats one more fact.
