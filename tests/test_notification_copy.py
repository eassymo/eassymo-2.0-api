"""Every builder reads 'who did what' per the accepted catalog (artboard 11): title, body, side, decision."""
import re
from datetime import datetime, timezone

import pytest

from app.factories import NotificationsCreator as nc
from app.utils.display_text import local_time_label

COMMON = dict(owner="u1", owner_group="g1", navigate_to_url="/x", meta_data={})
TIME = datetime(2026, 11, 23, 21, 17, tzinfo=timezone.utc)  # 3:17 p. m. in Mexico City
ORDER = "6b04752ac1cdd5189a0a4472"

CASES = [
    ("OFFER_CREATED", nc.create_offer_notification,
     dict(store_name="REFACCIONARIA AUTOPARTES ALEX", part_name="Conjunto De Rotor De Disco De Freno", price=1250),
     "Nueva oferta de Refaccionaria Autopartes Alex", "Conjunto de rotor de disco de freno · $1,250", "buy", None),
    ("WORKSHOP_PENDING_APPROVAL", nc.create_offer_workshop_approval,
     dict(store_name="AUTOPARTES ALEX", part_name="Conjunto De Rotor", price=1250, offer_id="of1"),
     "Una oferta espera tu aprobación", "Conjunto de rotor · $1,250 · Autopartes Alex", "buy", "offer:of1:approve"),
    ("OFFER_SELECTED_BY_COMMISSIONER", nc.create_offer_selected_by_commissioner_to_origin_group_notification,
     dict(store_name="AUTOPARTES ALEX", part_name="Árbol De Levas", order_id=ORDER, price=450),
     "Tu comisionado pidió una pieza", "Árbol de levas · $450 · Autopartes Alex", "buy", None),
    ("ORDER_CONFIRMED", nc.create_order_confirmed_notification,
     dict(store_name="AUTOPARTES ALEX", part_name="Conjunto De Rotor", order_id=ORDER, delivery_time=TIME),
     "Autopartes Alex está preparando tu pedido", "Conjunto de rotor · llega 3:17 p. m.", "buy", None),
    ("ORDER_DELAYED", nc.create_order_delayed_notification,
     dict(store_name="AUTOPARTES ALEX", part_name="Árbol De Levas", order_id=ORDER, delivery_time=TIME),
     "Autopartes Alex retrasó tu pedido", "Árbol de levas · ahora llega 3:17 p. m.", "buy", None),
    ("ORDER_READY_TO_BE_SENT", nc.create_order_ready_to_be_sent_notification,
     dict(store_name="AUTOPARTES ALEX", part_name="Alternador", order_id=ORDER),
     "Tu pedido está listo para salir", "Alternador · Autopartes Alex", "buy", None),
    ("ORDER_SENT", nc.create_order_sent_notification,
     dict(store_name="AUTOPARTES ALEX", part_name="Alternador", order_id=ORDER, rider_name="Eduardo"),
     "Tu pedido va en camino", "Alternador · con Eduardo", "buy", None),
    ("ORDER_RECIEVED", nc.create_order_received_notification,
     dict(part_name="Alternador", order_id=ORDER, buyer_name="TALLER HERNANDEZ", received_at=TIME),
     "Taller Hernandez recibió su pedido", "Alternador · 3:17 p. m.", "sell", None),
    ("OFFER_SELECTED", nc.create_offer_selected_notification,
     dict(store_name="TALLER HERNANDEZ", part_name="Árbol De Levas", price=450, order_id="o1"),
     "Taller Hernandez pidió tu oferta", "Árbol de levas · $450. Confirma la hora de entrega.", "sell", "order:o1:confirm"),
    ("PART_REQUEST_CREATED", nc.create_part_request_notification,
     dict(store_name="TALLER HERNANDEZ", part_name="Arandela De Tuerca De Limpiador"),
     "Taller Hernandez busca una pieza", "Arandela de tuerca de limpiador", "sell", None),
    ("PART_REQUEST_REMINDER", nc.create_part_request_reminder_notification,
     dict(store_name="TALLER HERNANDEZ", part_name="Arandela De Tuerca De Limpiador", request_id="r1"),
     "Taller Hernandez sigue esperando tu cotización", "Arandela de tuerca de limpiador", "sell", "request:r1:quote:g1"),
    ("OFFER_APPROVAL_REQUEST", nc.create_offer_approval_request_notification,
     dict(call_center_name="CALL CENTER NORTE", part_name="Árbol De Levas", price=450, offer_id="of2"),
     "Call Center Norte armó una oferta por ti", "Árbol de levas · $450. Revísala antes de que la vea el comprador.", "sell", "offer:of2:approve"),
    ("INVITE_ACCEPTED", nc.create_invite_accepted_notification,
     dict(store_name="MEDINA EXPRESS"),
     "Medina Express aceptó tu invitación", "Ya está en tu red.", None, None),
    ("PART_REQUEST_INVITE", nc.create_part_request_invite_notification,
     dict(inviter_group_name="TALLER HERNANDEZ", inviter_user="u9",
          meta_data={"partRequests": [{"vehicleInformation": {"maker": "Jeep", "model": "J10", "year": 1980}}] * 3}),
     "Taller Hernandez te invita a cotizar", "3 piezas · Jeep J10 1980", "sell", None),
    ("CALLCENTER_CONNECTED_GROUP", nc.create_callcenter_connected_group_selected_notification,
     dict(invited_group_name="MEDINA EXPRESS", vehicle="Jeep J10 1980",
          meta_data={"partRequest": {"part": {"tipoParteDescripcion": "Árbol De Levas"}}}),
     "Medina Express recibió una solicitud", "Árbol de levas · Jeep J10 1980. Cotiza por ellos.", "sell", None),
    ("CALLCENTER_OFFER_APPROVAL", nc.create_callcenter_offer_approval_approved_notification,
     dict(group_name="MEDINA EXPRESS", part_name="Árbol De Levas"),
     "Medina Express aprobó tu oferta", "Árbol de levas · ya la ve el comprador.", "sell", None),
    ("MOSTRADOR_FOLIO_SHARED", nc.create_mostrador_folio_shared_notification,
     dict(store_name="AUTOPARTES ALEX", piece_count=5, vehicle="Jeep J10 1980", meta_data={"folioId": "f1"}),
     "Autopartes Alex te mandó una cotización", "5 piezas · Jeep J10 1980", "buy", "folio:f1:open"),
    ("MOSTRADOR_FOLIO_ASSIGNED", nc.create_mostrador_folio_assigned_notification,
     dict(store_name="AUTOPARTES ALEX", piece_count=3, vehicle="Jeep J10 1980", meta_data={"folioId": "f2"}),
     "Autopartes Alex te pasó una lista", "3 piezas · Jeep J10 1980", "buy", "folio:f2:open"),
    ("MOSTRADOR_OPTION_ADDED", nc.create_mostrador_option_added_notification,
     dict(message="legacy", store_name="AUTOPARTES ALEX", part_name="Árbol De Levas", price=380),
     "Autopartes Alex agregó una opción", "Árbol de levas · $380", "buy", None),
    ("MOSTRADOR_ORDER_CREATED", nc.create_mostrador_order_created_notification,
     dict(store_name="AUTOPARTES ALEX", part_name="Árbol De Levas", order_id=ORDER, price=450),
     "Pediste en el mostrador de Autopartes Alex", "Árbol de levas · $450", "buy", None),
    ("MOSTRADOR_SHOP_INVITED", nc.create_mostrador_shop_invited_notification,
     dict(inviter_name="AUTOPARTES ALEX", piece_count=3, vehicle="Jeep J10 1980"),
     "Autopartes Alex te invita a cotizar su lista", "3 piezas · Jeep J10 1980", "sell", None),
]


@pytest.mark.parametrize("code,builder,kwargs,title,body,side,decision", CASES, ids=[c[0] for c in CASES])
def test_builder_copy(code, builder, kwargs, title, body, side, decision):
    n = builder(**{**COMMON, **kwargs})
    assert (n.title, n.body, n.side, n.decision_key) == (title, body, side, decision)
    assert n.message == f"{title}. {body}"
    assert not re.search(r"[0-9a-f]{24}", n.message)
    assert "¡" not in n.message and "Felicidades" not in n.message and "sorpréndelos" not in n.message
    assert not re.search(r"\b[A-ZÁÉÍÓÚÑ]{4,}\b", n.message)


def test_relationship_reminder_copy():
    n = nc.create_relationship_review_reminder(owner="u1", owner_group="g1")
    assert n.title == "Revisa tus relaciones"
    assert n.body == "Mira con qué tiendas trabajas y a quién te falta responder."


def test_missing_optional_data_drops_that_part_of_the_body():
    n = nc.create_offer_notification(store_name="AUTOPARTES ALEX", part_name="Alternador", **COMMON)
    assert n.body == "Alternador"
    n = nc.create_order_confirmed_notification(store_name="AUTOPARTES ALEX", part_name="Alternador", order_id=ORDER, **COMMON)
    assert n.body == "Alternador"


def test_local_time_label_uses_mexico_city():
    assert local_time_label(TIME) == "3:17 p. m."
    assert local_time_label("2026-11-23T21:17:00Z") == "3:17 p. m."
    assert local_time_label("2026-11-23T14:05:00Z") == "8:05 a. m."
    assert local_time_label(None) == ""


def test_single_request_invite_settles_when_the_store_quotes():
    n = nc.create_part_request_invite_notification(
        inviter_group_name="TALLER HERNANDEZ", inviter_user="u9", owner="u1", owner_group="g1", navigate_to_url="/x",
        meta_data={"partRequests": [{"_id": "r9", "vehicleInformation": {}}]})
    assert n.decision_key == "request:r9:quote:g1"
