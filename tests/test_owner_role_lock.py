"""A group's owner already holds every grant: nobody may give, change or activate roles on them.
Removing or deactivating a role on the owner stays allowed (cleanup), and so does the owner
activating their own first role during onboarding."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.dependencies import group_auth
from app.services import AdminWriteService as aws

GID = str(ObjectId())


def _request(uid):
    return SimpleNamespace(state=SimpleNamespace(user={"uid": uid}, groupSelected=GID), headers={})


@pytest.fixture
def owner_is_boss():
    with patch.object(group_auth, "is_group_owner", side_effect=lambda uid, gid: uid == "boss"):
        yield


# ── group API ───────────────────────────────────────────────────────────────

def test_admin_cannot_give_a_role_to_the_owner(owner_is_boss):
    with patch("app.services.authz.can_assign_role", return_value=(True, "")):
        with pytest.raises(HTTPException) as exc:
            group_auth.authorize_role_mutation(_request("admin"), "boss", GID, "215")
    assert exc.value.status_code == 409


def test_owner_cannot_give_themselves_a_role_outside_onboarding(owner_is_boss):
    with pytest.raises(HTTPException) as exc:
        group_auth.authorize_role_mutation(_request("boss"), "boss", GID, "215")
    assert exc.value.status_code == 409


def test_owner_can_activate_own_first_role_during_onboarding(owner_is_boss):
    group_auth.authorize_role_mutation(_request("boss"), "boss", GID, "322", owner_self_activation=True)


def test_removing_a_role_from_the_owner_is_allowed(owner_is_boss):
    group_auth.authorize_role_mutation(_request("boss"), "boss", GID, "215", removing=True)


def test_members_still_follow_normal_rules(owner_is_boss):
    with patch("app.services.authz.can_assign_role", return_value=(True, "")):
        group_auth.authorize_role_mutation(_request("boss"), "member", GID, "213")


# ── super-admin API ─────────────────────────────────────────────────────────

def _db(existing=None):
    roles = MagicMock()
    roles.find_one.side_effect = lambda q, *a, **k: (existing or {"_id": q["_id"]}) if isinstance(q.get("_id"), ObjectId) else None
    roles.find_one_and_update.side_effect = lambda q, u, **k: {**(existing or {}), **u["$set"]}
    roles.insert_one.return_value = SimpleNamespace(inserted_id=ObjectId())
    groups = MagicMock()
    groups.find_one.side_effect = lambda q, *a, **k: {"_id": q["_id"], "owner": "boss"}
    catalog = MagicMock()
    catalog.find_one.side_effect = lambda q, *a, **k: (
        {"value": "super_admin", "all_grants": True} if "super_admin" in str(q) else None
    )
    return {"UserRoles": roles, "groups": groups, "Roles": catalog, "AdminAuditLog": MagicMock()}


def test_super_admin_cannot_assign_a_role_to_the_owner():
    with patch.object(aws, "db", _db()):
        with pytest.raises(HTTPException) as exc:
            aws.AdminWriteService.assign_user_role("sa", {"user_uid": "boss", "role": "215", "group": GID})
    assert exc.value.status_code == 409


def test_super_admin_cannot_change_the_owners_role():
    existing = {"_id": ObjectId(), "user_uid": "boss", "group": GID, "role": "super_admin", "active": True}
    with patch.object(aws, "db", _db(existing)):
        with pytest.raises(HTTPException) as exc:
            aws.AdminWriteService.update_user_role("sa", str(existing["_id"]), {"role": "215"})
    assert exc.value.status_code == 409


def test_super_admin_can_deactivate_an_owner_role():
    existing = {"_id": ObjectId(), "user_uid": "boss", "group": GID, "role": "215", "active": True}
    db = _db(existing)
    with patch.object(aws, "db", db):
        aws.AdminWriteService.update_user_role("sa", str(existing["_id"]), {"active": False})
    assert db["UserRoles"].find_one_and_update.called


def test_super_admin_can_still_assign_roles_to_members():
    with patch.object(aws, "db", _db()):
        aws.AdminWriteService.assign_user_role("sa", {"user_uid": "member", "role": "213", "group": GID})


def test_assignment_rows_flag_the_group_owner():
    from app.services import AdminMetricsService as ams

    gid = ObjectId()
    fake = {
        "Roles": MagicMock(**{"find.return_value": []}),
        "groups": MagicMock(**{"find.return_value": [{"_id": gid, "name": "ITALIKA", "owner": "boss"}]}),
        "Users": MagicMock(**{"find.return_value": []}),
    }
    with patch.object(ams, "db", fake):
        rows = ams.AdminMetricsService._enrich_user_role_items([
            {"user_uid": "boss", "group": str(gid), "role": "215"},
            {"user_uid": "member", "group": str(gid), "role": "213"},
        ])
    assert [r["is_group_owner"] for r in rows] == [True, False]


def test_super_admin_can_give_the_owner_the_super_admin_role():
    # The owner lacks Eassymo grants; the all-grants role adds them, so it isn't a downgrade.
    with patch.object(aws, "db", _db()):
        aws.AdminWriteService.assign_user_role("sa", {"user_uid": "boss", "role": "super_admin", "group": GID})


def test_super_admin_can_switch_an_owner_row_to_super_admin():
    existing = {"_id": ObjectId(), "user_uid": "boss", "group": GID, "role": "215", "active": True}
    with patch.object(aws, "db", _db(existing)):
        aws.AdminWriteService.update_user_role("sa", str(existing["_id"]), {"role": "super_admin"})
