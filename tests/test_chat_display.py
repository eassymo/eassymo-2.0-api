from app.services.chat_display import (
    classify_message_party,
    mask_chat_for_viewer,
)


def _message(group_id: str, group_name: str = "Shop", sender_name: str = "Person") -> dict:
    return {
        "groupId": group_id,
        "senderId": "uid-1",
        "metaData": {"groupName": group_name, "senderName": sender_name},
        "content": "hello",
    }


def test_classify_message_party():
    assert classify_message_party("buyer-g", "buyer-g", "seller-a") == "buyer"
    assert classify_message_party("seller-a", "buyer-g", "seller-a") == "self"
    assert classify_message_party("seller-b", "buyer-g", "seller-a") == "other_seller"


def test_mask_chat_anonymous_other_seller_for_seller_viewer():
    chat = {
        "requestId": "req-1",
        "messages": [
            _message("buyer-g", "Buyer Shop", "Buyer Person"),
            _message("seller-a", "Seller A Shop", "Alice"),
            _message("seller-b", "Seller B Shop", "Bob"),
        ],
    }

    masked = mask_chat_for_viewer(
        chat,
        entity_type="request",
        creator_group_id="buyer-g",
        viewer_group_id="seller-a",
    )

    assert masked["messages"][0]["partyType"] == "buyer"
    assert masked["messages"][0]["metaData"]["groupName"] == ""
    assert masked["messages"][0]["metaData"]["senderName"] == "Buyer Person"

    assert masked["messages"][1]["partyType"] == "self"
    assert masked["messages"][1]["metaData"]["groupName"] == "Seller A Shop"

    assert masked["messages"][2]["partyType"] == "anonymous_seller"
    assert masked["messages"][2]["metaData"]["groupName"] == ""
    assert masked["messages"][2]["metaData"]["senderName"] == ""
    assert masked["messages"][2]["anonymousKey"]


def test_mask_chat_preserves_names_for_buyer_viewer():
    chat = {"messages": [_message("seller-b", "Seller B Shop", "Bob")]}

    masked = mask_chat_for_viewer(
        chat,
        entity_type="request",
        creator_group_id="buyer-g",
        viewer_group_id="buyer-g",
    )

    assert masked["messages"][0]["metaData"]["groupName"] == "Seller B Shop"
    assert "partyType" not in masked["messages"][0]


def test_mask_chat_skips_order_entity():
    chat = {"messages": [_message("seller-b", "Seller B Shop", "Bob")]}

    masked = mask_chat_for_viewer(
        chat,
        entity_type="order",
        creator_group_id="buyer-g",
        viewer_group_id="seller-a",
    )

    assert masked["messages"][0]["metaData"]["groupName"] == "Seller B Shop"
