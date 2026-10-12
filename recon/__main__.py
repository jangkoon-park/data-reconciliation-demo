"""Command line entry point.

    python -m recon generate     # build synthetic data + faulty report
    python -m recon reconcile    # compare source vs report, write reports/
    python -m recon all          # both
"""

from __future__ import annotations

import argparse
import time

from recon.db import get_engine
from recon.generate import GenConfig, generate
from recon.reconcile import reconcile
from recon.report import money, write_reports


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="recon", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["generate", "reconcile", "all"])
    p.add_argument("--db-url", help="SQLAlchemy URL (default: $RECON_DB_URL or local PostgreSQL)")
    p.add_argument("--out", default="reports", help="output directory for reports")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rows", type=int, default=30_000, help="approx. number of source actual-cost lines")
    args = p.parse_args(argv)
    if args.rows > 100_000:
        p.error("--rows is capped at 100,000 for this demo")

    engine = get_engine(args.db_url)
    print(f"database: {engine.url.render_as_string(hide_password=True)}")

    if args.command in ("generate", "all"):
        t0 = time.perf_counter()
        ds = generate(engine, GenConfig(seed=args.seed, target_actuals=args.rows))
        print(f"generated {len(ds.sites)} sites, {len(ds.contracts)} contracts, {len(ds.orders):,} orders, "
              f"{len(ds.actuals):,} actuals, {len(ds.ledger):,} report lines "
              f"({len(ds.defects):,} planted defects) in {time.perf_counter() - t0:.1f}s")

    if args.command in ("reconcile", "all"):
        t0 = time.perf_counter()
        result = reconcile(engine)
        paths = write_reports(result, args.out)
        t = result.totals
        print(f"reconciled in {time.perf_counter() - t0:.1f}s: {t['keys_mismatched']}/{t['keys_total']} keys mismatched, "
              f"{len(result.exceptions):,} exceptions, unexplained {t['unexplained_count']} lines / "
              f"{money(t['unexplained_amount_cents'])}")
        for _, row in result.causes.iterrows():
            print(f"  {row['category']:<16} {row['lines']:>6,} lines  net {money(row['amount_effect_cents'], signed=True)}")
        for path in paths:
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
