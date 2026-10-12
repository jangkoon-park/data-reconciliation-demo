"""Reconcile the source actual-cost tables against the reporting mart.

Two levels:

1. **Aggregate check** (SQL): line count and amount per site x contract for the
   reporting period, source vs ``rpt_site_contract_summary``.
2. **Line-level drill-down** (pandas): match source lines and report ledger
   lines on ``actual_id`` and classify every difference into a cause.

Each classified exception carries its effect on the site x contract totals, so
the causes can be summed back and checked against the aggregate differences.
Anything the causes do not explain shows up as an ``UNEXPLAINED`` residual.

All money is handled as integer cents to avoid floating point noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from recon.generate import REPORT_END, REPORT_START

KEY = ["site_code", "contract_code"]

# Per-line amount gap (in cents) still treated as a rounding difference.
ROUNDING_TOLERANCE_CENTS = 50

CATEGORIES = {
    "MISSING": "Source line is in the period but absent from the report.",
    "DUPLICATE": "Same source line loaded into the report more than once.",
    "ROUNDING": "Line matched, amount differs by no more than $0.50.",
    "CODE_MAPPING": "Line matched, but reported under a different site/contract.",
    "PERIOD_BOUNDARY": "Line on the wrong side of the period cut-off (first/last day filter bug).",
    "AMOUNT_MISMATCH": "Line matched, amount differs by more than the rounding tolerance.",
    "UNMATCHED_REPORT_ROW": "Report line with no source line at all.",
}

SOURCE_AGG_SQL = """
SELECT c.site_code, c.contract_code, COUNT(*) AS src_count, SUM(a.amount) AS src_amount
FROM src_actual a
JOIN src_order o ON o.order_id = a.order_id
JOIN src_contract c ON c.contract_code = o.contract_code
WHERE a.posting_date BETWEEN :start AND :end
GROUP BY c.site_code, c.contract_code
"""

REPORT_AGG_SQL = """
SELECT site_code, contract_code, line_count AS rpt_count, total_amount AS rpt_amount
FROM rpt_site_contract_summary
"""

SOURCE_LINES_SQL = """
SELECT a.actual_id, c.site_code, c.contract_code, a.posting_date, a.amount
FROM src_actual a
JOIN src_order o ON o.order_id = a.order_id
JOIN src_contract c ON c.contract_code = o.contract_code
"""

REPORT_LINES_SQL = """
SELECT ledger_row_id, actual_id, site_code, contract_code, posting_date, amount
FROM rpt_cost_ledger
"""


@dataclass
class ReconResult:
    start: date
    end: date
    by_key: pd.DataFrame        # one row per site x contract
    exceptions: pd.DataFrame    # one row per classified line-level difference
    effects: pd.DataFrame       # exception effects on site x contract totals
    causes: pd.DataFrame        # one row per category

    @property
    def totals(self) -> dict[str, int]:
        s = self.by_key
        return {
            "src_count": int(s["src_count"].sum()),
            "rpt_count": int(s["rpt_count"].sum()),
            "src_amount_cents": int(s["src_amount_cents"].sum()),
            "rpt_amount_cents": int(s["rpt_amount_cents"].sum()),
            "keys_total": len(s),
            "keys_mismatched": int((s["status"] != "MATCH").sum()),
            "unexplained_count": int(s["unexplained_count"].abs().sum()),
            "unexplained_amount_cents": int(s["unexplained_amount_cents"].abs().sum()),
        }


def to_cents(values: pd.Series) -> pd.Series:
    """Convert NUMERIC (Decimal on PostgreSQL, float on SQLite) to int cents."""
    return (values.astype(float) * 100).round().astype("int64")


def _to_date(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values).dt.date


def classify_lines(src: pd.DataFrame, rpt: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Classify line-level differences between source and report.

    ``src`` and ``rpt`` need: actual_id, site_code, contract_code, posting_date
    (``datetime.date``) and amount_cents. ``src`` should hold *all* source
    lines, not only the reporting period, so that out-of-period report lines
    can be recognised as period-boundary errors rather than phantom rows.
    """
    cols = ["category", "actual_id", "posting_date", "src_site", "src_contract", "src_amount_cents",
            "rpt_site", "rpt_contract", "rpt_amount_cents", "src_in_period", "detail"]

    rpt = rpt.copy()
    rpt["copy_no"] = rpt.groupby("actual_id").cumcount()
    src_by_id = src.set_index("actual_id")

    # Duplicates: every copy after the first.
    extra = rpt[rpt["copy_no"] > 0]
    dups = pd.DataFrame({
        "category": "DUPLICATE",
        "actual_id": extra["actual_id"].to_numpy(),
        "posting_date": extra["posting_date"].to_numpy(),
        "src_site": extra["actual_id"].map(src_by_id["site_code"]).to_numpy(),
        "src_contract": extra["actual_id"].map(src_by_id["contract_code"]).to_numpy(),
        "src_amount_cents": extra["actual_id"].map(src_by_id["amount_cents"]).to_numpy(),
        "rpt_site": extra["site_code"].to_numpy(),
        "rpt_contract": extra["contract_code"].to_numpy(),
        "rpt_amount_cents": extra["amount_cents"].to_numpy(),
        "src_in_period": False,  # the source side is accounted for by the first copy
        "detail": [f"copy #{n + 1} of actual_id {a}" for n, a in zip(extra["copy_no"], extra["actual_id"])],
    })

    first = rpt[rpt["copy_no"] == 0]
    m = src.merge(first, on="actual_id", how="outer", suffixes=("_src", "_rpt"), indicator=True)
    m["src_in_period"] = (m["_merge"] != "right_only") & m["posting_date_src"].map(
        lambda d: isinstance(d, date) and start <= d <= end)
    report_dates = set(rpt["posting_date"])

    src_only = m["_merge"] == "left_only"
    rpt_only = m["_merge"] == "right_only"
    both = m["_merge"] == "both"
    key_differs = (m["site_code_src"] != m["site_code_rpt"]) | (m["contract_code_src"] != m["contract_code_rpt"])
    gap = (m["amount_cents_rpt"] - m["amount_cents_src"]).abs()

    # A missing line on the first/last day of the period, on a date for which the
    # report holds no lines at all, points to the period filter, not a lost row.
    on_edge_gap = m["posting_date_src"].map(lambda d: d in (start, end) and d not in report_dates)

    category = pd.Series(pd.NA, index=m.index, dtype="object")
    category[src_only & m["src_in_period"] & on_edge_gap] = "PERIOD_BOUNDARY"
    category[src_only & m["src_in_period"] & ~on_edge_gap] = "MISSING"
    category[rpt_only] = "UNMATCHED_REPORT_ROW"
    category[both & ~m["src_in_period"]] = "PERIOD_BOUNDARY"
    in_both = both & m["src_in_period"]
    category[in_both & key_differs] = "CODE_MAPPING"
    category[in_both & ~key_differs & (gap > 0) & (gap <= ROUNDING_TOLERANCE_CENTS)] = "ROUNDING"
    category[in_both & ~key_differs & (gap > ROUNDING_TOLERANCE_CENTS)] = "AMOUNT_MISMATCH"
    m["category"] = category

    m = m[m["category"].notna()].copy()
    details = {
        "MISSING": lambda r: "not found in report ledger",
        "PERIOD_BOUNDARY": lambda r: (f"posted {r.posting_date_src}, outside {start}..{end}, but reported"
                                      if not r.src_in_period
                                      else f"posted {r.posting_date_src} (period edge); no report lines on that date"),
        "UNMATCHED_REPORT_ROW": lambda r: "actual_id does not exist in source",
        "CODE_MAPPING": lambda r: f"{r.site_code_src}/{r.contract_code_src} reported as {r.site_code_rpt}/{r.contract_code_rpt}",
        "ROUNDING": lambda r: f"diff {int(r.amount_cents_rpt - r.amount_cents_src)} cents",
        "AMOUNT_MISMATCH": lambda r: f"diff {int(r.amount_cents_rpt - r.amount_cents_src)} cents",
    }
    matched = pd.DataFrame({
        "category": m["category"],
        "actual_id": m["actual_id"],
        "posting_date": m["posting_date_src"].where(m["posting_date_src"].notna(), m["posting_date_rpt"]),
        "src_site": m["site_code_src"],
        "src_contract": m["contract_code_src"],
        "src_amount_cents": m["amount_cents_src"],
        "rpt_site": m["site_code_rpt"],
        "rpt_contract": m["contract_code_rpt"],
        "rpt_amount_cents": m["amount_cents_rpt"],
        "src_in_period": m["src_in_period"].astype(bool),
        "detail": [details[r.category](r) for r in m.itertuples()],
    })

    parts = [df for df in (matched, dups) if not df.empty]
    if not parts:
        return pd.DataFrame(columns=cols).astype({"src_in_period": bool})
    out = pd.concat(parts, ignore_index=True)
    out = out[cols].sort_values(["category", "actual_id"], kind="stable").reset_index(drop=True)
    for c in ("src_amount_cents", "rpt_amount_cents"):
        out[c] = out[c].astype("Int64")
    return out


def exception_effects(exceptions: pd.DataFrame) -> pd.DataFrame:
    """Turn each exception into its effect on site x contract totals.

    Effect = report minus source. The source side counts only when the source
    line is inside the period (otherwise it was never in the source totals);
    the report side counts whenever the report row exists.
    """
    src = exceptions[exceptions["src_in_period"]]
    src_side = pd.DataFrame({
        "site_code": src["src_site"], "contract_code": src["src_contract"], "category": src["category"],
        "count_effect": -1, "amount_effect_cents": -src["src_amount_cents"].astype("int64"),
    })
    rpt = exceptions[exceptions["rpt_site"].notna()]
    rpt_side = pd.DataFrame({
        "site_code": rpt["rpt_site"], "contract_code": rpt["rpt_contract"], "category": rpt["category"],
        "count_effect": 1, "amount_effect_cents": rpt["rpt_amount_cents"].astype("int64"),
    })
    eff = pd.concat([src_side, rpt_side], ignore_index=True)
    return eff.groupby(KEY + ["category"], as_index=False)[["count_effect", "amount_effect_cents"]].sum()


def compare_aggregates(src_agg: pd.DataFrame, rpt_agg: pd.DataFrame, effects: pd.DataFrame) -> pd.DataFrame:
    """Site x contract comparison with differences split by cause."""
    df = src_agg.merge(rpt_agg, on=KEY, how="outer")
    for c in ("src_count", "rpt_count", "src_amount_cents", "rpt_amount_cents"):
        df[c] = df[c].fillna(0).astype("int64")
    df["count_diff"] = df["rpt_count"] - df["src_count"]
    df["amount_diff_cents"] = df["rpt_amount_cents"] - df["src_amount_cents"]

    explained = effects.groupby(KEY, as_index=False)[["count_effect", "amount_effect_cents"]].sum()
    df = df.merge(explained, on=KEY, how="left").fillna({"count_effect": 0, "amount_effect_cents": 0})
    df["unexplained_count"] = df["count_diff"] - df["count_effect"].astype("int64")
    df["unexplained_amount_cents"] = df["amount_diff_cents"] - df["amount_effect_cents"].astype("int64")
    df = df.drop(columns=["count_effect", "amount_effect_cents"])

    causes = (effects.groupby(KEY)["category"].agg(lambda s: ", ".join(sorted(set(s))))
              .rename("causes").reset_index())
    df = df.merge(causes, on=KEY, how="left")
    df["causes"] = df["causes"].fillna("")
    has_residual = (df["unexplained_count"] != 0) | (df["unexplained_amount_cents"] != 0)
    df.loc[has_residual, "causes"] = (df.loc[has_residual, "causes"] + ", UNEXPLAINED").str.lstrip(", ")
    df["status"] = "MATCH"
    df.loc[(df["count_diff"] != 0) | (df["amount_diff_cents"] != 0), "status"] = "MISMATCH"
    return df.sort_values(KEY).reset_index(drop=True)


def summarize_causes(exceptions: pd.DataFrame, effects: pd.DataFrame) -> pd.DataFrame:
    if exceptions.empty:
        return pd.DataFrame(columns=["category", "lines", "count_effect", "amount_effect_cents",
                                     "gross_amount_cents", "site_contracts", "description"])
    lines = exceptions.groupby("category").size().rename("lines")
    eff = effects.groupby("category")[["count_effect", "amount_effect_cents"]].sum()
    gross = effects.assign(g=effects["amount_effect_cents"].abs()).groupby("category")["g"].sum().rename("gross_amount_cents")
    keys = effects.groupby("category").apply(lambda g: len(g[KEY].drop_duplicates()), include_groups=False).rename("site_contracts")
    out = pd.concat([lines, eff, gross, keys], axis=1).reindex(list(CATEGORIES)).fillna(0).astype("int64")
    out["description"] = [CATEGORIES[c] for c in out.index]
    out = out[out["lines"] > 0]
    return out.rename_axis("category").reset_index()


def load_frames(engine: Engine, start: date, end: date) -> tuple[pd.DataFrame, ...]:
    params = {"start": start, "end": end}
    with engine.connect() as conn:
        src_agg = pd.read_sql(text(SOURCE_AGG_SQL), conn, params=params)
        rpt_agg = pd.read_sql(text(REPORT_AGG_SQL), conn)
        src = pd.read_sql(text(SOURCE_LINES_SQL), conn)
        rpt = pd.read_sql(text(REPORT_LINES_SQL), conn)
    src_agg["src_amount_cents"] = to_cents(src_agg.pop("src_amount"))
    rpt_agg["rpt_amount_cents"] = to_cents(rpt_agg.pop("rpt_amount"))
    for df in (src, rpt):
        df["amount_cents"] = to_cents(df.pop("amount"))
        df["posting_date"] = _to_date(df["posting_date"])
    return src_agg, rpt_agg, src, rpt


def reconcile(engine: Engine, start: date = REPORT_START, end: date = REPORT_END) -> ReconResult:
    src_agg, rpt_agg, src, rpt = load_frames(engine, start, end)
    exceptions = classify_lines(src, rpt, start, end)
    effects = exception_effects(exceptions)
    by_key = compare_aggregates(src_agg, rpt_agg, effects)
    causes = summarize_causes(exceptions, effects)
    return ReconResult(start, end, by_key, exceptions, effects, causes)
