from bson import ObjectId

from scripts import grant_super_admin_role as script
from tests.test_roles_migration import FakeColl

G1, G2, G3 = ObjectId(), ObjectId(), ObjectId()


def _db():
    return {
        "groups": FakeColl([{"_id": G1, "owner": "me", "users": ["me"]},
                            {"_id": G2, "owner": "other", "users": ["me"]},
                            {"_id": G3, "owner": "other", "users": []}]),
        "Users": FakeColl([{"uid": "me", "groups": [str(G2)]}]),
        "Roles": FakeColl([]),
        "UserRoles": FakeColl([]),
    }


class OrFakeColl(FakeColl):
    """FakeColl plus the $or / membership matching the script uses on groups."""

    def find(self, filters=None, projection=None):
        if filters and "$or" in filters:
            out = []
            for d in self.docs:
                for cond in filters["$or"]:
                    (k, v), = cond.items()
                    val = d.get(k)
                    if val == v or (isinstance(val, list) and v in val):
                        out.append(dict(d))
                        break
            return out
        return super().find(filters, projection)


def test_plan_and_apply_are_idempotent():
    db = _db()
    db["groups"] = OrFakeColl(db["groups"].docs)
    p = script.plan(db, "me")
    assert p["create_role"] is True
    assert p["groups"] == sorted([str(G1), str(G2)])  # not G3: not a member
    script.apply(db, "me", p)
    role = db["Roles"].find_one({"value": "super_admin"})
    assert role["all_grants"] is True and role["assignable_by_group_admins"] is False
    assert len(db["UserRoles"].docs) == 2
    again = script.plan(db, "me")
    assert again["create_role"] is False and again["new_rows"] == []
    script.apply(db, "me", again)
    assert len(db["UserRoles"].docs) == 2
