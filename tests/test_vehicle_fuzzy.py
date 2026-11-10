import pytest

from app.utils import vehicle_fuzzy as vf

CATALOG = [
    ("Nissan", "Sentra"), ("Nissan", "Versa"), ("Nissan", "NP300"), ("Nissan", "X-Trail"),
    ("Kia", "Rio"), ("Kia", "Sportage"), ("Kia", "Forte"),
    ("Volkswagen", "Jetta"), ("Volkswagen", "Vento"), ("Volkswagen", "Golf"),
    ("Toyota", "Corolla"), ("Toyota", "Hilux"), ("Chevrolet", "Aveo"), ("Chevrolet", "Silverado"),
    ("Citroën", "C3"), ("Honda", "Civic"), ("Mazda", "Mazda3"),
]


def top(query, n=1):
    return [pair for pair, _ in vf.rank_candidates(query, CATALOG, limit=n)]


def test_fold_removes_accents_and_separators():
    assert vf.fold("Citroën C-3") == "citroenc3"
    assert vf.tokenize("Nissan X-Trail") == ["nissan", "x", "trail"]


def test_damerau_counts_a_transposition_as_one_edit():
    assert vf.damerau_levenshtein("kia", "kai") == 1
    assert vf.damerau_levenshtein("nissan", "nisan") == 1
    assert vf.damerau_levenshtein("abc", "xyz", max_distance=1) == 2  # early exit


@pytest.mark.parametrize("query,expected", [
    ("nisan sentra", ("Nissan", "Sentra")),     # dropped letter
    ("nissan setnra", ("Nissan", "Sentra")),    # transposed letters
    ("sentraa", ("Nissan", "Sentra")),          # doubled letter
    ("jeta", ("Volkswagen", "Jetta")),          # missing double letter
    ("bolkswagen golf", ("Volkswagen", "Golf")),  # v/b swap
    ("toyoya corola", ("Toyota", "Corolla")),   # typos in both words
    ("civc", ("Honda", "Civic")),
    ("sportaje", ("Kia", "Sportage")),          # g/j confusion at the end
    ("np 300", ("Nissan", "NP300")),            # spacing
    ("xtrail", ("Nissan", "X-Trail")),
    ("citroen c3", ("Citroën", "C3")),          # accents
    ("hilus", ("Toyota", "Hilux")),
    ("silverdo", ("Chevrolet", "Silverado")),
])
def test_common_typos_resolve_to_the_right_vehicle(query, expected):
    assert top(query) == [expected]


def test_partial_word_with_a_typo_still_matches():
    assert top("sentr")[0] == ("Nissan", "Sentra")


def test_transposed_make_returns_that_make():
    assert {pair[0] for pair in top("kai", n=10)} == {"Kia"}


def test_make_only_query_returns_every_model_of_that_make():
    makes = {pair[0] for pair in top("nisan", n=10)}
    assert makes == {"Nissan"}
    assert len(top("nisan", n=10)) == 4


def test_unrelated_text_matches_nothing():
    assert top("zzzzqqq") == []
    assert top("   ") == []


def test_short_exact_tokens_do_not_fuzzy_match_everything():
    # 2-letter queries allow no edits, so "np" cannot drift to unrelated models.
    assert ("Kia", "Rio") not in top("np", n=20)


def test_exact_beats_fuzzy():
    ranked = vf.rank_candidates("kia rio", CATALOG, limit=3)
    assert ranked[0][0] == ("Kia", "Rio")
    assert ranked[0][1] == pytest.approx(1.0)


def test_phonetic_key_equates_spanish_sound_swaps():
    assert vf.phonetic_key("bolkswagen") == vf.phonetic_key("volkswagen")


def test_short_words_do_not_match_unrelated_models_through_sound_alone():
    catalog = CATALOG + [("Morgan", "Plus 4"), ("Subaru", "Pleo Plus")]
    ranked = vf.rank_candidates("hilus", catalog, limit=10)
    assert [pair for pair, _ in ranked] == [("Toyota", "Hilux")]
