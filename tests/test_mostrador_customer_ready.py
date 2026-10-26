from app.services.mostrador_customer_ready import (
    customer_can_view,
    customer_view_only,
    diff_since_ready,
    edition_update,
)


def test_new_draft_stays_hidden_until_the_seller_marks_it():
    draft = {"status": "draft", "pieces": [{"piece_id": "p1", "name": "Sensor"}]}
    assert customer_can_view(draft) is False
    assert customer_view_only(draft) is False


def test_explicit_ready_is_view_only_until_share():
    ready = {"status": "draft", "customer_ready": True}
    assert customer_can_view(ready) is True
    assert customer_view_only(ready) is True


def test_shared_folio_keeps_the_order_flow():
    shared = {"status": "shared"}
    assert customer_can_view(shared) is True
    assert customer_view_only(shared) is False
    ready_then_shared = {"status": "shared", "customer_ready": True}
    assert customer_view_only(ready_then_shared) is False


def test_edition_lists_a_price_change_and_advances_the_baseline():
    doc = {
        "customer_ready": True,
        "customer_visible_baseline": {
            "pieces": [
                {
                    "piece_id": "p1",
                    "name": "Sensor de detonación",
                    "qty": 1,
                    "options": [{"brand": "Bosch", "price": 400}],
                }
            ],
            "vehicle": {"maker": "Chevrolet", "model": "Cheyenne", "year": "2020"},
        },
        "customer_editions": [],
    }
    pieces = [
        {
            "piece_id": "p1",
            "name": "Sensor de detonación",
            "qty": 1,
            "options": [{"brand": "Bosch", "price": 450}],
        }
    ]
    patch = edition_update(doc, pieces, doc["customer_visible_baseline"]["vehicle"])
    assert patch is not None
    assert patch["customer_editions"][0]["changes"] == [
        {
            "label": "Sensor de detonación",
            "detail": "Opciones: Bosch $400 → Bosch $450",
        }
    ]
    assert patch["customer_visible_baseline"]["pieces"] == pieces


def test_second_edition_keeps_the_previous_one():
    doc = {
        "customer_ready": True,
        "customer_visible_baseline": {
            "pieces": [{"piece_id": "p1", "name": "Sensor", "qty": 1, "options": []}],
            "vehicle": None,
        },
        "customer_editions": [
            {"at": "2026-10-26T15:00:00+00:00", "changes": [{"label": "Sensor", "detail": "Pieza agregada"}]}
        ],
    }
    patch = edition_update(
        doc,
        [{"piece_id": "p1", "name": "Sensor", "qty": 2, "options": []}],
        None,
    )
    assert len(patch["customer_editions"]) == 2
    assert patch["customer_editions"][1]["changes"][0]["detail"] == "Cantidad: 1 → 2"


def test_diff_reports_added_and_removed_pieces():
    changes = diff_since_ready(
        [{"piece_id": "old", "name": "Filtro"}],
        [{"piece_id": "new", "name": "Sensor"}],
        None,
        None,
    )
    details = [change["detail"] for change in changes]
    assert "Pieza agregada" in details
    assert "Pieza eliminada" in details
