"""One WhatsApp reply answering several open clarification questions at once.

Built from a real case: draft 76D7B3 asked brand, model and position in one
message, and the seller quoted it with "Es un Jetta y son delanteras".
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.WhatsappExtraction import ClarificationAnswers, ExtractionVehicle
from app.services import LlmExtractionService as llm_module
from app.services import WhatsappIntakeProcessorService as mod
from app.services import WhatsappClarificationService as clarify
from app.services.WhatsappCatalogMapper import VEHICLE_AMBIGUOUS, VEHICLE_MATCHED, VEHICLE_UNCHECKED

REPLY = "Es un Jetta y son delanteras"
QUOTED = "Borrador listo en Eassymo POS.\n❗ ¿Cuál es la marca del vehículo?"


def _folio():
    return {
        "_id": "folio-1",
        "folio_code": "76D7B3",
        "share_token": "tok",
        "vehicle": {"year": "2015", "maker": None, "model": None},
        "pieces": [{"piece_id": "p1", "name": "Balatas", "position": "No aplica"}],
        "whatsapp_pending_questions": [
            {"id": "q-make", "path": "vehicle.make", "prompt": "¿Cuál es la marca del vehículo?", "severity": "critical", "status": "open"},
            {"id": "q-model", "path": "vehicle.model", "prompt": "¿Cuál es el modelo del vehículo?", "severity": "critical", "status": "open"},
            {"id": "q-pos", "path": "piece:p1.position", "piece_id": "p1", "prompt": "¿Son delanteras o traseras?", "severity": "warning", "status": "open"},
        ],
    }


def _answers(*items):
    return ClarificationAnswers.model_validate(
        {"answers": [{"question_id": q, "value": v, "evidence": e} for q, v, e in items]}
    )


@pytest.fixture
def service():
    svc = mod.WhatsappIntakeProcessorService.__new__(mod.WhatsappIntakeProcessorService)
    svc.llm_service = MagicMock()
    svc.catalog_mapper = MagicMock()
    svc.catalog_mapper.map_vehicle_result.return_value = (
        ExtractionVehicle(make="Volkswagen", model="Jetta", year="2015"),
        VEHICLE_MATCHED,
    )
    return svc


@pytest.fixture
def io(service):
    saved = {}

    def update(_folio_id, patch_):
        saved.update(patch_)
        return {**_folio(), **patch_, "updated_at": "2026-11-02T18:00:00Z"}

    with patch.object(mod.folio_service, "update", side_effect=update) as update_mock, \
            patch.object(mod, "MySQLSessionLocal", None), \
            patch.object(service, "_send_bot_message") as send, \
            patch.object(service, "_inbound_doc", return_value={"direction": "outbound", "body": QUOTED}), \
            patch.object(service, "_draft_preview_link", return_value="https://pos/draft"), \
            patch.object(service, "_draft_card_image_url", return_value=None):
        yield {"saved": saved, "send": send, "update": update_mock}


def _apply(service, text=REPLY, folio=None):
    return service._apply_reasoned_answers(
        from_number="+52", folio=folio or _folio(), answer_text=text, quoted_sid="wamid.q", burst_id="b1",
    )


def _status(saved):
    return {q["id"]: q["status"] for q in saved["whatsapp_pending_questions"]}


def test_one_reply_answers_brand_model_and_position(service, io):
    service.llm_service.match_answers.return_value = _answers(
        ("q-make", "Volkswagen", "Jetta"), ("q-model", "Jetta", "Es un Jetta"), ("q-pos", "Delanteras", "son delanteras"),
    )
    assert _apply(service) is True
    assert io["saved"]["vehicle"]["maker"] == "Volkswagen"
    assert io["saved"]["vehicle"]["model"] == "Jetta"
    assert io["saved"]["pieces"][0]["position"] == "Delantera"
    assert _status(io["saved"]) == {"q-make": "answered", "q-model": "answered", "q-pos": "answered"}
    reply = io["send"].call_args.args[1]
    assert reply.startswith("Listo · 76D7B3 · Volkswagen Jetta · Balatas · Delantera.")


def test_model_and_questions_are_sent_to_the_llm_with_the_quoted_message(service, io):
    service.llm_service.match_answers.return_value = _answers()
    _apply(service)
    args, kwargs = service.llm_service.match_answers.call_args
    assert args[0] == [REPLY]
    assert [q["id"] for q in args[1]] == ["q-make", "q-model", "q-pos"]
    assert kwargs["quoted_text"] == QUOTED


def test_catalog_fills_the_brand_when_only_the_model_was_named(service, io):
    service.llm_service.match_answers.return_value = _answers(("q-model", "Jetta", "un Jetta"))
    assert _apply(service, text="Es un Jetta") is True
    assert io["saved"]["vehicle"]["maker"] == "Volkswagen"
    assert _status(io["saved"]) == {"q-make": "answered", "q-model": "answered", "q-pos": "open"}
    reply = io["send"].call_args.args[1]
    assert "⚠️ ¿Son delanteras o traseras?" in reply


def test_brand_and_model_stay_open_when_the_catalog_does_not_agree(service, io):
    service.catalog_mapper.map_vehicle_result.return_value = (
        ExtractionVehicle(model="Jetta", year="2015"), VEHICLE_AMBIGUOUS,
    )
    service.llm_service.match_answers.return_value = _answers(
        ("q-model", "Jetta", "Jetta"), ("q-pos", "Delantera", "delanteras"),
    )
    assert _apply(service) is True
    assert io["saved"]["vehicle"]["maker"] is None
    assert io["saved"]["vehicle"]["model"] is None
    assert _status(io["saved"]) == {"q-make": "open", "q-model": "open", "q-pos": "answered"}


def test_answer_without_evidence_in_the_reply_is_ignored(service, io):
    service.llm_service.match_answers.return_value = _answers(
        ("q-model", "Vento", "Vento"), ("q-pos", "Trasera", "traseras"),
    )
    assert _apply(service) is False
    io["update"].assert_not_called()
    io["send"].assert_not_called()


def test_position_value_that_is_not_a_position_is_ignored(service, io):
    service.llm_service.match_answers.return_value = _answers(("q-pos", "Jetta", "Jetta"))
    assert _apply(service) is False


def test_llm_failure_falls_back_without_saving(service, io):
    service.llm_service.match_answers.side_effect = RuntimeError("GLM down")
    assert _apply(service) is False
    io["update"].assert_not_called()


def test_handle_complement_uses_reasoned_answers_before_refusing(service, io):
    service.llm_service.match_answers.return_value = _answers(("q-pos", "Delantera", "delanteras"))
    with patch.object(service, "_can_resume_folio", return_value=(True, None)), \
            patch.object(service, "_remember_share_token"), \
            patch.object(service, "_filter_inbound_reaction_sids", return_value=[]), \
            patch.object(service, "_apply_chain_reactions"):
        handled = service._handle_complement_or_answer(
            from_number="+52", folio=_folio(), question=None, answer_text="son delanteras",
            message_sids=["wamid.r"], burst_id="b1", group_id="g1", creator_uid="u1", quoted_sid="wamid.q",
        )
    assert handled is True
    assert "varias aclaraciones" not in io["send"].call_args.args[1]
    assert io["send"].call_args.args[1].startswith("Listo · 76D7B3 · Balatas · Delantera.")


def test_handle_complement_still_asks_when_nothing_could_be_applied(service, io):
    service.llm_service.match_answers.return_value = _answers()
    with patch.object(service, "_can_resume_folio", return_value=(True, None)), \
            patch.object(service, "_remember_share_token"), \
            patch.object(service, "_filter_inbound_reaction_sids", return_value=[]), \
            patch.object(service, "_apply_chain_reactions"):
        service._handle_complement_or_answer(
            from_number="+52", folio=_folio(), question=None, answer_text="gracias",
            message_sids=["wamid.r"], burst_id="b1", group_id="g1", creator_uid="u1",
        )
    assert "Tienes varias aclaraciones abiertas" in io["send"].call_args.args[1]
    io["update"].assert_not_called()


def test_match_answers_parses_model_json():
    svc = llm_module.LlmExtractionService.__new__(llm_module.LlmExtractionService)
    svc.api_key = "k"
    with patch.object(svc, "_complete", return_value={"content": '{"answers": [{"question_id": "q-pos", "value": "Delantera", "evidence": "delanteras"}]}'}) as complete:
        result = svc.match_answers(["son delanteras"], [{"id": "q-pos", "prompt": "¿Son delanteras o traseras?"}], quoted_text=QUOTED)
    assert [(a.question_id, a.value) for a in result.answers] == [("q-pos", "Delantera")]
    user_prompt = complete.call_args.args[0][1]["content"]
    assert "q-pos" in user_prompt and QUOTED.splitlines()[0] in user_prompt and "son delanteras" in user_prompt


def test_match_answers_returns_nothing_for_unusable_output():
    svc = llm_module.LlmExtractionService.__new__(llm_module.LlmExtractionService)
    svc.api_key = "k"
    with patch.object(svc, "_complete", return_value={"content": "no json here"}):
        assert svc.match_answers(["x"], [{"id": "q", "prompt": "?"}]).answers == []


def _model_only_folio(year="2015"):
    folio = _folio()
    folio["vehicle"]["year"] = year
    folio["whatsapp_pending_questions"] = [folio["whatsapp_pending_questions"][1]]
    return folio


def _handle(service, folio, text):
    with patch.object(service, "_can_resume_folio", return_value=(True, None)), \
            patch.object(service, "_remember_share_token"), \
            patch.object(service, "_filter_inbound_reaction_sids", return_value=[]), \
            patch.object(service, "_apply_chain_reactions"), \
            patch.object(service, "_resend_open_clarification"):
        return service._handle_complement_or_answer(
            from_number="+52", folio=folio, question=folio["whatsapp_pending_questions"][0],
            answer_text=text, message_sids=["wamid.r"], burst_id="b1", group_id="g1",
            creator_uid="u1", quoted_sid="wamid.q",
        )


def test_single_model_question_never_saves_the_raw_reply(service, io):
    service.llm_service.match_answers.return_value = _answers(("q-model", "Jetta", "un Jetta"))
    assert _handle(service, _model_only_folio(), "Es un Jetta") is True
    assert io["saved"]["vehicle"]["model"] == "Jetta"
    assert io["saved"]["vehicle"]["maker"] == "Volkswagen"
    assert io["send"].call_args.args[1].startswith("Listo · 76D7B3 · Volkswagen Jetta.")


def test_single_model_question_reports_failure_instead_of_saving_junk(service, io):
    service.llm_service.match_answers.return_value = _answers()
    with patch.object(mod.clarify, "apply_material_note_to_folio", return_value=({}, False)):
        assert _handle(service, _model_only_folio(), "Es un Jetta") is True
    io["update"].assert_not_called()
    assert "No pude aplicar" in io["send"].call_args.args[1]


def test_without_a_year_the_stated_model_is_kept_but_not_an_inferred_brand(service, io):
    service.catalog_mapper.map_vehicle_result.return_value = (
        ExtractionVehicle(make="Volkswagen", model="Jetta"), VEHICLE_UNCHECKED,
    )
    service.llm_service.match_answers.return_value = _answers(
        ("q-make", "Volkswagen", "Jetta"), ("q-model", "Jetta", "Jetta"),
    )
    folio = _folio()
    folio["vehicle"]["year"] = None
    assert _apply(service, text="Es un Jetta", folio=folio) is True
    assert io["saved"]["vehicle"]["model"] == "Jetta"
    assert io["saved"]["vehicle"]["maker"] is None
    assert _status(io["saved"]) == {"q-make": "open", "q-model": "answered", "q-pos": "open"}


def test_without_a_year_a_brand_the_seller_wrote_is_kept(service, io):
    service.catalog_mapper.map_vehicle_result.return_value = (
        ExtractionVehicle(make="Volkswagen", model="Jetta"), VEHICLE_UNCHECKED,
    )
    service.llm_service.match_answers.return_value = _answers(
        ("q-make", "Volkswagen", "Volkswagen"), ("q-model", "Jetta", "Jetta"),
    )
    folio = _folio()
    folio["vehicle"]["year"] = None
    assert _apply(service, text="Volkswagen Jetta", folio=folio) is True
    assert (io["saved"]["vehicle"]["maker"], io["saved"]["vehicle"]["model"]) == ("Volkswagen", "Jetta")


def test_forwarded_answers_never_write_brand_or_model():
    filled = clarify.fill_open_questions(_folio(), "2020 traseras")
    patch_, _details = filled
    assert patch_["vehicle"]["maker"] is None and patch_["vehicle"]["model"] is None
    status = {q["id"]: q["status"] for q in patch_["whatsapp_pending_questions"]}
    assert status == {"q-make": "open", "q-model": "open", "q-pos": "answered"}

