from unittest.mock import patch

import pytest
from fastapi import HTTPException


@patch("app.services.MostradorFolioService.assign_to_group")
@patch("app.services.MostradorFolioService.folioRepository")
def test_business_assignment_uses_the_same_client_on_each_open_sibling(mock_repo, mock_assign):
    from app.services.MostradorFolioService import _assign_same_client_to_siblings

    source = {"_id": "cheyenne", "sibling_uid": "sib"}
    tsuru = {
        "_id": "tsuru",
        "sibling_uid": "sib",
        "customer": {"type": "guest", "name": "Taller López"},
        "pieces": [{"piece_id": "faro", "status": "pendiente"}],
    }
    already_other = {
        "_id": "other",
        "sibling_uid": "sib",
        "customer": {"group_id": "someone-else", "name": "Otro"},
        "part_request_ids": ["pr-9"],
    }
    mock_repo.find_by_sibling_uid.return_value = [source, tsuru, already_other]
    customer = {"type": "eassymo", "name": "Refa Alex", "group_id": "alex"}

    _assign_same_client_to_siblings(source, "alex", True, customer)

    mock_assign.assert_called_once_with("tsuru", "alex", True, include_siblings=False)


@patch("app.dependencies.group_auth.assert_group_membership")
@patch("app.services.MostradorFolioService.get_by_share_token", return_value={"ok": True})
@patch("app.services.MostradorFolioService.folioRepository")
def test_label_copies_name_onto_each_sibling_without_assigning(mock_repo, _mock_get, mock_member):
    from app.services.MostradorFolioService import label_customer_on_folio

    cheyenne = {
        "_id": "cheyenne",
        "share_token": "tok",
        "sibling_uid": "sib",
        "origin_group_id": "shop-1",
        "customer": {"type": "guest"},
        "status": "draft",
    }
    tsuru = {
        "_id": "tsuru",
        "share_token": "tok-2",
        "sibling_uid": "sib",
        "origin_group_id": "shop-1",
        "customer": {"type": "guest", "phone": "6140000000"},
        "status": "draft",
    }
    mock_repo.find_by_id.return_value = cheyenne
    mock_repo.find_by_sibling_uid.return_value = [cheyenne, tsuru]

    label_customer_on_folio("cheyenne", "  Taller   López ", "seller-1")
    mock_member.assert_called_once_with("seller-1", "shop-1")

    assert mock_repo.edit.call_count == 2
    for call in mock_repo.edit.call_args_list:
        patch_doc = call.args[1]
        assert patch_doc["customer"]["name"] == "Taller López"
        assert "status" not in patch_doc
    assert mock_repo.edit.call_args_list[1].args[1]["customer"]["phone"] == "6140000000"


@patch("app.dependencies.group_auth.assert_group_membership")
@patch("app.services.MostradorFolioService.get_by_share_token", return_value={"ok": True})
@patch("app.services.MostradorFolioService.folioRepository")
def test_label_skips_a_sibling_already_assigned_to_a_business(mock_repo, _mock_get, _mock_member):
    from app.services.MostradorFolioService import label_customer_on_folio

    open_draft = {
        "_id": "open",
        "share_token": "tok",
        "sibling_uid": "sib",
        "origin_group_id": "shop-1",
        "customer": {"type": "guest"},
    }
    assigned = {
        "_id": "assigned",
        "share_token": "tok-2",
        "sibling_uid": "sib",
        "customer": {"type": "eassymo", "name": "Refa Alex", "group_id": "g-1"},
        "part_request_ids": ["pr-1"],
    }
    mock_repo.find_by_id.return_value = open_draft
    mock_repo.find_by_sibling_uid.return_value = [open_draft, assigned]

    label_customer_on_folio("open", "Taller López", "seller-1")

    assert mock_repo.edit.call_count == 1
    assert mock_repo.edit.call_args.args[0] == "open"


@patch("app.dependencies.group_auth.assert_group_membership")
@patch("app.services.MostradorFolioService.folioRepository")
def test_label_rejects_a_blank_name(mock_repo, _mock_member):
    from app.services.MostradorFolioService import label_customer_on_folio

    mock_repo.find_by_id.return_value = {
        "_id": "cheyenne",
        "origin_group_id": "shop-1",
        "customer": {"type": "guest"},
    }
    with pytest.raises(HTTPException) as raised:
        label_customer_on_folio("cheyenne", "   ", "seller-1")
    assert raised.value.status_code == 400
    mock_repo.edit.assert_not_called()


@patch("app.dependencies.group_auth.assert_group_membership")
@patch("app.services.MostradorFolioService.folioRepository")
def test_label_rejects_an_assigned_draft(mock_repo, _mock_member):
    from app.services.MostradorFolioService import label_customer_on_folio

    mock_repo.find_by_id.return_value = {
        "_id": "assigned",
        "origin_group_id": "shop-1",
        "customer": {"group_id": "g-1", "name": "Refa Alex"},
    }
    with pytest.raises(HTTPException) as raised:
        label_customer_on_folio("assigned", "Otro", "seller-1")
    assert raised.value.status_code == 409
    mock_repo.edit.assert_not_called()


@patch("app.services.MostradorFolioService._hydrate", side_effect=lambda doc: doc)
@patch("app.services.MostradorFolioService.folioRepository")
def test_update_persists_whatsapp_pending_questions(mock_repo, _mock_hydrate):
    from app.services.MostradorFolioService import update

    mock_repo.find_by_id.return_value = {
        "_id": "folio-1",
        "status": "draft",
        "pieces": [],
        "participant_shops": [],
        "order_ids": [],
        "whatsapp_pending_questions": [],
    }
    mock_repo.edit.side_effect = lambda folio_id, data: {"_id": folio_id, **data}
    question = {
        "id": "q1",
        "path": "piece:p1.position",
        "piece_id": "p1",
        "prompt": "¿Las balatas del Chevrolet Cheyenne son delanteras o traseras?",
        "copy_text": "¿Las balatas del Chevrolet Cheyenne son delanteras o traseras?",
        "severity": "warning",
        "status": "open",
        "source": "catalog_position",
    }

    update("folio-1", {"whatsapp_pending_questions": [question]})

    saved = mock_repo.edit.call_args.args[1]
    assert saved["whatsapp_pending_questions"][0]["severity"] == "warning"
    assert "balatas" in saved["whatsapp_pending_questions"][0]["copy_text"].lower()
