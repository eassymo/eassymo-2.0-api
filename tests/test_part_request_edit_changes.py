"""Editing a sent part saves every field, records what changed (last_change + change_log), flags the offers made
before the change and tells only the stores that quoted it, once per store. An edit that changes nothing records
nothing, flags nothing and notifies no one."""
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException

from app.authz import grant_keys as g

from app.factories import NotificationsCreator as creator
from app.repositories import OfferRepository as offer_repo
from app.routers import PartRequestRouter as router
from app.schemas.Notification import NotificationType
from app.schemas.PartRequest import PartRequestEdit
from app.services import OfferWithdrawalService
from app.services import PartRequestService as prs
from app.services import authz
from tests.asgi_client import AsgiClient
from tests.test_part_removal import store_members
from tests.test_seller_reach_create import _all_compatible

PR_ID = "6560000000000000000000c3"
OTHER_ID = "6560000000000000000000d4"
BUYER = str(ObjectId())
STORE_A = str(ObjectId())
STORE_B = str(ObjectId())
NOW = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)


def _doc(**part):
    return {
        "_id": ObjectId(PR_ID),
        "creatorGroup": BUYER,
        "creatorUser": "buyer-u",
        "vehicleId": "veh-1",
        "subscribedSellers": [STORE_A, STORE_B],
        "partList": [],
        "part": {"tipoParteDescripcion": "Arandela De Tuerca De Limpiador", "amount": 1, "unitOfMeasure": "Pieza",
                 "position": "Izquierda", "comments": "", **part},
        "fulfillment_type": "pickup",
        "status": "Created",
        "origin": "mostrador",  # skips the seller reach cap, which has its own tests
    }


def _edit(**fields):
    base = {"id": PR_ID, "amount": 1, "comment": "", "position": "Izquierda", "unitOfMeasure": "Pieza"}
    return PartRequestEdit(**{**base, **fields})


def _save(items, by="u1", group_id=BUYER):
    """The buyer "u1" saves from the buyer's store, as the route does."""
    return prs.edit_part_request(items, by=by, group_id=group_id)


def _offer(group_id):
    return {"_id": ObjectId(), "request_id": PR_ID, "group_id": group_id, "status": "Created"}


class World:
    def __init__(self, doc, offers=()):
        self.doc = doc
        self.offers = list(offers)
        self.writes = []
        self.sent = []
        self.ordered = set()  # offer ids held by an order that is not canceled

    def _write(self, doc_id, data, push=None):
        self.writes.append({"set": data, "push": push})
        return {**self.doc, **data}

    def __enter__(self):
        self.stack = ExitStack()
        p = self.stack.enter_context
        p(patch.object(prs.partRequestRepository, "find_by_id", side_effect=lambda i: [self.doc]))
        p(patch.object(prs.partRequestRepository, "edit_part_request", side_effect=self._write))
        p(patch.object(prs.groupRepository, "find_by_id", return_value={"_id": ObjectId(BUYER), "name": "MOFLES SOLIDARIDAD"}))
        p(patch.object(prs, "expand_subscribed_sellers_with_accepted_comisionados", side_effect=lambda s, c=None: list(s)))
        p(patch.object(prs.ArmadoraCompatibilityService, "evaluate_bulk", side_effect=_all_compatible))
        p(patch.object(prs.SistemasCompatibilityService, "evaluate_bulk_for_car_part", side_effect=_all_compatible))
        p(patch.object(prs, "_now", return_value=NOW))
        p(patch("app.services.notification_fanout.fanout_part_request_to_new_sellers"))
        self.find_offers = p(patch.object(prs.offerRepository, "find", side_effect=lambda *a, **k: list(self.offers)))
        self.flag = p(patch.object(prs.offerRepository, "flag_before_change", return_value=len(self.offers)))
        self.users = p(patch.object(prs.groupService, "find_users_by_groups_ids_v2", side_effect=lambda ids: [
            {"_id": gid, "users": {STORE_A: ["a1", "a2"], STORE_B: ["b1"]}[gid]} for gid in ids]))
        p(patch.object(prs, "send_notifications_batch", side_effect=lambda batch: self.sent.extend(batch)))
        p(patch.object(prs, "_user_in_group", side_effect=lambda uid, gid: uid == "u1" and gid == BUYER))
        self.orders = p(patch.object(OfferWithdrawalService, "orderRepository"))
        self.orders.find_one.side_effect = lambda q: (
            {"status": "CONFIRMED"} if set(map(str, q["offer._id"]["$in"])) & self.ordered else None)
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


def test_position_and_unit_are_saved():
    with World(_doc()) as w:
        _save([_edit(position="Derecha", unitOfMeasure="Juego")])
    part = w.writes[0]["set"]["part"]
    assert part["position"] == "Derecha"
    assert part["unitOfMeasure"] == "Juego"


def test_none_position_and_unit_leave_the_saved_values():
    with World(_doc()) as w:
        _save([_edit(position=None, unitOfMeasure=None)])
    part = w.writes[0]["set"]["part"]
    assert part["position"] == "Izquierda"
    assert part["unitOfMeasure"] == "Pieza"


def test_change_is_recorded():
    with World(_doc()) as w:
        _save([_edit(position="Derecha", comment="Original GM, no genérica")], by="u1")
    write = w.writes[0]
    change = write["set"]["last_change"]
    assert change["at"] == NOW
    assert change["by"] == "u1"
    assert change["fields"] == [
        {"field": "position", "before": "Izquierda", "after": "Derecha"},
        {"field": "comments", "before": "", "after": "Original GM, no genérica"},
    ]
    assert write["push"] == {"change_log": change}


def test_unchanged_values_record_nothing():
    with World(_doc(comments="Original GM"), [_offer(STORE_A)]) as w:
        _save([_edit(comment="  Original GM ", amount=1)])
    write = w.writes[0]
    assert "last_change" not in write["set"]
    assert write["push"] is None  # no change_log entry either
    w.flag.assert_not_called()
    assert w.sent == []


@pytest.mark.parametrize("before, after", [
    (None, "No aplica"),
    ("", "No aplica"),
    ("Selecciona posición", "No aplica"),
    (None, "NO APLICA "),
    ("No aplica", ""),
    ("No Aplicá", "No aplica"),
    ("selecciona posicion", ""),
    ("Selecciona posicion", "Selecciona posición"),
    ("Selecciona posición", "Selecciona posicion"),
    ("Selecciona posicio\u0301n", "No aplica"),  # the accent as a combining mark (NFD)
])
def test_position_defaults_are_not_changes(before, after):
    with World(_doc(position=before), [_offer(STORE_A)]) as w:
        _save([_edit(position=after)])
    assert "last_change" not in w.writes[0]["set"]
    w.flag.assert_not_called()
    assert w.sent == []


@pytest.mark.parametrize("before, after", [(None, "Pieza"), ("", "Pieza"), ("Pieza", " pieza")])
def test_unit_defaults_are_not_changes(before, after):
    with World(_doc(unitOfMeasure=before), [_offer(STORE_A)]) as w:
        _save([_edit(unitOfMeasure=after)])
    assert "last_change" not in w.writes[0]["set"]
    w.flag.assert_not_called()


def test_removed_part_is_skipped_and_never_written():
    with World(_doc(), [_offer(STORE_A)]) as w:
        w.doc["removed"] = {"at": NOW, "by": "buyer-u"}
        result = _save([_edit(position="Derecha")])
    assert w.writes == []
    w.flag.assert_not_called()
    assert w.sent == []
    assert result == []


def test_offers_flagged_and_stores_notified_once():
    with World(_doc(), [_offer(STORE_A), _offer(STORE_A)]) as w:
        _save([_edit(position="Derecha", comment="Original GM, no genérica")], by="u1")
    w.flag.assert_called_once_with(PR_ID, NOW)
    assert [n.owner for n in w.sent] == ["a1", "a2"]
    for n in w.sent:
        assert n.type == NotificationType.PART_CHANGED
        assert n.ownerGroup == STORE_A
        assert n.side == "sell"
        assert n.title == "Mofles Solidaridad cambió Arandela de tuerca de limpiador"
        assert n.body == "Cambió la posición y la nota. Revisa tu oferta."
        assert n.action["label"] == "Revisar oferta"
        assert n.action["href"] == n.navigateToUrl
        assert PR_ID in n.navigateToUrl
        assert n.metaData == {"requestId": PR_ID}
        assert "¡" not in n.title + n.body


def test_store_without_offer_not_notified():
    # STORE_B is subscribed but never quoted.
    with World(_doc(), [_offer(STORE_A)]) as w:
        _save([_edit(amount=3)])
    assert {n.ownerGroup for n in w.sent} == {STORE_A}
    w.users.assert_called_once_with([STORE_A])


def test_change_without_offers_flags_and_notifies_no_one():
    with World(_doc(), []) as w:
        _save([_edit(amount=3)])
    assert w.writes[0]["set"]["last_change"]["fields"] == [{"field": "amount", "before": 1, "after": 3}]
    w.flag.assert_not_called()
    assert w.sent == []


def test_notification_failure_never_fails_the_edit():
    with World(_doc(), [_offer(STORE_A)]) as w:
        w.users.side_effect = RuntimeError("mongo down")
        result = _save([_edit(amount=3)])
    assert result == [PR_ID]
    w.flag.assert_called_once()


# ── Who may save ─────────────────────────────────────────────────────────────

def _error(items, **kw):
    with pytest.raises(HTTPException) as exc:
        _save(items, **kw)
    return exc.value.status_code, exc.value.detail


def test_missing_part_is_404_and_writes_nothing():
    with World(_doc()) as w, patch.object(prs.partRequestRepository, "find_by_id",
                                          side_effect=lambda i: [w.doc] if i == PR_ID else []):
        assert _error([_edit(amount=3), _edit(id=OTHER_ID, amount=2)]) == (404, "Esta pieza ya no existe.")
    assert w.writes == []


@pytest.mark.parametrize("by, group_id", [("u1", STORE_A), ("intruder", BUYER), (None, BUYER)])
def test_only_the_creator_store_may_save(by, group_id):
    with World(_doc()) as w:
        assert _error([_edit(amount=3)], by=by, group_id=group_id) == (
            403, "Solo quien creó la solicitud puede cambiar piezas.")
    assert w.writes == []
    assert w.sent == []


def test_one_foreign_part_writes_nothing():
    other = {**_doc(), "_id": ObjectId(OTHER_ID), "creatorGroup": STORE_B}
    with World(_doc()) as w, patch.object(prs.partRequestRepository, "find_by_id",
                                          side_effect=lambda i: [w.doc if i == PR_ID else other]):
        assert _error([_edit(amount=3), _edit(id=OTHER_ID, amount=2)])[0] == 403
    assert w.writes == []


def test_changing_an_ordered_part_is_409_and_writes_nothing():
    offers = [_offer(STORE_A), _offer(STORE_B)]
    with World(_doc(), offers) as w:
        w.ordered = {str(offers[1]["_id"])}
        assert _error([_edit(amount=3)]) == (409, "Ya pediste esta pieza. Para cambiarla, cancela el pedido primero.")
    assert w.writes == []
    w.flag.assert_not_called()
    assert w.sent == []


def test_ordered_part_saved_unchanged_is_not_blocked():
    """The sheet saves every part; one the buyer didn't touch passes even if it was ordered."""
    offers = [_offer(STORE_A)]
    with World(_doc(), offers) as w:
        w.ordered = {str(offers[0]["_id"])}
        assert _save([_edit()]) == [PR_ID]
    assert "last_change" not in w.writes[0]["set"]


def test_canceled_order_does_not_block_a_change():
    with World(_doc(), [_offer(STORE_A)]) as w:
        _save([_edit(amount=3)])
    assert w.orders.find_one.call_args.args[0]["status"] == {"$ne": "CANCELED"}
    assert w.writes[0]["set"]["last_change"]["fields"] == [{"field": "amount", "before": 1, "after": 3}]


# The real membership check, kept before World patches it.
REAL_IN_GROUP = prs._user_in_group
MEMBERS = dict(
    groups={BUYER: {"users": ["u1"], "owner": "owner-1"}, STORE_A: {"users": ["a1"]}},
    users={"listed-1": {"groups": [BUYER]}},
    roles=[("role-1", BUYER), ("other-1", STORE_A)],
)


@pytest.mark.parametrize("uid", ["owner-1", "listed-1", "role-1"])
def test_any_member_the_grant_check_accepts_may_save(uid):
    """Owner, the user's own groups list, an active role: the same membership require_grant uses."""
    with World(_doc()) as w, patch.object(prs, "_user_in_group", REAL_IN_GROUP), store_members(**MEMBERS):
        assert _save([_edit(amount=3)], by=uid) == [PR_ID]
    assert w.writes[0]["set"]["last_change"]["by"] == uid


def test_member_of_another_store_may_not_save():
    with World(_doc()) as w, patch.object(prs, "_user_in_group", REAL_IN_GROUP), store_members(**MEMBERS):
        assert _error([_edit(amount=3)], by="other-1") == (403, "Solo quien creó la solicitud puede cambiar piezas.")
    assert w.writes == []


HEADERS = {"GroupSelected": BUYER}


@pytest.fixture
def route():
    grants = {"keys": frozenset({g.REQUESTS_EDIT}), "uid": "u9"}

    def caller_uid(request):
        if not grants["uid"]:
            raise HTTPException(status_code=401, detail="User not authenticated")
        return grants["uid"]

    app = FastAPI()
    app.include_router(router.partRequestRouter)
    with patch.object(authz, "caller_uid", side_effect=caller_uid), \
         patch.object(authz, "effective_grants", side_effect=lambda *a: grants["keys"]), \
         patch.object(router.partRequestService, "edit_part_request", return_value=[PR_ID]) as edit:
        client = AsgiClient(app)
        put = lambda body: client.request("PUT", "/partRequest", headers=HEADERS, json=body)
        yield put, edit, grants


BODY = [{"id": PR_ID, "amount": 2, "comment": ""}]


def test_route_passes_the_caller_and_the_selected_store(route):
    put, edit, _ = route

    r = put(BODY)

    assert r.status_code == 200, r.text
    assert edit.call_args.kwargs == {"by": "u9", "group_id": BUYER}


def test_route_without_the_edit_grant_is_403(route):
    put, edit, grants = route
    grants["keys"] = frozenset({g.REQUESTS_VIEW})

    r = put(BODY)

    assert r.status_code == 403 and g.REQUESTS_EDIT in r.text
    edit.assert_not_called()


def test_route_without_a_signed_in_user_is_401(route):
    put, edit, grants = route
    grants["uid"] = None

    assert put(BODY).status_code == 401
    edit.assert_not_called()


def test_flag_before_change_flags_only_live_offers():
    coll = MagicMock()
    coll.update_many.return_value.modified_count = 2
    db = MagicMock()
    db.__getitem__.return_value = coll
    with patch.object(offer_repo.database, "db", db):
        assert offer_repo.flag_before_change(PR_ID, NOW) == 2
    query, update = coll.update_many.call_args.args
    assert query == {"request_id": PR_ID, "status": {"$nin": ["Rejected", "No_Inventory"]}}
    assert update == {"$set": {"before_change": True, "before_change_at": NOW}}


@pytest.mark.parametrize("fields, sentence", [
    (["comments"], "Cambió la nota."),
    (["position", "comments"], "Cambió la posición y la nota."),
    (["amount", "unitOfMeasure", "comments"], "Cambió la cantidad, la unidad y la nota."),
])
def test_change_sentence(fields, sentence):
    assert creator.change_sentence(fields) == sentence
