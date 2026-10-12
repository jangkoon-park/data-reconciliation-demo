"""Generate a fully synthetic construction-cost dataset and a faulty report.

Nothing here is derived from real company data: site names, vendors, codes and
amounts are produced by a seeded random generator.

Pipeline
--------
1. Build the source tables: sites -> contracts -> orders -> actual costs.
2. Run a deliberately buggy "reporting ETL" that copies actuals into
   ``rpt_cost_ledger`` and plants five kinds of defects.
3. Build ``rpt_site_contract_summary`` from the ledger with plain SQL, the
   way a reporting job would.
4. Store the planted defects in ``demo_injected_defect`` (answer key).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from recon import db

REPORT_START = date(2025, 1, 1)
REPORT_END = date(2025, 6, 30)

# Source data covers a wider range than the report so the window filter matters.
DATA_START = date(2024, 11, 1)
DATA_END = date(2025, 8, 31)

REGIONS = ["North", "South", "East", "West", "Central"]
SITE_NAMES = [
    "Riverside Logistics Center", "Maple Hill Apartments", "Harbor View Office Tower",
    "Pinecrest Elementary School", "Granite Bridge Overpass", "Sunfield Solar Plant",
    "Lakeshore Medical Clinic", "Oakridge Data Center", "Westgate Shopping Arcade",
    "Silverline Metro Depot", "Cedar Park Community Hall", "Bluewater Treatment Plant",
    "Northpoint Parking Structure", "Elmwood Senior Housing", "Ironworks Warehouse",
]
VENDOR_PREFIXES = [
    "Apex", "Summit", "Keystone", "Bedrock", "Northstar", "Ironclad", "Cornerstone",
    "Pioneer", "Atlas", "Trident", "Evergreen", "Redline", "Bluestone", "Vanguard",
]
COST_CATEGORIES = {
    "Concrete": "CON", "Structural Steel": "STL", "MEP": "MEP",
    "Earthwork": "EWK", "Finishing": "FIN", "Equipment Rental": "EQP",
}
VENDOR_SUFFIX = {
    "Concrete": "Concrete Works", "Structural Steel": "Steel Fabricators",
    "MEP": "Mechanical & Electric", "Earthwork": "Excavation", "Finishing": "Interiors",
    "Equipment Rental": "Equipment Hire",
}


@dataclass(frozen=True)
class GenConfig:
    seed: int = 42
    n_sites: int = 12
    contracts_per_site: tuple[int, int] = (5, 8)
    orders_per_contract: tuple[int, int] = (12, 30)
    target_actuals: int = 30_000
    legacy_contract_share: float = 0.15
    n_missing: int = 40
    n_duplicate: int = 30
    n_mismapped_orders: int = 3


@dataclass
class Dataset:
    sites: pd.DataFrame
    contracts: pd.DataFrame
    orders: pd.DataFrame
    actuals: pd.DataFrame
    ledger: pd.DataFrame
    defects: pd.DataFrame


def _random_dates(rng: np.random.Generator, start: date, end: date, n: int) -> list[date]:
    offsets = rng.integers(0, (end - start).days + 1, size=n)
    return [start + timedelta(days=int(o)) for o in offsets]


def build_source(cfg: GenConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)

    site_idx = rng.choice(len(SITE_NAMES), size=cfg.n_sites, replace=False)
    sites = pd.DataFrame({
        "site_code": [f"S{i + 1:02d}" for i in range(cfg.n_sites)],
        "site_name": [SITE_NAMES[i] for i in site_idx],
        "region": rng.choice(REGIONS, size=cfg.n_sites),
    })

    contract_rows = []
    for site_code in sites["site_code"]:
        n = int(rng.integers(cfg.contracts_per_site[0], cfg.contracts_per_site[1] + 1))
        for k in range(n):
            category = str(rng.choice(list(COST_CATEGORIES)))
            contract_rows.append({
                "contract_code": f"CT-{site_code[1:]}{k + 1:02d}",
                "site_code": site_code,
                "vendor_name": f"{rng.choice(VENDOR_PREFIXES)} {VENDOR_SUFFIX[category]}",
                "cost_category": category,
                "source_system": "LEGACY_SUB" if rng.random() < cfg.legacy_contract_share else "ERP",
            })
    contracts = pd.DataFrame(contract_rows)

    order_rows = []
    for contract_code in contracts["contract_code"]:
        n = int(rng.integers(cfg.orders_per_contract[0], cfg.orders_per_contract[1] + 1))
        for _ in range(n):
            order_rows.append({"order_id": f"PO-{len(order_rows) + 1:06d}", "contract_code": contract_code})
    orders = pd.DataFrame(order_rows)
    orders["order_date"] = _random_dates(rng, DATA_START - timedelta(days=60), DATA_END - timedelta(days=30), len(orders))

    # Spread actual cost lines across orders (Poisson around the target mean).
    lines_per_order = rng.poisson(cfg.target_actuals / len(orders), size=len(orders)).clip(min=1)
    n_actuals = int(lines_per_order.sum())
    order_ids = np.repeat(orders["order_id"].to_numpy(), lines_per_order)
    contract_of_order = orders.set_index("order_id")["contract_code"]
    category_of_contract = contracts.set_index("contract_code")["cost_category"]
    prefixes = category_of_contract.loc[contract_of_order.loc[order_ids]].map(COST_CATEGORIES).to_numpy()

    # Log-normal line amounts in USD cents: mostly hundreds to tens of thousands.
    cents = np.clip(np.round(rng.lognormal(mean=np.log(450_000), sigma=1.1, size=n_actuals)), 5_000, 25_000_000)
    actuals = pd.DataFrame({
        "actual_id": np.arange(1, n_actuals + 1),
        "order_id": order_ids,
        "cost_code": [f"{p}-{int(c):03d}" for p, c in zip(prefixes, rng.integers(100, 400, size=n_actuals))],
        "posting_date": _random_dates(rng, DATA_START, DATA_END, n_actuals),
        "amount_cents": cents.astype("int64"),
    })

    # Order and contract amounts are consistent with the actuals (plus headroom).
    spent = actuals.groupby("order_id")["amount_cents"].sum()
    orders["order_amount_cents"] = (orders["order_id"].map(spent).fillna(0) * rng.uniform(1.0, 1.25, len(orders))).round().astype("int64")
    committed = orders.groupby("contract_code")["order_amount_cents"].sum()
    contracts["contract_amount_cents"] = (contracts["contract_code"].map(committed) * rng.uniform(1.05, 1.3, len(contracts))).round().astype("int64")
    return sites, contracts, orders, actuals


def source_lines(contracts: pd.DataFrame, orders: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Denormalised actual-cost lines: one row per actual with site/contract."""
    lines = actuals.merge(orders[["order_id", "contract_code"]], on="order_id")
    return lines.merge(contracts[["contract_code", "site_code", "source_system"]], on="contract_code")


def run_faulty_etl(lines: pd.DataFrame, cfg: GenConfig, start: date = REPORT_START,
                   end: date = REPORT_END) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Copy source lines into the report ledger, planting defects on purpose.

    Returns (ledger, defects). ``defects`` is the answer key: one row per
    (actual_id, category). When a line is hit by the period-boundary bug that
    label wins, because the whole line is in the wrong period anyway.
    """
    rng = np.random.default_rng(cfg.seed + 1)
    defects: list[tuple[int, str]] = []
    in_window = (lines["posting_date"] >= start) & (lines["posting_date"] <= end)

    # Defect 5 - period boundary: the ETL filters with "> start AND <= end + 1 day"
    # instead of "BETWEEN start AND end". First day is dropped, the day after the
    # period leaks in.
    buggy_window = (lines["posting_date"] > start) & (lines["posting_date"] <= end + timedelta(days=1))
    for aid in lines.loc[in_window != buggy_window, "actual_id"]:
        defects.append((int(aid), "PERIOD_BOUNDARY"))
    ledger = lines.loc[buggy_window].copy()
    boundary_ids = set(lines.loc[in_window != buggy_window, "actual_id"])

    # Clean candidates for the random defects: correctly in-window ERP lines.
    edge_dates = {start, end, end + timedelta(days=1)}
    clean = ledger[(ledger["source_system"] == "ERP") & ~ledger["posting_date"].isin(edge_dates)]

    # Defect 4 - wrong code mapping: a stale crosswalk sends every line of a few
    # orders to a different contract (sometimes at a different site).
    all_contracts = lines[["contract_code", "site_code"]].drop_duplicates()
    mis_orders = rng.choice(clean["order_id"].unique(), size=cfg.n_mismapped_orders, replace=False)
    for order_id in mis_orders:
        mask = ledger["order_id"] == order_id
        current = ledger.loc[mask, "contract_code"].iloc[0]
        target = all_contracts[all_contracts["contract_code"] != current].sample(1, random_state=int(rng.integers(1 << 31))).iloc[0]
        ledger.loc[mask, ["contract_code", "site_code"]] = [target["contract_code"], target["site_code"]]
        for aid in ledger.loc[mask, "actual_id"]:
            if aid not in boundary_ids:
                defects.append((int(aid), "CODE_MAPPING"))
    clean = clean[~clean["order_id"].isin(mis_orders)]

    # Defect 1 - missing rows: lines silently dropped (e.g. a failed batch).
    missing_ids = rng.choice(clean["actual_id"], size=cfg.n_missing, replace=False)
    ledger = ledger[~ledger["actual_id"].isin(missing_ids)]
    defects += [(int(a), "MISSING") for a in missing_ids]
    clean = clean[~clean["actual_id"].isin(missing_ids)]

    # Defect 2 - duplicate rows: a batch re-delivered and loaded twice.
    dup_ids = rng.choice(clean["actual_id"], size=cfg.n_duplicate, replace=False)
    ledger = pd.concat([ledger, ledger[ledger["actual_id"].isin(dup_ids)]], ignore_index=True)
    defects += [(int(a), "DUPLICATE") for a in dup_ids]

    # Defect 3 - rounding: the legacy subcontract feed rounds to whole dollars
    # (half-up) before loading, so each line is off by up to $0.50.
    legacy = ledger["source_system"] == "LEGACY_SUB"
    rounded = ((ledger.loc[legacy, "amount_cents"] + 50) // 100) * 100
    changed = ledger.loc[legacy].index[rounded != ledger.loc[legacy, "amount_cents"]]
    ledger.loc[legacy, "amount_cents"] = rounded
    for aid in ledger.loc[changed, "actual_id"]:
        if aid not in boundary_ids:
            defects.append((int(aid), "ROUNDING"))

    ledger = ledger.sort_values(["posting_date", "actual_id"], kind="stable").reset_index(drop=True)
    ledger["ledger_row_id"] = np.arange(1, len(ledger) + 1)
    ledger = ledger[["ledger_row_id", "actual_id", "site_code", "contract_code", "posting_date", "amount_cents"]]
    defect_df = pd.DataFrame(defects, columns=["actual_id", "category"]).drop_duplicates()
    return ledger, defect_df


def build_dataset(cfg: GenConfig = GenConfig()) -> Dataset:
    sites, contracts, orders, actuals = build_source(cfg)
    ledger, defects = run_faulty_etl(source_lines(contracts, orders, actuals), cfg)
    return Dataset(sites, contracts, orders, actuals, ledger, defects)


def _money(df: pd.DataFrame, cents_col: str, out_col: str) -> pd.DataFrame:
    """Swap an integer-cents column for a dollars column ready for NUMERIC(14,2)."""
    out = df.drop(columns=[cents_col])
    out[out_col] = df[cents_col] / 100
    return out


SUMMARY_SQL = """
INSERT INTO rpt_site_contract_summary (site_code, contract_code, line_count, total_amount)
SELECT site_code, contract_code, COUNT(*), SUM(amount)
FROM rpt_cost_ledger
GROUP BY site_code, contract_code
"""


def load(engine: Engine, ds: Dataset) -> None:
    db.reset_schema(engine)
    opts = dict(if_exists="append", index=False, chunksize=2_000, method="multi")
    with engine.begin() as conn:
        ds.sites.to_sql("src_site", conn, **opts)
        _money(ds.contracts, "contract_amount_cents", "contract_amount").to_sql("src_contract", conn, **opts)
        _money(ds.orders, "order_amount_cents", "order_amount").to_sql("src_order", conn, **opts)
        _money(ds.actuals, "amount_cents", "amount").to_sql("src_actual", conn, **opts)
        _money(ds.ledger, "amount_cents", "amount").to_sql("rpt_cost_ledger", conn, **opts)
        conn.execute(text(SUMMARY_SQL))
        ds.defects.to_sql("demo_injected_defect", conn, **opts)


def generate(engine: Engine, cfg: GenConfig = GenConfig()) -> Dataset:
    ds = build_dataset(cfg)
    load(engine, ds)
    return ds
