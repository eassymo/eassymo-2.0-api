"""A store withdraws one of its offers on a part: it moves whole to OffersArchive (never hard-deleted) and only a
draft can come back (Deshacer)."""
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.services import OfferWithdrawalService as svc

OFFER_ID = str(ObjectId())
STORE = str(ObjectId())
REQ = str(ObjectId())


def _doc(status):
    return {"_id": ObjectId(OFFER_ID), "request_id": REQ, "group_id": STORE, "brand": "FRITEC", "price": 980,
            "status": status, "user_uid": "u1", "code": "", "guarantee": "", "unit_of_measure": "Pieza",
            "to_be_delivered_time": None, "internalComments": "", "publicComments": ""}


@pytest.fixture
def repos():
    offers, archive, orders = MagicMock(), MagicMock(), MagicMock()
    orders.find_one.return_value = None
    offers.delete_if_status.return_value = True
    calls = []
    archive.insert.side_effect = lambda doc: calls.append("archive")
    offers.delete_if_status.side_effect = lambda oid, st: calls.append("delete") or True
    with patch.object(svc, "offerRepository", offers), patch.object(svc, "offerArchiveRepository", archive), \
         patch.object(svc, "orderRepository", orders), \
         patch.object(svc, "_user_in_group", side_effect=lambda uid, gid: uid == "u1" and gid == STORE):
        yield offers, archive, orders, calls


def _status_error(fn, *args):
    with pytest.raises(HTTPException) as exc:
        fn(*args)
    return exc.value.status_code, exc.value.detail


def test_withdraw_draft_archives_then_deletes_and_allows_undo(repos):
    offers, archive, _, calls = repos
    offers.find_offer_by_id.return_value = _doc("Pending_Changes")
    result = svc.withdraw(OFFER_ID, "u1", STORE)
    assert calls == ["archive", "delete"]
    archived = archive.insert.call_args.args[0]
    assert archived["withdrawal"]["previous_status"] == "Pending_Changes"
    assert archived["withdrawal"]["by"] == "u1"
    assert archived["_id"] == ObjectId(OFFER_ID)
    offers.delete_if_status.assert_called_once_with(OFFER_ID, "Pending_Changes")
    assert result == {"offer_id": OFFER_ID, "request_id": REQ, "previous_status": "Pending_Changes", "can_undo": True}


def test_withdraw_sent_offer_cannot_be_undone(repos):
    offers, _, _, _ = repos
    offers.find_offer_by_id.return_value = _doc("Created")
    assert svc.withdraw(OFFER_ID, "u1", STORE)["can_undo"] is False


def test_withdraw_missing_offer_is_404(repos):
    offers, _, _, _ = repos
    offers.find_offer_by_id.return_value = None
    assert _status_error(svc.withdraw, OFFER_ID, "u1", STORE) == (404, "Esta opción ya no existe.")


def test_withdraw_refuses_other_store(repos):
    offers, archive, _, _ = repos
    offers.find_offer_by_id.return_value = _doc("Created")
    assert _status_error(svc.withdraw, OFFER_ID, "intruder", STORE) == (403, "Solo la tienda que cotizó puede eliminarla.")
    archive.insert.assert_not_called()


@pytest.mark.parametrize("status,order", [("Selected", None), ("Created", {"_id": "o1", "status": "CONFIRMED"})])
def test_withdraw_refuses_selected_or_live_order(repos, status, order):
    offers, archive, orders, _ = repos
    offers.find_offer_by_id.return_value = _doc(status)
    orders.find_one.return_value = order
    assert _status_error(svc.withdraw, OFFER_ID, "u1", STORE) == (
        409, "El comprador ya la pidió. Si no puedes surtirla, cancela desde la orden.")
    archive.insert.assert_not_called()


def test_live_order_lookup_skips_canceled_orders(repos):
    offers, _, orders, _ = repos
    offers.find_offer_by_id.return_value = _doc("Created")
    svc.withdraw(OFFER_ID, "u1", STORE)
    query = orders.find_one.call_args.args[0]
    assert query["status"] == {"$ne": "CANCELED"}
    assert OFFER_ID in query["offer._id"]["$in"]


@pytest.mark.parametrize("status", ["Pending_Approval", "Workshop_Approval_Pending"])
def test_withdraw_refuses_waiting_for_approval(repos, status):
    offers, archive, _, _ = repos
    offers.find_offer_by_id.return_value = _doc(status)
    assert _status_error(svc.withdraw, OFFER_ID, "u1", STORE) == (
        409, "Esta opción espera aprobación; todavía no se puede eliminar.")
    archive.insert.assert_not_called()


def test_withdraw_race_rolls_back_archive(repos):
    offers, archive, _, _ = repos
    offers.find_offer_by_id.return_value = _doc("Created")
    offers.delete_if_status.side_effect = lambda oid, st: False
    assert _status_error(svc.withdraw, OFFER_ID, "u1", STORE) == (409, "Esta opción cambió; vuelve a abrirla.")
    archive.delete.assert_called_once_with(OFFER_ID)


def test_restore_puts_draft_back_with_same_id(repos):
    offers, archive, _, _ = repos
    archive.find_by_id.return_value = {**_doc("Pending_Changes"),
                                       "withdrawal": {"by": "u1", "at": None, "previous_status": "Pending_Changes"}}
    result = svc.restore(OFFER_ID, "u1", STORE)
    restored = offers.insert_with_id.call_args.args[0]
    assert "withdrawal" not in restored
    assert restored["_id"] == ObjectId(OFFER_ID)
    archive.delete.assert_called_once_with(OFFER_ID)
    assert result["_id"] == OFFER_ID and result["brand"] == "FRITEC"


def test_restore_refuses_sent_offer(repos):
    offers, archive, _, _ = repos
    archive.find_by_id.return_value = {**_doc("Created"),
                                       "withdrawal": {"by": "u1", "at": None, "previous_status": "Created"}}
    assert _status_error(svc.restore, OFFER_ID, "u1", STORE) == (409, "Esta opción ya no se puede recuperar.")
    offers.insert_with_id.assert_not_called()


def test_restore_refuses_other_store(repos):
    _, archive, _, _ = repos
    archive.find_by_id.return_value = {**_doc("Pending_Changes"),
                                       "withdrawal": {"by": "u1", "at": None, "previous_status": "Pending_Changes"}}
    assert _status_error(svc.restore, OFFER_ID, "intruder", STORE)[0] == 403


def test_restore_missing_is_404(repos):
    _, archive, _, _ = repos
    archive.find_by_id.return_value = None
    assert _status_error(svc.restore, OFFER_ID, "u1", STORE) == (404, "Esta opción ya no existe.")


def test_withdraw_refuses_when_the_selected_store_is_not_the_offers(repos):
    """offers.edit is checked in the selected store; a member of the offer's store acting from another store is refused."""
    offers, archive, _, _ = repos
    offers.find_offer_by_id.return_value = _doc("Created")
    assert _status_error(svc.withdraw, OFFER_ID, "u1", str(ObjectId())) == (403, "Solo la tienda que cotizó puede eliminarla.")
    archive.insert.assert_not_called()


def test_call_center_that_posted_it_may_withdraw(repos):
    offers, _, _, _ = repos
    cc = str(ObjectId())
    offers.find_offer_by_id.return_value = {**_doc("Created"), "call_center_that_posted_offer": {"_id": cc, "name": "CC"}}
    with patch.object(svc, "_user_in_group", side_effect=lambda uid, gid: uid == "cc-user" and gid == cc):
        assert svc.withdraw(OFFER_ID, "cc-user", cc)["previous_status"] == "Created"


def test_restore_refuses_when_the_selected_store_is_not_the_offers(repos):
    _, archive, _, _ = repos
    archive.find_by_id.return_value = {**_doc("Pending_Changes"),
                                       "withdrawal": {"by": "u1", "at": None, "previous_status": "Pending_Changes"}}
    assert _status_error(svc.restore, OFFER_ID, "u1", str(ObjectId()))[0] == 403
