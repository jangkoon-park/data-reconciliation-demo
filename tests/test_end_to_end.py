"""End-to-end: generate data into a real database, reconcile, check the answer key.

Runs on SQLite always. Set RECON_TEST_PG_URL to also run against PostgreSQL,
e.g. postgresql+psycopg2://recon:recon@localhost:5432/recon_test
"""

import os

import pandas as pd
import pytest
from sqlalchemy import create_engine

from recon.generate import GenConfig, generate
from recon.reconcile import reconcile
from recon.report import to_html, to_markdown, write_reports

SMALL = GenConfig(seed=7, n_sites=6, target_actuals=4_000, n_missing=12, n_duplicate=9)

BACKENDS = ["sqlite"] + (["postgresql"] if os.environ.get("RECON_TEST_PG_URL") else [])


@pytest.fixture(scope="module", params=BACKENDS)
def run(request, tmp_path_factory):
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path_factory.mktemp('db') / 'recon.db'}"
    else:
        url = os.environ["RECON_TEST_PG_URL"]
    engine = create_engine(url)
    ds = generate(engine, SMALL)
    yield ds, reconcile(engine)
    engine.dispose()


def test_every_planted_defect_is_found_and_nothing_else(run):
    ds, result = run
    expected = set(map(tuple, ds.defects[["actual_id", "category"]].itertuples(index=False)))
    found = set(map(tuple, result.exceptions[["actual_id", "category"]].itertuples(index=False)))
    assert found == expected


def test_all_five_defect_types_are_present(run):
    _, result = run
    assert {"MISSING", "DUPLICATE", "ROUNDING", "CODE_MAPPING", "PERIOD_BOUNDARY"} <= set(result.causes["category"])
    assert "AMOUNT_MISMATCH" not in set(result.causes["category"])
    assert "UNMATCHED_REPORT_ROW" not in set(result.causes["category"])


def test_duplicate_and_missing_counts(run):
    _, result = run
    lines = result.causes.set_index("category")["lines"]
    assert lines["MISSING"] == SMALL.n_missing
    assert lines["DUPLICATE"] == SMALL.n_duplicate


def test_causes_fully_explain_aggregate_differences(run):
    _, result = run
    t = result.totals
    assert t["unexplained_count"] == 0
    assert t["unexplained_amount_cents"] == 0
    assert t["keys_mismatched"] > 0
    net = result.causes["amount_effect_cents"].sum()
    assert net == t["rpt_amount_cents"] - t["src_amount_cents"]


def test_reports_render(run, tmp_path):
    _, result = run
    md = to_markdown(result)
    assert "## Root causes" in md and "PERIOD_BOUNDARY" in md
    assert "<table" in to_html(result)
    paths = write_reports(result, tmp_path)
    assert all(p.exists() for p in paths)
    assert len(pd.read_csv(tmp_path / "exceptions.csv")) == len(result.exceptions)
