"""Give every grant its `frame_refs` (list of frame codes) from the approved frames catalog.

Replaces the old single `frame_ref`. Idempotent: grants that already have `frame_refs`
(migrated, or edited in Accesos) are left alone.
Usage: python -m scripts.migrate_frame_refs [--apply]
"""
import argparse

from scripts.seed_frames import load_catalog


def frame_refs_by_grant(catalog):
    refs = {}
    for frame in catalog:
        for key in frame["grants"]:
            refs.setdefault(key, []).append(frame["code"])
    return refs


def apply(db, catalog, write: bool = True) -> int:
    refs = frame_refs_by_grant(catalog)
    changed = 0
    for grant in list(db["grants"].find({})):
        if "frame_refs" in grant:
            continue
        changed += 1
        if write:
            db["grants"].update_one(
                {"key": grant["key"]},
                {"$set": {"frame_refs": refs.get(grant["key"], [])}, "$unset": {"frame_ref": ""}},
            )
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()
    from app.config import database

    n = apply(database.db, load_catalog(), write=args.apply)
    print(f"grants needing frame_refs: {n}" + ("" if args.apply else " (dry run, nothing written)"))


if __name__ == "__main__":
    main()
