"""POST /offer/{id}/withdraw and /offer/{id}/restore: offers.edit grant and pass-through of the service's answers."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException

from app.authz import grant_keys as g
from app.routers import OfferRouter as router_mod
from app.services import OfferWithdrawalService, authz
from tests.asgi_client import AsgiClient

OID = "64b7f0f0f0f0f0f0f0f0f0f0"


@pytest.fixture
def env():
    app = FastAPI()
    app.include_router(router_mod.offerRouter)
    grants = {"set": {g.OFFERS_EDIT}}
    with patch.object(authz, "caller_uid", return_value="store-uid"), \
         patch.object(authz, "selected_group", return_value="seller-group"), \
         patch.object(authz, "effective_grants", side_effect=lambda *a, **k: frozenset(grants["set"])), \
         patch.object(OfferWithdrawalService, "withdraw") as withdraw, \
         patch.object(OfferWithdrawalService, "restore") as restore:
        withdraw.return_value = {"offer_id": OID, "request_id": "r1", "previous_status": "Pending_Changes", "can_undo": True}
        restore.return_value = {"_id": OID, "status": "Pending_Changes"}
        yield AsgiClient(app), withdraw, restore, grants


def test_withdraw_returns_the_service_answer(env):
    client, withdraw, _, _ = env
    r = client.post(f"/offer/{OID}/withdraw")
    assert r.status_code == 200 and r.json()["body"]["can_undo"] is True
    withdraw.assert_called_once_with(OID, "store-uid", "seller-group")


def test_restore_returns_the_offer(env):
    client, _, restore, _ = env
    r = client.post(f"/offer/{OID}/restore")
    assert r.status_code == 200 and r.json()["body"]["_id"] == OID
    restore.assert_called_once_with(OID, "store-uid", "seller-group")


@pytest.mark.parametrize("path", ["withdraw", "restore"])
def test_without_offers_edit_is_403(env, path):
    client, withdraw, restore, grants = env
    grants["set"] = set()
    assert client.post(f"/offer/{OID}/{path}").status_code == 403
    withdraw.assert_not_called()
    restore.assert_not_called()


def test_service_409_passes_through_with_its_detail(env):
    client, withdraw, _, _ = env
    withdraw.side_effect = HTTPException(status_code=409, detail="Esta opción cambió; vuelve a abrirla.")
    r = client.post(f"/offer/{OID}/withdraw")
    assert r.status_code == 409 and "Esta opción cambió; vuelve a abrirla." in r.text
