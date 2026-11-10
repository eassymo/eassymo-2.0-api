import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

sys.modules.setdefault("app.config.database", MagicMock())

from app.schemas.StandarizedVehicles import StandarizedVehicles
from app.services import AcesVehiclesService as service_module
from app.services.AcesVehiclesService import AcesVehiclesService


def vehicle(make, model, year=2019, internal_id=1, non_aces=True):
    return StandarizedVehicles(
        VehiculoInternalId=internal_id, VehicleId=internal_id, BaseId=1,
        VehiculoDescripcion=f"{year}, {make}, {model}", VehiculoFabricante=make, VehiculoModelo=model,
        VehiculoSubModelo="", VehiculoAno=year, VehiculoTipo="Carro", VehiculoComentarios="",
        nonAcesVehicle=non_aces,
    )


VOCAB = [
    vehicle("Nissan", "Sentra", internal_id=1), vehicle("Nissan", "Versa", internal_id=2),
    vehicle("Nissan", "NP300", internal_id=3), vehicle("Kia", "Rio", internal_id=4),
    vehicle("Kia", "Sportage", internal_id=5), vehicle("Volkswagen", "Jetta", internal_id=6),
    vehicle("Toyota", "Corolla", internal_id=7),
]


def search(term, year="2019", skip=0, limit=20, page=None, total=None):
    """Run the service with the exact-search DB call stubbed to `page`/`total`."""
    page = page or []
    with patch.object(service_module, "search_non_aces_models_page", return_value=(page, total if total is not None else len(page))), \
         patch.object(service_module, "list_non_aces_models", return_value=VOCAB):
        return AcesVehiclesService.search_vehicles(MagicMock(), term, year, skip, limit)


def test_exact_results_are_returned_with_paging_metadata():
    page = [vehicle("Kia", "Rio"), vehicle("Kia", "Sportage")]
    result = search("kia", page=page, total=45, limit=2)
    assert result.match == "exact"
    assert [v.VehiculoModelo for v in result.vehicles] == ["Rio", "Sportage"]
    assert result.has_more is True
    assert result.meta()["total"] == 45


def test_last_page_has_no_more():
    result = search("kia", skip=40, limit=20, page=[vehicle("Kia", "Rio")], total=41)
    assert result.has_more is False


def test_typo_falls_back_to_closest_vehicles_and_suggests_them():
    result = search("nisan sentr", page=[], total=0)
    assert result.match == "fuzzy"
    assert (result.vehicles[0].VehiculoFabricante, result.vehicles[0].VehiculoModelo) == ("Nissan", "Sentra")
    assert result.suggestions[0]["term"] == "Nissan Sentra"


def test_make_only_typo_suggests_the_make():
    result = search("kai", page=[], total=0)
    assert result.match == "fuzzy"
    assert {v.VehiculoFabricante for v in result.vehicles} == {"Kia"}
    assert result.suggestions[0]["term"] == "Kia"
    assert result.suggestions[0]["model"] is None


def test_fuzzy_results_are_paged_too():
    result = search("nisan", page=[], total=0, limit=2)
    assert len(result.vehicles) == 2
    assert result.total == 3
    assert result.has_more is True
    second = search("nisan", page=[], total=0, skip=2, limit=2)
    assert len(second.vehicles) == 1
    assert second.has_more is False


def test_nothing_close_returns_none_without_suggestions():
    result = search("zzzzqqq", page=[], total=0)
    assert result.match == "none"
    assert result.vehicles == [] and result.suggestions == []


def test_few_exact_results_can_still_offer_a_better_suggestion():
    # "kia" matched a single odd row, but "Kia" the make is what they most likely meant.
    page = [vehicle("Kiawa", "Kia Special")]
    result = search("kia", page=page, total=1)
    assert result.match == "exact"
    assert any(s["term"] == "Kia" for s in result.suggestions)


def test_plenty_of_exact_results_get_no_suggestions():
    page = [vehicle("Nissan", m) for m in ("Sentra", "Versa", "NP300")]
    result = search("nissan", page=page, total=3)
    assert result.suggestions == []


def test_old_years_use_the_aces_repository():
    aces_vehicle = vehicle("Nissan", "Tsuru", year=2012, non_aces=False)
    with patch.object(service_module.AcesVehiclesRepository, "search_models_page", return_value=([aces_vehicle], 1)) as aces, \
         patch.object(service_module, "search_non_aces_models_page") as non_aces:
        result = AcesVehiclesService.search_vehicles(MagicMock(), "tsuru", "2012")
    aces.assert_called_once()
    non_aces.assert_not_called()
    assert result.vehicles == [aces_vehicle]


def test_validates_year_and_ignores_blank_terms():
    with pytest.raises(HTTPException) as err:
        search("kia", year="")
    assert err.value.status_code == 400
    with pytest.raises(HTTPException):
        search("kia", year="abc")
    assert search("   ", page=[]).match == "none"


def test_limit_is_capped():
    assert search("kia", limit=500, page=[vehicle("Kia", "Rio")]).limit == 50


def test_find_aces_vehicles_is_strict_by_default_so_callers_never_get_guesses():
    # The WhatsApp mapper auto-accepts a lone hit: a typo must stay "not found", not become a guess.
    with patch.object(service_module, "search_non_aces_models_page", return_value=([], 0)), \
         patch.object(service_module, "list_non_aces_models", return_value=VOCAB):
        assert AcesVehiclesService.find_aces_vehicles(MagicMock(), "nisan sentr", "2019") == []
        guessed = AcesVehiclesService.find_aces_vehicles(MagicMock(), "nisan sentr", "2019", allow_fuzzy=True)
    assert [(v.VehiculoFabricante, v.VehiculoModelo) for v in guessed] == [("Nissan", "Sentra")]


def test_find_aces_vehicles_still_returns_a_plain_list_for_other_callers():
    with patch.object(service_module, "search_non_aces_models_page", return_value=([vehicle("Kia", "Rio")], 1)), \
         patch.object(service_module, "list_non_aces_models", return_value=VOCAB):
        vehicles = AcesVehiclesService.find_aces_vehicles(MagicMock(), "kia", "2019")
    assert [v.VehiculoModelo for v in vehicles] == ["Rio"]


def test_a_near_miss_model_is_not_suggested_next_to_a_valid_result():
    # "np 300" legitimately matched via alias; "NV300" is a different van, not a typo of it.
    vocab_with_nv = [v for v in VOCAB if v.VehiculoModelo != "NP300"] + [vehicle("Nissan", "NV300", internal_id=9)]
    with patch.object(service_module, "search_non_aces_models_page", return_value=([vehicle("Nissan", "Navara (Frontier)")], 1)), \
         patch.object(service_module, "list_non_aces_models", return_value=vocab_with_nv):
        result = AcesVehiclesService.search_vehicles(MagicMock(), "np 300", "2019")
    assert result.suggestions == []
