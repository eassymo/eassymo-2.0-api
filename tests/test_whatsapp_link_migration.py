from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from bson import ObjectId

from app.services import WhatsappLinkMigrationService as svc


def _user(uid, phone, verified=None):
    u = {"uid": uid, "pos_whatsapp": phone}
    if verified:
        u["pos_whatsapp_verified_at"] = verified
    return u


@pytest.fixture
def env():
    groups = {}
    users = []
    state = {"can": {}, "roles": {}, "used": {}}
    with patch.object(svc, "inbound_repo") as ib, patch.object(svc, "userRepository") as ur, patch.object(
        svc, "groupRepository"
    ) as gr, patch.object(svc, "link_repo") as lr, patch.object(
        svc, "can"
    ) as can_, patch.object(svc, "userRolesRepository") as roles:
        ur.find.side_effect = lambda filters, limit=30: iter(users)
        gr.find_by_user.side_effect = lambda uid: iter(groups.get(uid, []))
        can_.side_effect = lambda uid, gid, perm: state["can"].get((uid, gid), True)
        roles.find.side_effect = lambda f: state["roles"].get(
            (f["user_uid"], f["group"]), []
        )
        lr.insert_if_absent.return_value = True
        lr.find.return_value = None
        ib.used_group_ids_by_creator.side_effect = lambda uid: state["used"].get(uid, [])
        yield {
            "users": users, "groups": groups, "state": state,
            "ur": ur, "lr": lr, "can": can_,
        }


def _g():
    return {"_id": ObjectId()}


def test_dry_run_writes_nothing(env):
    g = _g()
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g]
    r = svc.migrate(apply=False)
    env["lr"].insert_if_absent.assert_not_called()
    assert r["created"] == 1


def test_apply_creates_link_per_allowed_group(env):
    g1, g2 = _g(), _g()
    env["users"].append(_user("u1", "7779313704", "2026-01-02T03:04:05+00:00"))
    env["groups"]["u1"] = [g1, g2]
    env["state"]["used"]["u1"] = [str(g1["_id"]), str(g2["_id"])]
    r = svc.migrate(apply=True)
    assert r["created"] == 2
    calls = env["lr"].insert_if_absent.call_args_list
    assert calls[0].args[:3] == ("u1", str(g1["_id"]), "+5217779313704")
    assert calls[0].args[3] == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_second_apply_is_idempotent(env):
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [_g()]
    env["lr"].insert_if_absent.return_value = False
    r = svc.migrate(apply=True)
    assert r["created"] == 0 and r["existing"] == 1


def test_member_without_role_row_is_reported_not_linked(env):
    g = _g()
    gid = str(g["_id"])
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g]
    env["state"]["can"][("u1", gid)] = False
    r = svc.migrate(apply=True)
    env["lr"].insert_if_absent.assert_not_called()
    assert r["skipped_no_access"] == [
        {"uid": "u1", "group_id": gid, "reason": "no_role_row"}
    ]


def test_role_not_allowed_reason(env):
    g = _g()
    gid = str(g["_id"])
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g]
    env["state"]["can"][("u1", gid)] = False
    env["state"]["roles"][("u1", gid)] = [object()]
    r = svc.migrate(apply=False)
    assert r["skipped_no_access"][0]["reason"] == "role_not_allowed"


def test_invalid_phone_is_reported(env):
    env["users"].append(_user("u1", "123"))
    env["groups"]["u1"] = [_g()]
    r = svc.migrate(apply=True)
    assert r["invalid_phones"] == ["u1"]
    env["lr"].insert_if_absent.assert_not_called()


def test_duplicate_number_across_users_skipped(env):
    env["users"] += [_user("u1", "7779313704"), _user("u2", "+527779313704")]
    env["groups"]["u1"] = [_g()]
    env["groups"]["u2"] = [_g()]
    r = svc.migrate(apply=True)
    env["lr"].insert_if_absent.assert_not_called()
    assert r["phone_conflicts"] == ["***3704"]
    assert r["created"] == 0


def test_missing_verified_at_defaults_to_now(env):
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [_g()]
    svc.migrate(apply=True)
    v = env["lr"].insert_if_absent.call_args.args[3]
    assert abs((datetime.now(timezone.utc) - v).total_seconds()) < 5


def test_all_users_are_scanned_beyond_default_limit(env):
    svc.migrate(apply=False)
    assert env["ur"].find.call_args.kwargs.get("limit") == 0


def test_dry_run_reports_existing_links_without_writing(env):
    g1, g2 = _g(), _g()
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g1, g2]
    env["state"]["used"]["u1"] = [str(g1["_id"]), str(g2["_id"])]
    existing_gid = str(g1["_id"])
    env["lr"].find.side_effect = lambda uid, gid: (
        {"uid": uid, "group_id": gid} if gid == existing_gid else None
    )
    r = svc.migrate(apply=False)
    assert r["created"] == 1 and r["existing"] == 1
    env["lr"].insert_if_absent.assert_not_called()


def test_only_used_groups_are_linked(env):
    g1, g2, g3 = _g(), _g(), _g()
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g1, g2, g3]
    env["state"]["used"]["u1"] = [str(g2["_id"])]
    r = svc.migrate(apply=True)
    assert r["created"] == 1
    assert r["skipped_unused"] == 2
    env["lr"].insert_if_absent.assert_called_once()
    assert env["lr"].insert_if_absent.call_args.args[1] == str(g2["_id"])


def test_single_group_user_without_usage_is_linked(env):
    g = _g()
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g]
    r = svc.migrate(apply=True)
    assert r["created"] == 1 and r["skipped_unused"] == 0


def test_multi_group_user_without_usage_links_nothing(env):
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [_g(), _g()]
    r = svc.migrate(apply=True)
    assert r["created"] == 0 and r["skipped_unused"] == 2
    env["lr"].insert_if_absent.assert_not_called()


def test_used_group_without_access_is_still_reported(env):
    g = _g()
    gid = str(g["_id"])
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g, _g()]
    env["state"]["used"]["u1"] = [gid]
    env["state"]["can"][("u1", gid)] = False
    r = svc.migrate(apply=True)
    assert r["created"] == 0
    assert [x["group_id"] for x in r["skipped_no_access"]] == [gid]


def test_dry_run_counts_unused_groups_without_writing(env):
    g1, g2 = _g(), _g()
    env["users"].append(_user("u1", "7779313704"))
    env["groups"]["u1"] = [g1, g2]
    env["state"]["used"]["u1"] = [str(g1["_id"])]
    r = svc.migrate(apply=False)
    assert r["created"] == 1 and r["skipped_unused"] == 1
    env["lr"].insert_if_absent.assert_not_called()
