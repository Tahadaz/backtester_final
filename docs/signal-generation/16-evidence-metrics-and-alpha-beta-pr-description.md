## PR Description Notes

- A5 basis: alpha/beta is effective-book beta, not stock beta. It regresses the traded equity path on MASI daily returns, keeps flat 0-days, and annualizes alpha linearly with x252.
- B2 uplift study (`python analysis/sr_overlay_uplift_study.py`, sr-desk-grade worktree): actionable=0, research_only=0, unavailable=145.
- MASI ticker verification: `load_close_for_symbol(db, "MASI")` succeeds with 736 closes; `MASI.CS` and `MASI.MA` are unavailable.
