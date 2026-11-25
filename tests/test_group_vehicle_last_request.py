from datetime import datetime, timezone
from unittest.mock import patch

from bson import ObjectId

from app.services import GroupCarService as svc


def _vehicle(oid):
    return {"_id": oid, "maker": "Jeep", "model": "J10", "year": "1980", "engine": "", "group": "g", "user": "u", "subModel": None}


def test_vehicles_carry_the_time_of_their_latest_part_request():
    v1, v2, v3 = ObjectId(), ObjectId(), ObjectId()
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = datetime(2026, 11, 20, tzinfo=timezone.utc)
    requests = {
        str(v1): [{"parent_request_uid": "p1", "createdAt": old}],
        str(v2): [{"parent_request_uid": "p2", "createdAt": new}, {"parent_request_uid": "p2", "createdAt": old}],
        str(v3): [],
    }
    with patch.object(svc.GroupCarRepository, "find_by_group", return_value=[_vehicle(v1), _vehicle(v2), _vehicle(v3)]), \
         patch.object(svc.PartRequestRepository, "find", side_effect=lambda f, p: requests[f["vehicleId"]]):
        out = {v["_id"]: v for v in svc.find_by_group("g")}
    assert out[str(v2)]["lastRequestAt"].startswith("2026-11-20")
    assert out[str(v1)]["lastRequestAt"].startswith("2026-01-01")
    assert out[str(v3)]["lastRequestAt"] is None
    assert out[str(v3)]["numberOfRequests"] == 0
