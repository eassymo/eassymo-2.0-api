import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.authz.grant_keys import ALL_KEYS
from app.repositories import FrameRepository
from app.services import AccessAdminService as access
from app.services import FrameAdminService as frames_svc
from scripts import migrate_frame_refs, upload_frame_screenshots
from tests.test_access_admin import Coll

CATALOG = Path(__file__).resolve().parents[1] / "scripts" / "data" / "frames_catalog.json"


def _catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


# ── catalog consistency ─────────────────────────────────────────────────────

def test_catalog_codes_unique_and_grants_known():
    catalog = _catalog()
    codes = [f["code"] for f in catalog]
    assert len(codes) == len(set(codes)) == 65
    for frame in catalog:
        assert set(frame["grants"]) <= set(ALL_KEYS), frame["code"]
        assert frame["status"] in ("active", "pending")
        if frame["status"] == "active":
            assert frame["route"], f"{frame['code']} is active but has no route"


def test_every_grant_has_at_least_one_frame():
    covered = {g for f in _catalog() for g in f["grants"]}
    assert covered == set(ALL_KEYS)


# ── repository / seed ───────────────────────────────────────────────────────

def test_upsert_missing_frames_never_overwrites():
    coll = MagicMock()
    coll.find.return_value = [{"code": "C.WG.1"}]
    inserted = FrameRepository.upsert_missing(
        [{"code": "C.WG.1", "name": "edited"}, {"code": "C.WG.2.S", "name": "Sistemas"}], collection=coll)
    assert inserted == 1
    (args, _), = coll.insert_many.call_args_list
    assert [d["code"] for d in args[0]] == ["C.WG.2.S"]
    assert "grants" not in args[0][0]  # grant links live on grants (frame_refs), not on frames


# ── frame_refs migration ────────────────────────────────────────────────────

def test_migrate_frame_refs_sets_list_from_catalog_and_is_idempotent():
    grants = Coll([
        {"key": "store.edit_profile", "frame_ref": "C.WG.1"},
        {"key": "deliveries.perform", "frame_ref": None},
        {"key": "offers.create", "frame_refs": ["custom"]},  # already migrated / edited: keep
    ])
    db = {"grants": grants}
    changed = migrate_frame_refs.apply(db, _catalog())
    by_key = {g["key"]: g for g in grants.docs}
    assert by_key["store.edit_profile"]["frame_refs"] == ["C.WG.1", "C.WG.1.M"]
    assert by_key["deliveries.perform"]["frame_refs"] == ["V.N3.S5", "V.N3.S5.M", "V.N3.S5.1"]
    assert by_key["offers.create"]["frame_refs"] == ["custom"]
    assert changed == 2
    assert migrate_frame_refs.apply(db, _catalog()) == 0


# ── admin service ───────────────────────────────────────────────────────────

@pytest.fixture
def db():
    data = {
        "frames": Coll([
            {"code": "C.WG.1", "name": "Configurar tienda", "pov": "ambos", "status": "active", "sort_order": 0,
             "screenshot_url": "https://b.s3.amazonaws.com/frames/C.WG.1.png"},
            {"code": "C.WG.8", "name": "Agrupador", "pov": "ambos", "status": "pending", "sort_order": 1},
        ]),
        "grants": Coll([
            {"key": "store.edit_profile", "name": "Configurar Grupo", "area": "Configuración", "pov": "ambos",
             "active": True, "sort_order": 1, "frame_refs": ["C.WG.1"]},
        ]),
        "Roles": Coll([]),
        "UserRoles": Coll([]),
        "AdminAuditLog": Coll(),
    }
    with patch.object(access, "_db", return_value=data):
        yield data


def test_list_frames_includes_grants_pointing_to_each(db):
    frames = {f["code"]: f for f in frames_svc.list_frames()}
    assert frames["C.WG.1"]["grants"] == [{"key": "store.edit_profile", "name": "Configurar Grupo"}]
    assert frames["C.WG.8"]["grants"] == []


def test_update_frame_rejects_code_and_audits(db):
    with pytest.raises(HTTPException) as exc:
        frames_svc.update_frame("admin", "C.WG.1", {"code": "X"})
    assert exc.value.status_code == 400
    frames_svc.update_frame("admin", "C.WG.1", {"name": "Datos de la tienda"})
    assert db["frames"].find_one({"code": "C.WG.1"})["name"] == "Datos de la tienda"
    assert db["AdminAuditLog"].docs[-1]["action"] == "update_frame"


def test_update_unknown_frame_is_404(db):
    with pytest.raises(HTTPException) as exc:
        frames_svc.update_frame("admin", "NOPE", {"name": "x"})
    assert exc.value.status_code == 404


def test_upload_screenshot_stores_url_and_source(db):
    async def fake_upload(session, file, prefix):
        assert prefix == "frames/C.WG.1"
        return "https://b.s3.amazonaws.com/frames/C.WG.1/new.png"

    file = MagicMock(content_type="image/png", size=1000, filename="shot.png")
    with patch.object(frames_svc, "create_aws_session"), \
         patch.object(frames_svc, "_upload_image_to_s3_with_prefix", side_effect=fake_upload):
        result = asyncio.run(frames_svc.upload_screenshot("admin", "C.WG.1", file))
    assert result["screenshot_url"].endswith("/new.png")
    assert result["screenshot_source"] == "manual"
    assert db["frames"].find_one({"code": "C.WG.1"})["captured_by"] == "admin"


def test_upload_rejects_non_image(db):
    file = MagicMock(content_type="application/pdf", size=10, filename="x.pdf")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(frames_svc.upload_screenshot("admin", "C.WG.1", file))
    assert exc.value.status_code == 400


def test_list_grants_includes_frames(db):
    grants = access.list_grants()
    assert grants[0]["frames"] == [{
        "code": "C.WG.1", "name": "Configurar tienda", "status": "active",
        "screenshot_url": "https://b.s3.amazonaws.com/frames/C.WG.1.png", "needs_update": False,
    }]


def test_update_grant_validates_frame_refs(db):
    with pytest.raises(HTTPException) as exc:
        access.update_grant("admin", "store.edit_profile", {"frame_refs": ["C.WG.1", "NOPE"]})
    assert exc.value.status_code == 400
    access.update_grant("admin", "store.edit_profile", {"frame_refs": ["C.WG.8", "C.WG.1"]})
    assert db["grants"].find_one({"key": "store.edit_profile"})["frame_refs"] == ["C.WG.8", "C.WG.1"]


def test_update_grant_rejects_old_frame_ref_field(db):
    with pytest.raises(HTTPException):
        access.update_grant("admin", "store.edit_profile", {"frame_ref": "C.WG.1"})


# ── screenshot upload script ────────────────────────────────────────────────

def test_upload_script_uploads_known_codes_only(tmp_path):
    (tmp_path / "C.WG.1.png").write_bytes(b"png")
    (tmp_path / "UNKNOWN.png").write_bytes(b"png")
    frames = Coll([{"code": "C.WG.1"}])
    bucket = MagicMock()
    result = upload_frame_screenshots.run(tmp_path, {"frames": frames}, bucket, "b")
    assert result == {"uploaded": ["C.WG.1"], "skipped": ["UNKNOWN"]}
    key = bucket.upload_file.call_args[0][1]
    assert key.startswith("frames/C.WG.1/") and key.endswith(".png")
    doc = frames.find_one({"code": "C.WG.1"})
    assert doc["screenshot_source"] == "script"
    assert doc["needs_update"] is False
    assert doc["screenshot_url"] == f"https://b.s3.amazonaws.com/{key}"


# ── capture samples (read-only, staging only) ───────────────────────────────

from bson import ObjectId
from scripts import capture_samples


class SortableColl(Coll):
    def find(self, flt=None, projection=None):
        docs = list(super().find(flt))

        class _Cur(list):
            def sort(self, *_):
                return _Cur(sorted(self, key=lambda d: str(d["_id"]), reverse=True))

            def limit(self, n):
                return _Cur(self[:n])

        return _Cur(docs)


def test_capture_samples_refuses_non_staging():
    with pytest.raises(SystemExit):
        capture_samples.assert_staging("EASSYMO")
    capture_samples.assert_staging("EASSYMOSTAGING")


def test_capture_samples_finds_latest_records_and_reports_missing():
    seller, buyer, req, offer = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    db = {
        "groups": SortableColl([{"_id": seller, "owner": "v"}, {"_id": buyer, "owner": "c"}]),
        "PartRequests": SortableColl([{"_id": req, "creatorGroup": str(buyer), "parent_request_uid": "p1",
                                       "vehicleInformation": {"_id": "veh1"}}]),
        "Offers": SortableColl([{"_id": offer, "group_id": str(seller)}]),
        "Orders": SortableColl([]),
        "MostradorFolios": SortableColl([]),
    }
    found, missing = capture_samples.find_samples(db, "v", "c")
    assert found == {"CAPTURE_REQUEST": str(req), "CAPTURE_PARENT_REQUEST": "p1",
                     "CAPTURE_VEHICLE": "veh1", "CAPTURE_OFFER": str(offer)}
    assert missing == ["CAPTURE_ORDER", "CAPTURE_FOLIO", "CAPTURE_DRAFT_TOKEN"]


def test_list_frames_with_captured_at_serializes_through_the_router(db):
    """Regression: captured_at is a datetime; the admin router's JSONResponse must not 500."""
    from datetime import datetime, timezone
    from app.routers import AdminRouter

    db["frames"].docs[0]["captured_at"] = datetime.now(timezone.utc)
    resp = AdminRouter.access_list_frames()
    assert resp.status_code == 200
    body = json.loads(resp.body)["body"]
    assert isinstance(body[0]["captured_at"], str)


def test_update_frame_rejects_non_string_values(db):
    with pytest.raises(HTTPException) as exc:
        frames_svc.update_frame("admin", "C.WG.1", {"route": {"x": 1}})
    assert exc.value.status_code == 400


def test_upload_script_only_uploads_codes_captured_in_this_run(tmp_path):
    (tmp_path / "C.WG.1.png").write_bytes(b"png")
    (tmp_path / "C.WG.8.png").write_bytes(b"stale")  # left over from an earlier run
    (tmp_path / "capture-report.json").write_text(json.dumps({"captured": ["C.WG.1"], "skipped": []}))
    frames = Coll([{"code": "C.WG.1"}, {"code": "C.WG.8"}])
    result = upload_frame_screenshots.run(tmp_path, {"frames": frames}, MagicMock(), "b")
    assert result["uploaded"] == ["C.WG.1"]
    assert result["not_in_report"] == ["C.WG.8"]


def test_upload_script_accepts_jpg_with_its_content_type(tmp_path):
    (tmp_path / "C.WG.1.jpg").write_bytes(b"jpg")
    (tmp_path / "capture-report.json").write_text(json.dumps({"captured": ["C.WG.1"]}))
    frames = Coll([{"code": "C.WG.1"}])
    bucket = MagicMock()
    result = upload_frame_screenshots.run(tmp_path, {"frames": frames}, bucket, "b")
    assert result["uploaded"] == ["C.WG.1"]
    args, kwargs = bucket.upload_file.call_args
    assert args[1].endswith(".jpg")
    assert kwargs["ExtraArgs"] == {"ContentType": "image/jpeg"}


# ── "needs update" flag ─────────────────────────────────────────────────────

def test_flag_frames_marks_them_with_reason_and_skips_unknown(db):
    result = frames_svc.flag_frames(["C.WG.1", "NOPE"], "Cambió el formulario de la tienda", "agent:feat/x")
    assert result == {"flagged": ["C.WG.1"], "unknown": ["NOPE"]}
    doc = db["frames"].find_one({"code": "C.WG.1"})
    assert doc["needs_update"] is True
    assert doc["update_reason"] == "Cambió el formulario de la tienda"
    assert doc["flagged_by"] == "agent:feat/x"
    assert doc["flagged_at"]


def test_upload_clears_the_flag(db):
    frames_svc.flag_frames(["C.WG.1"], "cambio", "agent")

    async def fake_upload(session, file, prefix):
        return "https://b.s3.amazonaws.com/frames/C.WG.1/new.png"

    file = MagicMock(content_type="image/png", size=10, filename="x.png")
    with patch.object(frames_svc, "create_aws_session"), \
         patch.object(frames_svc, "_upload_image_to_s3_with_prefix", side_effect=fake_upload):
        result = asyncio.run(frames_svc.upload_screenshot("admin", "C.WG.1", file))
    assert result["needs_update"] is False


def test_super_admin_can_dismiss_the_flag(db):
    frames_svc.flag_frames(["C.WG.1"], "cambio", "agent")
    frames_svc.update_frame("admin", "C.WG.1", {"needs_update": False})
    assert db["frames"].find_one({"code": "C.WG.1"})["needs_update"] is False
    with pytest.raises(HTTPException):
        frames_svc.update_frame("admin", "C.WG.1", {"needs_update": "yes"})


def test_list_grants_frames_carry_the_flag(db):
    frames_svc.flag_frames(["C.WG.1"], "cambio", "agent")
    assert access.list_grants()[0]["frames"][0]["needs_update"] is True
