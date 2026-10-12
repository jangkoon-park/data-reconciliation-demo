"""Unit tests for the line-level classifier on hand-built frames."""

from datetime import date

import pandas as pd
import pytest

from recon.reconcile import classify_lines, compare_aggregates, exception_effects

START, END = date(2025, 1, 1), date(2025, 6, 30)


def frame(rows):
    return pd.DataFrame(rows, columns=["actual_id", "site_code", "contract_code", "posting_date", "amount_cents"])


def categories(exc):
    return sorted(zip(exc["actual_id"], exc["category"]))


def run(src_rows, rpt_rows):
    return classify_lines(frame(src_rows), frame(rpt_rows), START, END)


BASE = (1, "S01", "CT-0101", date(2025, 3, 10), 100_000)


def test_identical_data_has_no_exceptions():
    assert run([BASE], [BASE]).empty


def test_missing_row():
    exc = run([BASE, (2, "S01", "CT-0101", date(2025, 3, 11), 5_000)], [BASE])
    assert categories(exc) == [(2, "MISSING")]


def test_duplicate_row_counts_only_extra_copies():
    exc = run([BASE], [BASE, BASE, BASE])
    assert categories(exc) == [(1, "DUPLICATE"), (1, "DUPLICATE")]


def test_rounding_within_tolerance():
    exc = run([(1, "S01", "CT-0101", date(2025, 3, 10), 100_049)], [(1, "S01", "CT-0101", date(2025, 3, 10), 100_000)])
    assert categories(exc) == [(1, "ROUNDING")]


def test_amount_mismatch_beyond_tolerance():
    exc = run([BASE], [(1, "S01", "CT-0101", date(2025, 3, 10), 100_051)])
    assert categories(exc) == [(1, "AMOUNT_MISMATCH")]


def test_code_mapping():
    exc = run([BASE], [(1, "S02", "CT-0203", date(2025, 3, 10), 100_000)])
    assert categories(exc) == [(1, "CODE_MAPPING")]
    assert exc.loc[0, "detail"] == "S01/CT-0101 reported as S02/CT-0203"


def test_out_of_period_line_in_report_is_period_boundary():
    late = (2, "S01", "CT-0101", date(2025, 7, 1), 7_000)
    exc = run([BASE, late], [BASE, late])
    assert categories(exc) == [(2, "PERIOD_BOUNDARY")]


def test_missing_edge_day_with_no_report_lines_is_period_boundary():
    first_day = (2, "S01", "CT-0101", START, 7_000)
    exc = run([BASE, first_day], [BASE])
    assert categories(exc) == [(2, "PERIOD_BOUNDARY")]


def test_missing_edge_day_with_other_report_lines_is_missing():
    a = (2, "S01", "CT-0101", START, 7_000)
    b = (3, "S01", "CT-0101", START, 8_000)
    exc = run([BASE, a, b], [BASE, b])
    assert categories(exc) == [(2, "MISSING")]


def test_out_of_period_source_line_absent_from_report_is_ignored():
    assert run([BASE, (2, "S01", "CT-0101", date(2024, 12, 31), 1)], [BASE]).empty


def test_report_row_without_source():
    exc = run([BASE], [BASE, (99, "S01", "CT-0101", date(2025, 3, 10), 1)])
    assert categories(exc) == [(99, "UNMATCHED_REPORT_ROW")]


@pytest.fixture
def mixed():
    src = [
        BASE,
        (2, "S01", "CT-0101", date(2025, 2, 1), 20_000),   # missing
        (3, "S01", "CT-0101", date(2025, 2, 2), 30_000),   # duplicated
        (4, "S01", "CT-0102", date(2025, 2, 3), 40_049),   # rounded
        (5, "S01", "CT-0102", date(2025, 2, 4), 50_000),   # mapped to S02
        (6, "S02", "CT-0201", date(2025, 7, 1), 60_000),   # leaked in from July
    ]
    rpt = [
        BASE,
        (3, "S01", "CT-0101", date(2025, 2, 2), 30_000),
        (3, "S01", "CT-0101", date(2025, 2, 2), 30_000),
        (4, "S01", "CT-0102", date(2025, 2, 3), 40_000),
        (5, "S02", "CT-0201", date(2025, 2, 4), 50_000),
        (6, "S02", "CT-0201", date(2025, 7, 1), 60_000),
    ]
    return frame(src), frame(rpt)


def aggregate(df, prefix):
    g = df.groupby(["site_code", "contract_code"]).agg(n=("actual_id", "size"), a=("amount_cents", "sum")).reset_index()
    return g.rename(columns={"n": f"{prefix}_count", "a": f"{prefix}_amount_cents"})


def test_effects_explain_aggregate_differences_exactly(mixed):
    src, rpt = mixed
    exc = classify_lines(src, rpt, START, END)
    assert categories(exc) == [(2, "MISSING"), (3, "DUPLICATE"), (4, "ROUNDING"),
                               (5, "CODE_MAPPING"), (6, "PERIOD_BOUNDARY")]

    in_period = src[src["posting_date"].between(START, END)]
    by_key = compare_aggregates(aggregate(in_period, "src"), aggregate(rpt, "rpt"), exception_effects(exc))
    assert (by_key["unexplained_count"] == 0).all()
    assert (by_key["unexplained_amount_cents"] == 0).all()

    s02 = by_key.set_index(["site_code", "contract_code"]).loc[("S02", "CT-0201")]
    assert s02["amount_diff_cents"] == 110_000
    assert s02["causes"] == "CODE_MAPPING, PERIOD_BOUNDARY"


def test_unexplained_residual_is_flagged(mixed):
    src, rpt = mixed
    exc = classify_lines(src, rpt, START, END)
    in_period = src[src["posting_date"].between(START, END)]
    rpt_agg = aggregate(rpt, "rpt")
    rpt_agg.loc[0, "rpt_amount_cents"] += 1  # summary table drifted from its ledger
    by_key = compare_aggregates(aggregate(in_period, "src"), rpt_agg, exception_effects(exc))
    flagged = by_key[by_key["unexplained_amount_cents"] != 0]
    assert len(flagged) == 1
    assert flagged.iloc[0]["causes"].endswith("UNEXPLAINED")
