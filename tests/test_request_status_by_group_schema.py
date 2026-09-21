from datetime import datetime
from zoneinfo import ZoneInfo

from app.schemas.RequestStatusByGroup import RequestStatusByGroup
from app.schemas.Offer import OfferStatus


def test_request_status_by_group_to_json_includes_recycled_parent_request_uid():
    model = RequestStatusByGroup(
        group_id="seller-1",
        request_id="req-1",
        status=OfferStatus.created,
        recycled_parent_request_uid="parent-abc",
        createdAt=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        updatedAt=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
    )

    payload = model.toJson()

    assert payload["recycled_parent_request_uid"] == "parent-abc"
    assert payload["status"] == "Created"


def test_request_status_by_group_insert_payload_keeps_recycled_parent_request_uid():
    model = RequestStatusByGroup(
        group_id="seller-1",
        request_id="req-1",
        status=OfferStatus.created,
        recycled_parent_request_uid="parent-abc",
        createdAt=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        updatedAt=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
    )

    insert_payload = model.toJson()
    insert_payload.pop("_id", None)

    assert insert_payload["recycled_parent_request_uid"] == "parent-abc"
    assert insert_payload["request_id"] == "req-1"

    round_trip = RequestStatusByGroup(**insert_payload)

    assert round_trip.recycled_parent_request_uid == "parent-abc"
