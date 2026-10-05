"""Tests for WhatsApp clarification helpers and intake clarifications."""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from app.schemas.WhatsappExtraction import (
    ExtractionEvidence,
    ExtractionIntent,
    ExtractionLine,
    ExtractionUncertainty,
    ExtractionVehicle,
    WhatsappExtractionProposal,
)
from app.services import WhatsappClarificationService as clarify


def test_derive_position_question_for_catalog_piece_without_position():
    folio = {
        "folio_code": "ABC123",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018", "engine": "1.6"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "position": "No aplica",
                "qty": 1,
            }
        ],
        "whatsapp_pending_questions": [],
    }
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="balatas", quantity=1)],
        vehicle=ExtractionVehicle(make="Nissan", model="Versa", year="2018", engine="1.6"),
    )

    questions = clarify.derive_pending_questions(folio, proposal, mysql_db=None)
    assert len(questions) == 1
    assert questions[0]["path"] == "piece:p1.position"
    assert "delanteras" in questions[0]["prompt"].lower()
    assert all("catálogo" not in q["prompt"].lower() for q in questions)
    assert all("match" not in q["prompt"].lower() for q in questions)


def test_derive_pending_questions_for_position_and_engine():
    folio = {
        "folio_code": "ABC123",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "position": "No aplica",
                "qty": 1,
            }
        ],
        "whatsapp_pending_questions": [],
    }
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="balatas", quantity=1)],
        vehicle=ExtractionVehicle(make="Nissan", model="Versa", year="2018"),
    )

    questions = clarify.derive_pending_questions(folio, proposal, mysql_db=None)
    paths = {q["path"] for q in questions}

    assert len(questions) == 2
    assert "piece:p1.position" in paths
    assert "vehicle.engine" in paths


def test_apply_position_answer_updates_piece():
    folio = {
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "position": "No aplica",
                "position_suggested": False,
            }
        ],
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
            }
        ],
    }
    question = folio["whatsapp_pending_questions"][0]
    patch, ok, detail = clarify.apply_answer_to_folio(folio, question, "delanteras")
    assert ok is True
    assert patch["pieces"][0]["position"] == "Delantera"
    assert "Delantera" in (detail or "")


def test_map_evidence_sids_skips_noise():
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[
            ExtractionLine(
                local_id="l1",
                part_name="balatas",
                quantity=1,
                raw="Necesito balatas para Versa 2018 motor 1.6",
            )
        ],
        vehicle=ExtractionVehicle(make="Nissan", model="Versa", year="2018", engine="1.6"),
        evidence=[ExtractionEvidence(path="lines[0].part_name", raw="balatas", kind="literal")],
    )
    messages = [
        {"message_sid": "SM1", "body": "jaja"},
        {
            "message_sid": "SM2",
            "body": "Necesito balatas para Versa 2018 motor 1.6",
        },
        {"message_sid": "SM3", "body": "LISTO"},
    ]
    mapped = clarify.map_evidence_sids(messages, proposal, [messages[1]["body"]])
    assert "SM2" in mapped
    assert "SM1" not in mapped
    assert "SM3" not in mapped


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.MySQLSessionLocal", None)
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
def test_create_draft_sends_position_clarification_and_link_fallback(
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    session = {
        "from_number": "+5217779313704",
        "group_id": "g1",
        "creator_uid": "uid-1",
        "group_name": "Tienda A",
        "messages": [
            {
                "message_sid": "SM1",
                "body": "Necesito balatas para Versa 2018 motor 1.6",
            }
        ],
    }
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[
            ExtractionLine(
                local_id="l1",
                part_name="balatas",
                quantity=1,
                raw="Necesito balatas para Versa 2018 motor 1.6",
            )
        ],
        vehicle=ExtractionVehicle(make="Nissan", model="Versa", year="2018", engine="1.6"),
        evidence=[ExtractionEvidence(path="lines[0].part_name", raw="balatas", kind="literal")],
    )
    created = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "ABC123",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018", "engine": "1.6"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "position": "No aplica",
                "qty": 1,
            }
        ],
        "whatsapp_pending_questions": [],
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    updated = {
        **created,
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
            }
        ],
    }

    mock_llm_cls.return_value.extract.return_value = proposal
    mock_folio_service.create.return_value = created
    mock_folio_service.update.side_effect = [updated, updated]
    mock_folio_service._normalize_vehicle.return_value = created["vehicle"]
    mock_folio_service._resolve_client_base_url.return_value = "http://localhost:3000"
    mock_inbound_repo.find_by_message_sid.return_value = {"message_sid": "SM1"}
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.side_effect = [
        {"message_sid": "SM-DRAFT"},
        {"message_sid": "SM-CLARIFY"},
    ]

    service = WhatsappIntakeProcessorService()
    service._flush_session("+5217779313704", session)

    bodies = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    mock_folio_service.create.assert_called_once()
    clarify_bodies = [body for body in bodies if "delanteras o traseras" in body.lower()]
    assert len(clarify_bodies) == 1
    assert all("catálogo" not in body.lower() for body in bodies)
    assert all("vinculado" not in body for body in bodies)
    assert "Borrador listo" in bodies[0]
    assert "delanteras" in bodies[1].lower()
    assert ":" not in bodies[0].split("?", 1)[-1]
    draft_v = bodies[0].split("?v=", 1)[1].split("\n", 1)[0]
    assert draft_v.isdigit()
    mock_whatsapp_cls.return_value.react_to_message.assert_not_called()


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
def test_handle_complement_or_answer_patches_position(
    mock_folio_service,
    mock_whatsapp_cls,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    folio = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "ABC123",
        "source": "whatsapp",
        "status": "draft",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "position": "No aplica",
                "qty": 1,
            }
        ],
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
            }
        ],
    }
    mock_folio_service.update.return_value = {
        **folio,
        "pieces": [{**folio["pieces"][0], "position": "Delantera"}],
        "whatsapp_pending_questions": [
            {**folio["whatsapp_pending_questions"][0], "status": "answered"}
        ],
        "updated_at": "2026-01-02T00:00:00+00:00",
    }
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_inbound_repo.find_by_message_sid.return_value = {"message_sid": "SM2"}
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.side_effect = [
        {"message_sid": "SM-CONFIRM"},
    ]

    service = WhatsappIntakeProcessorService()
    handled = service._handle_complement_or_answer(
        from_number="+5217779313704",
        folio=folio,
        question=folio["whatsapp_pending_questions"][0],
        answer_text="delanteras",
        message_sids=["SM2"],
        burst_id="burst-1",
        group_id="g1",
        creator_uid="uid-1",
    )

    assert handled is True
    sent = [call.args[1] for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list]
    assert all("vinculado" not in body for body in sent)
    assert "Listo · ABC123" in sent[0]
    confirm_v = sent[0].split("?v=", 1)[1].split("\n", 1)[0]
    assert confirm_v.isdigit()
    assert ":" not in sent[0].split("?", 1)[-1]
    update_payload = mock_folio_service.update.call_args.args[1]
    assert update_payload["pieces"][0]["position"] == "Delantera"
    assert update_payload["whatsapp_pending_questions"][0]["status"] == "answered"
    mock_inbound_repo.update_fields.assert_called()
    linked_updates = [
        call.args[1]
        for call in mock_inbound_repo.update_fields.call_args_list
        if call.args[1].get("linked_reaction")
    ]
    assert linked_updates
    assert linked_updates[0]["linked_reaction"]["folio_code"] == "ABC123"


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
def test_stamp_evidence_paths_links_only_request_message(mock_inbound_repo):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    request_body = "Necesito balatas para Versa 2018 motor 1.6"
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[
            ExtractionLine(
                local_id="l1",
                part_name="balatas",
                quantity=1,
                raw=request_body,
            )
        ],
        vehicle=ExtractionVehicle(make="Nissan", model="Versa", year="2018", engine="1.6"),
        evidence=[ExtractionEvidence(path="lines[0].part_name", raw="balatas", kind="literal")],
    )
    session = {
        "messages": [
            {"message_sid": "SM1", "body": "jaja"},
            {"message_sid": "SM2", "body": request_body},
            {"message_sid": "SM3", "body": "LISTO"},
        ]
    }

    service = WhatsappIntakeProcessorService()
    linked_sids = service._stamp_evidence_paths(session, proposal, [request_body])

    assert linked_sids == ["SM2"]
    assert mock_inbound_repo.update_fields.call_count == 1


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
def test_handle_complement_garbage_keeps_question_open(
    mock_folio_service,
    mock_whatsapp_cls,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    folio = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "ABC123",
        "source": "whatsapp",
        "status": "draft",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "position": "No aplica",
                "qty": 1,
            }
        ],
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
                "asked_message_sid": "SM-CLARIFY",
            }
        ],
    }
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_inbound_repo.find_by_message_sid.return_value = {"message_sid": "SM2"}
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.return_value = {
        "message_sid": "SM-ERROR",
    }

    service = WhatsappIntakeProcessorService()
    handled = service._handle_complement_or_answer(
        from_number="+5217779313704",
        folio=folio,
        question=folio["whatsapp_pending_questions"][0],
        answer_text="jaja no se",
        message_sids=["SM2"],
        burst_id="burst-1",
        group_id="g1",
        creator_uid="uid-1",
    )

    assert handled is True
    mock_folio_service.update.assert_not_called()
    sent = [call.args[1] for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list]
    assert any("Vinculado a ABC123" in body for body in sent)
    assert any("No pude aplicar" in body for body in sent)
    assert mock_whatsapp_cls.return_value.send_text_message.call_count == 1
    linked_updates = [
        call.args[1]
        for call in mock_inbound_repo.update_fields.call_args_list
        if call.args[1].get("linked_reaction")
    ]
    assert linked_updates


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
def test_handle_complement_ceramic_stores_note_and_reasks_position(
    mock_folio_service,
    mock_whatsapp_cls,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    folio = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "ABC123",
        "source": "whatsapp",
        "status": "draft",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "position": "No aplica",
                "qty": 1,
            }
        ],
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
                "asked_message_sid": "SM-CLARIFY",
            }
        ],
    }
    updated_folio = {
        **folio,
        "pieces": [{**folio["pieces"][0], "comments": "Cerámicas"}],
    }
    mock_folio_service.update.side_effect = [
        updated_folio,
        {
            **updated_folio,
            "whatsapp_pending_questions": [
                {
                    **folio["whatsapp_pending_questions"][0],
                    "asked_message_sid": "SM-REASK",
                }
            ],
        },
    ]
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_inbound_repo.find_by_message_sid.return_value = {"message_sid": "SM2"}
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.side_effect = [
        {"message_sid": "SM-ERROR"},
        {"message_sid": "SM-REASK"},
    ]

    service = WhatsappIntakeProcessorService()
    handled = service._handle_complement_or_answer(
        from_number="+5217779313704",
        folio=folio,
        question=folio["whatsapp_pending_questions"][0],
        answer_text="Y que sean ceramicas",
        message_sids=["SM2"],
        burst_id="burst-1",
        group_id="g1",
        creator_uid="uid-1",
    )

    assert handled is True
    material_update = mock_folio_service.update.call_args_list[0].args[1]
    assert material_update["pieces"][0]["comments"] == "Cerámicas"
    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert any("No pude aplicar" in body for body in sent)
    assert any("delanteras o traseras" in body.lower() for body in sent)
    assert mock_whatsapp_cls.return_value.send_text_message.call_count == 2
    reask_update = mock_folio_service.update.call_args_list[1].args[1]
    assert reask_update["whatsapp_pending_questions"][0]["asked_message_sid"] == "SM-REASK"
    assert reask_update["whatsapp_pending_questions"][0]["status"] == "open"


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
def test_apply_chain_reactions_reacts_to_all_when_requested(
    mock_whatsapp_cls,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.side_effect = lambda sid: {
        "message_sid": sid,
        "direction": "inbound",
        "kind": "content",
        "whatsapp_message_id": f"wamid.{sid}",
    }
    mock_whatsapp_cls.return_value.native_reactions_enabled = True
    mock_whatsapp_cls.return_value.react_to_message.return_value = {"success": True}

    service = WhatsappIntakeProcessorService()
    service._apply_chain_reactions(
        from_number="+5217779313704",
        folio={"_id": "folio-1", "folio_code": "ABC123"},
        message_sids=["SM1", "SM2"],
        burst_id="burst-1",
        react_all=True,
    )

    assert mock_whatsapp_cls.return_value.react_to_message.call_count == 2
    linked_updates = [
        call.args[1]
        for call in mock_inbound_repo.update_fields.call_args_list
        if call.args[1].get("linked_reaction")
    ]
    assert len(linked_updates) == 2


def test_resolve_material_note_detects_ceramicas():
    assert clarify.resolve_material_note("Y que sean ceramicas") == "Cerámicas"


def test_apply_material_note_appends_to_piece_comments():
    folio = {
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "comments": None,
            }
        ]
    }
    question = {"piece_id": "p1", "path": "piece:p1.position"}
    patch, stored = clarify.apply_material_note_to_folio(
        folio, question, "Y que sean ceramicas"
    )
    assert stored is True
    assert patch["pieces"][0]["comments"] == "Cerámicas"


def _collecting_session(**overrides):
    session = {
        "from_number": "+5217779313704",
        "status": "collecting",
        "group_id": "g1",
        "creator_uid": "uid-1",
        "group_name": "Tienda A",
        "messages": [],
        "generation": 1,
    }
    session.update(overrides)
    return session


def _open_versa_folio(**overrides):
    folio = {
        "_id": "folio-versa",
        "share_token": "share-versa",
        "folio_code": "VERSA1",
        "source": "whatsapp",
        "status": "draft",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018", "engine": "1.6"},
        "pieces": [
            {
                "piece_id": "p1",
                "name": "Balatas",
                "tipoParteId": "10",
                "qty": 1,
                "position": "No aplica",
            }
        ],
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
            }
        ],
    }
    folio.update(overrides)
    return folio


@patch("app.services.WhatsappIntakeProcessorService.pending_repo")
@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
def test_resend_matching_burst_links_both_messages_without_new_draft(
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
    mock_pending_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    existing = _open_versa_folio()
    session = _collecting_session(
        messages=[
            {
                "message_sid": "SM1",
                "body": "Necesito balatas para Versa 2018 motor 1.6",
            },
            {"message_sid": "SM2", "body": "Y que sean ceramicas"},
        ],
    )
    mock_inbound_repo.find_by_message_sid.side_effect = lambda sid: {
        "message_sid": sid,
        "direction": "inbound",
        "kind": "content",
        "whatsapp_message_id": f"wamid.{sid}",
    }
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[
            ExtractionLine(
                local_id="l1",
                part_name="balatas",
                quantity=1,
                raw="Necesito balatas para Versa 2018 motor 1.6",
            )
        ],
        vehicle=ExtractionVehicle(make="Nissan", model="Versa", year="2018", engine="1.6"),
    )
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_folio_service.get_by_share_token.return_value = existing
    mock_pending_repo.get_last_share_token.return_value = "share-versa"
    mock_whatsapp_cls.return_value.native_reactions_enabled = True
    mock_whatsapp_cls.return_value.react_to_message.return_value = {"success": True}

    with patch(
        "app.services.WhatsappIntakeProcessorService.clarify.find_drafts_with_open_questions",
        return_value=[existing],
    ):
        service = WhatsappIntakeProcessorService()
        service.extract_enabled = True
        service._flush_session("+5217779313704", session)

    mock_folio_service.create.assert_not_called()
    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert not any("Borrador listo" in body for body in sent)
    assert not any("delanteras o traseras" in body.lower() for body in sent)
    assert mock_whatsapp_cls.return_value.react_to_message.call_count == 2


@patch("app.services.WhatsappIntakeProcessorService.pending_repo")
@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.MySQLSessionLocal", None)
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
def test_resend_for_different_vehicle_still_creates_draft(
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
    mock_pending_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    existing = _open_versa_folio()
    session = _collecting_session(
        messages=[
            {
                "message_sid": "SM1",
                "body": "Necesito balatas para Jetta 2015",
            }
        ],
    )
    mock_inbound_repo.find_by_message_sid.return_value = {"_id": "mongo-1"}
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="balatas", quantity=1)],
        vehicle=ExtractionVehicle(make="Volkswagen", model="Jetta", year="2015"),
    )
    mock_folio_service.create.return_value = {
        "_id": "folio-new",
        "share_token": "share-new",
        "folio_code": "JETTA1",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    mock_folio_service.update.return_value = mock_folio_service.create.return_value
    mock_folio_service._normalize_vehicle.return_value = {
        "maker": "Volkswagen",
        "model": "Jetta",
        "year": 2015,
    }
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_folio_service.get_by_share_token.return_value = existing
    mock_pending_repo.get_last_share_token.return_value = "share-versa"
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.side_effect = [
        {"message_sid": "SM-OUT-DRAFT"},
    ]

    with patch(
        "app.services.WhatsappIntakeProcessorService.clarify.find_drafts_with_open_questions",
        return_value=[existing],
    ):
        service = WhatsappIntakeProcessorService()
        service.extract_enabled = True
        service.client_base_url = "https://www.eassymo.mx"
        service.whatsapp_public_base_url = "https://www.eassymo.mx"
        service._flush_session("+5217779313704", session)

    mock_folio_service.create.assert_called_once()
    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert any("Borrador listo" in body for body in sent)


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
def test_handle_complement_multiple_open_questions_without_link(
    mock_folio_service,
    mock_whatsapp_cls,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    folio = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "ABC123",
        "source": "whatsapp",
        "status": "draft",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018"},
        "pieces": [],
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
            },
            {
                "id": "q2",
                "path": "vehicle.engine",
                "prompt": "¿Cuál es el motor del vehículo?",
                "status": "open",
            },
        ],
    }
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_inbound_repo.find_by_message_sid.return_value = {"message_sid": "SM2"}
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.return_value = {"message_sid": "SM-ASK"}

    service = WhatsappIntakeProcessorService()
    handled = service._handle_complement_or_answer(
        from_number="+5217779313704",
        folio=folio,
        question=None,
        answer_text="1.6",
        message_sids=["SM2"],
        burst_id="burst-1",
        group_id="g1",
        creator_uid="uid-1",
    )

    assert handled is True
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args.args[1]
    assert "varias aclaraciones abiertas" in sent.lower()
    mock_folio_service.update.assert_not_called()


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
def test_resolve_complement_folio_uses_draft_token(
    mock_folio_service,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "e345073775574ed99fb22efa3627e5ce"
    folio = {
        "_id": "folio-target",
        "share_token": token,
        "folio_code": "TARGET1",
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "vehicle.engine",
                "prompt": "¿Cuál es el motor del vehículo?",
                "status": "open",
            }
        ],
    }
    mock_folio_service.get_by_share_token.return_value = folio

    service = WhatsappIntakeProcessorService()
    service.client_base_url = "http://localhost:3000"
    body = (
        "Borrador listo en Eassymo POS.\n"
        f"Revisa vehículo y piezas aquí:\nhttp://localhost:3000/whatsapp-draft/{token}\n"
        "motor 1.6"
    )
    resolved_folio, question = service._resolve_complement_folio(
        from_number="+5217779313704",
        bodies=[body],
        group_id="g1",
        creator_uid="uid-1",
    )

    assert resolved_folio["folio_code"] == "TARGET1"
    assert question["path"] == "vehicle.engine"


@patch("app.services.WhatsappClarificationService.folioRepository")
def test_resolve_complement_folio_reply_to_clarify_sid(mock_folio_repo):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    folio = {
        "_id": "folio-1",
        "folio_code": "ABC123",
        "whatsapp_pending_questions": [
            {
                "id": "q1",
                "path": "piece:p1.position",
                "piece_id": "p1",
                "prompt": "¿Son delanteras o traseras?",
                "status": "open",
                "asked_message_sid": "SM-CLARIFY",
            }
        ],
    }
    mock_folio_repo.find_by_clarify_message_sid.return_value = folio

    service = WhatsappIntakeProcessorService()
    resolved_folio, question = service._resolve_complement_folio(
        from_number="+5217779313704",
        bodies=["delanteras"],
        group_id="g1",
        creator_uid="uid-1",
        original_replied_message_sid="SM-CLARIFY",
    )

    assert resolved_folio["folio_code"] == "ABC123"
    assert question["asked_message_sid"] == "SM-CLARIFY"


@patch("app.services.WhatsappClarificationService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
def test_apply_chain_reactions_native_with_wamid(
    mock_processor_inbound_repo,
    mock_clarify_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    inbound_doc = {
        "message_sid": "SM1",
        "whatsapp_message_id": "wamid.HBgNNTIxNzc3OTMxMzcwNBUCABEYEj",
        "kind": "content",
    }
    mock_processor_inbound_repo.find_by_message_sid.return_value = inbound_doc

    service = WhatsappIntakeProcessorService()
    mock_whatsapp = MagicMock()
    mock_whatsapp.native_reactions_enabled = True
    mock_whatsapp.react_to_message.return_value = {"success": True}
    service.whatsapp_service = mock_whatsapp
    service._apply_chain_reactions(
        from_number="+5217779313704",
        folio={"_id": "folio-1", "folio_code": "ABC123"},
        message_sids=["SM1"],
        burst_id="burst-1",
    )

    mock_whatsapp.react_to_message.assert_called_once()
    mock_whatsapp.send_text_message.assert_not_called()
    stamp = mock_processor_inbound_repo.update_fields.call_args.args[1]["linked_reaction"]
    assert stamp["method"] == "native"
    assert stamp["folio_code"] == "ABC123"


def test_format_clarify_message_includes_multi_draft_hint():
    folio = {
        "folio_code": "ABC123",
        "vehicle": {"maker": "Nissan", "model": "Versa", "year": "2018"},
        "pieces": [{"piece_id": "p1", "name": "Balatas"}],
    }
    question = {
        "piece_id": "p1",
        "prompt": "¿Son delanteras o traseras?",
    }

    body = clarify.format_clarify_message(folio, question, multi_draft_hint=True)

    assert "varios borradores abiertos" in body.lower()
    assert "enlace del borrador" in body.lower()


def test_extract_whatsapp_message_id_from_channel_metadata():
    metadata = '{"messages":[{"id":"wamid.HBgNNTIxNzc3OTMxMzcwNBUCABEYEj"}]}'
    assert (
        clarify.extract_whatsapp_message_id(metadata)
        == "wamid.HBgNNTIxNzc3OTMxMzcwNBUCABEYEj"
    )


def test_cache_bust_version_from_iso_has_no_colons():
    from app.services.WhatsappIntakeProcessorService import _cache_bust_version

    token = _cache_bust_version("2026-09-21T22:04:41.883972Z")
    assert token
    assert token.isdigit()
    assert ":" not in token


def test_draft_preview_link_prefers_whatsapp_public_base_url():
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    service = WhatsappIntakeProcessorService()
    service.whatsapp_public_base_url = "https://wa-preview.example.com"
    service.client_base_url = "http://localhost:3000"
    link = service._draft_preview_link(
        "share-abc",
        "folio-1",
        version="2026-09-21T22:04:41.883972Z",
    )

    assert link.startswith("https://wa-preview.example.com/whatsapp-draft/share-abc?v=")
    assert ":" not in link.split("?", 1)[-1]
    assert link.split("?v=", 1)[1].isdigit()
    assert "localhost" not in link
    image = service._draft_card_image_url(
        "share-abc",
        version="2026-09-21T22:04:41.883972Z",
    )
    assert image == (
        "https://wa-preview.example.com/api/og/whatsapp-draft"
        f"?token=share-abc&v={link.split('?v=', 1)[1]}"
    )


def test_draft_card_image_url_skips_localhost():
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    service = WhatsappIntakeProcessorService()
    service.whatsapp_public_base_url = "http://localhost:3000"
    assert service._draft_card_image_url("share-abc", version="1767225600") is None


@patch.dict(os.environ, {"WHATSAPP_PUBLIC_BASE_URL": "https://wa-preview.example.com"})
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
def test_whatsapp_public_base_url_env_overrides_client(mock_folio_service):
    mock_folio_service._resolve_client_base_url.return_value = "http://localhost:3000"
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    service = WhatsappIntakeProcessorService()
    assert service.whatsapp_public_base_url == "https://wa-preview.example.com"


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
def test_apply_chain_reactions_skips_outbound_and_bot_messages(
    mock_whatsapp_cls,
    mock_inbound_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    def _doc_for_sid(sid: str) -> dict:
        docs = {
            "SM-IN": {"message_sid": "SM-IN", "direction": "inbound", "kind": "content"},
            "SM-OUT": {"message_sid": "SM-OUT", "direction": "outbound", "kind": "bot_draft"},
            "SM-CMD": {"message_sid": "SM-CMD", "direction": "inbound", "kind": "command"},
        }
        return docs.get(sid, {})

    mock_inbound_repo.find_by_message_sid.side_effect = lambda sid: _doc_for_sid(sid)
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.return_value = {"message_sid": "SM-LINK"}

    service = WhatsappIntakeProcessorService()
    service._apply_chain_reactions(
        from_number="+5217779313704",
        folio={"_id": "folio-1", "folio_code": "ABC123"},
        message_sids=["SM-IN", "SM-OUT", "SM-CMD"],
        burst_id="burst-1",
    )

    mock_whatsapp_cls.return_value.send_text_message.assert_not_called()
    mock_whatsapp_cls.return_value.react_to_message.assert_not_called()
    stamped_sids = [
        call.args[0]
        for call in mock_inbound_repo.update_fields.call_args_list
        if call.args[1].get("linked_reaction")
    ]
    assert stamped_sids == ["SM-IN"]
