"""Legacy Roles store `value` as a number (215); assignments must always hold it as text."""
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.schemas.UserRoles import UserRoles
from app.services import AdminWriteService as aws


def test_user_roles_reads_numeric_role_as_text():
    assert UserRoles(user_uid="u", role=215, group="g").role == "215"


def test_admin_update_saves_role_as_text():
    existing = {"_id": ObjectId(), "user_uid": "u", "group": "g", "role": "213", "active": True}
    coll = MagicMock()
    coll.find_one.side_effect = [existing, None]
    coll.find_one_and_update.return_value = {**existing, "role": "215"}
    with patch.object(aws, "db", {"UserRoles": coll, "groups": MagicMock(**{"find_one.return_value": None}), "Roles": MagicMock(**{"find_one.return_value": None}), "AdminAuditLog": MagicMock()}):
        aws.AdminWriteService.update_user_role("admin", str(existing["_id"]), {"role": 215})
    (_, update), _ = coll.find_one_and_update.call_args
    assert update["$set"]["role"] == "215"
    duplicate_query = coll.find_one.call_args_list[1][0][0]
    assert duplicate_query["role"] == "215"


def test_new_assignment_lets_mongo_create_the_id():
    doc = UserRoles(user_uid="u", role="215", group="g").toJson()
    assert "_id" not in doc


def test_existing_id_is_kept():
    oid = ObjectId()
    assert UserRoles(_id=oid, user_uid="u", role="215").toJson()["_id"] == str(oid)


def test_created_at_is_the_creation_time_not_import_time():
    import time
    first = UserRoles(user_uid="u", role="1").created_at
    time.sleep(0.01)
    assert UserRoles(user_uid="u", role="1").created_at > first


def test_roles_schema_reads_legacy_numeric_value_and_entity_type():
    from app.schemas.Roles import RolesSchema

    role = RolesSchema(**{"_id": ObjectId(), "description": "Repartidor Refaccionaria", "value": 215, "entityType": 1})
    assert role.value == "215"
    assert role.entityType == "1"


def test_invite_lookup_works_for_a_legacy_numeric_role():
    from unittest.mock import patch
    from app.services import TeamMemberInviteService as tmis

    invite = {"_id": ObjectId(), "inviter_user": "boss", "group": str(ObjectId()), "role": str(ObjectId()),
              "timestamp": "2026-11-17", "contact_method": "+52", "status_changes": [], "is_public": False}
    group = {"_id": ObjectId(invite["group"]), "name": "ITALIKA", "owner": "boss"}
    with patch.object(tmis.teamMemberInviteRepository, "find_by_id", return_value=invite), \
         patch.object(tmis.groupRepository, "find_by_id", return_value=group), \
         patch.object(tmis.rolesRepository, "find_by_id", return_value={"value": 215, "entityType": 1, "description": "Repartidor"}), \
         patch.object(tmis.userRepository, "find_by_uid", return_value=[]):
        body = tmis.find_by_id(str(invite["_id"]))
    assert body["role"]["value"] == "215"
