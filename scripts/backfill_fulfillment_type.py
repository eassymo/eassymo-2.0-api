"""
One-off backfill: set fulfillment_type to 'delivery' on PartRequests missing the field.

Run from repo root with MONGO_URI in .env:
  python scripts/backfill_fulfillment_type.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.database import db  # noqa: E402


def main() -> None:
    result = db["PartRequests"].update_many(
        {"fulfillment_type": {"$exists": False}},
        {"$set": {"fulfillment_type": "delivery"}},
    )
    print(
        f"PartRequests matched={result.matched_count} modified={result.modified_count}"
    )


if __name__ == "__main__":
    main()
