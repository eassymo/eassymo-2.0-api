"""Phase 1 migration: give every role a grant set and keep today's access.

- Legacy roles (212, 213, 214, 215, 322, 324, 326, 327) become system roles with the
  grant sets approved in role-templates.csv (legacy.* rows).
- Role templates from the Excel are upserted as system roles (value = template id).
- "Miembro (legado)" is created and assigned to members that have no active role in a
  group, because today membership alone gives full marketplace access.

Usage:
  python -m scripts.migrate_roles_to_grants            # dry run, prints the report
  python -m scripts.migrate_roles_to_grants --apply    # writes
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone

from app.authz.legacy_roles import LEGACY_VALUE_TO_SET, role_data
from app.repositories.RolesRepository import value_variants

LEGACY_MEMBER = "legacy_member"
DELIVERY_ROLE = "215"


def _role_data():
    return role_data()


def _legacy_fields(grants):
    return {
        "grants": sorted(grants),
        "pov": "ambos",
        "entity_types": [],  # fits every business type, like today
        "function": "legacy",
        "is_system": True,
        "active": True,
    }


def _members_by_group(db):
    by_group = defaultdict(set)
    owners = {}
    for g in db["groups"].find({}, {"_id": 1, "users": 1, "owner": 1}):
        gid = str(g["_id"])
        by_group[gid].update(str(u) for u in (g.get("users") or []))
        if g.get("owner"):
            owners[gid] = str(g["owner"])
    for u in db["Users"].find({}, {"uid": 1, "groups": 1}):
        for gid in u.get("groups") or []:
            by_group[str(gid)].add(str(u["uid"]))
    for gid, owner in owners.items():
        by_group[gid].discard(owner)
    return by_group


def plan(db):
    data = _role_data()
    role_updates = {}

    existing = {str(r["value"]): r for r in db["Roles"].find({}, {"value": 1, "display": 1})}
    for value, set_id in LEGACY_VALUE_TO_SET.items():
        if value in existing:
            role_updates[value] = {
                **_legacy_fields(data[set_id]["grants"]),
                "assignable_by_group_admins": True,
            }

    role_updates[LEGACY_MEMBER] = {
        **_legacy_fields(data["legacy.standard"]["grants"]),
        "description": "Miembro (legado)",
        "display": False,
        "assignable_by_group_admins": False,
    }

    for rid, r in data.items():
        if r["kind"] != "template":
            continue
        role_updates[rid] = {
            "description": r["name"],
            "grants": sorted(r["grants"]),
            "pov": r["pov"],
            "entity_types": r["entity_types"],
            "function": r["function"],
            "assignable_by_group_admins": r["assignable"],
            "is_system": True,
            "active": True,
            "display": False,
        }

    active_rows = db["UserRoles"].find({"active": True}, {"user_uid": 1, "group": 1, "role": 1})
    roles_by_member = defaultdict(set)
    for row in active_rows:
        if row.get("group"):
            roles_by_member[(str(row["user_uid"]), str(row["group"]))].add(str(row["role"]))

    legacy_member_rows = []
    for gid, uids in sorted(_members_by_group(db).items()):
        for uid in sorted(uids):
            if not roles_by_member.get((uid, gid)):
                legacy_member_rows.append(
                    {"user_uid": uid, "group": gid, "role": LEGACY_MEMBER, "active": True}
                )

    non_admin_legacy = {"213", "214", "324", "326", "327"}
    delivery_plus_other = [
        {"uid": uid, "group": gid, "roles": sorted(roles)}
        for (uid, gid), roles in sorted(roles_by_member.items())
        if DELIVERY_ROLE in roles and roles & non_admin_legacy and not roles & {"212", "322"}
    ]

    return {
        "role_updates": role_updates,
        "legacy_member_rows": legacy_member_rows,
        "delivery_plus_other": delivery_plus_other,
    }


def apply(db, migration_plan):
    now = datetime.now(timezone.utc)
    for value, fields in migration_plan["role_updates"].items():
        update = {"$set": {**fields, "updated_at": now, "updated_by": "migration"}}
        # Legacy roles store `value` as a number; keep the stored form, never duplicate.
        existing = db["Roles"].find_one({"value": {"$in": value_variants([value])}}, {"_id": 1, "grants": 1})
        if existing and "grants" in existing:
            continue  # already migrated: never overwrite edits made in Accesos
        if existing:
            db["Roles"].update_one({"_id": existing["_id"]}, update)
        else:
            db["Roles"].update_one({"value": value}, update, upsert=True)
    rows = [{**r, "created_at": now} for r in migration_plan["legacy_member_rows"]]
    if rows:
        db["UserRoles"].insert_many(rows)


def report(migration_plan):
    lines = ["Roles to update:"]
    for value, f in sorted(migration_plan["role_updates"].items()):
        lines.append(f"  {value:28s} {len(f['grants']):3d} grants  assignable={f['assignable_by_group_admins']}")
    lines.append(f"Members getting '{LEGACY_MEMBER}': {len(migration_plan['legacy_member_rows'])}")
    lines.append(f"215 + non-admin role (gain access with the union rule): {len(migration_plan['delivery_plus_other'])}")
    for r in migration_plan["delivery_plus_other"]:
        lines.append(f"  uid={r['uid']} group={r['group']} roles={','.join(r['roles'])}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()

    from app.config import database
    db = database.db
    p = plan(db)
    print(report(p))
    if args.apply:
        apply(db, p)
        print("Applied.")
    else:
        print("Dry run: nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
