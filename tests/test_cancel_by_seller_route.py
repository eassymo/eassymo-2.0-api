"""POST /order/{id}/cancel-by-seller: grant check and pass-through of the service's answers."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException

from app.authz import grant_keys as g
from app.routers import OrderRouter as router_mod
from app.services import OrderCancellationService, authz
from tests.asgi_client import AsgiClient

OID = "64b7f0f0f0f0f0f0f0f0f0f0"


@pytest.fixture
def env():
    app = FastAPI()
    app.include_router(router_mod.orderRouter)
    grants = {"set": {g.ORDERS_CHANGE_STATUS}}
    with patch.object(authz, "caller_uid", return_value="store-uid"), \
         patch.object(authz, "selected_group", return_value="seller-group"), \
         patch.object(authz, "effective_grants", side_effect=lambda *a, **k: frozenset(grants["set"])), \
         patch.object(OrderCancellationService, "cancel_by_seller") as cancel:
        cancel.return_value = {"_id": OID, "status": "CANCELED"}
        yield AsgiClient(app), cancel, grants


def test_cancels_and_returns_the_order(env):
    client, cancel, _ = env
    r = client.post(f"/order/{OID}/cancel-by-seller", json={"reason": "sold", "note": "Se vendió"})
    assert r.status_code == 200 and r.json()["body"]["status"] == "CANCELED"
    cancel.assert_called_once_with(OID, "store-uid", "sold", "Se vendió")


def test_without_the_grant_is_403(env):
    client, cancel, grants = env
    grants["set"] = set()
    r = client.post(f"/order/{OID}/cancel-by-seller", json={"reason": "sold"})
    assert r.status_code == 403
    cancel.assert_not_called()


def test_service_409_passes_through_with_its_detail(env):
    client, cancel, _ = env
    cancel.side_effect = HTTPException(status_code=409, detail="La pieza ya salió de la tienda.")
    r = client.post(f"/order/{OID}/cancel-by-seller", json={"reason": "no_stock"})
    assert r.status_code == 409 and "La pieza ya salió de la tienda." in r.text


def test_note_over_200_chars_is_422(env):
    client, cancel, _ = env
    r = client.post(f"/order/{OID}/cancel-by-seller", json={"reason": "sold", "note": "a" * 201})
    assert r.status_code == 422
    cancel.assert_not_called()
