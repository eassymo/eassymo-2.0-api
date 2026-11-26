"""POST /partRequest/{id}/send-reminder: stores get an hour to answer a new request before the buyer can nudge them."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import PartRequestService as svc


def _send(created_at):
    with patch.object(svc.partRequestRepository, "find_one_by_id", return_value={"_id": "pr-1", "createdAt": created_at}), \
         patch.object(svc.partRequestRepository, "edit_part_request"), \
         patch.object(svc, "__format_part_request", return_value={}), \
         patch("app.services.notification_fanout.fanout_part_request_reminder", return_value=3) as fanout:
        return svc.send_seller_reminder("pr-1", ["g1", "g2", "g3"], "Taller"), fanout


def test_refused_in_the_first_hour():
    with pytest.raises(HTTPException) as exc:
        _send(datetime.now(timezone.utc) - timedelta(minutes=10))
    assert exc.value.status_code == 409
    assert exc.value.detail == "Podrás enviar un recordatorio una hora después de crear la solicitud."


def test_refused_with_a_string_date_too():
    with pytest.raises(HTTPException):
        _send((datetime.now(timezone.utc) - timedelta(minutes=59)).isoformat())


def test_sent_after_the_hour():
    sent, fanout = _send(datetime.now(timezone.utc) - timedelta(minutes=61))
    assert sent == 3
    fanout.assert_called_once()


def test_a_naive_date_counts_as_utc():
    sent, _ = _send(datetime.utcnow() - timedelta(hours=2))
    assert sent == 3


def _send_with(doc):
    with patch.object(svc.partRequestRepository, "find_one_by_id", return_value={"_id": "pr-1", **doc}), \
         patch.object(svc.partRequestRepository, "edit_part_request") as write, \
         patch.object(svc, "__format_part_request", return_value={}), \
         patch("app.services.notification_fanout.fanout_part_request_reminder", return_value=2):
        return svc.send_seller_reminder("pr-1", ["g1", "g2"], "Taller"), write


def test_a_sent_reminder_stamps_last_reminder_at():
    _, write = _send_with({"createdAt": datetime.now(timezone.utc) - timedelta(hours=3)})
    data = write.call_args.args[1]
    assert write.call_args.args[0] == "pr-1"
    assert datetime.now(timezone.utc) - data["last_reminder_at"] < timedelta(seconds=5)


def test_another_reminder_waits_an_hour_after_the_last_one():
    with pytest.raises(HTTPException) as exc:
        _send_with({"createdAt": datetime.now(timezone.utc) - timedelta(hours=5),
                    "last_reminder_at": datetime.now(timezone.utc) - timedelta(minutes=20)})
    assert exc.value.status_code == 409
    assert exc.value.detail == "Podrás enviar otro recordatorio una hora después del anterior."


def test_the_monitor_receives_both_moments():
    from app.schemas.PartRequest import PartRequest
    at = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
    pr = PartRequest(**{"_id": "pr-1", "creatorGroup": "g", "creatorUser": "u", "part": {}, "status": "Created", "vehicleId": "v1", "subscribedSellers": [],
                        "last_reminder_at": at, "last_widened_at": at})
    out = pr.toJson()
    assert out["last_reminder_at"].startswith("2026-11-26") and out["last_widened_at"].startswith("2026-11-26")
