"""Database connection helpers and table definitions.

The demo targets PostgreSQL, but every query is written in portable SQL so the
same code also runs on SQLite (used by the test suite and as a fallback when
no PostgreSQL server is available).
"""

from __future__ import annotations

import os

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
)
from sqlalchemy.engine import Engine

DEFAULT_DB_URL = "postgresql+psycopg2://recon:recon@localhost:5432/recon_demo"

metadata = MetaData()

# --- Source system (ERP) -----------------------------------------------------

src_site = Table(
    "src_site",
    metadata,
    Column("site_code", String(8), primary_key=True),
    Column("site_name", String(80), nullable=False),
    Column("region", String(20), nullable=False),
)

src_contract = Table(
    "src_contract",
    metadata,
    Column("contract_code", String(16), primary_key=True),
    Column("site_code", String(8), ForeignKey("src_site.site_code"), nullable=False),
    Column("vendor_name", String(80), nullable=False),
    Column("cost_category", String(30), nullable=False),
    Column("contract_amount", Numeric(14, 2), nullable=False),
    # ERP = entered directly; LEGACY_SUB = arrives via the old subcontract feed
    Column("source_system", String(16), nullable=False),
)

src_order = Table(
    "src_order",
    metadata,
    Column("order_id", String(16), primary_key=True),
    Column("contract_code", String(16), ForeignKey("src_contract.contract_code"), nullable=False),
    Column("order_date", Date, nullable=False),
    Column("order_amount", Numeric(14, 2), nullable=False),
)

src_actual = Table(
    "src_actual",
    metadata,
    Column("actual_id", Integer, primary_key=True),
    Column("order_id", String(16), ForeignKey("src_order.order_id"), nullable=False),
    Column("cost_code", String(16), nullable=False),
    Column("posting_date", Date, nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
)

# --- Reporting mart ----------------------------------------------------------

# Line-level copy of actual costs as loaded by the reporting ETL.
# No primary key on actual_id on purpose: the faulty ETL can load duplicates.
rpt_cost_ledger = Table(
    "rpt_cost_ledger",
    metadata,
    Column("ledger_row_id", Integer, primary_key=True),
    Column("actual_id", Integer, nullable=False),
    Column("site_code", String(8), nullable=False),
    Column("contract_code", String(16), nullable=False),
    Column("posting_date", Date, nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
)

# The management report: totals per site x contract for the reporting period.
rpt_site_contract_summary = Table(
    "rpt_site_contract_summary",
    metadata,
    Column("site_code", String(8), primary_key=True),
    Column("contract_code", String(16), primary_key=True),
    Column("line_count", Integer, nullable=False),
    Column("total_amount", Numeric(16, 2), nullable=False),
)

# --- Answer key (demo only) --------------------------------------------------

# Records which defects the generator planted. The reconciler never reads it;
# tests use it to prove the reconciler finds exactly what was planted.
demo_injected_defect = Table(
    "demo_injected_defect",
    metadata,
    Column("actual_id", Integer, primary_key=True),
    Column("category", String(20), primary_key=True),
)


def get_engine(url: str | None = None) -> Engine:
    """Create an engine from an explicit URL, $RECON_DB_URL, or the default."""
    return create_engine(url or os.environ.get("RECON_DB_URL", DEFAULT_DB_URL))


def reset_schema(engine: Engine) -> None:
    metadata.drop_all(engine)
    metadata.create_all(engine)
