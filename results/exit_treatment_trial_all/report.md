# Exit-Treatment Trial — edge counts & quality per treatment

Symbols: ADH, ADI, AED, AFI, AFM, AGM, AKT, ALM, ARD, ATH, ATL, ATW, BAL, BCI, BCP, BOA, BRENT, BTC, CAC, CAP, CDM, CFG, CIH, CMA, CMG, CMT, COL, CRS, CSR, CTM, DHO, DWY, DXY, DYT, EQD, EURUSD, FBR, FTSE, GAZ, GOLD, GTM, HPS, IAM, IBC, IMO, INV, JET, LBV, LES, LHM, M2M, MAB, MASI, MASI_20, MDP, MIC, MLE, MNG, MOX, MSA, MUT, N225, NDX, NKL, OUL, RDS, REB, RIS, S2M, SAH, SBM, SID, SILVER, SLF, SMI, SNA, SNP, SOT, SP500, SRM, STR, TGC, TMA, TQM, US10Y, VCN, VIX, WAA, ZDJ
Signals (symbol×category): 344  |  Folds evaluated: 9389
Edge rule: n≥30, Wilson hit-LB>0.5, bootstrap net-LB>0 (proven); n≥30 only → watch; else insufficient
Cost: 33.0 bps/side = 66 bps round-trip, all treatments

Only signals WITH an edge (proven+watch) are summarised for quality.

| Treatment | #Proven | #Watch | #Edged | Edged mean net ER | Edged mean hit% | Edged mean score |
|-----------|---------|--------|--------|-------------------|-----------------|------------------|
| none | 11 | 254 | 265 | -0.0045 | 41.4% | -0.0189 |
| atr_1.5_1.5 | 10 | 255 | 265 | -0.0049 | 42.7% | -0.0182 |
| atr_2.0_1.0 | 10 | 255 | 265 | -0.0048 | 45.8% | -0.0180 |
| atr_3.0_1.0 | 11 | 254 | 265 | -0.0047 | 46.2% | -0.0180 |
| mae_mfe | 10 | 255 | 265 | -0.0050 | 42.6% | -0.0182 |

**#Proven** = signals that clear the full edge gate; **#Edged** = proven+watch.
Question: does any exit treatment yield MORE / STRONGER edged signals than `none`?