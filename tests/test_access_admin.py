from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import AccessAdminService as svc

GID = str(ObjectId())


class Cursor:
    def __init__(self, items):
        self._it = iter(list(items))

    def __iter__(self):
        return self._it

    def __bool__(self):
        return True


class Coll:
    """Small in-memory stand-in for a pymongo collection (only what the service uses)."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    @staticmethod
    def _match(doc, flt):
        for k, v in (flt or {}).items():
            val = doc.get(k)
            if isinstance(v, dict):
                if "$in" in v and val not in v["$in"]:
                    return False
                if "$ne" in v and val == v["$ne"]:
                    return False
            elif isinstance(val, list):
                if v not in val:
                    return False
            elif val != v:
                return False
        return True

    def find(self, flt=None, projection=None):
        # pymongo returns a one-pass cursor (always truthy); mimic that so double reads fail here too
        return Cursor(dict(d) for d in self.docs if self._match(d, flt))

    def find_one(self, flt=None, projection=None):
        found = list(self.find(flt))
        return found[0] if found else None

    def update_one(self, flt, upd):
        for d in self.docs:
            if self._match(d, flt):
                d.update(upd.get("$set", {}))

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def delete_one(self, flt):
        self.docs = [d for d in self.docs if not self._match(d, flt)]


@pytest.fixture
def db():
    data = {
        "grants": Coll([
            {"key": "offers.create", "name": "Crear Ofertas", "area": "Ofertas", "pov": "vendedor", "implemented": True, "active": True, "sort_order": 2},
            {"key": "requests.create", "name": "Crear Solicitudes", "area": "Solicitudes", "pov": "comprador", "implemented": True, "active": True, "sort_order": 1},
            {"key": "chat.private", "name": "Chat", "area": "Mensajes", "pov": "ambos", "implemented": True, "active": True, "sort_order": 3},
            {"key": "kitting.configure", "name": "Kitting", "area": "Pedidos", "pov": "vendedor", "implemented": False, "active": True, "sort_order": 4},
            {"key": "eassymo.uom", "name": "UOM", "area": "Eassymo", "pov": "eassymo", "implemented": False, "active": True, "sort_order": 5},
        ]),
        "Roles": Coll([
            {"_id": ObjectId(), "value": "215", "description": "Repartidor", "grants": ["chat.private"], "is_system": True, "pov": "ambos"},
            {"_id": ObjectId(), "value": "r_custom", "description": "Mostrador", "grants": ["offers.create"], "is_system": False, "pov": "vendedor"},
        ]),
        "UserRoles": Coll([
            {"user_uid": "d1", "group": GID, "role": "215", "active": True},
            {"user_uid": "d2", "group": "other", "role": "215", "active": True},
        ]),
        "AdminAuditLog": Coll(),
        "frames": Coll(),
        "groups": Coll([{"_id": ObjectId(GID), "owner": "o", "users": ["d1"], "type": 1}]),
    }
    with patch.object(svc, "_db", return_value=data):
        yield data


def test_list_grants_sorted_with_counts_and_sin_efecto(db):
    grants = svc.list_grants()
    assert [g["key"] for g in grants] == ["requests.create", "offers.create", "chat.private", "kitting.configure", "eassymo.uom"]
    by_key = {g["key"]: g for g in grants}
    assert by_key["chat.private"]["roles_count"] == 1
    assert by_key["kitting.configure"]["sin_efecto"] is True
    # offers.create is in the catalog but no code checks it yet (phase 2)
    assert by_key["offers.create"]["sin_efecto"] is True
    assert by_key["offers.create"]["sections"] == []
    assert by_key["requests.create"]["sin_efecto"] is False
    assert by_key["requests.create"]["sections"][0]["layer"] == "app"


def test_update_grant_rejects_key_fields(db):
    with pytest.raises(HTTPException) as exc:
        svc.update_grant("admin", "offers.create", {"pov": "comprador"})
    assert exc.value.status_code == 400


def test_update_grant_writes_audit(db):
    svc.update_grant("admin", "offers.create", {"name": "Cotizar", "active": False})
    assert db["grants"].find_one({"key": "offers.create"})["name"] == "Cotizar"
    log = db["AdminAuditLog"].docs[-1]
    assert log["action"] == "update_grant" and log["entity_id"] == "offers.create"


def test_grant_impact_counts_holders(db):
    assert svc.grant_impact("chat.private") == {"users": 2, "groups": 2}


def test_create_role_rejects_eassymo_and_pov_mismatch(db):
    with pytest.raises(HTTPException):
        svc.create_role("admin", {"description": "X", "pov": "vendedor", "grants": ["eassymo.uom"]})
    with pytest.raises(HTTPException):
        svc.create_role("admin", {"description": "X", "pov": "vendedor", "grants": ["requests.create"]})
    with pytest.raises(HTTPException):
        svc.create_role("admin", {"description": "X", "pov": "vendedor", "grants": ["nope.key"]})


def test_create_role_ok(db):
    role = svc.create_role("admin", {"description": "Cajero", "pov": "vendedor", "entity_types": ["1"],
                                     "function": "vendedor", "grants": ["offers.create", "chat.private"],
                                     "assignable_by_group_admins": True})
    assert role["value"].startswith("r_") and len(role["value"]) == 10
    assert role["is_system"] is False and role["display"] is False
    assert db["AdminAuditLog"].docs[-1]["action"] == "create_access_role"


def test_update_role_audits_before_after(db):
    svc.update_role("admin", "r_custom", {"grants": ["offers.create", "chat.private"]})
    payload = db["AdminAuditLog"].docs[-1]["payload"]
    assert payload["before"] == ["offers.create"]
    assert payload["after"] == ["chat.private", "offers.create"]


def test_delete_system_role_is_409(db):
    with pytest.raises(HTTPException) as exc:
        svc.delete_role("admin", "215")
    assert exc.value.status_code == 409


def test_delete_role_with_holders_is_409(db):
    db["UserRoles"].docs.append({"user_uid": "x", "group": GID, "role": "r_custom", "active": True})
    with pytest.raises(HTTPException) as exc:
        svc.delete_role("admin", "r_custom")
    assert exc.value.status_code == 409


def test_duplicate_role(db):
    copy = svc.duplicate_role("admin", "215")
    assert copy["description"] == "Repartidor (copia)"
    assert copy["is_system"] is False and copy["grants"] == ["chat.private"]


def test_list_roles_counts(db):
    roles = {r["value"]: r for r in svc.list_roles({})}
    assert roles["215"]["users_count"] == 2 and roles["215"]["groups_count"] == 2
    assert roles["215"]["grants_count"] == 1
    assert [r["value"] for r in svc.list_roles({"kind": "custom"})] == ["r_custom"]


def test_access_check_reports_sources(db):
    with patch.object(svc.group_auth, "user_belongs_to_group", return_value=True), \
         patch.object(svc.group_auth, "is_group_owner", return_value=False), \
         patch.object(svc.authz, "effective_grants", return_value=frozenset({"chat.private"})):
        result = svc.access_check("d1", GID)
    assert result["is_member"] is True and result["is_owner"] is False
    assert result["grants"] == [{"key": "chat.private", "sources": ["215"]}]
    assert "offers.create" in result["missing"] and "eassymo.uom" not in result["missing"]


def test_access_check_owner_source(db):
    with patch.object(svc.group_auth, "user_belongs_to_group", return_value=True), \
         patch.object(svc.group_auth, "is_group_owner", return_value=True), \
         patch.object(svc.authz, "effective_grants", return_value=frozenset({"offers.create"})):
        result = svc.access_check("o", GID)
    assert result["grants"] == [{"key": "offers.create", "sources": ["dueño"]}]


def test_delete_custom_role_without_holders(db):
    assert svc.delete_role("admin", "r_custom") == {"deleted": "r_custom"}


def test_metrics_counts(db):
    m = svc.metrics()
    assert m["active_roles"] == 2 and m["active_grants"] == 5
    assert m["sin_efecto"] == 4  # every fixture grant except requests.create is unchecked


def test_super_admin_role_lists_all_grants_and_cannot_be_edited(db):
    db["Roles"].docs.append({"_id": ObjectId(), "value": "super_admin", "description": "Super Admin",
                             "all_grants": True, "grants": [], "is_system": True, "pov": "ambos"})
    roles = {r["value"]: r for r in svc.list_roles({})}
    assert roles["super_admin"]["grants_count"] == 5  # every active grant in the fixture catalog
    with pytest.raises(HTTPException) as exc:
        svc.update_role("admin", "super_admin", {"grants": ["chat.private"]})
    assert exc.value.status_code == 400


def test_access_check_names_super_admin_and_owner_as_sources(db):
    db["Roles"].docs.append({"_id": ObjectId(), "value": "super_admin", "all_grants": True, "grants": []})
    db["UserRoles"].docs.append({"user_uid": "o", "group": GID, "role": "super_admin", "active": True})
    with patch.object(svc.group_auth, "user_belongs_to_group", return_value=True), \
         patch.object(svc.group_auth, "is_group_owner", return_value=True), \
         patch.object(svc.authz, "effective_grants", return_value=frozenset({"offers.create", "eassymo.uom"})):
        result = svc.access_check("o", GID)
    by_key = {g["key"]: g["sources"] for g in result["grants"]}
    assert by_key["offers.create"] == ["dueño", "super_admin"]
    assert by_key["eassymo.uom"] == ["super_admin"]
