from app.utils.display_text import display_name, sentence_case, vehicle_label


def test_display_name_cases():
    assert display_name("REFACCIONARIA AUTOPARTES ALEX") == "Refaccionaria Autopartes Alex"
    assert display_name("RÍO BLANCO DE LA SIERRA") == "Río Blanco de la Sierra"
    assert display_name("FRANCO 3") == "Franco 3"
    assert display_name("Taller Hernández") == "Taller Hernández"
    assert display_name(None) == ""


def test_sentence_case_keeps_acronyms():
    assert sentence_case("Conector De La Linea Del Enfriador De Aceite") == "Conector de la linea del enfriador de aceite"
    assert sentence_case("Valvula PCV") == "Valvula PCV"
    assert sentence_case(None) == ""


def test_vehicle_label():
    assert vehicle_label({"brand": "Nissan", "model": "Versa", "year": 2018}) == "Nissan Versa 2018"
    assert vehicle_label({"brand": "Nissan"}) == "Nissan"
    assert vehicle_label(None) == ""
