# Conventions Card — Print This

Day-one reference for the offshore cross-asset desk. Built 2026-08-12 from the
diagnostic in `10-final-4-days.md`. Everything here is a convention, not a
judgement call: getting it wrong loses money mechanically.

---

## FX

**Reading a quote.** In `EUR/USD`, **EUR is the base** (first currency), **USD is
the quote** (second, also "term" or "counter"). Read it as *one unit of base
costs X of quote*. Number up = base stronger.

**Pips.** 0.0001 for most pairs. **0.01 for JPY pairs** (they quote to 2dp).
USD/JPY 156.20 → 156.45 = 25 pips.

**Settlement.** Spot is **T+2** business days, holidays in *both* home centres
counted. Not instant. Exceptions: **USD/CAD is T+1**, also USD/TRY. "Value date"
= settlement date.

**Formulas.**

```
P&L (quote ccy)  = notional_base × (rate_close − rate_open)
Pip value        = notional_base × pip_size        # 1m EUR/USD → 1 pip = $100
Cross (chain)    = EUR/USD × USD/MAD = EUR/MAD     # common ccy cancels
Cross (divide)   = GBP/EUR = (GBP/USD) / (EUR/USD)
```

**Forwards — covered interest parity.**

```
F = S × (1 + r_quote × t) / (1 + r_base × t)        t = days / basis
Forward points ≈ S × (r_quote − r_base) × t         # the mental-math version
```

Money-market basis: USD, EUR = **ACT/360**. GBP = **ACT/365**.

> **THE RULE: the high-yielding currency trades at a forward discount.**

Positive points on EUR/USD ⇒ F > S ⇒ EUR at a forward **premium** ⇒ **USD rate
is higher**. Why: holding the high-yielder earns more interest, so the forward
must give that advantage back or the borrow-spot-deposit-sell-forward arb prints
money. That arb closing *is* the formula.

Carry trade corollary: you earn the differential spot and pay it away forward.
Carry only wins if spot fails to move by what the forward already implied.

---

## Commodities

**Curve shape.** Front below deferred = **contango**. Front above = **backwardation**.

**Roll.** A long in contango **bleeds** — sell the cheap front, buy the dearer
next, every roll, before price even moves. Backwardation pays the long roller.
This is why long-only commodity index products lag spot.

**Contract sizes — cannot size a trade without these.**

| Contract | Size | Unit move |
|---|---|---|
| WTI / Brent | 1,000 barrels | $1.00 = **$1,000** |
| Gold (COMEX) | 100 troy oz | $1.00/oz = **$100** |
| Silver | 5,000 oz | $0.01/oz = **$50** |
| Copper (COMEX) | 25,000 lbs | $0.01/lb = **$250** |
| Nat gas (Henry Hub) | 10,000 MMBtu | $0.01 = **$100** |

---

## Rates & eurobonds

**Clean vs dirty.** The quoted price is **clean**. What you pay is **dirty**.

```
Dirty = Clean + Accrued
Accrued = (annual coupon / freq) × (days since last coupon / days in period)
```

Both per 100 of face. $10m at 98.40 clean + 1.20 accrued → wire $9,960,000.

Quoted clean because the dirty price sawtooths with the coupon calendar; that
motion is not market information. Clean is the signal, accrued is the calendar.

**Day counts — they define "days" above.**

| Convention | Used by |
|---|---|
| **30/360** | Most USD corporates and eurobonds |
| **ACT/ACT** | US Treasuries, most euro govvies (ICMA) |
| **ACT/360** | Money markets, FRNs, USD/EUR deposits |
| **ACT/365** | GBP money markets |

Settlement: eurobonds **T+2**, USTs **T+1**.

**Duration and DV01.**

```
ΔP/P ≈ −D_mod × Δy                         # 10bp on D=8 → −0.80%
ΔP/P ≈ −D_mod × Δy + ½ × Convexity × Δy²   # matters at 100bp, not 10bp
DV01  = market value × duration × 0.0001
```

> **THE SHORTCUT: per $1m notional, DV01 ≈ duration × $100.**

D=8 → $800/million → **$8,000 on $10m**. D=5 on €25m → $12,500.

Use DV01 not duration because duration is a percentage and percentages don't add
across differently-sized positions. DV01 is money, so it is **additive**: desk
risk is the sum of DV01s, limits are set in it, and you hedge by matching DV01s
— never notionals. "What's your DV01?" = "what do you lose on a one-beep move?"

**Spread ladder — people are precise about which one.**

| Spread | Measured over |
|---|---|
| **G-spread** | Interpolated government curve — what "+180 over" usually means |
| **I-spread** | Matching-maturity swap rate |
| **Z-spread** | Parallel shift to the zero curve making PV = market price |
| **ASW** | Asset swap spread — spread received swapping the bond to floating |

Credit trades **in spread, not price**: "+178/+174" is a bid/offer. Price follows.

**Primary vs secondary.** Primary = **new issue**, issuer raises new money via a
syndicate. Secondary = investors trading existing bonds through dealers; the
issuer gets nothing. New-issue sequence, spoken fast on a desk:

> mandate → **IPTs** (initial price thoughts) → guidance → books open →
> "books are covered" → pricing → free to trade

**New issue concession (NIC)** = extra spread over the issuer's existing curve
needed to clear the deal. That's the number people argue about.

---

## Answering "what's going on?"

Four parts, always: **level, move, driver, and what would change your mind.**

> "Brent's at 82, down two and a half on the week on optimism the strait
> reopens — if that slips past the weekend I'd expect it to give it back."

Specific and falsifiable. Vague narrative without levels reads as no narrative.

---

## Posture (matters more than any of the above in week one)

- **Never bluff a number.** "Je vérifie et je reviens vers toi" — then come back
  the same day, unprompted.
- **Repeat every instruction back** before acting. Every time.
- **Say the number *and* the unit.** bp vs %, base vs quote, lots vs notional.
- **Write it all down.** Batch the embarrassing questions, ask at a calm moment.
- **Ask properly:** "I looked at X, I think it's Y — am I reading this right?"
