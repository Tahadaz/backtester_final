# Mental Math Drills

10 minutes a day, no calculator, answers to ~2 significant figures. These are
the computations trading interviews test live and desks use constantly. Rotate
one set per day; by week 4 mix sets randomly. Target: each answer in under 20
seconds, spoken aloud (interviews are verbal).

## Set A — Bond price/yield (daily until automatic)

Core approximation: **ΔP ≈ −MD · Δy · P** (Δy in decimal), **DV01 = MD · P ·
0.0001** per unit face.

Worked example: $1mm face, price 100, mod duration 8. DV01 = 8 × 1,000,000 ×
0.0001 = **$800/bp**. A 15bp sell-off ≈ −$12,000.

Drill patterns (generate your own numbers):
1. Price 98, MD 7.2, yield +25bp → price change? *(−7.2 × 0.0025 × 98 ≈ −1.76
   points → ≈ 96.24.)*
2. $5mm 10y, MD 8 → DV01? P&L on −40bp? *($4,000/bp; +$160k.)*
3. Convexity correction: same bond, convexity 60, Δy = +100bp → add
   ½·60·0.01² ·P ≈ +0.30 points back. Rule: convexity helps you both ways.
4. Hedge ratio: long $10mm A (DV01 $9k), hedge with B (DV01/mm $750) → sell
   $12mm B. *(9,000 / 750 = 12.)*
5. Yield conversions: 6% semi-annual = (1.03)² − 1 ≈ 6.09% annual. Know that
   semi < annual for the same cash flows.

## Set B — FX forwards & crosses (daily until automatic)

Core approximation: **points ≈ S · (r_quote − r_base) · τ**. Positive when the
quote (second) currency has the higher rate → base trades at a **premium**
(forward > spot).

Worked example: EUR/USD 1.0900, 3m USD 5%, EUR 4%: 1.09 × 0.01 × 0.25 ≈ 0.0027
= **+27 pips**, forward ≈ 1.0927. EUR at a premium (CIP: what you lose in
carry holding the low-rate currency you make back on the forward).

Drill patterns:
1. USD/JPY 150, 6m JPY 0.5%, USD 5.25% → points? *(150 × (0.005 − 0.0525) ×
   0.5 ≈ −3.56 → forward ≈ 146.44; USD at a discount vs JPY.)*
2. Cross rates with spreads: EUR/USD 1.0898/1.0900, USD/JPY 149.95/150.00 →
   EUR/JPY? *(bid 1.0898 × 149.95 ≈ 163.41, offer 1.0900 × 150.00 = 163.50.)*
3. Pip values: 1mm EUR/USD position, 1 pip = $100. 1mm USD/JPY, 1 pip (0.01) =
   ¥10,000 ≈ $67 at 150.
4. Carry per month: long AUD/JPY, rate diff 4% p.a. → ≈ 33bp/month if spot
   unchanged. Then ask: what spot move erases a year of carry? (4%.)

## Set C — Curve & carry (3×/week)

1. 2s10s from levels instantly: 2y 4.60, 10y 4.20 → **−40bp, inverted**. Bear
   steepener = long end sells off more; bull steepener = front end rallies more.
   Drill naming the regime from two days of levels.
2. DV01-neutral steepener sizing: long 2y (DV01/mm $190), short 10y (DV01/mm
   $800) → ratio ≈ 4.2:1 notional.
3. Bond carry: yield 5%, funding (repo) 5.3% → negative carry 30bp/yr ≈
   2.5bp/month; roll-down: 1y of roll on a curve 15bp/yr steep = +15bp. Total
   carry+roll ≈ +12.5bp/yr → breakeven yield rise ≈ 12.5bp/duration... know the
   *structure* of this reasoning, not just numbers.

## Set D — Futures & commodities (3×/week)

1. Roll: WTI front 82.00, second 81.40 → backwardation; long earns roll ≈
   0.60/82 ≈ **+0.73%/month** ≈ +9% annualized if the curve shape persists.
   Reverse the sign for contango. Drill until the sign is reflexive.
2. Contract P&L: WTI = 1,000 bbl/contract, tick 0.01 = $10. Long 5 contracts,
   +$1.20 → +$6,000. Gold = 100 oz, $1 move = $100/contract.
3. SOFR futures: price 95.80 → 4.20% priced. Rates −10bp → price +0.10; $25/bp
   per contract (3m × $1mm ÷ 4... just memorize $25/bp).
4. % ↔ bp reflexes: 0.25% = 25bp; 7 points on a 98 bond ≈ 7.1%; "up 40 pips
   from 1.0900" = +0.37%.

## Set E — General speed (interview classic warm-ups, 2×/week)

- Rule of 72 (doubling times); 17 × 24-style two-digit products; quick
  percentages (18% of 350); expected-value bets ("pay 5 to roll a die, win the
  face value — take it?"); annualize a monthly return; √252 ≈ 15.9 for
  daily→annual vol scaling (memorize).

## Protocol

- Speak answers aloud, time yourself, log misses. Twice a week have the numbers
  generated randomly (script it or have someone quiz you).
- When a drill is consistently <20s and error-free for a week, demote it to the
  weekly mix and promote a harder variant (add bid/offer, add convexity, add a
  second leg).
- Before any interview: 20-minute mixed session from all sets, same morning.
