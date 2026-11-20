"""Create the "Super Admin" system role and give it to a user in every group they belong to.

The role has `all_grants: True`: in those groups the user holds every active grant, Eassymo
grants included, and grants added later too. It is not assignable from the app (nobody can
delegate it); only this script gives it. Idempotent.

Usage:
  python -m scripts.grant_super_admin_role --uid <firebase uid>           # dry run
  python -m scripts.grant_super_admin_role --uid <firebase uid> --apply   # writes
"""
import argparse
from datetime import datetime, timezone

SUPER_ADMIN = "super_admin"

ROLE_DOC = {
    "value": SUPER_ADMIN,
    "description": "Super Admin",
    "all_grants": True,
    "grants": [],
    "pov": "ambos",
    "entity_types": [],
    "function": "admin",
    "assignable_by_group_admins": False,
    "active": True,
    "is_system": True,
    "display": False,
}


def user_group_ids(db, uid: str):
    groups = {str(g["_id"]) for g in db["groups"].find({"$or": [{"owner": uid}, {"users": uid}]}, {"_id": 1})}
    for user in db["Users"].find({"uid": uid}, {"groups": 1}):
        groups.update(str(g.get("_id", g)) if isinstance(g, dict) else str(g) for g in user.get("groups") or [])
    return sorted(groups)


def plan(db, uid: str) -> dict:
    groups = user_group_ids(db, uid)
    has = {str(r["group"]) for r in db["UserRoles"].find(
        {"user_uid": uid, "role": SUPER_ADMIN, "active": True}, {"group": 1})}
    return {
        "create_role": db["Roles"].find_one({"value": SUPER_ADMIN}) is None,
        "groups": groups,
        "new_rows": [g for g in groups if g not in has],
    }


def apply(db, uid: str, p: dict) -> None:
    now = datetime.now(timezone.utc)
    db["Roles"].update_one(
        {"value": SUPER_ADMIN},
        {"$set": {**ROLE_DOC, "updated_at": now, "updated_by": "grant_super_admin_role"}},
        upsert=True,
    )
    rows = [{"user_uid": uid, "group": g, "role": SUPER_ADMIN, "active": True, "created_at": now} for g in p["new_rows"]]
    if rows:
        db["UserRoles"].insert_many(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from app.config import database

    p = plan(database.db, args.uid)
    print(f"role super_admin: {'create' if p['create_role'] else 'exists (refresh fields)'}")
    print(f"groups of user: {len(p['groups'])}; new Super Admin assignments: {len(p['new_rows'])}")
    for g in p["new_rows"]:
        print(f"  + {g}")
    if args.apply:
        apply(database.db, args.uid, p)
        print("Applied.")
    else:
        print("Dry run: nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
