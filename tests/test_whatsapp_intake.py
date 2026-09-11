from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.WhatsappExtraction import ExtractionIntent, ExtractionVehicle, WhatsappExtractionProposal
from app.services.LlmExtractionService import LlmExtractionService
from app.services.WhatsappIntakeVerificationService import WhatsappIntakeVerificationService, _hash_token
from app.services.WhatsappSellerIdentityService import WhatsappSellerIdentityService
from app.utils.phone_normalize import normalize_phone_e164, phone_lookup_variants, phones_match


def test_normalize_mexico_mobile():
    assert normalize_phone_e164("7779313704") == "+527779313704"
    assert normalize_phone_e164("+5217779313704") == "+5217779313704"


def test_phone_variants_include_52_and_521():
    variants = phone_lookup_variants("+5217779313704")
    assert "+5217779313704" in variants
    assert "+527779313704" in variants


def test_phones_match_twilio_and_local_formats():
    assert phones_match("+5217779313704", "7779313704")
    assert phones_match("+527779313704", "+5217779313704")


def test_extraction_vehicle_coerces_year_int_to_string():
    vehicle = ExtractionVehicle.model_validate(
        {"make": "Volkswagen", "model": "Jetta", "year": 2015}
    )
    assert vehicle.year == "2015"


def test_extraction_proposal_accepts_glm_int_year():
    proposal = WhatsappExtractionProposal.model_validate(
        {
            "schema_version": "1.0",
            "intent": "new_request",
            "vehicle": {"make": "Volkswagen", "model": "Jetta", "year": 2015},
            "lines": [
                {
                    "local_id": "line_a",
                    "part_name": "balata delantera",
                    "quantity": 1,
                    "unit": "pieza",
                }
            ],
            "uncertainties": [],
            "evidence": [{"path": "vehicle.model", "raw": "Jettita", "kind": "inferred"}],
        }
    )
    assert proposal.vehicle.year == "2015"
    assert proposal.vehicle.model == "Jetta"


def test_extraction_proposal_unknown_intent():
    proposal = WhatsappExtractionProposal(intent=ExtractionIntent.UNKNOWN)
    assert proposal.intent == ExtractionIntent.UNKNOWN
    assert proposal.lines == []


def test_llm_extract_json_strips_markdown_fence():
    service = LlmExtractionService()
    parsed = service._extract_json(
        '```json\n{"schema_version":"1.0","intent":"unknown","lines":[]}\n```'
    )
    assert parsed["intent"] == "unknown"


@patch("app.services.LlmExtractionService.time.sleep")
@patch("app.services.LlmExtractionService.requests.post")
def test_llm_retries_on_429_then_succeeds(mock_post, mock_sleep):
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    success = MagicMock()
    success.status_code = 200
    success.raise_for_status.return_value = None
    success.json.return_value = {
        "choices": [{"message": {"content": '{"schema_version":"1.0","intent":"unknown","lines":[]}'}}]
    }
    mock_post.side_effect = [rate_limited, success]

    service = LlmExtractionService()
    service.api_key = "test-key"
    proposal = service.extract("Jetta 2015, filtro de aire", store_name="Tienda A")

    assert proposal.intent == ExtractionIntent.UNKNOWN
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


@patch("app.services.LlmExtractionService.time.sleep")
@patch("app.services.LlmExtractionService.requests.post")
def test_llm_raises_rate_limit_after_retries(mock_post, mock_sleep):
    from app.services.LlmExtractionService import LlmRateLimitError

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    mock_post.return_value = rate_limited

    service = LlmExtractionService()
    service.api_key = "test-key"
    service.max_retries = 2

    with pytest.raises(LlmRateLimitError):
        service.extract("Jetta 2015, filtro de aire", store_name="Tienda A")

    assert mock_post.call_count == 2


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_sends_rate_limit_message(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo
):
    from app.services.LlmExtractionService import LlmRateLimitError
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_llm_cls.return_value.extract.side_effect = LlmRateLimitError("429")

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-3",
            "message_sid": "SM429",
            "from_number": "+5217779313704",
            "body": "Jetta 2015, filtro de aire",
        }
    )

    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "ocupado" in sent.lower()
    assert mock_inbound_repo.update_fields.call_args[0][1]["extraction_status"] == "rate_limited"


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_identity_pending_link_when_user_not_verified(mock_pending, mock_user_repo, mock_group_repo):
    mock_pending.get_by_phone.return_value = None
    mock_user_repo.find_one.return_value = None
    mock_user_repo.find.return_value = []

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "Jetta 2015")

    assert result.status == "pending_link"
    assert "Mi cuenta" in (result.message or "")
    mock_pending.upsert_pending.assert_called_once()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_identity_pending_selection_for_multiple_groups(mock_pending, mock_user_repo, mock_group_repo):
    mock_pending.get_by_phone.return_value = None
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "pos_whatsapp": "+5217779313704"}
    mock_user_repo.find.return_value = []
    mock_group_repo.find_by_user.return_value = [
        {"_id": "g1", "name": "Tienda A"},
        {"_id": "g2", "name": "Tienda B"},
    ]

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "filtro de aire")

    assert result.status == "pending_selection"
    assert result.candidates is not None
    assert len(result.candidates) == 2


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_identity_resolves_single_group(mock_pending, mock_user_repo, mock_group_repo):
    mock_pending.get_by_phone.return_value = None
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "pos_whatsapp": "+5217779313704"}
    mock_user_repo.find.return_value = []
    mock_group_repo.find_by_user.return_value = [
        {"_id": "g1", "name": "Tienda A"},
    ]

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "Jetta 2015, filtro")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    mock_pending.clear.assert_called_once()


@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
@patch("app.services.WhatsappIntakeVerificationService.WhatsappService")
def test_start_sends_template_with_name_and_token(mock_whatsapp_service, mock_user_repo, mock_verify_repo):
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "name": "Ian"}
    mock_verify_repo.find_open_by_uid.return_value = None
    mock_verify_repo.count_distinct_phones.return_value = 0
    mock_verify_repo.list_starts_since.return_value = []
    mock_whatsapp_service.return_value.send_template_message.return_value = {
        "message_sid": "SM123",
    }

    service = WhatsappIntakeVerificationService()
    service.template_sid = "HXtest"
    service.start("uid-1", "7779313704")

    sent_message = mock_whatsapp_service.return_value.send_template_message.call_args[0][0]
    assert sent_message.template.variables[0] == "Ian"
    assert len(sent_message.template.variables[1]) >= 16


@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
@patch("app.services.WhatsappIntakeVerificationService.WhatsappService")
def test_confirm_writes_user_pos_whatsapp(mock_whatsapp_service, mock_user_repo, mock_verify_repo):
    token = "abc123token"
    pending = {
        "uid": "uid-1",
        "phone": "+5217779313704",
        "token_hash": _hash_token(token),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "consumed_at": None,
    }
    mock_verify_repo.find_by_token_hash.return_value = pending
    mock_user_repo.find_one.return_value = None

    service = WhatsappIntakeVerificationService()
    service.template_sid = "HXtest"
    result = service.confirm("uid-1", token)

    assert result["pos_whatsapp"] == "+5217779313704"
    mock_user_repo.update_user.assert_called_once()
    mock_verify_repo.mark_consumed.assert_called_once()


@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
def test_confirm_rejects_wrong_uid(mock_user_repo, mock_verify_repo):
    token = "abc123token"
    pending = {
        "uid": "uid-owner",
        "phone": "+5217779313704",
        "token_hash": _hash_token(token),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "consumed_at": None,
    }
    mock_verify_repo.find_by_token_hash.return_value = pending

    service = WhatsappIntakeVerificationService()
    with pytest.raises(HTTPException) as exc:
        service.confirm("uid-other", token)
    assert exc.value.status_code == 403


@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
def test_get_status_returns_open_pending(mock_user_repo, mock_verify_repo):
    now = datetime.now(timezone.utc)
    open_pending = {
        "phone": "+527779313704",
        "expires_at": now + timedelta(minutes=8),
        "created_at": now - timedelta(minutes=3),
        "last_sent_at": now - timedelta(minutes=3),
    }
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "pos_whatsapp": None}
    mock_verify_repo.find_open_by_uid.return_value = open_pending
    mock_verify_repo.count_distinct_phones.return_value = 1

    service = WhatsappIntakeVerificationService()
    result = service.get_status("uid-1")

    assert result["verified"] is False
    assert result["pending"]["phone"] == "+527779313704"
    assert result["pending"]["masked_phone"] == "***3704"
    assert result["pending"]["can_change"] is True
    assert result["pending"]["can_resend"] is True


@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
@patch("app.services.WhatsappIntakeVerificationService.WhatsappService")
def test_start_allows_second_distinct_phone(mock_whatsapp_service, mock_user_repo, mock_verify_repo):
    now = datetime.now(timezone.utc)
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "name": "Ian"}
    mock_verify_repo.find_open_by_uid.return_value = {
        "phone": "+527779111111",
        "created_at": now - timedelta(minutes=5),
        "last_sent_at": now - timedelta(minutes=5),
    }
    mock_verify_repo.count_distinct_phones.return_value = 1
    mock_verify_repo.list_starts_since.return_value = [{"phone": "+527779111111", "created_at": now - timedelta(minutes=5)}]
    mock_whatsapp_service.return_value.send_template_message.return_value = {"message_sid": "SM123"}

    service = WhatsappIntakeVerificationService()
    service.template_sid = "HXtest"
    service.start("uid-1", "7779222222")

    mock_verify_repo.supersede_open.assert_called_once()
    mock_whatsapp_service.return_value.send_template_message.assert_called_once()


@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
@patch("app.services.WhatsappIntakeVerificationService.WhatsappService")
def test_start_blocks_third_distinct_phone(mock_whatsapp_service, mock_user_repo, mock_verify_repo):
    now = datetime.now(timezone.utc)
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "name": "Ian"}
    mock_verify_repo.find_open_by_uid.return_value = None
    mock_verify_repo.count_distinct_phones.return_value = 2
    mock_verify_repo.list_starts_since.return_value = [
        {"phone": "+527779111111", "created_at": now - timedelta(minutes=20)},
        {"phone": "+527779222222", "created_at": now - timedelta(minutes=10)},
    ]

    service = WhatsappIntakeVerificationService()
    service.template_sid = "HXtest"
    with pytest.raises(HTTPException) as exc:
        service.start("uid-1", "7779333333")
    assert exc.value.status_code == 429
    mock_whatsapp_service.return_value.send_template_message.assert_not_called()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_identity_resolves_store_selection_with_just_selected(mock_pending, mock_user_repo, mock_group_repo):
    mock_pending.get_by_phone.return_value = {
        "candidates": [
            {"group_id": "g1", "name": "Tienda A"},
            {"group_id": "g2", "name": "Tienda B"},
        ],
        "creator_uid": "uid-1",
    }

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "1")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    assert result.group_name == "Tienda A"
    assert result.just_selected is True
    mock_pending.set_selected_store.assert_called_once()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
@pytest.mark.parametrize("command", ["cambiar", "menu", "menú", "atras", "atrás"])
def test_change_store_commands_clear_selection_and_resend_list(
    mock_pending, mock_user_repo, mock_group_repo, command
):
    candidates = [
        {"group_id": "g1", "name": "Tienda A"},
        {"group_id": "g2", "name": "Tienda B"},
    ]
    mock_pending.get_by_phone.return_value = {
        "selected_group_id": "g1",
        "candidates": candidates,
        "creator_uid": "uid-1",
    }

    result = WhatsappSellerIdentityService().resolve("+5217779313704", command)

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    assert "Tienda B" in (result.message or "")
    mock_pending.clear_selected_store.assert_called_once()


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_sends_store_confirmation_without_extract(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=True,
        message=None,
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-1",
            "message_sid": "SM123",
            "from_number": "+5217779313704",
            "body": "1",
        }
    )

    mock_llm_cls.return_value.extract.assert_not_called()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "Tienda confirmada: Tienda A" in sent
    assert "Si te equivocaste, escribe CAMBIAR, MENU o ATRAS" in sent


@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.MySQLSessionLocal", None)
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_extracts_after_sticky_store(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionLine,
        ExtractionVehicle,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aire", quantity=1)],
        vehicle=ExtractionVehicle(make="Volkswagen", model="Jetta", year="2015"),
    )
    mock_folio_service.create.return_value = {"_id": "folio-1", "share_token": "share-abc"}
    mock_folio_service._normalize_vehicle.return_value = {
        "maker": "Volkswagen",
        "model": "Jetta",
        "year": 2015,
    }

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.client_base_url = "https://www.eassymo.mx"
    service.process_inbound(
        {
            "mongo_id": "in-2",
            "message_sid": "SM456",
            "from_number": "+5217779313704",
            "body": "Jetta 2015, filtro de aire",
        }
    )

    mock_llm_cls.return_value.extract.assert_called_once()
    mock_folio_service.create.assert_called_once()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "Borrador listo" in sent
    assert "whatsapp-draft/share-abc" in sent


@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_asks_clarification_from_uncertainty(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionUncertainty,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.UNKNOWN,
        uncertainties=[
            ExtractionUncertainty(
                path="vehicle.model",
                reason="¿Es un Volkswagen Jetta 2015?",
            )
        ],
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-4",
            "message_sid": "SM789",
            "from_number": "+5217779313704",
            "body": "Una balata delantera pa un Jettita 2015",
        }
    )

    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert sent == "¿Es un Volkswagen Jetta 2015?"



@patch("app.services.WhatsappIntakeVerificationService.verify_repo")
@patch("app.services.WhatsappIntakeVerificationService.userRepository")
@patch("app.services.WhatsappIntakeVerificationService.WhatsappService")
def test_start_same_number_resend_does_not_hit_change_cap(mock_whatsapp_service, mock_user_repo, mock_verify_repo):
    now = datetime.now(timezone.utc)
    mock_user_repo.find_one.return_value = {"uid": "uid-1", "name": "Ian"}
    mock_verify_repo.find_open_by_uid.return_value = {
        "phone": "+527779313704",
        "created_at": now - timedelta(minutes=5),
        "last_sent_at": now - timedelta(minutes=5),
    }
    mock_verify_repo.count_distinct_phones.return_value = 2
    mock_verify_repo.list_starts_since.return_value = [
        {"phone": "+527779313704", "created_at": now - timedelta(minutes=20)},
        {"phone": "+527779222222", "created_at": now - timedelta(minutes=10)},
    ]
    mock_whatsapp_service.return_value.send_template_message.return_value = {"message_sid": "SM123"}

    service = WhatsappIntakeVerificationService()
    service.template_sid = "HXtest"
    service.start("uid-1", "7779313704")

    mock_verify_repo.supersede_open.assert_called_once()
    mock_whatsapp_service.return_value.send_template_message.assert_called_once()
