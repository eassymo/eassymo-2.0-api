from unittest.mock import patch

import pytest
from bson import ObjectId

from app.services import ConversationService as svc

G = "g-me"
OTHER = "g-other"
UID = "u1"


def _msg(group, at, *, read=False, kind="text", content="hola", name=None):
    return {
        "type": kind,
        "groupId": group,
        "content": content,
        "createdAt": at,
        "metaData": {"groupName": name or group},
        "usersThatRead": {f"{UID}-{G}": True} if read else {},
    }


def _request(rid, *, creator=G, status="Created", active=True, created="2026-11-01T10:00:00Z",
             part="Balatas", maker="Honda", model="Civic", year=2018):
    return {
        "_id": ObjectId(rid) if len(rid) == 24 else rid,
        "creatorGroup": creator,
        "subscribedSellers": [OTHER] if creator == G else [G],
        "status": status,
        "isActive": active,
        "createdAt": created,
        "part": {"tipoParteDescripcion": part},
        "vehicleInformation": {"maker": maker, "model": model, "year": year},
    }


def _order(oid, *, buyer=G, seller=OTHER, status="DISPATCHED", number="4821"):
    return {
        "_id": ObjectId(oid),
        "order_id": number,
        "group": buyer,
        "offer": {"group_id": seller},
        "status": status,
        "offer_group": {"_id": seller, "name": f"Tienda {seller}"},
        "request_group": {"_id": buyer, "name": f"Tienda {buyer}"},
    }


@pytest.fixture
def env():
    state = {"requests": [], "orders": [], "chats": [], "names": {}}
    with patch.object(svc, "repo") as repo:
        repo.request_docs_for_group.side_effect = lambda g: list(state["requests"])
        repo.order_docs_for_group.side_effect = lambda g: list(state["orders"])
        repo.chats_for.side_effect = lambda rids, oids: list(state["chats"])
        repo.group_names.side_effect = lambda ids: {i: state["names"].get(i, i) for i in ids}
        yield state


def _rid(n):
    return f"{n:024x}"


def test_unread_first_then_recent(env):
    a, b = _rid(1), _rid(2)
    env["requests"] += [_request(a), _request(b)]
    env["chats"] += [
        {"_id": ObjectId(), "requestId": a, "messages": [_msg(OTHER, "2026-11-13T10:00:00Z", read=True)]},
        {"_id": ObjectId(), "requestId": b, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]},
    ]
    r = svc.list_conversations(G, UID)
    assert [i["entity_id"] for i in r["items"]] == [b, a]
    assert r["items"][0]["unread_count"] == 1
    assert r["unread_conversations"] == 1


def test_waiting_request_only_for_creator(env):
    rid = _rid(3)
    env["requests"].append(_request(rid, created="2026-11-02T08:00:00Z"))
    r = svc.list_conversations(G, UID)
    assert len(r["items"]) == 1
    item = r["items"][0]
    assert item["kind"] == "waiting_request"
    assert item["last_message"] is None
    assert item["activity_at"] == "2026-11-02T08:00:00Z"

    env["requests"][0] = _request(rid, creator=OTHER)
    assert svc.list_conversations(G, UID)["items"] == []


def test_order_counterpart_is_other_side(env):
    oid = _rid(4)
    env["orders"].append(_order(oid, buyer=OTHER, seller=G))
    env["chats"].append({"_id": ObjectId(), "orderId": oid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]})
    assert svc.list_conversations(G, UID)["items"][0]["counterpart"]["name"] == f"Tienda {OTHER}"

    env["orders"][0] = _order(oid, buyer=G, seller=OTHER)
    assert svc.list_conversations(G, UID)["items"][0]["counterpart"]["name"] == f"Tienda {OTHER}"
    env["orders"][0] = _order(oid, buyer=G, seller="g-seller")
    assert svc.list_conversations(G, UID)["items"][0]["counterpart"]["name"] == "Tienda g-seller"


def test_request_chat_counterpart_for_creator_uses_latest_other_group(env):
    rid = _rid(5)
    env["requests"].append(_request(rid))
    env["chats"].append({"_id": ObjectId(), "requestId": rid, "messages": [
        _msg(OTHER, "2026-11-13T09:00:00Z", name="TECNOGOLF", read=True),
        _msg(G, "2026-11-13T10:00:00Z", name="YO", read=True),
    ]})
    item = svc.list_conversations(G, UID)["items"][0]
    assert item["counterpart"]["name"] == "TECNOGOLF"
    assert item["last_message"]["from_me"] is True


def test_request_chat_counterpart_for_seller_is_creator_name(env):
    rid = _rid(6)
    env["requests"].append(_request(rid, creator=OTHER))
    env["names"][OTHER] = "Taller Norte"
    env["chats"].append({"_id": ObjectId(), "requestId": rid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]})
    assert svc.list_conversations(G, UID)["items"][0]["counterpart"]["name"] == "Taller Norte"


def test_preview_for_attachments(env):
    a, b = _rid(7), _rid(8)
    env["requests"] += [_request(a), _request(b)]
    env["chats"] += [
        {"_id": ObjectId(), "requestId": a, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z", kind="image", content="")]},
        {"_id": ObjectId(), "requestId": b, "messages": [_msg(G, "2026-11-13T08:00:00Z", kind="file", content="", read=True)]},
    ]
    items = {i["entity_id"]: i for i in svc.list_conversations(G, UID)["items"]}
    assert items[a]["last_message"]["kind"] == "image"
    assert items[a]["last_message"]["text"] == "Foto"
    assert items[a]["last_message"]["from_me"] is False
    assert items[b]["last_message"]["text"] == "Archivo"
    assert items[b]["last_message"]["from_me"] is True


def test_closed_flags(env):
    oid, rid = _rid(9), _rid(10)
    env["orders"].append(_order(oid, status="RECIEVED"))
    env["requests"].append(_request(rid, status="Offer_selected"))
    env["chats"] += [
        {"_id": ObjectId(), "orderId": oid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]},
        {"_id": ObjectId(), "requestId": rid, "messages": [_msg(OTHER, "2026-11-13T08:00:00Z")]},
    ]
    items = svc.list_conversations(G, UID)["items"]
    assert all(i["is_closed"] for i in items)
    order = next(i for i in items if i["type"] == "order")
    assert order["context_title"] == "Orden #4821 · Entregada"


def test_filters(env):
    read_rid, unread_rid, wait_rid, oid = _rid(11), _rid(12), _rid(13), _rid(14)
    env["requests"] += [_request(read_rid), _request(unread_rid), _request(wait_rid)]
    env["orders"].append(_order(oid))
    env["chats"] += [
        {"_id": ObjectId(), "requestId": read_rid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z", read=True)]},
        {"_id": ObjectId(), "requestId": unread_rid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]},
        {"_id": ObjectId(), "orderId": oid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z", read=True)]},
    ]
    ids = lambda f: {i["entity_id"] for i in svc.list_conversations(G, UID, filter=f)["items"]}
    assert ids("unread") == {unread_rid}
    assert ids("request") == {read_rid, unread_rid, wait_rid}
    assert ids("order") == {oid}
    assert ids("waiting") == {wait_rid}


def test_search_accent_insensitive(env):
    rid, oid = _rid(15), _rid(16)
    env["requests"].append(_request(rid))
    env["orders"].append(_order(oid, number="4821"))
    env["chats"] += [
        {"_id": ObjectId(), "requestId": rid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]},
        {"_id": ObjectId(), "orderId": oid, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]},
    ]
    ids = lambda q: [i["entity_id"] for i in svc.list_conversations(G, UID, q=q)["items"]]
    assert ids("balata") == [rid]
    assert ids("4821") == [oid]
    assert ids("ÓRDEN") == [oid]
    assert ids("BÁLATAS") == [rid]


def test_pagination_cursor(env):
    for n in range(25):
        rid = _rid(100 + n)
        env["requests"].append(_request(rid))
        env["chats"].append({"_id": ObjectId(), "requestId": rid,
                             "messages": [_msg(OTHER, f"2026-11-13T09:{n:02d}:00Z", read=True)]})
    first = svc.list_conversations(G, UID, limit=20)
    assert len(first["items"]) == 20
    assert first["next_cursor"] == "20"
    second = svc.list_conversations(G, UID, cursor="20", limit=20)
    assert len(second["items"]) == 5
    assert second["next_cursor"] is None


def test_chat_without_entity_is_skipped(env):
    env["chats"].append({"_id": ObjectId(), "requestId": _rid(200), "messages": [_msg(OTHER, "2026-11-13T09:00:00Z")]})
    assert svc.list_conversations(G, UID)["items"] == []


def test_unread_summary_counts_conversations(env):
    a, b = _rid(201), _rid(202)
    env["requests"] += [_request(a), _request(b)]
    env["chats"] += [
        {"_id": ObjectId(), "requestId": a, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z"), _msg(OTHER, "2026-11-13T09:01:00Z")]},
        {"_id": ObjectId(), "requestId": b, "messages": [_msg(OTHER, "2026-11-13T09:00:00Z", read=True)]},
    ]
    assert svc.unread_summary(G, UID) == {"unread_conversations": 1}
