"""Render a ReconResult as Markdown and HTML."""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from recon.reconcile import CATEGORIES, ReconResult

SAMPLES_PER_CATEGORY = 5
TOP_KEYS = 15


def money(cents, signed: bool = False) -> str:
    if cents is None or pd.isna(cents):
        return ""
    cents = int(cents)
    sign = "-" if cents < 0 else ("+" if signed and cents > 0 else "")
    return f"{sign}${abs(cents) / 100:,.2f}"


def signed_int(n) -> str:
    n = int(n)
    return f"+{n:,}" if n > 0 else f"{n:,}"


def _tables(r: ReconResult) -> list[tuple[str, str, pd.DataFrame]]:
    """(title, intro, table) blocks shared by both renderers."""
    t = r.totals
    headline = pd.DataFrame([
        ["Line count", f"{t['src_count']:,}", f"{t['rpt_count']:,}", signed_int(t["rpt_count"] - t["src_count"])],
        ["Amount", money(t["src_amount_cents"]), money(t["rpt_amount_cents"]),
         money(t["rpt_amount_cents"] - t["src_amount_cents"], signed=True)],
        ["Site x contract keys", f"{t['keys_total']:,}", "",
         f"{t['keys_mismatched']:,} mismatched"],
    ], columns=["Metric", "Source", "Report", "Difference (report - source)"])

    causes = pd.DataFrame({
        "Cause": r.causes["category"],
        "Lines": r.causes["lines"].map("{:,}".format),
        "Count effect": r.causes["count_effect"].map(signed_int),
        "Net amount effect": r.causes["amount_effect_cents"].map(lambda c: money(c, signed=True)),
        "Gross amount": r.causes["gross_amount_cents"].map(money),
        "Site x contracts hit": r.causes["site_contracts"],
        "What it means": r.causes["description"],
    })

    mism = r.by_key[r.by_key["status"] != "MATCH"].copy()
    mism = mism.reindex(mism["amount_diff_cents"].abs().sort_values(ascending=False).index).head(TOP_KEYS)
    keys = pd.DataFrame({
        "Site": mism["site_code"], "Contract": mism["contract_code"],
        "Src lines": mism["src_count"].map("{:,}".format), "Rpt lines": mism["rpt_count"].map("{:,}".format),
        "Src amount": mism["src_amount_cents"].map(money), "Rpt amount": mism["rpt_amount_cents"].map(money),
        "Diff": mism["amount_diff_cents"].map(lambda c: money(c, signed=True)),
        "Causes": mism["causes"],
    })

    ex = r.exceptions
    samples = ex.groupby("category", sort=False).head(SAMPLES_PER_CATEGORY)
    sample_tbl = pd.DataFrame({
        "Cause": samples["category"], "actual_id": samples["actual_id"], "Posted": samples["posting_date"].astype(str),
        "Source key": (samples["src_site"].fillna("") + "/" + samples["src_contract"].fillna("")).str.strip("/"),
        "Report key": (samples["rpt_site"].fillna("") + "/" + samples["rpt_contract"].fillna("")).str.strip("/"),
        "Src amount": samples["src_amount_cents"].map(money), "Rpt amount": samples["rpt_amount_cents"].map(money),
        "Detail": samples["detail"],
    })

    residual = (f"Causes explain **all** differences: unexplained count = {t['unexplained_count']}, "
                f"unexplained amount = {money(t['unexplained_amount_cents'])}."
                if t["unexplained_count"] == 0 and t["unexplained_amount_cents"] == 0 else
                f"**Warning:** {t['unexplained_count']} lines / {money(t['unexplained_amount_cents'])} "
                "not explained by any cause - investigate keys tagged UNEXPLAINED.")

    return [
        ("Headline", f"Reporting period **{r.start} to {r.end}**. Source = ERP actual costs; "
                     "report = `rpt_site_contract_summary`.", headline),
        ("Root causes", residual, causes),
        (f"Mismatched site x contract keys (top {TOP_KEYS} by amount)",
         f"{t['keys_mismatched']} of {t['keys_total']} keys differ. The full list is in "
         "`site_contract_comparison.csv`.", keys),
        (f"Exception samples (up to {SAMPLES_PER_CATEGORY} per cause)",
         f"{len(ex):,} line-level exceptions in total. The full list is in `exceptions.csv`.", sample_tbl),
    ]


def _md_table(df: pd.DataFrame) -> str:
    rows = [list(map(str, df.columns))] + df.astype(str).values.tolist()
    rows = [[c.replace("|", "\\|") for c in row] for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join("---" for _ in rows[0]) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def to_markdown(r: ReconResult) -> str:
    parts = ["# Cost Data Reconciliation Report", ""]
    for title, intro, df in _tables(r):
        parts += [f"## {title}", "", intro, "", _md_table(df), ""]
    return "\n".join(parts)


def _md_inline(s: str) -> str:
    s = html.escape(s)
    while "**" in s:
        s = s.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
    while "`" in s:
        s = s.replace("`", "<code>", 1).replace("`", "</code>", 1)
    return s


HTML_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cost Reconciliation Report</title>
<style>
:root { --bg:#fff; --fg:#1f2328; --muted:#59636e; --line:#d1d9e0; --head:#f6f8fa; --bad:#b42318; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#3d444d; --head:#151b23; --bad:#ff7b72; } }
body { background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, sans-serif; margin:0 auto;
       max-width:1200px; padding:24px 16px; }
h1 { font-size:24px; } h2 { font-size:18px; margin-top:32px; } p { color:var(--muted); }
.wrap { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { border-bottom:1px solid var(--line); padding:6px 10px; text-align:left; white-space:nowrap; }
th { background:var(--head); font-weight:600; } td:last-child { white-space:normal; }
code { font-size:12px; }
</style></head><body>
<h1>Cost Data Reconciliation Report</h1>
"""


def to_html(r: ReconResult) -> str:
    parts = [HTML_HEAD]
    for title, intro, df in _tables(r):
        parts.append(f"<h2>{html.escape(title)}</h2>\n<p>{_md_inline(intro)}</p>")
        parts.append('<div class="wrap">' + df.to_html(index=False, border=0, escape=True) + "</div>")
    parts.append("</body></html>\n")
    return "\n".join(parts)


def write_reports(r: ReconResult, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "md": out / "reconciliation_report.md",
        "html": out / "reconciliation_report.html",
        "exceptions": out / "exceptions.csv",
        "keys": out / "site_contract_comparison.csv",
    }
    paths["md"].write_text(to_markdown(r), encoding="utf-8")
    paths["html"].write_text(to_html(r), encoding="utf-8")
    r.exceptions.to_csv(paths["exceptions"], index=False)
    r.by_key.to_csv(paths["keys"], index=False)
    return list(paths.values())


__all__ = ["CATEGORIES", "to_markdown", "to_html", "write_reports"]
