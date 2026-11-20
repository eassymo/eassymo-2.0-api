from app.schemas.Notification import Notification, NotificationType

DELIVERY_TYPES = [
    "DELIVERY_ASSIGNED",
    "DELIVERY_TIME_CHANGED",
    "DELIVERY_REASSIGNED",
    "DELIVERY_CANCELED",
    "DELIVERY_FAILED",
]


def test_delivery_types_exist_with_the_same_string_value():
    for name in DELIVERY_TYPES:
        assert NotificationType[name].value == name


def test_a_notification_can_carry_a_guest_token_and_no_owner_uid():
    n = Notification(
        type=NotificationType.DELIVERY_ASSIGNED,
        message="Te asignaron una entrega",
        ownerGroup="",
        owner="",
        metaData={"orderId": "o1"},
        read=False,
        guest_token="tok-1",
    )
    assert n.guest_token == "tok-1"
    assert n.owner == ""


def test_existing_notifications_still_validate_without_guest_token():
    n = Notification(
        type=NotificationType.ORDER_SENT,
        message="x",
        ownerGroup="g1",
        owner="u1",
        metaData={},
        read=False,
    )
    assert n.guest_token is None
