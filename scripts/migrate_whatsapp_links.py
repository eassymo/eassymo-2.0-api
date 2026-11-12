"""
Migrate legacy users.pos_whatsapp into per-group WhatsappLinks.

Dry run by default (writes nothing). Run from repo root with MONGO_URI in .env:
  python scripts/migrate_whatsapp_links.py            # dry run
  python scripts/migrate_whatsapp_links.py --apply    # write links
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.WhatsappLinkMigrationService import migrate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write links (default: dry run)")
    args = parser.parse_args()

    report = migrate(apply=args.apply)
    mode = "APPLY" if args.apply else "DRY RUN"
    c, e = ("created", "existing") if args.apply else ("would_create", "would_exist")
    print(f"[{mode}] {c}={report['created']} {e}={report['existing']}")
    print(f"invalid_phones={len(report['invalid_phones'])}: {report['invalid_phones']}")
    print(f"phone_conflicts={len(report['phone_conflicts'])}: {report['phone_conflicts']}")
    print(f"skipped_no_access={len(report['skipped_no_access'])}")
    for item in report["skipped_no_access"]:
        print(f"  uid={item['uid']} group={item['group_id']} reason={item['reason']}")


if __name__ == "__main__":
    main()
