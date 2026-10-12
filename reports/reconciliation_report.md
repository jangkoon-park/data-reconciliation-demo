# Cost Data Reconciliation Report

## Headline

Reporting period **2025-01-01 to 2025-06-30**. Source = ERP actual costs; report = `rpt_site_contract_summary`.

| Metric | Source | Report | Difference (report - source) |
|---|---|---|---|
| Line count | 17,891 | 17,908 | +17 |
| Amount | $149,972,438.40 | $150,145,848.12 | +$173,409.72 |
| Site x contract keys | 76 |  | 71 mismatched |

## Root causes

Causes explain **all** differences: unexplained count = 0, unexplained amount = $0.00.

| Cause | Lines | Count effect | Net amount effect | Gross amount | Site x contracts hit | What it means |
|---|---|---|---|---|---|---|
| MISSING | 40 | -40 | -$461,641.39 | $461,641.39 | 29 | Source line is in the period but absent from the report. |
| DUPLICATE | 30 | +30 | +$247,184.67 | $247,184.67 | 24 | Same source line loaded into the report more than once. |
| ROUNDING | 3,403 | 0 | +$24.72 | $57.96 | 12 | Line matched, amount differs by no more than $0.50. |
| CODE_MAPPING | 30 | 0 | $0.00 | $752,152.40 | 6 | Line matched, but reported under a different site/contract. |
| PERIOD_BOUNDARY | 193 | +27 | +$387,841.72 | $1,289,788.60 | 66 | Line on the wrong side of the period cut-off (first/last day filter bug). |

## Mismatched site x contract keys (top 15 by amount)

71 of 76 keys differ. The full list is in `site_contract_comparison.csv`.

| Site | Contract | Src lines | Rpt lines | Src amount | Rpt amount | Diff | Causes |
|---|---|---|---|---|---|---|---|
| S04 | CT-0403 | 219 | 233 | $1,542,687.50 | $1,710,511.17 | +$167,823.67 | CODE_MAPPING, DUPLICATE, PERIOD_BOUNDARY |
| S06 | CT-0607 | 309 | 298 | $2,908,019.80 | $2,770,673.42 | -$137,346.38 | CODE_MAPPING |
| S01 | CT-0104 | 325 | 333 | $3,052,031.19 | $3,186,867.97 | +$134,836.78 | CODE_MAPPING, PERIOD_BOUNDARY |
| S03 | CT-0308 | 211 | 210 | $1,693,138.71 | $1,567,497.00 | -$125,641.71 | PERIOD_BOUNDARY, ROUNDING |
| S08 | CT-0803 | 209 | 202 | $1,880,432.13 | $1,760,976.37 | -$119,455.76 | CODE_MAPPING, PERIOD_BOUNDARY |
| S10 | CT-1001 | 315 | 318 | $2,706,323.89 | $2,803,655.84 | +$97,331.95 | DUPLICATE, PERIOD_BOUNDARY |
| S11 | CT-1106 | 199 | 210 | $1,699,041.77 | $1,785,563.18 | +$86,521.41 | CODE_MAPPING, MISSING, PERIOD_BOUNDARY |
| S10 | CT-1003 | 183 | 183 | $1,454,032.69 | $1,539,695.60 | +$85,662.91 | MISSING, PERIOD_BOUNDARY |
| S05 | CT-0502 | 278 | 273 | $2,244,113.30 | $2,175,482.42 | -$68,630.88 | DUPLICATE, MISSING, PERIOD_BOUNDARY |
| S07 | CT-0702 | 279 | 280 | $2,133,686.46 | $2,069,399.57 | -$64,286.89 | MISSING, PERIOD_BOUNDARY |
| S05 | CT-0503 | 224 | 214 | $1,778,699.58 | $1,714,996.04 | -$63,703.54 | CODE_MAPPING, MISSING, PERIOD_BOUNDARY |
| S10 | CT-1004 | 195 | 197 | $1,436,361.61 | $1,498,677.37 | +$62,315.76 | DUPLICATE, MISSING, PERIOD_BOUNDARY |
| S12 | CT-1207 | 169 | 168 | $1,497,284.89 | $1,443,877.04 | -$53,407.85 | MISSING, PERIOD_BOUNDARY |
| S11 | CT-1101 | 166 | 164 | $1,594,856.41 | $1,544,117.81 | -$50,738.60 | PERIOD_BOUNDARY |
| S03 | CT-0307 | 279 | 274 | $2,063,215.61 | $2,017,845.77 | -$45,369.84 | MISSING, PERIOD_BOUNDARY |

## Exception samples (up to 5 per cause)

3,696 line-level exceptions in total. The full list is in `exceptions.csv`.

| Cause | actual_id | Posted | Source key | Report key | Src amount | Rpt amount | Detail |
|---|---|---|---|---|---|---|---|
| CODE_MAPPING | 11197 | 2025-06-30 | S05/CT-0503 | S11/CT-1106 | $41,554.39 | $41,554.39 | S05/CT-0503 reported as S11/CT-1106 |
| CODE_MAPPING | 11198 | 2025-04-23 | S05/CT-0503 | S11/CT-1106 | $3,312.05 | $3,312.05 | S05/CT-0503 reported as S11/CT-1106 |
| CODE_MAPPING | 11200 | 2025-02-22 | S05/CT-0503 | S11/CT-1106 | $1,666.19 | $1,666.19 | S05/CT-0503 reported as S11/CT-1106 |
| CODE_MAPPING | 11202 | 2025-01-19 | S05/CT-0503 | S11/CT-1106 | $2,428.78 | $2,428.78 | S05/CT-0503 reported as S11/CT-1106 |
| CODE_MAPPING | 11207 | 2025-01-24 | S05/CT-0503 | S11/CT-1106 | $10,050.75 | $10,050.75 | S05/CT-0503 reported as S11/CT-1106 |
| DUPLICATE | 101 | 2025-03-01 | S01/CT-0101 | S01/CT-0101 | $715.99 | $715.99 | copy #2 of actual_id 101 |
| DUPLICATE | 107 | 2025-04-12 | S01/CT-0101 | S01/CT-0101 | $1,957.12 | $1,957.12 | copy #2 of actual_id 107 |
| DUPLICATE | 2310 | 2025-05-12 | S02/CT-0201 | S02/CT-0201 | $26,420.99 | $26,420.99 | copy #2 of actual_id 2310 |
| DUPLICATE | 2535 | 2025-03-30 | S02/CT-0202 | S02/CT-0202 | $8,766.44 | $8,766.44 | copy #2 of actual_id 2535 |
| DUPLICATE | 2538 | 2025-06-29 | S02/CT-0202 | S02/CT-0202 | $3,591.58 | $3,591.58 | copy #2 of actual_id 2538 |
| MISSING | 104 | 2025-05-19 | S01/CT-0101 |  | $6,764.89 |  | not found in report ledger |
| MISSING | 336 | 2025-05-25 | S01/CT-0102 |  | $2,798.05 |  | not found in report ledger |
| MISSING | 4585 | 2025-02-04 | S02/CT-0206 |  | $3,144.54 |  | not found in report ledger |
| MISSING | 5611 | 2025-03-03 | S03/CT-0301 |  | $2,029.03 |  | not found in report ledger |
| MISSING | 6425 | 2025-04-05 | S03/CT-0304 |  | $6,022.02 |  | not found in report ledger |
| PERIOD_BOUNDARY | 25 | 2025-07-01 | S01/CT-0101 | S01/CT-0101 | $8,661.54 | $8,661.54 | posted 2025-07-01, outside 2025-01-01..2025-06-30, but reported |
| PERIOD_BOUNDARY | 111 | 2025-07-01 | S01/CT-0101 | S01/CT-0101 | $6,645.93 | $6,645.93 | posted 2025-07-01, outside 2025-01-01..2025-06-30, but reported |
| PERIOD_BOUNDARY | 262 | 2025-01-01 | S01/CT-0101 |  | $1,587.73 |  | posted 2025-01-01 (period edge); no report lines on that date |
| PERIOD_BOUNDARY | 294 | 2025-01-01 | S01/CT-0101 |  | $1,606.12 |  | posted 2025-01-01 (period edge); no report lines on that date |
| PERIOD_BOUNDARY | 447 | 2025-01-01 | S01/CT-0102 |  | $12,221.11 |  | posted 2025-01-01 (period edge); no report lines on that date |
| ROUNDING | 1539 | 2025-04-28 | S01/CT-0105 | S01/CT-0105 | $5,268.31 | $5,268.00 | diff -31 cents |
| ROUNDING | 1541 | 2025-04-14 | S01/CT-0105 | S01/CT-0105 | $9,559.42 | $9,559.00 | diff -42 cents |
| ROUNDING | 1542 | 2025-03-15 | S01/CT-0105 | S01/CT-0105 | $6,423.09 | $6,423.00 | diff -9 cents |
| ROUNDING | 1543 | 2025-03-27 | S01/CT-0105 | S01/CT-0105 | $4,223.94 | $4,224.00 | diff 6 cents |
| ROUNDING | 1546 | 2025-02-17 | S01/CT-0105 | S01/CT-0105 | $10,019.78 | $10,020.00 | diff 22 cents |
