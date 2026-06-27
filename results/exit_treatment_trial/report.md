# Exit-Treatment Trial — edge counts & quality per treatment

Symbols: ADH, IAM, MNG, SMI, CMT, MSA, AKT, BCP, BOA, ATW
Signals (symbol×category): 40  |  Folds evaluated: 1356
Edge rule: n≥30, Wilson hit-LB>0.5, bootstrap net-LB>0 (proven); n≥30 only → watch; else insufficient
Cost: 33.0 bps/side = 66 bps round-trip, all treatments

Only signals WITH an edge (proven+watch) are summarised for quality.

| Treatment | #Proven | #Watch | #Edged | Edged mean net ER | Edged mean hit% | Edged mean score |
|-----------|---------|--------|--------|-------------------|-----------------|------------------|
| none | 0 | 34 | 34 | +0.0027 | 43.2% | -0.0132 |
| atr_1.5_1.5 | 0 | 34 | 34 | +0.0005 | 44.8% | -0.0133 |
| atr_2.0_1.0 | 0 | 34 | 34 | +0.0002 | 49.0% | -0.0135 |
| atr_3.0_1.0 | 0 | 34 | 34 | +0.0003 | 49.9% | -0.0136 |
| mae_mfe | 0 | 34 | 34 | +0.0004 | 44.6% | -0.0134 |

**#Proven** = signals that clear the full edge gate; **#Edged** = proven+watch.
Question: does any exit treatment yield MORE / STRONGER edged signals than `none`?