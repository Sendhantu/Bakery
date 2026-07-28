import argparse
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app  # noqa: E402
from services.finance_service import FinanceService, period_bounds  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "One-time backfill for missing sale FinancialTransaction rows on "
            "historical delivered and paid orders. Dry-run by default."
        )
    )
    parser.add_argument("--commit", action="store_true", help="Persist generated transactions.")
    parser.add_argument("--start-date", help="Inclusive order placed date, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Inclusive order placed date, YYYY-MM-DD.")
    parser.add_argument(
        "--config",
        default=os.environ.get("FLASK_ENV", "development"),
        choices=["development", "production", "testing"],
        help="Flask config name.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    os.environ["PORTAL_LAUNCHER_CHILD"] = "1"
    if args.config != "production":
        os.environ.setdefault("AUTO_INIT_DB", "true")
        os.environ.setdefault("SHOW_DEMO_ACCOUNTS", "false")
    app = create_app(args.config, portal_role="admin")
    with app.app_context():
        start = end = None
        if args.start_date or args.end_date:
            start, end = period_bounds(
                "custom",
                start_date=args.start_date,
                end_date=args.end_date,
            )

        result = FinanceService().backfill_missing_sale_transactions(
            start=start,
            end=end,
            commit=args.commit,
        )
        mode = "committed" if args.commit else "dry-run"
        print(
            f"Finance sale transaction backfill {mode}: "
            f"checked={result['checked']} created={result['created']}"
        )
        if result["order_ids"]:
            print("Order IDs:", ", ".join(str(order_id) for order_id in result["order_ids"]))
        if not args.commit:
            print("No changes saved. Re-run with --commit to persist these rows.")


if __name__ == "__main__":
    main()
