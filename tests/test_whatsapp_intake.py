from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import HTTPException

from app.schemas.WhatsappExtraction import ExtractionIntent, ExtractionVehicle, WhatsappExtractionProposal
from app.services.LlmExtractionService import LlmExtractionService
from app.services.WhatsappIntakeVerificationService import WhatsappIntakeVerificationService, _hash_token
from app.services.WhatsappSellerIdentityService import WhatsappSellerIdentityService
from app.utils.phone_normalize import normalize_phone_e164, phone_lookup_variants, phones_match


def _collecting_session(
    *,
    from_number: str = "+5217779313704",
    messages=None,
    generation: int = 1,
    group_id: str = "g1",
    creator_uid: str = "uid-1",
    group_name: str = "Tienda A",
):
    return {
        "from_number": from_number,
        "status": "collecting",
        "group_id": group_id,
        "creator_uid": creator_uid,
        "group_name": group_name,
        "messages": messages or [],
        "generation": generation,
        "started_at": datetime.now(timezone.utc),
    }


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


def test_extraction_quantity_defaults_null_and_spanish_articles_to_one():
    for qty in (None, "", "un", "una", "unas", "unos", "ÚnA"):
        proposal = WhatsappExtractionProposal.model_validate(
            {
                "schema_version": "1.0",
                "intent": "new_request",
                "vehicle": {"make": "Renault", "model": "Koleos", "year": "2020"},
                "lines": [
                    {
                        "local_id": "line_a",
                        "part_name": "sensor de detonación",
                        "quantity": 1,
                    },
                    {
                        "local_id": "line_b",
                        "part_name": "balatas",
                        "quantity": qty,
                        "position": "delantera",
                    },
                ],
            }
        )
        assert proposal.lines[1].quantity == 1


def test_extraction_proposal_koleos_burst_with_null_second_qty():
    proposal = WhatsappExtractionProposal.model_validate(
        {
            "schema_version": "1.0",
            "intent": "new_request",
            "vehicle": {"make": "Renault", "model": "Koleos", "year": "2020"},
            "lines": [
                {
                    "local_id": "line_a",
                    "part_name": "sensor de detonación",
                    "quantity": 1,
                    "raw": "Un sensor de detonación porfa",
                },
                {
                    "local_id": "line_b",
                    "part_name": "balatas",
                    "quantity": None,
                    "position": "delantera",
                    "raw": "Y también unas balatas delanteras",
                },
            ],
        }
    )
    assert proposal.vehicle.model == "Koleos"
    assert proposal.lines[0].quantity == 1
    assert proposal.lines[1].quantity == 1
    assert proposal.lines[1].position == "delantera"


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


def test_llm_format_thread_single_message():
    service = LlmExtractionService()
    assert service._format_thread(["Jetta 2015, filtro"]) == "Jetta 2015, filtro"


def test_llm_format_thread_multiple_messages():
    service = LlmExtractionService()
    formatted = service._format_thread(["Jettita 2015", "balata delantera"])
    assert formatted == "[1] Jettita 2015\n[2] balata delantera"


@patch("app.services.LlmExtractionService.requests.post")
def test_llm_extract_uses_reasoning_content_when_content_empty(mock_post):
    success = MagicMock()
    success.status_code = 200
    success.raise_for_status.return_value = None
    success.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": '{"schema_version":"1.0","intent":"new_request","vehicle":{"make":"Volkswagen","model":"Jetta","year":"2015"},"lines":[{"local_id":"line_a","part_name":"balatas","quantity":1}]}',
                }
            }
        ]
    }
    mock_post.return_value = success

    service = LlmExtractionService()
    service.api_key = "test-key"
    proposal = service.extract(
        ["Te encargo pa un jettita", "2015", "Unas balatas delanteras"],
        store_name="Tienda A",
    )

    assert proposal.intent == ExtractionIntent.NEW_REQUEST
    assert proposal.vehicle.model == "Jetta"
    assert proposal.lines[0].part_name == "balatas"


@patch("app.services.LlmExtractionService.requests.post")
def test_llm_extract_retries_empty_then_repairs_with_original_thread(mock_post):
    empty = MagicMock()
    empty.status_code = 200
    empty.raise_for_status.return_value = None
    empty.json.return_value = {"choices": [{"message": {"content": ""}}]}
    repaired = MagicMock()
    repaired.status_code = 200
    repaired.raise_for_status.return_value = None
    repaired.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"schema_version":"1.0","intent":"new_request","lines":[{"local_id":"line_a","part_name":"balatas","quantity":1}]}'
                }
            }
        ]
    }
    mock_post.side_effect = [empty, empty, repaired]

    service = LlmExtractionService()
    service.api_key = "test-key"
    proposal = service.extract(
        ["Te encargo pa un jettita", "2015", "Unas balatas delanteras"],
        store_name="Tienda A",
    )

    assert proposal.intent == ExtractionIntent.NEW_REQUEST
    repair_prompt = mock_post.call_args_list[-1].kwargs["json"]["messages"][1]["content"]
    assert "Te encargo pa un jettita" in repair_prompt
    assert "new_request" in repair_prompt


@patch("app.services.LlmExtractionService.requests.post")
def test_llm_extract_accepts_message_list(mock_post):
    success = MagicMock()
    success.status_code = 200
    success.raise_for_status.return_value = None
    success.json.return_value = {
        "choices": [{"message": {"content": '{"schema_version":"1.0","intent":"unknown","lines":[]}'}}]
    }
    mock_post.return_value = success

    service = LlmExtractionService()
    service.api_key = "test-key"
    service.extract(["msg1", "msg2"], store_name="Tienda A")

    user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "[1] msg1" in user_content
    assert "[2] msg2" in user_content


@patch("app.services.LlmExtractionService.requests.post")
def test_llm_extract_includes_known_vehicle_context(mock_post):
    success = MagicMock()
    success.status_code = 200
    success.raise_for_status.return_value = None
    success.json.return_value = {
        "choices": [{"message": {"content": '{"schema_version":"1.0","intent":"new_request","lines":[{"local_id":"l1","part_name":"filtro de aire","quantity":1}]}'}}]
    }
    mock_post.return_value = success

    service = LlmExtractionService()
    service.api_key = "test-key"
    service.extract(
        ["y también agrega un filtro de aire please"],
        store_name="Tienda A",
        known_vehicle="2020 Renault Koleos",
    )

    user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "2020 Renault Koleos" in user_content
    assert "NO lo pongas en uncertainties" in user_content


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


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_sends_rate_limit_message(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.services.LlmExtractionService import LlmRateLimitError
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    payload = {
        "mongo_id": "in-3",
        "message_sid": "SM429",
        "from_number": "+5217779313704",
        "body": "Jetta 2015, filtro de aire",
    }
    session = _collecting_session(
        messages=[{"message_sid": "SM429", "body": payload["body"]}],
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = None
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_llm_cls.return_value.extract.side_effect = LlmRateLimitError("429")

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(payload)
    mock_llm_cls.return_value.extract.assert_not_called()

    mock_session_repo.get_by_phone.return_value = session
    service.flush_if_ready(payload["from_number"], 1)

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


def _sticky_pending(**overrides):
    candidates = [
        {"group_id": "g1", "name": "Tienda A"},
        {"group_id": "g2", "name": "Tienda B"},
    ]
    base = {
        "selected_group_id": "g1",
        "candidates": candidates,
        "creator_uid": "uid-1",
    }
    base.update(overrides)
    return base


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_sticky_store_with_recent_activity_still_resolves_and_touches(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "balatas delanteras")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    assert result.group_name == "Tienda A"
    mock_pending.touch_last_inbound.assert_called_once()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_sticky_store_expires_after_inactivity_and_reprompts_selection(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=13),
    )

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "balatas delanteras")

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    assert "Tienda B" in (result.message or "")
    mock_pending.clear_selected_store.assert_called_once()
    mock_pending.touch_last_inbound.assert_not_called()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_sticky_store_without_last_inbound_starts_clock_without_expiring(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = _sticky_pending()

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "balatas delanteras")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    mock_pending.clear_selected_store.assert_not_called()
    mock_pending.touch_last_inbound.assert_called_once()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_change_store_still_works_with_recent_activity(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "cambiar")

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    mock_pending.clear_selected_store.assert_called_once()
    mock_pending.touch_last_inbound.assert_not_called()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_sticky_store_concurrent_expiry_only_first_prompt_sends_list(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=13),
    )
    mock_pending.claim_identity_prompt.return_value = False

    result = WhatsappSellerIdentityService().resolve("+5217779313704", "2020")

    assert result.status == "pending_selection"
    assert result.message is None
    mock_pending.clear_selected_store.assert_called_once()
    mock_pending.claim_identity_prompt.assert_called_once()
    mock_user_repo.find_one.assert_not_called()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_pending_selection_does_not_reprompt_for_content_burst(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = {
        "candidates": [
            {"group_id": "g1", "name": "Tienda A"},
            {"group_id": "g2", "name": "Tienda B"},
        ],
        "creator_uid": "uid-1",
    }
    mock_pending.claim_identity_prompt.return_value = False

    result = WhatsappSellerIdentityService().resolve(
        "+5217779313704", "Y también unas balatas delanteras"
    )

    assert result.status == "pending_selection"
    assert result.message is None
    mock_pending.upsert_pending.assert_not_called()
    mock_user_repo.find_one.assert_not_called()


@patch("app.services.WhatsappSellerIdentityService.groupRepository")
@patch("app.services.WhatsappSellerIdentityService.userRepository")
@patch("app.services.WhatsappSellerIdentityService.pending_repo")
def test_pending_selection_reprompts_after_cooldown(
    mock_pending, mock_user_repo, mock_group_repo
):
    mock_pending.get_by_phone.return_value = {
        "candidates": [
            {"group_id": "g1", "name": "Tienda A"},
            {"group_id": "g2", "name": "Tienda B"},
        ],
        "creator_uid": "uid-1",
    }
    mock_pending.claim_identity_prompt.return_value = True

    result = WhatsappSellerIdentityService().resolve(
        "+5217779313704", "Te encargo pa una koleos"
    )

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    assert "Tienda B" in (result.message or "")
    mock_pending.claim_identity_prompt.assert_called_once()


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_expired_sticky_burst_sends_store_list_once(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_session_repo.get_by_phone.return_value = None
    mock_session_repo.append_message.return_value = (
        {"status": "collecting", "group_id": "", "messages": [{}], "generation": 1},
        False,
        False,
    )
    store_list = "Tienes varias tiendas en Eassymo. Responde con el número..."
    mock_identity_cls.return_value.resolve.side_effect = [
        MagicMock(
            status="pending_selection",
            group_id=None,
            creator_uid="uid-1",
            just_selected=False,
            message=store_list,
        ),
        MagicMock(
            status="pending_selection",
            group_id=None,
            creator_uid="uid-1",
            just_selected=False,
            message=None,
        ),
        MagicMock(
            status="pending_selection",
            group_id=None,
            creator_uid="uid-1",
            just_selected=False,
            message=None,
        ),
        MagicMock(
            status="pending_selection",
            group_id=None,
            creator_uid="uid-1",
            just_selected=False,
            message=None,
        ),
    ]

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    bodies = [
        "Te encargo pa una koleos",
        "2020",
        "Un sensor de detonación porfa",
        "Y también unas balatas delanteras",
    ]
    for i, body in enumerate(bodies):
        service.process_inbound(
            {
                "mongo_id": f"in-{i}",
                "message_sid": f"SM{i}",
                "from_number": "+526141115669",
                "body": body,
            }
        )

    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert sent == [store_list]
    assert mock_session_repo.append_message.call_count == 4
    mock_llm_cls.return_value.extract.assert_not_called()


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_store_selection_flushes_messages_buffered_during_pending(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    buffered = _collecting_session(
        messages=[
            {"message_sid": "SM0", "body": "Te encargo pa una koleos"},
            {"message_sid": "SM1", "body": "2020"},
        ],
        group_id="",
        group_name="",
    )
    attached = {**buffered, "group_id": "g1", "group_name": "Tienda A"}
    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_session_repo.get_by_phone.return_value = buffered
    mock_session_repo.ensure_collecting_session.return_value = attached
    mock_session_repo.try_acquire_flush.return_value = attached
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=True,
        message=None,
    )
    mock_llm_cls.return_value.extract.return_value = MagicMock(
        vehicle=None,
        lines=[],
        uncertainties=[],
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-sel",
            "message_sid": "SM-sel",
            "from_number": "+5217779313704",
            "body": "1",
        }
    )

    mock_session_repo.ensure_collecting_session.assert_called_once()
    mock_session_repo.try_acquire_flush.assert_called_once()
    mock_llm_cls.return_value.extract.assert_called_once()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args_list[0].args[1]
    assert "Tienda confirmada: Tienda A" in sent


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_sends_store_confirmation_without_extract(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_session_repo.get_by_phone.return_value = None
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
    assert "PEDIDO" in sent
    assert "Si te equivocaste, escribe CAMBIAR, MENU o ATRAS" in sent


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
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
    mock_session_repo,
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionLine,
        ExtractionVehicle,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    payload = {
        "mongo_id": "in-2",
        "message_sid": "SM456",
        "from_number": "+5217779313704",
        "body": "Jetta 2015, filtro de aire",
    }
    session = _collecting_session(
        messages=[{"message_sid": "SM456", "body": payload["body"]}],
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = None
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aire", quantity=1)],
        vehicle=ExtractionVehicle(make="Volkswagen", model="Jetta", year="2015"),
    )
    mock_folio_service.create.return_value = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "JETTA1",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    mock_folio_service.update.return_value = mock_folio_service.create.return_value
    mock_folio_service._normalize_vehicle.return_value = {
        "maker": "Volkswagen",
        "model": "Jetta",
        "year": 2015,
    }
    mock_whatsapp_cls.return_value.native_reactions_enabled = False

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.client_base_url = "https://www.eassymo.mx"
    service.process_inbound(payload)
    mock_llm_cls.return_value.extract.assert_not_called()

    mock_session_repo.get_by_phone.return_value = session
    service.flush_if_ready(payload["from_number"], 1)

    mock_llm_cls.return_value.extract.assert_called_once_with(
        [payload["body"]],
        store_name="Tienda A",
        known_vehicle="",
    )
    mock_folio_service.create.assert_called_once()
    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert any("Borrador listo" in body for body in sent)
    assert any("whatsapp-draft/share-abc" in body for body in sent)


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_asks_clarification_from_uncertainty(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionUncertainty,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    payload = {
        "mongo_id": "in-4",
        "message_sid": "SM789",
        "from_number": "+5217779313704",
        "body": "Una balata delantera pa un Jettita 2015",
    }
    session = _collecting_session(
        messages=[{"message_sid": "SM789", "body": payload["body"]}],
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = None
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
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
    service.process_inbound(payload)
    mock_session_repo.get_by_phone.return_value = session
    service.flush_if_ready(payload["from_number"], 1)

    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert sent == "¿Es un Volkswagen Jetta 2015?"


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_buffers_burst_until_listo(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
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

    session_after_first = _collecting_session(
        messages=[{"message_sid": "SM1", "body": "Jettita 2015"}],
        generation=1,
    )
    session_after_second = _collecting_session(
        messages=[
            {"message_sid": "SM1", "body": "Jettita 2015"},
            {"message_sid": "SM2", "body": "jaja está bien jodido"},
        ],
        generation=1,
    )

    mock_session_repo.open_session.return_value = session_after_first
    mock_session_repo.ensure_collecting_session.return_value = session_after_first
    mock_session_repo.append_message.side_effect = [
        (session_after_first, False, True),
        (session_after_second, False, False),
        (session_after_second, False, False),
    ]
    mock_session_repo.try_acquire_flush.return_value = session_after_second
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.UNKNOWN,
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True

    mock_session_repo.get_by_phone.return_value = None
    service.process_inbound(
        {
            "mongo_id": "in-a",
            "message_sid": "SM0",
            "from_number": "+5217779313704",
            "body": "PEDIDO",
        }
    )

    mock_session_repo.get_by_phone.return_value = None
    service.process_inbound(
        {
            "mongo_id": "in-b",
            "message_sid": "SM1",
            "from_number": "+5217779313704",
            "body": "Jettita 2015",
        }
    )

    mock_session_repo.get_by_phone.return_value = session_after_first
    service.process_inbound(
        {
            "mongo_id": "in-c",
            "message_sid": "SM2",
            "from_number": "+5217779313704",
            "body": "jaja está bien jodido",
        }
    )

    mock_llm_cls.return_value.extract.assert_not_called()

    mock_session_repo.get_by_phone.return_value = session_after_second
    mock_session_repo.bump_generation.return_value = {
        **session_after_second,
        "generation": 2,
    }
    service.process_inbound(
        {
            "mongo_id": "in-d",
            "message_sid": "SM3",
            "from_number": "+5217779313704",
            "body": "LISTO",
        }
    )

    mock_session_repo.bump_generation.assert_called_once()
    mock_llm_cls.return_value.extract.assert_called_once()
    bodies = mock_llm_cls.return_value.extract.call_args[0][0]
    assert bodies == [
        "Jettita 2015",
        "jaja está bien jodido",
    ]


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_if_ready_ignores_stale_generation(
    mock_identity_cls, mock_llm_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    session = _collecting_session(
        messages=[{"message_sid": "SM1", "body": "Jetta 2015"}],
        generation=2,
    )
    mock_session_repo.get_by_phone.return_value = session

    service = WhatsappIntakeProcessorService()
    service.flush_if_ready("+5217779313704", 1)

    mock_session_repo.try_acquire_flush.assert_not_called()
    mock_llm_cls.return_value.extract.assert_not_called()


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_process_inbound_cancel_clears_burst(
    mock_identity_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
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
    mock_session_repo.get_by_phone.return_value = _collecting_session(
        messages=[{"message_sid": "SM1", "body": "Jetta 2015"}],
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-x",
            "message_sid": "SMX",
            "from_number": "+5217779313704",
            "body": "CANCELAR",
        }
    )

    mock_session_repo.delete_session.assert_called_once_with("+5217779313704")
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "cancelada" in sent.lower()


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_change_store_during_collecting_clears_session(
    mock_identity_cls, mock_whatsapp_cls, mock_inbound_repo, mock_session_repo
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="pending_selection",
        group_id=None,
        creator_uid="uid-1",
        just_selected=False,
        message="Tienes varias tiendas...",
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-y",
            "message_sid": "SMY",
            "from_number": "+5217779313704",
            "body": "CAMBIAR",
        }
    )

    mock_session_repo.delete_session.assert_called_once_with("+5217779313704")


def _resume_folio(**overrides):
    folio = {
        "_id": "folio-resume-1",
        "folio_code": "RESUME1",
        "share_token": "e345073775574ed99fb22efa3627e5ce",
        "source": "whatsapp",
        "status": "draft",
        "origin_group_id": "g1",
        "creator_user": "uid-1",
        "vehicle": {
            "maker": "Renault",
            "model": "Koleos",
            "year": "2020",
            "engine": "2.5",
        },
        "pieces": [
            {
                "piece_id": "piece-1",
                "name": "filtro de aceite",
                "tipoParteId": "tp-1",
                "qty": 1,
                "unitOfMeasure": "Pieza",
                "position": "Delantera",
                "status": "pendiente",
                "options": [],
            }
        ],
        "customer": {"type": "guest"},
        "whatsapp_pending_questions": [],
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    folio.update(overrides)
    return folio


def test_extract_draft_token_uses_last_url():
    from app.services.WhatsappIntakeProcessorService import _extract_draft_token

    bodies = [
        "http://localhost:3000/whatsapp-draft/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "también http://localhost:3000/whatsapp-draft/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb filtro",
    ]
    assert _extract_draft_token(bodies) == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_extract_draft_token_tolerates_zero_width_and_newlines():
    from app.services.WhatsappIntakeProcessorService import _extract_draft_token, _has_draft_pointer

    token = "2121e1307ee04a868fcfcb8f9c64d05c"
    bodies = [
        (
            "Borrador listo en Eassymo POS.\n"
            "Revisa vehículo y piezas aquí:\n"
            f"http://localhost:3000/whatsapp-draft/\u200b{token}"
        )
    ]
    assert _extract_draft_token(bodies) == token
    assert _has_draft_pointer(bodies) is True
    assert _extract_draft_token(
        [f"http://localhost:3000/whatsapp-draft/\n{token}"]
    ) == token


def test_strip_draft_boilerplate_keeps_extra_content():
    from app.services.WhatsappIntakeProcessorService import _strip_draft_boilerplate

    bodies = [
        (
            "Borrador listo en Eassymo POS.\n"
            "Revisa vehículo y piezas aquí:\n"
            "http://localhost:3000/whatsapp-draft/e345073775574ed99fb22efa3627e5ce\n"
            "también un filtro de aire"
        )
    ]
    assert _strip_draft_boilerplate(bodies) == ["también un filtro de aire"]


def test_merge_vehicle_fills_missing_without_wiping_model():
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    service = WhatsappIntakeProcessorService()
    existing = {"maker": "Renault", "model": "Koleos", "year": "2020"}
    new = {"year": "2021"}
    merged = service._merge_vehicle(existing, new)
    assert merged["maker"] == "Renault"
    assert merged["model"] == "Koleos"
    assert merged["year"] == "2020"


def test_merge_pieces_preserves_options_and_appends_new_line():
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    service = WhatsappIntakeProcessorService()
    existing = [
        {
            "piece_id": "piece-1",
            "name": "filtro de aceite",
            "tipoParteId": "tp-1",
            "qty": 1,
            "options": [{"brand": "Bosch", "code": "123"}],
            "status": "cotizada",
        }
    ]
    new = [
        {
            "piece_id": "piece-new",
            "name": "filtro de aceite",
            "tipoParteId": "tp-1",
            "qty": 2,
            "comments": "cliente pidió dos",
            "status": "pendiente",
            "options": [],
        },
        {
            "piece_id": "piece-2",
            "name": "balata delantera",
            "qty": 1,
            "status": "pendiente",
            "options": [],
        },
    ]
    merged = service._merge_pieces(existing, new)
    assert len(merged) == 2
    assert merged[0]["piece_id"] == "piece-1"
    assert merged[0]["qty"] == 2
    assert merged[0]["comments"] == "cliente pidió dos"
    assert merged[0]["options"] == [{"brand": "Bosch", "code": "123"}]
    assert merged[1]["name"] == "balata delantera"


def test_resume_piece_comments_omit_vehicle_uncertainty_when_folio_has_car():
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionLine,
        ExtractionUncertainty,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    service = WhatsappIntakeProcessorService()
    service.catalog_mapper.map_lines = MagicMock(
        return_value=[
            MagicMock(
                tipo_parte_id=None,
                tipo_parte_descripcion="Filtro De Aire",
                categoria_id=None,
                sub_categoria_id=None,
                name="Filtro De Aire",
                qty=1,
                unit_of_measure="Pieza",
                position="No aplica",
                position_suggested=False,
                catalog_matched=True,
            )
        ]
    )
    proposal = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[
            ExtractionLine(
                local_id="l1",
                part_name="filtro de aire",
                quantity=1,
                raw="un filtro de aire",
            )
        ],
        uncertainties=[
            ExtractionUncertainty(
                path="vehicle",
                reason="No se especifica el vehículo. ¿Para qué auto es el filtro de aire?",
            )
        ],
    )
    pieces = service._lines_to_pieces(
        None,
        proposal,
        known_vehicle={"maker": "Renault", "model": "Koleos", "year": "2020"},
    )
    assert pieces[0]["comments"] == "un filtro de aire"
    assert "vehículo" not in (pieces[0]["comments"] or "").lower()


@patch("app.services.LlmExtractionService.requests.post")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.MySQLSessionLocal", None)
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_resumes_draft_with_extra_piece(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionLine,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "e345073775574ed99fb22efa3627e5ce"
    link = f"http://localhost:3000/whatsapp-draft/{token}"
    body = f"Borrador listo en Eassymo POS.\nRevisa vehículo y piezas aquí:\n{link}\ntambién un filtro de aire"
    session = _collecting_session(
        messages=[{"message_sid": "SM-resume-1", "body": body}],
    )
    resume_doc = _resume_folio(share_token=token)

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = session
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_folio_service.get_by_share_token.return_value = resume_doc
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_folio_service.update.return_value = resume_doc
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aire", quantity=1)],
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.client_base_url = "http://localhost:3000"
    service.catalog_mapper.map_lines = MagicMock(
        return_value=[
            MagicMock(
                tipo_parte_id=None,
                tipo_parte_descripcion="filtro de aire",
                categoria_id=None,
                sub_categoria_id=None,
                qty=1,
                unit_of_measure="Pieza",
                position="No aplica",
                position_suggested=False,
                catalog_matched=False,
            )
        ]
    )
    service.catalog_mapper.map_lines.return_value[0].name = "filtro de aire"
    service.process_inbound(
        {
            "mongo_id": "in-resume-1",
            "message_sid": "SM-resume-1",
            "from_number": "+5217779313704",
            "body": body,
        }
    )
    service.flush_if_ready("+5217779313704", 1)

    mock_llm_cls.return_value.extract.assert_called_once_with(
        ["también un filtro de aire"],
        store_name="Tienda A",
        known_vehicle="2020 Renault Koleos",
    )
    mock_folio_service.create.assert_not_called()
    assert mock_folio_service.update.call_count >= 1
    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert any("Borrador actualizado" in body for body in sent)
    assert any(f"whatsapp-draft/{token}" in body for body in sent)


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_resume_link_only_skips_extract(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "e345073775574ed99fb22efa3627e5ce"
    link = f"http://localhost:3000/whatsapp-draft/{token}"
    body = f"Borrador listo en Eassymo POS.\nRevisa vehículo y piezas aquí:\n{link}"
    session = _collecting_session(
        messages=[{"message_sid": "SM-link-only", "body": body}],
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = session
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_folio_service.get_by_share_token.return_value = _resume_folio(share_token=token)
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.client_base_url = "http://localhost:3000"
    service.process_inbound(
        {
            "mongo_id": "in-link-only",
            "message_sid": "SM-link-only",
            "from_number": "+5217779313704",
            "body": body,
        }
    )
    service.flush_if_ready("+5217779313704", 1)

    mock_llm_cls.return_value.extract.assert_not_called()
    mock_folio_service.create.assert_not_called()
    mock_folio_service.update.assert_not_called()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "Borrador ya existe" in sent
    assert f"whatsapp-draft/{token}" in sent


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_resume_refuses_wrong_shop(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "e345073775574ed99fb22efa3627e5ce"
    link = f"http://localhost:3000/whatsapp-draft/{token}"
    body = f"{link}\ntambién un filtro"
    session = _collecting_session(
        messages=[{"message_sid": "SM-wrong-shop", "body": body}],
        group_id="g2",
        group_name="Tienda B",
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g2",
        group_name="Tienda B",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = session
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_folio_service.get_by_share_token.return_value = _resume_folio(
        share_token=token,
        origin_group_id="g1",
    )
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-wrong-shop",
            "message_sid": "SM-wrong-shop",
            "from_number": "+5217779313704",
            "body": body,
        }
    )
    service.flush_if_ready("+5217779313704", 1)

    mock_llm_cls.return_value.extract.assert_not_called()
    mock_folio_service.create.assert_not_called()
    mock_folio_service.update.assert_not_called()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "otra tienda" in sent


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_resume_refuses_confirmed_status(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "e345073775574ed99fb22efa3627e5ce"
    link = f"http://localhost:3000/whatsapp-draft/{token}"
    body = f"{link}\ntambién un filtro"
    session = _collecting_session(
        messages=[{"message_sid": "SM-confirmed", "body": body}],
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = session
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_folio_service.get_by_share_token.return_value = _resume_folio(
        share_token=token,
        status="confirmed",
    )
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-confirmed",
            "message_sid": "SM-confirmed",
            "from_number": "+5217779313704",
            "body": body,
        }
    )
    service.flush_if_ready("+5217779313704", 1)

    mock_llm_cls.return_value.extract.assert_not_called()
    mock_folio_service.create.assert_not_called()
    mock_folio_service.update.assert_not_called()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "compartido o confirmado" in sent


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.pending_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_draft_link_missing_folio_does_not_create(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_pending_repo,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "2121e1307ee04a868fcfcb8f9c64d05c"
    body = (
        "Borrador listo en Eassymo POS.\n"
        f"Revisa vehículo y piezas aquí:\nhttp://localhost:3000/whatsapp-draft/{token}\n"
        "y también agrega un filtro de aire please"
    )
    session = _collecting_session(
        messages=[{"message_sid": "SM-missing", "body": body}],
    )
    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = session
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_folio_service.get_by_share_token.side_effect = HTTPException(
        status_code=404, detail="Folio not found"
    )
    mock_pending_repo.get_last_share_token.return_value = None

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-missing",
            "message_sid": "SM-missing",
            "from_number": "+5217779313704",
            "body": body,
        }
    )
    service.flush_if_ready("+5217779313704", 1)

    mock_folio_service.create.assert_not_called()
    mock_llm_cls.return_value.extract.assert_not_called()
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert "No encontramos ese borrador" in sent


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.pending_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.MySQLSessionLocal", None)
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_vehicle_less_extras_resume_last_draft(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_pending_repo,
    mock_session_repo,
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionLine,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    token = "2121e1307ee04a868fcfcb8f9c64d05c"
    body = "y también agrega un filtro de aire please"
    session = _collecting_session(
        messages=[{"message_sid": "SM-extra-only", "body": body}],
    )
    resume_doc = _resume_folio(share_token=token)

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_inbound_repo.find_latest_share_token.return_value = token
    mock_pending_repo.get_last_share_token.return_value = token
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.return_value = session
    mock_session_repo.ensure_collecting_session.return_value = session
    mock_session_repo.append_message.return_value = (session, False, True)
    mock_session_repo.try_acquire_flush.return_value = session
    mock_folio_service.get_by_share_token.return_value = resume_doc
    mock_folio_service._is_assigned_to_buyer.return_value = False
    mock_folio_service._has_ordered_pieces.return_value = False
    mock_folio_service.update.return_value = resume_doc
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aire", quantity=1)],
    )

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.client_base_url = "http://localhost:3000"
    service.catalog_mapper.map_lines = MagicMock(
        return_value=[
            MagicMock(
                tipo_parte_id=None,
                tipo_parte_descripcion="filtro de aire",
                categoria_id=None,
                sub_categoria_id=None,
                qty=1,
                unit_of_measure="Pieza",
                position="No aplica",
                position_suggested=False,
                catalog_matched=False,
            )
        ]
    )
    service.catalog_mapper.map_lines.return_value[0].name = "filtro de aire"
    service.process_inbound(
        {
            "mongo_id": "in-extra-only",
            "message_sid": "SM-extra-only",
            "from_number": "+5217779313704",
            "body": body,
        }
    )
    service.flush_if_ready("+5217779313704", 1)

    mock_folio_service.create.assert_not_called()
    assert mock_folio_service.update.call_count >= 1
    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert any("Borrador actualizado" in body for body in sent)
    assert any(f"whatsapp-draft/{token}" in body for body in sent)


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


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.MySQLSessionLocal", None)
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_stamps_burst_and_persists_outbound_draft(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    from app.schemas.WhatsappExtraction import (
        ExtractionIntent,
        ExtractionLine,
        ExtractionVehicle,
        WhatsappExtractionProposal,
    )
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    payload = {
        "mongo_id": "in-burst",
        "message_sid": "SM-BURST-1",
        "from_number": "+5217779313704",
        "body": "Jetta 2015, filtro de aire",
    }
    session = _collecting_session(
        messages=[
            {"message_sid": "SM-BURST-1", "body": payload["body"], "forwarded": True},
            {"message_sid": "SM-BURST-LISTO", "body": "LISTO", "forwarded": False},
        ],
    )

    mock_inbound_repo.find_by_message_sid.return_value = {"_id": "mongo-1"}
    mock_llm_cls.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aire", quantity=1)],
        vehicle=ExtractionVehicle(make="Volkswagen", model="Jetta", year="2015"),
    )
    mock_folio_service.create.return_value = {
        "_id": "folio-1",
        "share_token": "share-abc",
        "folio_code": "JETTA1",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    mock_folio_service.update.return_value = mock_folio_service.create.return_value
    mock_folio_service._normalize_vehicle.return_value = {
        "maker": "Volkswagen",
        "model": "Jetta",
        "year": 2015,
    }
    mock_whatsapp_cls.return_value.native_reactions_enabled = False
    mock_whatsapp_cls.return_value.send_text_message.side_effect = [
        {"message_sid": "SM-OUT-DRAFT"},
    ]

    service = WhatsappIntakeProcessorService()
    service._flush_session(payload["from_number"], session)

    burst_updates = [
        call.args[1]
        for call in mock_inbound_repo.update_fields.call_args_list
        if call.args[1].get("burst_id")
    ]
    assert burst_updates
    burst_id = burst_updates[0]["burst_id"]
    assert mock_inbound_repo.insert_outbound.call_count >= 1
    outbound_calls = mock_inbound_repo.insert_outbound.call_args_list
    outbound_kinds = [call.args[0]["kind"] for call in outbound_calls]
    assert "bot_link" not in outbound_kinds
    assert "bot_draft" in outbound_kinds
    assert outbound_calls[0].args[0]["burst_id"] == burst_id
    mock_inbound_repo.link_burst_to_folio.assert_called_once()
    link_call = mock_inbound_repo.link_burst_to_folio.call_args
    assert link_call.args[1] == "folio-1"
    assert link_call.args[2] == "share-abc"
    assert link_call.kwargs["processing_status"] == "draft_created"


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_listo_command_appended_before_flush(
    mock_identity_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    session = _collecting_session(
        messages=[{"message_sid": "SM1", "body": "Jetta 2015, filtro de aire"}],
        generation=1,
    )
    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.side_effect = [session, {**session, "generation": 2}]
    mock_session_repo.append_message.return_value = (session, False, False)
    mock_session_repo.try_acquire_flush.return_value = session

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-listo",
            "message_sid": "SM-LISTO",
            "from_number": "+5217779313704",
            "body": "LISTO",
        }
    )

    appended = mock_session_repo.append_message.call_args.args[1]
    assert appended["message_sid"] == "SM-LISTO"
    assert appended["body"] == "LISTO"
    mock_session_repo.bump_generation.assert_called_once()


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_first_content_burst_sends_procesando_ack_once(
    mock_identity_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    first_session = _collecting_session(
        messages=[{"message_sid": "SM1", "body": "Jetta 2015, filtro de aire"}],
    )
    continuing_session = _collecting_session(
        messages=[
            {"message_sid": "SM1", "body": "Jetta 2015, filtro de aire"},
            {"message_sid": "SM2", "body": "Y balatas delanteras"},
        ],
    )

    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.side_effect = [None, continuing_session]
    mock_session_repo.ensure_collecting_session.return_value = first_session
    mock_session_repo.append_message.side_effect = [
        (first_session, False, True),
        (continuing_session, False, False),
    ]

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True

    service.process_inbound(
        {
            "mongo_id": "in-1",
            "message_sid": "SM1",
            "from_number": "+5217779313704",
            "body": "Jetta 2015, filtro de aire",
        }
    )
    service.process_inbound(
        {
            "mongo_id": "in-2",
            "message_sid": "SM2",
            "from_number": "+5217779313704",
            "body": "Y balatas delanteras",
        }
    )

    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert sent.count("Procesando tu solicitud…") == 1


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_listo_command_does_not_send_procesando_ack(
    mock_identity_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_session_repo,
):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    session = _collecting_session(
        messages=[{"message_sid": "SM1", "body": "Jetta 2015, filtro de aire"}],
        generation=1,
    )
    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_identity_cls.return_value.resolve.return_value = MagicMock(
        status="resolved",
        group_id="g1",
        group_name="Tienda A",
        creator_uid="uid-1",
        just_selected=False,
        message=None,
    )
    mock_session_repo.get_by_phone.side_effect = [session, {**session, "generation": 2}]
    mock_session_repo.append_message.return_value = (session, False, False)
    mock_session_repo.try_acquire_flush.return_value = session

    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service.process_inbound(
        {
            "mongo_id": "in-listo",
            "message_sid": "SM-LISTO",
            "from_number": "+5217779313704",
            "body": "LISTO",
        }
    )

    sent = [
        call.args[1]
        for call in mock_whatsapp_cls.return_value.send_text_message.call_args_list
    ]
    assert "Procesando tu solicitud…" not in sent
