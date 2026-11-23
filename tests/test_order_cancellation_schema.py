from datetime import datetime, timezone

from app.schemas.Order import Order, OrderCancellation
from app.schemas.PartRequest import PartRequest
from tests.test_report_failed_delivery import _doc

AT = datetime(2026, 11, 23, 15, 17, tzinfo=timezone.utc)


def _order(**extra):
    doc = _doc()
    doc.pop("_id")
    return Order(**{**doc, **extra})


def test_cancellation_serialized():
    data = _order(cancellation={"by": "seller", "group_id": "g1", "user_id": "u1", "reason": "sold", "note": None, "at": AT}).toJson()
    assert data["cancellation"]["reason"] == "sold"
    assert isinstance(data["cancellation"]["at"], str)


def test_order_without_cancellation_round_trips():
    order = _order()
    assert order.cancellation is None
    assert order.toJson()["cancellation"] is None


def test_part_request_last_cancellation():
    pr = PartRequest(creatorGroup="g", creatorUser="u", vehicleId="v", subscribedSellers=[],
                     last_cancellation={"order_id": "o1", "store_group_id": "g1", "store_name": "Autopartes Alex", "reason": "sold", "note": None, "at": AT})
    assert pr.toJson()["last_cancellation"]["store_name"] == "Autopartes Alex"
