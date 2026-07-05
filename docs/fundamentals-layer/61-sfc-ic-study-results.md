# 61 - SFC IC study results

Generated: 2026-07-05T13:17:01.670168+00:00
Config hash: `8bdb5a6aa7d3e150`
Chosen selection-half variant: `pmom_6_1`
Selection/proof split date: `2023-07-31`

## Selection-half variants

| variant_id   | split     | signal      | horizon   |   periods |   pairs |   mean_ic |   nw_t_stat |   pooled_hac_t_stat |   pvalue |
|:-------------|:----------|:------------|:----------|----------:|--------:|----------:|------------:|--------------------:|---------:|
| pmom_6_1     | selection | pillar_val  | 3m        |        28 |     398 |    0.12   |      1.9728 |              2.3826 |   0.0485 |
| pmom_6_1     | selection | pillar_val  | 6m        |        28 |     398 |    0.1752 |      4.1891 |              3.508  |   0      |
| pmom_6_1     | selection | pillar_val  | 12m       |        28 |     398 |    0.2945 |      4.3837 |              3.8219 |   0      |
| pmom_6_1     | selection | pillar_qual | 3m        |        30 |     447 |   -0.0737 |     -0.7177 |              0.7492 |   0.4729 |
| pmom_6_1     | selection | pillar_qual | 6m        |        30 |     447 |   -0.0207 |     -0.1726 |              1.3146 |   0.863  |
| pmom_6_1     | selection | pillar_qual | 12m       |        30 |     447 |    0.0979 |      1.4    |              2.8478 |   0.1615 |
| pmom_6_1     | selection | pillar_fmom | 3m        |         4 |     203 |   -0.0205 |     -0.401  |             -1.1693 |   0.6884 |
| pmom_6_1     | selection | pillar_fmom | 6m        |         4 |     203 |   -0.0228 |     -1.0348 |             -1.5439 |   0.3008 |
| pmom_6_1     | selection | pillar_fmom | 12m       |         4 |     203 |   -0.0114 |     -0.2716 |             -1.6213 |   0.786  |
| pmom_6_1     | selection | pillar_pmom | 3m        |        26 |     237 |    0.0138 |      0.1692 |             -0.5502 |   0.8656 |
| pmom_6_1     | selection | pillar_pmom | 6m        |        26 |     237 |   -0.0164 |     -0.2067 |             -1.238  |   0.8363 |
| pmom_6_1     | selection | pillar_pmom | 12m       |        26 |     237 |   -0.0081 |     -0.0854 |              0.7908 |   0.9319 |
| pmom_6_1     | selection | sfc         | 3m        |        30 |     445 |   -0.0146 |     -0.251  |              0.2817 |   0.8018 |
| pmom_6_1     | selection | sfc         | 6m        |        30 |     445 |   -0.043  |     -0.8884 |              0.4205 |   0.3743 |
| pmom_6_1     | selection | sfc         | 12m       |        30 |     445 |    0.0348 |      0.4935 |              2.6911 |   0.6217 |
| pmom_12_1    | selection | pillar_val  | 3m        |        28 |     398 |    0.12   |      1.9728 |              2.3826 |   0.0485 |
| pmom_12_1    | selection | pillar_val  | 6m        |        28 |     398 |    0.1752 |      4.1891 |              3.508  |   0      |
| pmom_12_1    | selection | pillar_val  | 12m       |        28 |     398 |    0.2945 |      4.3837 |              3.8219 |   0      |
| pmom_12_1    | selection | pillar_qual | 3m        |        30 |     447 |   -0.0737 |     -0.7177 |              0.7492 |   0.4729 |
| pmom_12_1    | selection | pillar_qual | 6m        |        30 |     447 |   -0.0207 |     -0.1726 |              1.3146 |   0.863  |
| pmom_12_1    | selection | pillar_qual | 12m       |        30 |     447 |    0.0979 |      1.4    |              2.8478 |   0.1615 |
| pmom_12_1    | selection | pillar_fmom | 3m        |         4 |     203 |   -0.0205 |     -0.401  |             -1.1693 |   0.6884 |
| pmom_12_1    | selection | pillar_fmom | 6m        |         4 |     203 |   -0.0228 |     -1.0348 |             -1.5439 |   0.3008 |
| pmom_12_1    | selection | pillar_fmom | 12m       |         4 |     203 |   -0.0114 |     -0.2716 |             -1.6213 |   0.786  |
| pmom_12_1    | selection | pillar_pmom | 3m        |        20 |     188 |   -0.0267 |     -0.3508 |             -1.2909 |   0.7257 |
| pmom_12_1    | selection | pillar_pmom | 6m        |        20 |     188 |   -0.1161 |     -0.9965 |             -1.3107 |   0.319  |
| pmom_12_1    | selection | pillar_pmom | 12m       |        20 |     188 |   -0.0763 |     -0.5469 |              1.3863 |   0.5845 |
| pmom_12_1    | selection | sfc         | 3m        |        30 |     445 |   -0.0396 |     -0.7388 |             -0.3847 |   0.46   |
| pmom_12_1    | selection | sfc         | 6m        |        30 |     445 |   -0.0939 |     -1.8889 |              0.1152 |   0.0589 |
| pmom_12_1    | selection | sfc         | 12m       |        30 |     445 |    0.0394 |      0.5633 |              3.0755 |   0.5732 |

## Proof-half IC with BH-FDR

| variant_id   | split   | signal      | horizon   |   periods |   pairs |   mean_ic |   nw_t_stat |   pooled_hac_t_stat |   pvalue |   fdr_qvalue | fdr_reject_10pct   |
|:-------------|:--------|:------------|:----------|----------:|--------:|----------:|------------:|--------------------:|---------:|-------------:|:-------------------|
| pmom_6_1     | proof   | pillar_val  | 3m        |        30 |    1981 |    0.086  |      2.5936 |              5.2768 |   0.0095 |       0.0285 | True               |
| pmom_6_1     | proof   | pillar_val  | 6m        |        28 |    1836 |    0.1275 |      3.5391 |              6.7624 |   0.0004 |       0.0017 | True               |
| pmom_6_1     | proof   | pillar_val  | 12m       |        22 |    1427 |    0.2283 |      7.6325 |              8.1201 |   0      |       0      | True               |
| pmom_6_1     | proof   | pillar_qual | 3m        |        30 |    2026 |    0.0056 |      0.1765 |              0.0134 |   0.8599 |       0.9213 | False              |
| pmom_6_1     | proof   | pillar_qual | 6m        |        28 |    1879 |    0.0103 |      0.2908 |              0.9519 |   0.7712 |       0.8899 | False              |
| pmom_6_1     | proof   | pillar_qual | 12m       |        22 |    1464 |    0.0312 |      1.225  |              3.7868 |   0.2206 |       0.3309 | False              |
| pmom_6_1     | proof   | pillar_fmom | 3m        |        30 |    2018 |    0.0118 |      0.4515 |             -0.4609 |   0.6516 |       0.8145 | False              |
| pmom_6_1     | proof   | pillar_fmom | 6m        |        28 |    1871 |    0.0008 |      0.0254 |              1.3386 |   0.9797 |       0.9797 | False              |
| pmom_6_1     | proof   | pillar_fmom | 12m       |        22 |    1456 |   -0.0268 |     -0.7564 |              2.8343 |   0.4494 |       0.6129 | False              |
| pmom_6_1     | proof   | pillar_pmom | 3m        |        30 |    1834 |    0.108  |      1.5839 |              2.1821 |   0.1132 |       0.1998 | False              |
| pmom_6_1     | proof   | pillar_pmom | 6m        |        28 |    1691 |    0.1432 |      1.6357 |              3.4246 |   0.1019 |       0.1911 | False              |
| pmom_6_1     | proof   | pillar_pmom | 12m       |        22 |    1281 |    0.2135 |      2.9397 |              5.0126 |   0.0033 |       0.0123 | True               |
| pmom_6_1     | proof   | sfc         | 3m        |        30 |    2026 |    0.0624 |      1.7375 |              3.1653 |   0.0823 |       0.1646 | False              |
| pmom_6_1     | proof   | sfc         | 6m        |        28 |    1879 |    0.0852 |      2.1836 |              4.7472 |   0.029  |       0.0725 | True               |
| pmom_6_1     | proof   | sfc         | 12m       |        22 |    1464 |    0.1691 |      5.4805 |              7.2589 |   0      |       0      | True               |
| pmom_12_1    | proof   | pillar_val  | 3m        |        30 |    1981 |    0.086  |      2.5936 |              5.2768 |   0.0095 |       0.0285 | True               |
| pmom_12_1    | proof   | pillar_val  | 6m        |        28 |    1836 |    0.1275 |      3.5391 |              6.7624 |   0.0004 |       0.0017 | True               |
| pmom_12_1    | proof   | pillar_val  | 12m       |        22 |    1427 |    0.2283 |      7.6325 |              8.1201 |   0      |       0      | True               |
| pmom_12_1    | proof   | pillar_qual | 3m        |        30 |    2026 |    0.0056 |      0.1765 |              0.0134 |   0.8599 |       0.9213 | False              |
| pmom_12_1    | proof   | pillar_qual | 6m        |        28 |    1879 |    0.0103 |      0.2908 |              0.9519 |   0.7712 |       0.8899 | False              |
| pmom_12_1    | proof   | pillar_qual | 12m       |        22 |    1464 |    0.0312 |      1.225  |              3.7868 |   0.2206 |       0.3309 | False              |
| pmom_12_1    | proof   | pillar_fmom | 3m        |        30 |    2018 |    0.0118 |      0.4515 |             -0.4609 |   0.6516 |       0.8145 | False              |
| pmom_12_1    | proof   | pillar_fmom | 6m        |        28 |    1871 |    0.0008 |      0.0254 |              1.3386 |   0.9797 |       0.9797 | False              |
| pmom_12_1    | proof   | pillar_fmom | 12m       |        22 |    1456 |   -0.0268 |     -0.7564 |              2.8343 |   0.4494 |       0.6129 | False              |
| pmom_12_1    | proof   | pillar_pmom | 3m        |        30 |    1475 |    0.1824 |      1.9635 |              1.6265 |   0.0496 |       0.1063 | False              |
| pmom_12_1    | proof   | pillar_pmom | 6m        |        28 |    1333 |    0.2611 |      2.2216 |              3.8101 |   0.0263 |       0.0718 | True               |
| pmom_12_1    | proof   | pillar_pmom | 12m       |        22 |     928 |    0.3626 |      3.793  |              4.2353 |   0.0001 |       0.0009 | True               |
| pmom_12_1    | proof   | sfc         | 3m        |        30 |    2026 |    0.0498 |      1.4847 |              2.7222 |   0.1376 |       0.2294 | False              |
| pmom_12_1    | proof   | sfc         | 6m        |        28 |    1879 |    0.0789 |      2.0885 |              4.4944 |   0.0368 |       0.0848 | True               |
| pmom_12_1    | proof   | sfc         | 12m       |        22 |    1464 |    0.153  |      6.6009 |              7.4862 |   0      |       0      | True               |

## Tercile spread backtest

| horizon   |   cost_bps |   periods |   mean_spread |   total_spread |   avg_turnover |   bootstrap_pvalue |
|:----------|-----------:|----------:|--------------:|---------------:|---------------:|-------------------:|
| 3m        |         33 |        30 |      0.033597 |        1.62543 |         0.2518 |                  0 |
| 3m        |         75 |        30 |      0.031482 |        1.46868 |         0.2518 |                  0 |

## Gate verdict

Verdict: **PASS**
Composite IC gate passed: `True`
Net spread gate passed: `True`

The proof-half FDR family includes every selection-half variant carried to proof.

## Reviewer caveats (Claude verification pass, 2026-07-05)

Implementation verified faithful to brief 60: selection/proof split is disjoint and chronological,
the tercile backtest runs on the proof half only (`ic_study.py:185-186`), publication dates are
joined through `fundamental_source_document` (`ic_study.py:261`), look-ahead assertions are in
place, and the FDR family counts both PMOM variants. The PASS stands, with the following
qualifications that MUST accompany any presentation of these numbers:

1. **The selection half was data-starved** (~14 scored names/period vs ~66 in proof; FMOM had
   only 4 selection periods). The split still did its job — only two low-stakes PMOM variants
   were searched — but the effective evidence window is one contiguous regime (2023-07 → 2026-07).
2. **The 12m rows overstate certainty.** 22 overlapping monthly periods contain ~2 independent
   12-month windows; NW correction cannot repair that. The credible core of the PASS is the 6m
   composite line (IC 0.085, NW t 2.18, q 0.073) plus the 3m tercile spread (+3.36%/quarter net
   at 33 bps, block-bootstrap p ≈ 0 over 30 periods). Cite those; treat 12m as directional.
3. **VAL carries the composite** (proof IC 0.086/0.128/0.228); PMOM contributes at 12m;
   QUAL and FMOM are flat in this sample (FMOM's consensus/indicator history barely exists yet).
   Note SFC 6m IC (0.085) < VAL-alone (0.128): equal weighting currently *dilutes* — that is the
   accepted price of robustness per brief 59 §3.5, not a defect, but expectations should be set:
   today this is a value(+momentum) strategy; QUAL/FMOM are options on future data depth.
4. **Vintage caveat.** The panel uses the current corrected DB. Defensible — brief-38/42
   corrections re-extracted figures from the original published PDFs (fixing our extraction
   errors, not restating history) and availability uses publication dates — but ingestion
   *coverage* is a 2026 choice: names never ingested are absent from history (mild
   coverage-selection bias; delisted names lack fundamentals even where PIT prices exist).
5. **`total_spread` is not an investable cumulative return** — it compounds overlapping 3m
   returns sampled monthly. Use `mean_spread` per period; remove or relabel `total_spread` in
   Phase 2+ reporting.
6. **Magnitudes are top-of-global-range** (institutional value ICs typically 0.03–0.07).
   Plausible for a thin, low-coverage frontier market — it is the brief-59 §3.3 mechanism — but
   present them with the single-regime caveat attached.

**Follow-ups for the Phase 2 run**: report the share of panel rows using a real
`publication_date` vs each fallback lag; add a VAL-only comparison line to the standard output;
drop `total_spread`. UI language in Phase 3 must say "validé sur 2023–2026 (une seule période de
marché)" rather than an unqualified "validé".
