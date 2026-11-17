"""Super-admin frames: named places in the app with a screenshot, linked from grants."""

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import HTTPException, UploadFile

from app.factories.AwsFactory import create_aws_session
from app.schemas.Frame import EDITABLE_FRAME_FIELDS
from app.services import AccessAdminService as access
from app.services.UploadPictureService import _upload_image_to_s3_with_prefix, _validate_upload_file


def _frame_or_404(code: str) -> dict:
    frame = access._db()["frames"].find_one({"code": code})
    if not frame:
        raise HTTPException(status_code=404, detail="Frame no encontrado")
    return frame


def list_frames() -> List[dict]:
    grants_by_frame: Dict[str, list] = {}
    for grant in access._find("grants", {}):
        for code in grant.get("frame_refs") or []:
            grants_by_frame.setdefault(code, []).append({"key": grant["key"], "name": grant.get("name")})
    frames = sorted(access._find("frames", {}), key=lambda f: f.get("sort_order", 0))
    return [{**access._clean(f), "grants": grants_by_frame.get(f["code"], [])} for f in frames]


def update_frame(admin_uid: str, code: str, data: Dict[str, Any]) -> dict:
    invalid = set(data) - EDITABLE_FRAME_FIELDS
    if invalid:
        raise HTTPException(status_code=400, detail=f"Campos no editables: {', '.join(sorted(invalid))}")
    wrong_type = sorted(
        k for k, v in data.items()
        if v is not None and not isinstance(v, bool if k == "needs_update" else str)
    )
    if wrong_type:
        raise HTTPException(status_code=400, detail=f"Tipo inválido: {', '.join(wrong_type)}")
    if data.get("status") not in (None, "active", "pending"):
        raise HTTPException(status_code=400, detail="Estado inválido")
    before = _frame_or_404(code)
    access._db()["frames"].update_one(
        {"code": code}, {"$set": {**data, "updated_at": access._now(), "updated_by": admin_uid}})
    access._log(admin_uid, "update_frame", "frame", code,
                {"before": {k: before.get(k) for k in data}, "after": data})
    return access._clean(access._db()["frames"].find_one({"code": code}))


async def upload_screenshot(admin_uid: str, code: str, file: UploadFile) -> dict:
    _validate_upload_file(file)
    before = _frame_or_404(code)
    url = await _upload_image_to_s3_with_prefix(create_aws_session(), file, prefix=f"frames/{code}")
    access._db()["frames"].update_one({"code": code}, {"$set": {
        "screenshot_url": url,
        "screenshot_source": "manual",
        "captured_at": datetime.now(timezone.utc),
        "captured_by": admin_uid,
        "needs_update": False,
    }})
    access._log(admin_uid, "upload_frame_screenshot", "frame", code,
                {"before": before.get("screenshot_url"), "after": url})
    return access._clean(access._db()["frames"].find_one({"code": code}))


def flag_frames(codes: List[str], reason: str, flagged_by: str, db=None) -> Dict[str, List[str]]:
    """Mark frames whose screen changed so super admins know the screenshot is outdated."""
    coll = (db or access._db())["frames"]
    known = {f["code"] for f in coll.find({"code": {"$in": list(codes)}}, {"code": 1})}
    flagged = [c for c in dict.fromkeys(codes) if c in known]
    now = datetime.now(timezone.utc)
    for code in flagged:
        coll.update_one({"code": code}, {"$set": {
            "needs_update": True,
            "update_reason": reason,
            "flagged_at": now,
            "flagged_by": flagged_by,
        }})
    return {"flagged": flagged, "unknown": [c for c in dict.fromkeys(codes) if c not in known]}
