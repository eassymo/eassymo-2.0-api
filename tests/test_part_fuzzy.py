from app.utils import part_fuzzy as pf

CATALOG = [
    {"tipoParteId": 1, "tipoParteDescripcion": "Balatas", "tags": []},
    {"tipoParteId": 2, "tipoParteDescripcion": "Embrague", "tags": []},
    {"tipoParteId": 3, "tipoParteDescripcion": "Cable De Embrague", "tags": []},
    {"tipoParteId": 4, "tipoParteDescripcion": "Radiador", "tags": []},
    {"tipoParteId": 5, "tipoParteDescripcion": "Terminal De Dirección", "tags": []},
    {"tipoParteId": 6, "tipoParteDescripcion": "Terminal de Rin", "tags": []},
    {"tipoParteId": 7, "tipoParteDescripcion": "Luz Baja", "tags": []},
    {"tipoParteId": 8, "tipoParteDescripcion": "Luz Alta", "tags": []},
    {"tipoParteId": 9, "tipoParteDescripcion": "Pluma Limpiaparabrisas", "tags": []},
    {"tipoParteId": 10, "tipoParteDescripcion": "Sujetador De Plumas Limpiaparabrisas", "tags": []},
    {"tipoParteId": 11, "tipoParteDescripcion": "Amortiguadores", "tags": ["shock"]},
]


def ids(ranked):
    return [r.part["tipoParteId"] for r in ranked]


def test_exact_name_ignores_case_accents_plurals_filler_and_slang():
    assert [p["tipoParteId"] for p in pf.exact_matches("BALATA", CATALOG)] == [1]
    assert [p["tipoParteId"] for p in pf.exact_matches("el clutch", CATALOG)] == [2]
    assert [p["tipoParteId"] for p in pf.exact_matches("clutch completo", CATALOG)] == [2]
    assert [p["tipoParteId"] for p in pf.exact_matches("terminal de direccion", CATALOG)] == [5]


def test_partial_names_are_not_exact():
    assert pf.exact_matches("terminal", CATALOG) == []
    assert pf.exact_matches("", CATALOG) == []


def test_typo_is_ranked_to_the_right_part_and_corrected_silently():
    ranked = pf.rank_parts("balatsa", CATALOG)
    assert ids(ranked)[0] == 1
    assert pf.can_auto_correct(ranked)
    assert ids(pf.rank_parts("radiadro", CATALOG))[0] == 4


def test_a_word_that_fits_two_parts_is_never_auto_corrected():
    ranked = pf.rank_parts("terminal", CATALOG)
    assert set(ids(ranked)[:2]) == {5, 6}
    assert not pf.can_auto_correct(ranked)


def test_tags_and_slang_find_parts():
    assert ids(pf.rank_parts("shocks", CATALOG))[0] == 11


def test_unrelated_text_matches_nothing():
    assert pf.rank_parts("cafetera", CATALOG) == []
    assert pf.rank_parts("   ", CATALOG) == []


def test_unique_closest_only_when_one_part_is_clearly_nearest():
    assert pf.unique_closest("pluma", CATALOG)["tipoParteId"] == 9   # 1 extra word vs 2
    assert pf.unique_closest("luz", CATALOG) is None                 # Luz Baja / Luz Alta tie
    assert pf.unique_closest("terminal", CATALOG) is None            # two parts, same distance
    assert pf.unique_closest("cafetera", CATALOG) is None


def test_noise_is_not_a_part():
    for noise in ["", "ok", "jajaja", "👍", "gracias", "hola buenas", "12", "x", "cuanto sale"]:
        assert pf.is_noise_part_name(noise), noise
    for part in ["balatas", "filtro de aire", "foco"]:
        assert not pf.is_noise_part_name(part), part
