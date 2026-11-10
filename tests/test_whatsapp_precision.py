"""Precision rules of the WhatsApp bot with sloppy messages (offline: catalogs are faked).

The live counterpart is scripts/whatsapp_validation_loop.py.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("app.config.database", MagicMock())

from app.schemas.WhatsappExtraction import (  # noqa: E402
    ExtractionEvidence,
    ExtractionIntent,
    ExtractionLine,
    ExtractionUncertainty,
    ExtractionVehicle,
    WhatsappExtractionProposal,
)
from app.services import WhatsappCatalogMapper as mapper_module  # noqa: E402
from app.services import WhatsappClarificationService as clarify  # noqa: E402
from app.services.AcesVehiclesService import VehicleSearchResult  # noqa: E402
from app.services.LlmExtractionService import LlmExtractionService  # noqa: E402
from app.services.WhatsappCatalogMapper import (  # noqa: E402
    PART_CORRECTED,
    PART_MATCHED,
    PART_NONE,
    PART_SUGGESTED,
    VEHICLE_CORRECTED,
    VEHICLE_MATCHED,
    VEHICLE_SUGGESTED,
    VEHICLE_UNCHECKED,
    WhatsappCatalogMapper,
    resolve_part,
    vehicle_is_written,
    year_is_grounded,
)
from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService  # noqa: E402


def hit(make, model):
    return MagicMock(VehiculoFabricante=make, VehiculoModelo=model)


def proposal(make=None, model=None, year=None, lines=(), evidence=()):
    return WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        vehicle=ExtractionVehicle(make=make, model=model, year=year),
        lines=[ExtractionLine(local_id=f"l{i}", part_name=n) for i, n in enumerate(lines)],
        evidence=list(evidence),
    )


def fuzzy_result(*suggestions):
    return VehicleSearchResult(
        [], len(suggestions), 0, 5, "fuzzy" if suggestions else "none", "q",
        [{"term": f"{m} {mo}", "make": m, "model": mo, "score": sc} for m, mo, sc in suggestions],
    )


@pytest.fixture
def aces():
    with patch.object(mapper_module.AcesVehiclesService, "find_aces_vehicles", return_value=[]) as strict, \
         patch.object(mapper_module.AcesVehiclesService, "search_vehicles", return_value=fuzzy_result()) as fuzzy:
        yield strict, fuzzy


def map_vehicle(p, bodies, **kw):
    return WhatsappCatalogMapper().map_vehicle_result(MagicMock(), p, bodies, **kw)


# ---------------------------------------------------------------- vehicle ---------------------------------
def test_obvious_typo_is_corrected_and_the_seller_is_told(aces):
    _, fuzzy = aces
    fuzzy.return_value = fuzzy_result(("Mazda", "3", 1.0))
    v, status = map_vehicle(proposal("Mazda", "Mazda3", "2014"), ["mazda3 2014 bujias"])
    assert status == VEHICLE_CORRECTED
    assert (v.make, v.model, v.corrected_from) == ("Mazda", "3", "Mazda Mazda3")


def test_a_plausible_but_unsure_match_is_offered_not_applied(aces):
    _, fuzzy = aces
    fuzzy.return_value = fuzzy_result(("Toyota", "Hilux", 0.8))
    v, status = map_vehicle(proposal(None, "hilus", "2015"), ["hilus 2015 radiador"])
    assert status == VEHICLE_SUGGESTED
    assert v.make is None and v.model is None
    assert v.suggestion["model"] == "Hilux"


def test_two_close_candidates_are_not_auto_corrected(aces):
    _, fuzzy = aces
    fuzzy.return_value = fuzzy_result(("Nissan", "Versa", 0.92), ("Nissan", "Versa Note", 0.9))
    _, status = map_vehicle(proposal("Nissan", "Versaa", "2017"), ["versaa 2017"])
    assert status != VEHICLE_CORRECTED


def test_generation_words_are_trimmed(aces):
    strict, _ = aces
    strict.side_effect = lambda db, term, year: [hit("Volkswagen", "Jetta")] if term == "Volkswagen Jetta" else []
    v, status = map_vehicle(proposal("Volkswagen", "Jetta A6", "2015"), ["Jetta A6 2015 balatas"])
    assert status == VEHICLE_MATCHED and v.model == "Jetta"


def test_exact_model_wins_over_a_longer_variant(aces):
    strict, _ = aces
    strict.return_value = [hit("Volkswagen", "Pointer"), hit("Volkswagen", "Pointer Truck")]
    v, status = map_vehicle(proposal("Volkswagen", "Pointer", "2006"), ["mi pointer 2006 calavera"])
    assert status == VEHICLE_MATCHED and v.model == "Pointer"


def test_model_family_is_matched_with_the_name_the_seller_used(aces):
    strict, _ = aces
    strict.return_value = [hit("Chevrolet", "Silverado 1500"), hit("Chevrolet", "Silverado 2500")]
    v, status = map_vehicle(proposal("Chevrolet", "Silverado", "2012"), ["silverado 2012 bomba de agua"])
    assert status == VEHICLE_MATCHED and v.model == "Silverado"


def test_a_word_inside_another_word_is_not_a_match(aces):
    strict, _ = aces
    strict.return_value = [hit("Kia", "Rio"), hit("Jeep", "Patriot")]  # "rio" is inside "Patriot"
    v, status = map_vehicle(proposal("Kia", "Rio", "2016"), ["rio 2016 filtro"])
    assert status == VEHICLE_MATCHED and v.make == "Kia"


def test_a_year_the_seller_did_not_write_is_asked_not_guessed(aces):
    v, status = map_vehicle(proposal("Toyota", "Corolla", "2012"), ["bomba de agua corola doce"])
    assert status == VEHICLE_UNCHECKED
    assert v.year is None and v.suggestion == {"year": "2012"}


@pytest.mark.parametrize("body,grounded", [
    ("jetta 2015 balatas", True), ("jetta dos mil quince", True), ("sentra dosmil dieciseis", True),
    ("jetta 20155 balatas", False), ("corolla doce", False), ("jetta 15", False),
])
def test_year_grounding(body, grounded):
    year = "2015" if "jetta" in body else "2012"
    assert year_is_grounded(year, [body]) is grounded


def test_a_car_the_seller_never_wrote_is_not_trusted(aces):
    strict, _ = aces
    strict.return_value = [hit("Nissan", "Tsuru")]
    v, status = map_vehicle(proposal("Nissan", "Tsuru", "2015"), ["para mi Lupita 2015 bujias"])
    assert status == VEHICLE_UNCHECKED and v.make is None and v.model is None


def test_a_decoded_nickname_is_offered_to_confirm(aces):
    strict, _ = aces
    strict.return_value = [hit("Volkswagen", "Sedan")]
    evidence = [ExtractionEvidence(path="vehicle.model", raw="vochito", kind="inferred")]
    v, status = map_vehicle(proposal("Volkswagen", "Sedan", "2015", evidence=evidence), ["mi vochito 2015 balatas"])
    assert status == VEHICLE_SUGGESTED and v.suggestion["model"] == "Sedan"


def test_a_diminutive_of_the_model_name_is_trusted(aces):
    strict, _ = aces
    strict.return_value = [hit("Volkswagen", "Jetta")]
    v, status = map_vehicle(proposal("Volkswagen", "Jetta", "2015"), ["mi jettita 2015 balatas"])
    assert status == VEHICLE_MATCHED


def test_a_mistyped_car_the_model_could_not_read_is_offered(aces):
    _, fuzzy = aces
    fuzzy.return_value = fuzzy_result(("Honda", "Civic", 0.92))
    p = proposal(None, None, "2013", lines=["balatas"])
    v, status = map_vehicle(p, ["balatas delanteras sibic 2013"])
    assert status == VEHICLE_SUGGESTED and v.suggestion["model"] == "Civic"


def test_stray_fuzzy_never_runs_for_short_or_clearly_unrelated_words(aces):
    _, fuzzy = aces
    p = proposal(None, None, "2013", lines=["balatas"])
    _, status = map_vehicle(p, ["bro balatas 2013"])
    fuzzy.assert_not_called()
    assert status == VEHICLE_UNCHECKED


def test_data_from_a_draft_is_not_second_guessed(aces):
    strict, _ = aces
    strict.return_value = [hit("Volkswagen", "Jetta")]
    v, status = map_vehicle(proposal("Volkswagen", "Jetta", "2015"), ["si"], ground_year=False)
    assert status == VEHICLE_MATCHED and v.year == "2015"


@pytest.mark.parametrize("make,model,body,written", [
    ("Volkswagen", "Jetta", "jetta 2015", True), ("Toyota", "Hilux", "hilus 2015", True),
    ("Nissan", "X-Trail", "xtrail 2013", True), ("Chevrolet", "Chevy", "chevy 2008", True),
    ("Nissan", "Tsuru", "para mi Lupita 2015", False),
])
def test_vehicle_is_written(make, model, body, written):
    assert vehicle_is_written(ExtractionVehicle(make=make, model=model), [body]) is written


# ------------------------------------------------------------------- parts --------------------------------
VOCAB = [
    {"tipoParteId": 1, "tipoParteDescripcion": "Balatas", "categoriaId": 1, "subCategoriaId": 1, "tipoParteSensiblePosicion": True, "tags": []},
    {"tipoParteId": 2, "tipoParteDescripcion": "Embrague", "categoriaId": 1, "subCategoriaId": 2, "tipoParteSensiblePosicion": False, "tags": []},
    {"tipoParteId": 3, "tipoParteDescripcion": "Cable De Embrague", "categoriaId": 1, "subCategoriaId": 2, "tipoParteSensiblePosicion": False, "tags": []},
    {"tipoParteId": 5, "tipoParteDescripcion": "Terminal De Dirección", "categoriaId": 1, "subCategoriaId": 3, "tipoParteSensiblePosicion": False, "tags": []},
    {"tipoParteId": 6, "tipoParteDescripcion": "Terminal de Rin", "categoriaId": 1, "subCategoriaId": 3, "tipoParteSensiblePosicion": False, "tags": []},
    {"tipoParteId": 7, "tipoParteDescripcion": "Luz Baja", "categoriaId": 1, "subCategoriaId": 4, "tipoParteSensiblePosicion": False, "tags": []},
    {"tipoParteId": 8, "tipoParteDescripcion": "Luz Alta", "categoriaId": 1, "subCategoriaId": 4, "tipoParteSensiblePosicion": False, "tags": []},
]


@pytest.fixture
def parts():
    with patch.object(mapper_module, "_part_vocabulary", return_value=VOCAB), \
         patch.object(mapper_module, "_pick_catalog_match", return_value=None) as strict:
        yield strict


def test_exact_part_name_wins_even_when_the_strict_search_finds_nothing(parts):
    res = resolve_part(MagicMock(), ["clutch"])
    assert res.status == PART_MATCHED and res.match["tipoParteDescripcion"] == "Embrague"


def test_typo_in_a_part_is_corrected_and_remembered(parts):
    res = resolve_part(MagicMock(), ["balatsa"])
    assert res.status == PART_CORRECTED and res.corrected_from == "balatsa"
    assert res.match["tipoParteId"] == 1


def test_a_generic_word_offers_the_candidates(parts):
    res = resolve_part(MagicMock(), ["terminal"])
    assert res.status == PART_SUGGESTED
    assert {c["tipoParteId"] for c in res.suggestions} == {5, 6}
    assert res.match is None


def test_a_nonsense_part_is_not_forced(parts):
    assert resolve_part(MagicMock(), ["cafetera"]).status == PART_NONE


def test_strict_winner_that_is_not_the_closest_part_is_rejected(parts):
    # strict search liked «Luz Baja» for "luz", but «Luz Alta» is just as close
    parts.return_value = {"tipoParteId": 7, "tipoParteDescripcion": "Luz Baja"}
    res = resolve_part(MagicMock(), ["luz"])
    assert res.status == PART_SUGGESTED and res.match is None


def test_a_position_word_that_is_part_of_the_name_is_kept_as_a_second_term(parts):
    parts.side_effect = lambda db, term: {"tipoParteId": 9, "tipoParteDescripcion": "Rótula Inferior"} if term == "rotula inferior" else None
    line = ExtractionLine(local_id="a", part_name="rotula", position="inferior")
    with patch.object(mapper_module, "_map_position", return_value=("Inferior", True, False, True)), \
         patch.object(mapper_module, "_map_unit", return_value=("Pieza", True)):
        mapped = WhatsappCatalogMapper().map_line(MagicMock(), line)
    assert mapped.tipo_parte_descripcion is None or "Rótula" in mapped.tipo_parte_descripcion


# ------------------------------------------------------------ the model's output -------------------------
def test_chat_filler_is_dropped_from_the_model_proposal():
    p = proposal("Volkswagen", "Jetta", "2015", lines=["balatas", "ok", "jajaja", "👍"])
    cleaned = LlmExtractionService.drop_noise_lines(p)
    assert [l.part_name for l in cleaned.lines] == ["balatas"]
    assert cleaned.warnings


def test_mapper_only_fields_cannot_come_from_the_model():
    fitted = LlmExtractionService._fit_vehicle({"make": "Kia", "suggestion": {"x": 1}, "corrected_from": "kai"})
    assert fitted == {"make": "Kia"}


# -------------------------------------------------------- applying results to the draft -------------------
@pytest.fixture
def processor():
    return object.__new__(WhatsappIntakeProcessorService)


def test_a_suggested_car_becomes_a_question_with_the_answer_attached(processor):
    p = proposal(None, None, "2015")
    resolved = ExtractionVehicle(year="2015", suggestion={"make": "Toyota", "model": "Hilux", "year": "2015"})
    processor._apply_resolved_vehicle(p, resolved, VEHICLE_SUGGESTED)
    unc = [u for u in p.uncertainties if u.path == "vehicle.model"]
    assert unc and unc[0].reason == "¿Es un Toyota Hilux 2015?" and unc[0].suggestion["model"] == "Hilux"
    assert p.vehicle.suggestion is None  # never travels into the draft vehicle


def test_a_corrected_car_leaves_a_note(processor):
    p = proposal("Mazda", "Mazda3", "2014")
    resolved = ExtractionVehicle(make="Mazda", model="3", year="2014", corrected_from="Mazda Mazda3")
    processor._apply_resolved_vehicle(p, resolved, VEHICLE_CORRECTED)
    assert any(u.path == "note.vehicle_corrected" and "Mazda Mazda3" in u.reason for u in p.uncertainties)


def test_an_unwritten_year_becomes_a_year_question(processor):
    p = proposal("Toyota", "Corolla", "2012")
    resolved = ExtractionVehicle(make="Toyota", model="Corolla", year=None, suggestion={"year": "2012"})
    processor._apply_resolved_vehicle(p, resolved, VEHICLE_UNCHECKED)
    assert any(u.path == "vehicle.year" and u.suggestion == {"year": "2012"} for u in p.uncertainties)


# ------------------------------------------------------------------ questions and answers -----------------
def folio_with(pieces=None, vehicle=None):
    return {"vehicle": vehicle or {}, "pieces": pieces or []}


def test_piece_suggestions_become_warning_questions():
    choices = [
        {"tipoParteId": 5, "tipoParteDescripcion": "Terminal De Dirección"},
        {"tipoParteId": 6, "tipoParteDescripcion": "Terminal de Rin"},
    ]
    folio = folio_with([{"piece_id": "p1", "name": "terminal", "catalog_suggestions": choices}], {"maker": "Nissan", "model": "Tsuru", "year": "2010"})
    qs = clarify.derive_pending_questions(folio, proposal("Nissan", "Tsuru", "2010"))
    q = next(q for q in qs if q["path"] == "piece:p1.catalog_choice")
    assert q["severity"] == "warning" and q["choices"] == choices
    assert "1) Terminal De Dirección" in q["copy_text"] and "2) Terminal de Rin" in q["copy_text"]


def test_a_part_without_suggestions_still_reports_a_plain_miss():
    folio = folio_with([{"piece_id": "p1", "name": "cafetera"}], {"maker": "Nissan", "model": "Tsuru", "year": "2010"})
    qs = clarify.derive_pending_questions(folio, proposal("Nissan", "Tsuru", "2010"))
    assert [q["severity"] for q in qs if q["path"] == "piece:p1.catalog"] == ["info"]


def test_a_corrected_part_is_reported_as_a_note():
    folio = folio_with([{"piece_id": "p1", "name": "Balatas", "tipoParteId": "1", "catalog_corrected_from": "balatsa"}],
                       {"maker": "Nissan", "model": "Tsuru", "year": "2010"})
    qs = clarify.derive_pending_questions(folio, proposal("Nissan", "Tsuru", "2010"))
    note = next(q for q in qs if q["path"] == "piece:p1.catalog_corrected")
    assert note["severity"] == "info" and "balatsa" in note["copy_text"]


def test_vehicle_questions_carry_the_suggestion():
    p = proposal(None, None, "2015")
    p.uncertainties = [ExtractionUncertainty(path="vehicle.model", reason="¿Es un Toyota Hilux 2015?", suggestion={"make": "Toyota", "model": "Hilux", "year": "2015"})]
    qs = clarify.derive_pending_questions(folio_with(vehicle={"year": "2015"}), p)
    q = next(q for q in qs if q["path"] == "vehicle.model")
    assert q["suggestion"]["model"] == "Hilux" and q["copy_text"] == "¿Es un Toyota Hilux 2015?"


@pytest.mark.parametrize("text,yes", [
    ("sí", True), ("si", True), ("sí, ese", True), ("correcto", True), ("simón", True), ("dale", True),
    ("no", False), ("no, es otro", False), ("si pero son traseras de otro carro que tengo en casa", False), ("", False),
])
def test_is_affirmative(text, yes):
    assert clarify.is_affirmative(text) is yes


def vehicle_question():
    return {"id": "q1", "path": "vehicle.model", "status": "open", "severity": "critical",
            "suggestion": {"make": "Toyota", "model": "Hilux", "year": "2015"}}


def test_si_confirms_a_suggested_car():
    folio = {"vehicle": {"year": "2015"}, "pieces": [], "whatsapp_pending_questions": [vehicle_question()]}
    patch_, details = clarify.fill_open_questions(folio, "sí, esa")
    assert patch_["vehicle"]["maker"] == "Toyota" and patch_["vehicle"]["model"] == "Hilux"
    assert patch_["whatsapp_pending_questions"][0]["status"] == "answered"
    assert details == ["Toyota Hilux 2015"]


def test_no_does_not_confirm_a_suggested_car():
    folio = {"vehicle": {"year": "2015"}, "pieces": [], "whatsapp_pending_questions": [vehicle_question()]}
    assert clarify.fill_open_questions(folio, "no") is None


def part_question(choices):
    return {"id": "q2", "path": "piece:p1.catalog_choice", "piece_id": "p1", "status": "open", "severity": "warning", "choices": choices}


CHOICES = [
    {"tipoParteId": 5, "tipoParteDescripcion": "Terminal De Dirección", "categoriaId": 1, "subCategoriaId": 3, "tipoParteSensiblePosicion": False},
    {"tipoParteId": 6, "tipoParteDescripcion": "Terminal de Rin", "categoriaId": 1, "subCategoriaId": 3, "tipoParteSensiblePosicion": False},
]


@pytest.mark.parametrize("answer,expected", [("2", 6), ("la de dirección", 5), ("terminal de direccion", 5), ("la 1", 5)])
def test_a_part_choice_is_picked_by_number_or_name(answer, expected):
    folio = {"vehicle": {}, "pieces": [{"piece_id": "p1", "name": "terminal"}], "whatsapp_pending_questions": [part_question(CHOICES)]}
    patch_, _ = clarify.fill_open_questions(folio, answer)
    piece = patch_["pieces"][0]
    assert piece["tipoParteId"] == str(expected) and piece["catalog_suggestions"] is None


def test_si_confirms_a_single_part_suggestion_but_not_several():
    folio = {"vehicle": {}, "pieces": [{"piece_id": "p1", "name": "balatsa"}], "whatsapp_pending_questions": [part_question(CHOICES[:1])]}
    patch_, _ = clarify.fill_open_questions(folio, "sí")
    assert patch_["pieces"][0]["tipoParteId"] == "5"
    folio["whatsapp_pending_questions"] = [part_question(CHOICES)]
    assert clarify.fill_open_questions(folio, "sí") is None


def test_the_messy_corpus_is_well_formed():
    from tests.whatsapp_messy_corpus import CASES, FRESH, HOLDOUT

    everything = CASES + HOLDOUT + FRESH
    assert len({c["id"] for c in everything}) == len(everything)
    for case in everything:
        assert case["text"].strip() and set(case) == {"id", "text", "vehicle", "parts"}
