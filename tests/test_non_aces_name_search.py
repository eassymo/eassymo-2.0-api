from app.repositories import NonAcesVehiclesRepository as repo


def test_squash_ignores_spacing_and_punctuation():
    assert repo.squash_text("NP 300") == repo.squash_text("np300") == repo.squash_text("NP-300") == "np300"
    assert repo.squash_text("X-Trail") == repo.squash_text("x trail") == "xtrail"


def test_short_tokens_are_not_matched_independently():
    # "np" alone would match inside unrelated words; only the squashed phrase counts.
    conditions, squashed, _ = repo.build_name_match("np 300")
    assert squashed == "np300"
    assert len(conditions) == 2  # squashed phrase + alias; no AND-ed token branch


def test_multi_word_queries_match_in_any_order():
    conditions, squashed, aliases = repo.build_name_match("sentra nissan")
    assert squashed == "sentranissan"
    assert aliases == []
    assert any("$and" in c for c in conditions)


def test_np300_is_aliased_to_navara_frontier():
    # The catalog lists the NP300 Frontier as «NP 300» until 2018 and «Navara (Frontier)» after.
    _, _, aliases = repo.build_name_match("NP 300")
    assert aliases == ["navarafrontier"]
    _, _, aliases = repo.build_name_match("np300")
    assert aliases == ["navarafrontier"]


def test_empty_query_builds_no_conditions():
    assert repo.build_name_match("   ")[0] == []


def test_numeric_catalog_fields_become_strings():
    vehicle = repo._doc_to_standarized(
        {"trim_id": 1, "make_id": 2, "year": 2019, "make": "Mazda", "model": 6, "generation": 5, "trim": 2.5, "gearbox": "AT"}
    )
    assert vehicle.VehiculoModelo == "6"
    assert vehicle.VehiculoSubModelo == "5"
    assert vehicle.VehiculoFabricante == "Mazda"
