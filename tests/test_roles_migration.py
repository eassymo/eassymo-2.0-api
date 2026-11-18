from bson import ObjectId

from scripts import migrate_roles_to_grants as mig


class FakeColl:
    def __init__(self, docs=None):
        self.docs = [{"_id": ObjectId(), **d} for d in (docs or [])]

    @staticmethod
    def _match(doc, filters):
        for k, v in filters.items():
            if isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    def find(self, filters=None, projection=None):
        return [dict(d) for d in self.docs if self._match(d, filters or {})]

    def find_one(self, filters=None, projection=None):
        found = self.find(filters)
        return found[0] if found else None

    def update_one(self, filters, update, upsert=False):
        for d in self.docs:
            if self._match(d, filters):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({"_id": ObjectId(), **filters, **update.get("$set", {}), **update.get("$setOnInsert", {})})

    def insert_many(self, docs):
        self.docs.extend(dict(d) for d in docs)


G1 = ObjectId()


def _db(user_roles=None, roles=None, groups=None, users=None):
    return {
        "Roles": FakeColl(roles or [{"value": "212"}, {"value": "213"}, {"value": "215"}]),
        "UserRoles": FakeColl(user_roles or []),
        "groups": FakeColl(groups or [{"_id": G1, "owner": "o", "users": ["a", "b"], "type": 1}]),
        "Users": FakeColl(users or []),
    }


def test_plan_maps_legacy_values_to_sets():
    plan = mig.plan(_db())
    assert "whatsapp.create_draft" in plan["role_updates"]["212"]["grants"]
    assert set(plan["role_updates"]["215"]["grants"]) == {"deliveries.perform", "chat.private"}
    assert plan["role_updates"]["212"]["is_system"] is True
    assert plan["role_updates"]["212"]["assignable_by_group_admins"] is True
    assert plan["role_updates"]["212"]["entity_types"] == []
    assert "store.edit_profile" in plan["role_updates"]["212"]["grants"]
    assert "team.assign_roles" not in plan["role_updates"]["212"]["grants"]


def test_plan_seeds_templates_and_legacy_member():
    plan = mig.plan(_db())
    assert "tpl.v.admin" in plan["role_updates"]
    member = plan["role_updates"][mig.LEGACY_MEMBER]
    assert member["assignable_by_group_admins"] is False
    assert member["display"] is False
    assert not any(k.startswith("eassymo.") for r in plan["role_updates"].values() for k in r["grants"])


def test_plan_adds_legacy_member_for_member_without_active_role():
    db = _db(user_roles=[{"user_uid": "a", "group": str(G1), "role": "213", "active": True},
                         {"user_uid": "b", "group": str(G1), "role": "213", "active": False}])
    plan = mig.plan(db)
    assert plan["legacy_member_rows"] == [
        {"user_uid": "b", "group": str(G1), "role": mig.LEGACY_MEMBER, "active": True}
    ]


def test_plan_counts_user_groups_membership_and_skips_owner():
    db = _db(groups=[{"_id": G1, "owner": "o", "users": [], "type": 2}],
             users=[{"uid": "c", "groups": [str(G1)]}, {"uid": "o", "groups": [str(G1)]}])
    rows = mig.plan(db)["legacy_member_rows"]
    assert [r["user_uid"] for r in rows] == ["c"]


def test_plan_reports_215_plus_other():
    db = _db(user_roles=[{"user_uid": "a", "group": str(G1), "role": "215", "active": True},
                         {"user_uid": "a", "group": str(G1), "role": "213", "active": True},
                         {"user_uid": "b", "group": str(G1), "role": "215", "active": True},
                         {"user_uid": "b", "group": str(G1), "role": "212", "active": True}])
    report = mig.plan(db)["delivery_plus_other"]
    assert report == [{"uid": "a", "group": str(G1), "roles": ["213", "215"]}]


def test_apply_is_idempotent():
    db = _db()
    mig.apply(db, mig.plan(db))
    second = mig.plan(db)
    assert second["legacy_member_rows"] == []
    mig.apply(db, second)
    assert len([d for d in db["UserRoles"].docs if d["role"] == mig.LEGACY_MEMBER]) == 2
    assert db["Roles"].find_one({"value": "212"})["is_system"] is True


def test_apply_keeps_numeric_legacy_values_without_duplicates():
    db = _db(roles=[{"_id": ObjectId(), "value": 212}, {"_id": ObjectId(), "value": 215}])
    mig.apply(db, mig.plan(db))
    values = [d["value"] for d in db["Roles"].docs]
    assert values.count(212) == 1 and "212" not in values
    assert db["Roles"].find_one({"value": 212})["is_system"] is True


def test_rerun_keeps_grants_edited_in_accesos():
    db = _db()
    mig.apply(db, mig.plan(db))
    db["Roles"].update_one({"value": "212"}, {"$set": {"grants": ["chat.private"]}})
    db["Roles"].update_one({"value": "tpl.v.admin"}, {"$set": {"description": "Admin de mostrador"}})
    mig.apply(db, mig.plan(db))
    assert db["Roles"].find_one({"value": "212"})["grants"] == ["chat.private"]
    assert db["Roles"].find_one({"value": "tpl.v.admin"})["description"] == "Admin de mostrador"
