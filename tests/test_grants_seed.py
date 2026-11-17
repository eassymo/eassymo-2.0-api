import json
from pathlib import Path
from unittest.mock import MagicMock

from app.authz.grant_keys import ALL_KEYS
from app.repositories import GrantRepository

CATALOG = Path(__file__).resolve().parents[1] / "scripts" / "data" / "grants_catalog.json"


def _catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_all_keys_match_catalog_json():
    catalog = _catalog()
    assert len(catalog) == 58
    assert ALL_KEYS == frozenset(g["key"] for g in catalog)


def test_upsert_missing_inserts_only_new_keys():
    coll = MagicMock()
    coll.find.return_value = [{"key": "offers.accept"}]
    docs = [
        {"key": "offers.accept", "name": "edited elsewhere"},
        {"key": "offers.create", "name": "Crear Ofertas"},
    ]
    inserted = GrantRepository.upsert_missing(docs, collection=coll)
    assert inserted == 1
    (args, _), = coll.insert_many.call_args_list
    assert [d["key"] for d in args[0]] == ["offers.create"]


def test_upsert_missing_noop_when_all_present():
    coll = MagicMock()
    coll.find.return_value = [{"key": "offers.accept"}]
    assert GrantRepository.upsert_missing([{"key": "offers.accept"}], collection=coll) == 0
    coll.insert_many.assert_not_called()


def test_active_keys_reads_only_active():
    coll = MagicMock()
    coll.find.return_value = [{"key": "a"}, {"key": "b"}]
    assert GrantRepository.active_keys(collection=coll) == {"a", "b"}
    assert coll.find.call_args[0][0] == {"active": {"$ne": False}}
