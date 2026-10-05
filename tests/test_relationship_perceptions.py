from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.schemas.Groups import GroupSchema
from app.schemas.Relationship import (
    RelationshipAnswer,
    RelationshipDirection,
    ReminderCadence,
    SubmitPerceptionRequest,
)
from app.services import RelationshipService as svc

BUYER_GROUP_ID = "674a11111111111111111111"
SELLER_GROUP_ID = "674a22222222222222222222"
OTHER_GROUP_ID = "674a33333333333333333333"


def _completed_order(*, buyer=BUYER_GROUP_ID, seller=SELLER_GROUP_ID, days_ago=1, status="RECIEVED"):
    now = datetime.now(timezone.utc)
    completed_at = now - timedelta(days=days_ago)
    return {
        "_id": "507f1f77bcf86cd799439011",
        "group": buyer,
        "status": status,
        "offer": {"group_id": seller, "created_at": completed_at - timedelta(hours=1), "price": 100},
        "part_request": {
            "_id": "507f1f77bcf86cd799439099",
            "creatorGroup": buyer,
            "created_at": completed_at - timedelta(hours=2),
        },
        "status_history": [
            {"status": "CONFIRMED", "timestamp": completed_at - timedelta(hours=3)},
            {"status": "READY_TO_BE_DISPATCHED", "timestamp": completed_at - timedelta(hours=2)},
            {"status": status, "timestamp": completed_at},
        ],
        "created_at": completed_at - timedelta(days=1),
        "updated_at": completed_at,
    }


@patch("app.services.RelationshipService.relationshipRepository.find_latest_perceptions", return_value=[])
@patch("app.services.RelationshipService.groupRepository.find_by_id", return_value={"name": "Refaccionaria López"})
@patch("app.services.RelationshipService.orderRepository.find")
def test_due_when_completed_and_unanswered(mock_find, _group, _latest):
    mock_find.side_effect = [[_completed_order()], []]
    result = svc.list_relationships(BUYER_GROUP_ID, RelationshipDirection.COMPRANDO)
    assert result["due_count"] == 1
    assert result["principales"][0]["counterpart_group_id"] == SELLER_GROUP_ID
    assert result["principales"][0]["due"] is True


@patch("app.services.RelationshipService.relationshipRepository.find_latest_perceptions")
@patch("app.services.RelationshipService.groupRepository.find_by_id", return_value={"name": "Refaccionaria López"})
@patch("app.services.RelationshipService.orderRepository.find")
def test_not_due_after_answer_newer_than_order(mock_find, _group, mock_latest):
    order = _completed_order(days_ago=3)
    mock_find.side_effect = [[order], []]
    mock_latest.return_value = [
        {
            "counterpart_group_id": SELLER_GROUP_ID,
            "direction": "comprando",
            "answer": "bien",
            "created_at": datetime.now(timezone.utc),
        }
    ]
    result = svc.list_relationships(BUYER_GROUP_ID, RelationshipDirection.COMPRANDO)
    assert result["due_count"] == 0
    assert result["principales"][0]["reviewed_today"] is True


@patch("app.services.RelationshipService.relationshipRepository.find_latest_perceptions", return_value=[])
@patch("app.services.RelationshipService.groupRepository.find_by_id", return_value={"name": "Taller Norte"})
@patch("app.services.RelationshipService.orderRepository.find")
def test_both_directions_are_independent(mock_find, _group, _latest):
    buying = _completed_order(buyer=BUYER_GROUP_ID, seller=SELLER_GROUP_ID)
    selling = _completed_order(buyer=SELLER_GROUP_ID, seller=BUYER_GROUP_ID)
    selling["_id"] = "507f1f77bcf86cd799439012"
    mock_find.side_effect = [[buying], [selling]]
    buying_list = svc.list_relationships(BUYER_GROUP_ID, RelationshipDirection.COMPRANDO)
    mock_find.side_effect = [[buying], [selling]]
    selling_list = svc.list_relationships(BUYER_GROUP_ID, RelationshipDirection.VENDIENDO)
    assert buying_list["due_count"] == 1
    assert selling_list["due_count"] == 1
    assert buying_list["principales"][0]["counterpart_group_id"] == SELLER_GROUP_ID
    assert selling_list["principales"][0]["counterpart_group_id"] == SELLER_GROUP_ID


@patch("app.services.RelationshipService.relationshipRepository.find_latest_perceptions", return_value=[])
@patch("app.services.RelationshipService.orderRepository.find")
def test_incomplete_orders_are_ignored(mock_find, _latest):
    pending = _completed_order()
    pending["status"] = "CONFIRMED"
    pending["status_history"] = [{"status": "CONFIRMED", "timestamp": datetime.now(timezone.utc)}]
    mock_find.side_effect = [[pending], []]
    result = svc.list_relationships(BUYER_GROUP_ID, RelationshipDirection.COMPRANDO)
    assert result["due_count"] == 0
    assert result["principales"] == []


@patch("app.services.RelationshipService.relationshipRepository.insert_perception")
@patch("app.services.RelationshipService.orderRepository.find")
def test_submit_perception_requires_completed_order(mock_find, mock_insert):
    mock_find.side_effect = [[_completed_order()], []]
    result = svc.submit_perception(
        user_uid="user-1",
        reviewer_group_id=BUYER_GROUP_ID,
        payload=SubmitPerceptionRequest(
            counterpart_group_id=SELLER_GROUP_ID,
            direction=RelationshipDirection.COMPRANDO,
            answer=RelationshipAnswer.BIEN,
        ),
    )
    assert result["answer"] == "bien"
    mock_insert.assert_called_once()


@patch("app.services.RelationshipService.orderRepository.find")
def test_submit_perception_rejects_missing_completed_order(mock_find):
    mock_find.side_effect = [[], []]
    with pytest.raises(HTTPException) as exc:
        svc.submit_perception(
            user_uid="user-1",
            reviewer_group_id=BUYER_GROUP_ID,
            payload=SubmitPerceptionRequest(
                counterpart_group_id=OTHER_GROUP_ID,
                direction=RelationshipDirection.COMPRANDO,
                answer=RelationshipAnswer.REGULAR,
            ),
        )
    assert exc.value.status_code == 400


@patch("app.services.RelationshipService.offerRepository.find", return_value=[])
@patch("app.services.RelationshipService.relationshipRepository.find_latest_perception", return_value=None)
@patch("app.services.RelationshipService.groupRepository.find_by_id", return_value={"name": "Meineke"})
@patch("app.services.RelationshipService.orderRepository.find")
def test_habitual_response_averages_selected_seller_offer(mock_find, _group, _perception, _offers):
    now = datetime.now(timezone.utc)

    def order(oid: str, request_id: str, offer_minutes: int):
        request_at = now - timedelta(hours=5)
        return {
            "_id": oid,
            "group": BUYER_GROUP_ID,
            "status": "RECIEVED",
            "created_at": now - timedelta(days=1),
            "updated_at": now - timedelta(days=1),
            "offer": {
                "_id": f"offer-{oid}",
                "group_id": SELLER_GROUP_ID,
                "createdAt": request_at + timedelta(minutes=offer_minutes),
                "price": 100,
                "status": "Selected",
            },
            "part_request": {
                "_id": request_id,
                "creatorGroup": BUYER_GROUP_ID,
                "createdAt": request_at.isoformat().replace("+00:00", "Z"),
            },
            "status_history": [{"status": "RECIEVED", "timestamp": now - timedelta(days=1)}],
        }

    other_seller = _completed_order(seller=OTHER_GROUP_ID)
    mock_find.side_effect = [
        [
            order("507f1f77bcf86cd799439021", "req-1", 30),
            order("507f1f77bcf86cd799439022", "req-2", 90),
            other_seller,
        ],
        [],
    ]
    result = svc.get_activity(BUYER_GROUP_ID, SELLER_GROUP_ID, RelationshipDirection.COMPRANDO)
    assert result["respuesta_habitual"]["minutes"] == 60
    assert result["respuesta_habitual"]["responded"] == 2
    assert result["respuesta_habitual"]["sample"] == 2


def test_group_to_json_omits_reputation():
    group = GroupSchema(
        **{
            "_id": BUYER_GROUP_ID,
            "name": "Taller Norte",
            "type": 1,
            "state": "CDMX",
            "city": "Mexico",
            "group_store_type": 1,
            "reputation": {"score_avg": 4.5, "score_count": 2},
        }
    )
    payload = group.toJson()
    assert "reputation" not in payload


def test_prefs_match_friday_17_mexico():
    friday = datetime(2026, 9, 25, 23, 5, tzinfo=timezone.utc)  # 17:05 Mexico
    prefs = {"cadence": "weekly", "weekday": 4, "hour": 17, "minute": 0}
    assert svc.prefs_match_local_slot(prefs, friday) is True


def test_prefs_skip_off_and_wrong_hour():
    friday = datetime(2026, 9, 25, 23, 5, tzinfo=timezone.utc)
    assert svc.prefs_match_local_slot({"cadence": "off", "weekday": 4, "hour": 17}, friday) is False
    assert svc.prefs_match_local_slot({"cadence": "weekly", "weekday": 4, "hour": 9}, friday) is False


@patch("app.services.RelationshipService.notificationService.create")
@patch("app.services.RelationshipService.group_has_due_direction", return_value=True)
@patch("app.services.RelationshipService._groups_for_uid", return_value=[BUYER_GROUP_ID])
@patch("app.services.RelationshipService.relationshipRepository.claim_send_slot")
@patch("app.services.RelationshipService.relationshipRepository.find_all_active_prefs")
def test_reminder_sends_once_per_window(mock_prefs, mock_claim, _groups, _due, mock_create):
    now = datetime(2026, 9, 25, 23, 5, tzinfo=timezone.utc)
    mock_prefs.return_value = [
        {
            "uid": "user-1",
            "cadence": "weekly",
            "weekday": 4,
            "hour": 17,
            "minute": 0,
        }
    ]
    mock_claim.side_effect = [True, False]
    first = svc.send_due_reminders(now)
    assert first["sent"] == 1
    mock_create.assert_called_once()

    second = svc.send_due_reminders(now)
    assert second["sent"] == 0


@patch("app.services.RelationshipService.notificationService.create")
@patch("app.services.RelationshipService.group_has_due_direction", return_value=False)
@patch("app.services.RelationshipService._groups_for_uid", return_value=[BUYER_GROUP_ID])
@patch("app.services.RelationshipService.relationshipRepository.find_all_active_prefs")
def test_reminder_skips_when_nothing_due(mock_prefs, _groups, _due, mock_create):
    now = datetime(2026, 9, 25, 23, 5, tzinfo=timezone.utc)
    mock_prefs.return_value = [
        {"uid": "user-1", "cadence": "weekly", "weekday": 4, "hour": 17, "minute": 0}
    ]
    result = svc.send_due_reminders(now)
    assert result["sent"] == 0
    mock_create.assert_not_called()


def test_reminder_summary_weekly_friday():
    summary = svc.reminder_summary(
        {"cadence": ReminderCadence.WEEKLY.value, "weekday": 4, "hour": 17, "minute": 0}
    )
    assert summary == "Cada semana · Viernes · 5:00 p.m."
