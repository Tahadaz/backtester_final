# Knowledge Track — 12-Week Syllabus

Spine: the **ACI Dealing Certificate (New Version)** syllabus — it is written for
dealers with 0–24 months experience and covers exactly your seat (FX, rates,
FICC derivatives). Supplement: **ICMA FIC** topic list for the eurobond leg,
**CME Institute** free courses for commodities.

**Primary references** (get these once, use throughout):
- ACI syllabus PDF: acifma.com → ACI Dealing Certificate New Version (free download).
- Bob Steiner, *Mastering Financial Calculations* (3rd ed.) — the standard ACI
  companion; every drill in `03` comes from this material.
- Fabozzi, *Handbook of Fixed Income Securities* — reference, not cover-to-cover.
- FX Global Code (Dec 2024, 55 principles): globalfxc.org — free PDF.
- CME Institute: cmegroup.com/education/courses — free, 60+ courses.
- Ilmanen, *Expected Returns* — weeks 9+ only, ties carry/momentum together.

Each week = 5 sessions × ~1h. Every session ends with: (a) 3 self-test questions
answered from memory, (b) one open question written down for Saturday.

---

## Block 1 — Money markets & FX cash (weeks 1–4)

**Week 1 — Rates arithmetic and money markets.**
Day-count conventions (ACT/360, ACT/365, 30E/360) and why a "5%" deposit isn't
one number; simple vs compound vs continuous; discount vs yield quotation
(T-bills); money-market instruments (deposits, CDs, CP, repo); SOFR/€STR and
what replaced LIBOR; central bank corridors (Fed funds/IORB, ECB depo/refi).
*Steiner ch. 1–3. Self-test: convert a 5.00% ACT/360 rate to ACT/365; price a
90-day bill at a 5.2% discount rate.*

**Week 2 — FX spot.**
Quotation conventions (base/quote, direct/indirect, pips), bid/offer and who
pays the spread, cross-rate arithmetic through USD, position keeping (long EUR
vs short USD is one position), market structure preview (dealers, ECNs, prime
brokerage — details in `05`). Value dates and T+2 settlement, settlement risk
(Herstatt) and CLS.
*Steiner FX chapters. Self-test: given EUR/USD and USD/JPY bid/offer, make a
two-way EUR/JPY price.*

**Week 3 — FX forwards and swaps.**
Covered interest parity: F = S·(1+r_quote·τ)/(1+r_base·τ); forward points sign
from the rate differential; FX swaps as the funding instrument (spot leg +
forward leg), rolling positions with tom/next; NDFs for restricted currencies
(directly relevant to MAD); forward-forward and what a swap dealer actually
risks (rate differential, not spot).
*Self-test: EUR/USD 1.0900, 3m USD 5%, 3m EUR 4% — compute the 3m points and
say whether EUR is at a premium or discount, before checking.*

**Week 4 — Consolidation + FX Global Code, first pass.**
Redo weeks 1–3 self-tests cold. Read FX Global Code Principles 1–20 (ethics,
governance, information sharing) and 17 (last look) + the pre-hedging guidance.
Write half a page in your own words: what is last look, why is it controversial,
what did the Dec-2024 update change (settlement risk, client data transparency).

## Block 2 — Bonds & eurobonds (weeks 5–8)

**Week 5 — Bond pricing mechanics.** *(Pairs with the Phase 1 build — ideally
you have already built this by now; the week is then revision.)*
Clean vs dirty price, accrued interest under 30E/360 and ACT/ACT-ICMA; YTM and
its limits; price/yield inversion; semi-annual vs annual yield conversion;
settlement conventions (eurobonds: T+2, ICMA rules).
*Self-test: hand-compute accrued on a 5% annual eurobond 100 days after coupon
under 30E/360, then verify with your own pricer.*

**Week 6 — Risk measures.**
Macaulay/modified duration, convexity, DV01; portfolio DV01 and hedge ratios
(how many futures/how much 10y to neutralize); why duration fails for big moves;
carry and roll-down as the P&L of doing nothing.
*Self-test: $5mm of a bond at price 98, mod duration 7.2 — DV01? P&L on a 25bp
sell-off with and without convexity 60?*

**Week 7 — The curve and curve trades.**
Par/zero/forward curves and bootstrapping (conceptually + your Phase 3 build);
2s10s, 5s30s; bull/bear steepeners/flatteners and which CB regime produces
which; DV01-neutral curve trade sizing; monetary policy transmission (front end
= policy expectations, long end = term premium + inflation expectations).
*ICMA FIC topics "Trading the yield curve with cash market securities",
"Monetary policy & the yield curve". Self-test: you expect the ECB to cut faster
than priced — which trade, and how do you size it DV01-neutral?*

**Week 8 — Credit and the eurobond market.**
What a eurobond is (offshore, bearer-origin, ICMA-governed, Euroclear/Clearstream
settled); primary market mechanics (syndication, book-building, NIP — details in
`05`); G-spread, I-spread, Z-spread, ASW (definitions and when each misleads);
sovereign credit and ratings; EM sovereign complex — and specifically Morocco's
outstanding USD/EUR eurobonds as your case study: pull prices/yields, compute
G-spread vs UST/Bund, track it in the blotter from now on.
*Fabozzi credit chapters + ICMA FIC "Sovereign credit risk". Self-test: define
Z-spread vs G-spread and give one situation where they diverge materially.*

## Block 3 — Derivatives & commodities (weeks 9–12)

**Week 9 — Rates derivatives (survey level).**
STIR futures (SOFR futures, pricing = 100 − rate), bond futures (CTD concept,
basis — survey only; Burghardt later if the seat demands), interest rate swaps
(par swap rate, DV01 of a swap, asset-swapping a bond).
*CME "Introduction to STIR/Treasury futures" courses + ICMA FIC derivative
topics. Self-test: SOFR future at 95.80 — what rate is priced? You buy 10
contracts and rates fall 10bp — P&L direction and rough size?*

**Week 10 — Commodity futures mechanics.**
Contract specs (multiplier, tick, delivery months, first notice) for WTI/Brent,
gold, one ag; margin and daily settlement; contango/backwardation; roll yield —
why a long in backwardation earns positive roll; storage/convenience yield
(theory of storage); who hedges what (producers/consumers/CTAs).
*CME "Introduction to Futures" + energy/metals product courses. Self-test: WTI
front 82.00, second 81.40 — contango or backwardation? Monthly roll P&L for a
long, in % terms?*

**Week 11 — FX & commodity options (vocabulary level).**
Calls/puts, forwards vs options, delta/gamma/vega/theta in words, implied vol,
risk reversals and what 25d RR skew says about positioning, straddles around
events. Goal: fluent vocabulary, not pricing models.
*CME "Introduction to Options". Self-test: EUR/USD 1-week straddle costs 80
pips — what break-even move is priced for the ECB meeting?*

**Week 12 — Integration + carry/momentum literature.**
Read Ilmanen (carry, trend chapters) + skim MOP 2012 and Koijen et al. "Carry"
— you have implemented these by now in the FX slice, so read them as the theory
behind your own numbers. Full-syllabus cold self-test: 20 questions sampled
from all weeks. Anything below 8/10 → repeat that week's self-tests until cold.

---

## Optional: sit the actual ACI exam

€320, computer-based, bookable at test centres worldwide. Worth it if the target
bank values it (many EMEA banks do; it is *the* junior dealer certificate).
Decision point: week 8 — by then you'll know if the syllabus feels cold-passable
after two more weeks of drills.
