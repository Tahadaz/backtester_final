# Structural Value v2 transaction-cost source

- Source: desk workbook `fees_trades_equity (1).xlsx`
- Workbook creator: Mouad IZELGUE
- Workbook creation timestamp: 2026-02-10 14:27:15
- SHA-256: `7EF1F33618CD715544A0DF645B599795A6A16AF07694BD57D520F328374E1553`
- Intermediation commission HT: 20 bps
- SBVC commission HT: 10 bps
- TVA: 3 bps
- Total applied cost: 33 bps per executed notional

The original workbook remains desk-controlled outside the repository. The hash above identifies
the exact workbook inspected for this configuration. The engine applies 33 bps to both purchases
and sales through its total-traded-notional turnover calculation.
