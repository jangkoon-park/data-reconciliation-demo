# data-reconciliation-demo

Source vs report reconciliation for construction cost data: verify totals, find every
mismatched line, and explain **why** each total is off.

> **All data is synthetic.** Site names, vendors, codes and amounts come from a seeded
> random generator. No real company data is used anywhere.

## The problem

A (fictional) general contractor tracks job costs in its ERP:

```
src_site ──< src_contract ──< src_order ──< src_actual
 (site)       (contract)       (purchase    (actual cost line,
                                order)       posting date + amount)
```

A nightly reporting job copies the actual cost lines into a reporting mart
(`rpt_cost_ledger`) and builds the management report `rpt_site_contract_summary`
(line count and total amount per site × contract for the period
**2025-01-01 – 2025-06-30**).

Finance notices that the report does not tie out to the ERP. The task is to find out
where the totals differ, which lines cause it, and what kind of error each one is.

To make the exercise realistic, the generator's reporting ETL plants five classic defects:

| Planted defect | How it happens in the fake ETL | What the reconciler calls it |
|---|---|---|
| Missing rows | 40 random lines silently dropped (failed batch) | `MISSING` |
| Duplicate rows | 30 lines loaded twice (re-delivered batch) | `DUPLICATE` |
| Rounding differences | Legacy subcontract feed rounds every amount to whole dollars | `ROUNDING` |
| Wrong code mapping | A stale code crosswalk posts every line of 3 purchase orders to the wrong contract (sometimes the wrong site) | `CODE_MAPPING` |
| Period boundary error | Filter written as `date > start AND date <= end + 1 day` instead of `BETWEEN start AND end`: Jan 1 is dropped, Jul 1 leaks in | `PERIOD_BOUNDARY` |

The generator also writes an answer key (`demo_injected_defect`). The reconciler never
reads it; the tests use it to prove the reconciler finds exactly the planted defects.

## Approach

**1. Aggregate check (SQL).** Count and sum source lines per site × contract for the period
(joining actual → order → contract), and compare with the report summary table. This shows
*where* the report is wrong, but not *why*.

**2. Line-level drill-down (pandas).** Full outer join of all source lines with the report
ledger on `actual_id`, then classify each difference:

| Situation | Category |
|---|---|
| Second, third… copy of the same `actual_id` in the report | `DUPLICATE` |
| In the report, but the source line is posted outside the period | `PERIOD_BOUNDARY` |
| In-period source line not in the report, on the first/last day of the period, and the report has no lines at all for that date | `PERIOD_BOUNDARY` |
| Any other in-period source line not in the report | `MISSING` |
| Matched, but site or contract differs | `CODE_MAPPING` |
| Matched, amount differs by ≤ $0.50 | `ROUNDING` |
| Matched, amount differs by more | `AMOUNT_MISMATCH` |
| Report line whose `actual_id` does not exist in the source | `UNMATCHED_REPORT_ROW` |

The last two categories are not planted, but the reconciler checks for them anyway: they are
what a real investigation would also look for.

**3. Proof that the causes add up.** Each exception is turned into its effect on the
site × contract totals (report minus source; a code-mapping error is −amount on the source key
and +amount on the reported key). Summing the effects per key must give exactly the
aggregate difference from step 1. Anything left over is flagged `UNEXPLAINED`, so the method
cannot quietly miss a cause. On the demo data the residual is **0 lines and $0.00**.

Design choices:

- Money is handled as **integer cents** in Python, `NUMERIC(14,2)` in the database: no float drift.
- SQL is kept portable: the same queries run on PostgreSQL and SQLite.
- Reconciliation is read-only; it never fixes data, it produces evidence.

## Database: PostgreSQL (with SQLite support)

The demo was built and run against **PostgreSQL 16**, which was available in the
development environment, so no SQLite fallback was needed for the main run. The code also
runs on SQLite (any SQLAlchemy URL works), and the automated tests use SQLite by default so
they run anywhere without a server. The end-to-end tests were also run against PostgreSQL
(see below).

## How to run

Requirements: Python 3.10+ and, for the default setup, a local PostgreSQL.

```bash
pip install -r requirements.txt

# PostgreSQL (default URL: postgresql+psycopg2://recon:recon@localhost:5432/recon_demo)
createuser recon --pwprompt          # password: recon
createdb recon_demo -O recon

python -m recon all                  # generate data + reconcile + write reports/
```

Or point it at any database:

```bash
export RECON_DB_URL=sqlite:///recon_demo.db     # no server needed
python -m recon all
```

Commands and options:

```
python -m recon generate    # rebuild tables with synthetic data and the faulty report
python -m recon reconcile   # compare source vs report, write reports/
python -m recon all         # both
  --db-url URL   --out DIR   --seed N   --rows N (approx. source lines, capped at 100,000)
```

Output in `reports/`:

| File | Content |
|---|---|
| `reconciliation_report.md` / `.html` | Headline, root-cause summary, worst keys, exception samples |
| `site_contract_comparison.csv` | Every site × contract: counts, amounts, diffs, causes, unexplained residual |
| `exceptions.csv` | Every line-level exception with its category and detail |

Tests:

```bash
pytest                                   # unit tests + end-to-end on SQLite
RECON_TEST_PG_URL=postgresql+psycopg2://recon:recon@localhost:5432/recon_test pytest   # + PostgreSQL
```

The tests cover each category on hand-built data, the priority rules (e.g. an
out-of-period line is a boundary error, not a phantom row), that the effects add up to the
aggregate differences, that a drifted summary table is flagged `UNEXPLAINED`, and, end to
end, that the set of `(actual_id, category)` found equals the answer key exactly.

## Results (example run)

PostgreSQL 16, seed 42: 12 sites, 76 contracts, 1,568 purchase orders, 30,020 source cost
lines, 17,908 report lines (≈ 50k rows in total). Generation took 5.5 s, reconciliation 0.5 s.
The full report is in [`reports/reconciliation_report.md`](reports/reconciliation_report.md).

**Headline: the report is $173,409.72 too high, and 71 of 76 site × contract totals are wrong.**

| Metric | Source | Report | Difference (report − source) |
|---|---|---|---|
| Line count | 17,891 | 17,908 | +17 |
| Amount | $149,972,438.40 | $150,145,848.12 | +$173,409.72 |
| Site × contract keys | 76 | | 71 mismatched |

**Root causes** (unexplained residual: 0 lines, $0.00):

| Cause | Lines | Count effect | Net amount effect | Gross amount | Site × contracts hit |
|---|---|---|---|---|---|
| MISSING | 40 | −40 | −$461,641.39 | $461,641.39 | 29 |
| DUPLICATE | 30 | +30 | +$247,184.67 | $247,184.67 | 24 |
| ROUNDING | 3,403 | 0 | +$24.72 | $57.96 | 12 |
| CODE_MAPPING | 30 | 0 | $0.00 | $752,152.40 | 6 |
| PERIOD_BOUNDARY | 193 | +27 | +$387,841.72 | $1,289,788.60 | 66 |

The net amounts tell only part of the story: code-mapping errors net to $0.00 for the
company as a whole, yet move $376k between contracts, which is exactly what a project manager
would see on their cost report. The small headline count difference (+17) also hides
123 lines absent from the report and 140 extra lines that largely cancel out.

**Worst site × contract keys** (excerpt):

| Site | Contract | Src lines | Rpt lines | Src amount | Rpt amount | Diff | Causes |
|---|---|---|---|---|---|---|---|
| S04 | CT-0403 | 219 | 233 | $1,542,687.50 | $1,710,511.17 | +$167,823.67 | CODE_MAPPING, DUPLICATE, PERIOD_BOUNDARY |
| S06 | CT-0607 | 309 | 298 | $2,908,019.80 | $2,770,673.42 | −$137,346.38 | CODE_MAPPING |
| S01 | CT-0104 | 325 | 333 | $3,052,031.19 | $3,186,867.97 | +$134,836.78 | CODE_MAPPING, PERIOD_BOUNDARY |
| S03 | CT-0308 | 211 | 210 | $1,693,138.71 | $1,567,497.00 | −$125,641.71 | PERIOD_BOUNDARY, ROUNDING |

**Exception samples** (one per cause):

| Cause | actual_id | Posted | Source key | Report key | Src amount | Rpt amount | Detail |
|---|---|---|---|---|---|---|---|
| CODE_MAPPING | 11197 | 2025-06-30 | S05/CT-0503 | S11/CT-1106 | $41,554.39 | $41,554.39 | S05/CT-0503 reported as S11/CT-1106 |
| DUPLICATE | 101 | 2025-03-01 | S01/CT-0101 | S01/CT-0101 | $715.99 | $715.99 | copy #2 of actual_id 101 |
| MISSING | 104 | 2025-05-19 | S01/CT-0101 | | $6,764.89 | | not found in report ledger |
| PERIOD_BOUNDARY | 25 | 2025-07-01 | S01/CT-0101 | S01/CT-0101 | $8,661.54 | $8,661.54 | posted 2025-07-01, outside 2025-01-01..2025-06-30, but reported |
| PERIOD_BOUNDARY | 262 | 2025-01-01 | S01/CT-0101 | | $1,587.73 | | posted 2025-01-01 (period edge); no report lines on that date |
| ROUNDING | 1539 | 2025-04-28 | S01/CT-0105 | S01/CT-0105 | $5,268.31 | $5,268.00 | diff −31 cents |

Accuracy against the answer key: **3,696 of 3,696 planted defects found, 0 false positives.**

## Limitations

- The `PERIOD_BOUNDARY` rule for *missing* lines is a heuristic: a whole edge date absent from
  the report points to the period filter. A single line lost on Jan 1 while other Jan 1 lines
  arrived is reported as `MISSING`.
- Matching relies on a stable line key (`actual_id`) being carried into the report. Without
  one, matching would need fuzzy keys (date + amount + contract), which this demo does not cover.
- Defects are planted so they do not overlap (except that a period-boundary error takes priority
  on any line it hits). Real data can stack several errors on one line.

## Project layout

```
recon/
  db.py          table definitions (SQLAlchemy Core), engine helper
  generate.py    synthetic data + faulty reporting ETL + answer key
  reconcile.py   aggregate SQL check, line classifier, effect/residual logic
  report.py      Markdown / HTML / CSV output
  __main__.py    CLI
tests/
  test_classify.py    unit tests on hand-built frames
  test_end_to_end.py  generate -> reconcile -> compare with answer key (SQLite, optional PostgreSQL)
reports/              output of the example run above
TASK.md               original task brief
```
