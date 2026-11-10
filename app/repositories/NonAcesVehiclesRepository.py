import time
from typing import Dict, List, Tuple

from app.config import database
from app.schemas.StandarizedVehicles import StandarizedVehicles
from app.utils.armadora_names import (
    format_armadora_display_name,
    normalize_armadora_name,
    pick_preferred_armadora_display,
)
from app.utils.regex_sanitize import sanitize_search_term, MAX_SEARCH_LENGTH


def _text_expr(field: str) -> dict:
    """Catalog rows store some names as numbers (Mazda 6, Porsche 911)."""
    return {
        "$convert": {
            "input": f"${field}",
            "to": "string",
            "onNull": "",
            "onError": "",
        }
    }

# Characters that don't carry meaning when comparing vehicle names ("NP 300" == "NP300" == "np-300").
_SEPARATORS = " -._,()/'"
MIN_TOKEN_LENGTH = 3

# Same vehicle sold under different catalog names depending on the year. Keys/values are "squashed"
# (lowercase, no separators). The NP300 Frontier is listed as «NP 300» until 2018 and as
# «Navara (Frontier)» from 2019 on.
SEARCH_ALIASES: Dict[str, List[str]] = {
    "np300": ["navarafrontier"],
    "np300frontier": ["navarafrontier"],
    "nissannp300": ["nissannavarafrontier"],
}


def squash_text(text: str) -> str:
    """Lowercase and drop separators so spacing/punctuation differences don't matter."""
    out = (text or "").lower()
    for ch in _SEPARATORS:
        out = out.replace(ch, "")
    return out


def search_tokens(text: str) -> List[str]:
    out = (text or "").lower()
    for ch in _SEPARATORS:
        out = out.replace(ch, " ")
    return [t for t in out.split() if t]


def _squash_expr(parts: List[dict]) -> dict:
    """Mongo expression equivalent of `squash_text` over the concatenation of `parts`."""
    expr: dict = {"$toLower": {"$concat": parts}}
    for ch in _SEPARATORS:
        expr = {"$replaceAll": {"input": expr, "find": ch, "replacement": ""}}
    return expr


def _blob_contains(field: str, needle: str) -> dict:
    return {"$gte": [{"$indexOfCP": [f"${field}", needle]}, 0]}


def build_name_match(search_argument: str):
    """
    Separator-insensitive, token-aware matching on top of the plain regex match.

    Returns (match_conditions, squashed_query, alias_needles): conditions evaluated against the
    `search_blob` field (make+model+generation+trim, squashed).
    """
    squashed = squash_text(search_argument[:MAX_SEARCH_LENGTH])
    # Very short tokens ("np", "x", "1") match inside unrelated words, so they only count through the
    # squashed full-phrase match above, never as independent AND-ed tokens.
    tokens = [t for t in search_tokens(search_argument[:MAX_SEARCH_LENGTH]) if len(t) >= MIN_TOKEN_LENGTH]
    conditions: List[dict] = []
    if squashed:
        conditions.append(_blob_contains("search_blob", squashed))
    if len(tokens) > 1:
        conditions.append({"$and": [_blob_contains("search_blob", t) for t in tokens]})
    aliases = SEARCH_ALIASES.get(squashed, [])
    for alias in aliases:
        conditions.append(_blob_contains("search_blob", alias))
    return conditions, squashed, aliases


def find_distinct_makes() -> List[str]:
    makes = database.db["NonAcesVehicles"].distinct(
        "make",
        {
            "is_active": 1,
            "make": {"$exists": True, "$nin": [None, ""]},
        },
    )

    canonical_by_key: Dict[str, str] = {}
    for make in makes:
        if not isinstance(make, str):
            continue
        display = format_armadora_display_name(make)
        key = normalize_armadora_name(display)
        if not key:
            continue
        if key in canonical_by_key:
            canonical_by_key[key] = pick_preferred_armadora_display(
                canonical_by_key[key], display
            )
        else:
            canonical_by_key[key] = display

    return sorted(canonical_by_key.values(), key=normalize_armadora_name)


def _name_search_stages(search_argument: str, year: int):
    """Aggregation stages (match + relevance score + sort) shared by the list and paged searches.

    Returns None when the search term is empty after sanitising.
"""
    safe_search = sanitize_search_term(search_argument)
    if not safe_search:
        return None

    search_pattern = {"$regex": safe_search, "$options": "i"}
    make_text = _text_expr("make")
    model_text = _text_expr("model")
    generation_text = _text_expr("generation")
    trim_text = _text_expr("trim")

    blob_conditions, squashed_query, alias_needles = build_name_match(search_argument)

    stages = [
        {
            "$match": {
                "year": year,
                "is_active": 1
            }
        },
        {
            "$addFields": {
                "make": make_text,
                "model": model_text,
                "generation": generation_text,
                "trim": trim_text,
                "make_model_combined": {
                    "$concat": [make_text, " ", model_text]
                },
                "search_blob": _squash_expr(
                    [make_text, model_text, generation_text, trim_text]),
                "make_model_blob": _squash_expr([make_text, model_text]),
            }
        },
        {
            "$match": {
                "$or": [
                    {"make": search_pattern},
                    {"model": search_pattern},
                    {"make_model_combined": search_pattern},
                    {"generation": search_pattern},
                    {"trim": search_pattern},
                    *([{"$expr": {"$or": blob_conditions}}] if blob_conditions else []),
                ]
            }
        },
        {
            "$addFields": {
                "relevance_score": {
                    "$add": [
                        # Exact make match gets highest score
                        {"$cond": [{"$eq": [{"$toLower": "$make"}, search_argument.lower()[:MAX_SEARCH_LENGTH]]}, 100, 0]},
                        # Exact model match gets high score
                        {"$cond": [{"$eq": [{"$toLower": "$model"}, search_argument.lower()[:MAX_SEARCH_LENGTH]]}, 90, 0]},
                        # Make starts with search gets medium score
                        {"$cond": [{"$regexMatch": {"input": "$make", "regex": f"^{safe_search}", "options": "i"}}, 50, 0]},
                        # Model starts with search gets medium score
                        {"$cond": [{"$regexMatch": {"input": "$model", "regex": f"^{safe_search}", "options": "i"}}, 45, 0]},
                        # Contains match gets low score
                        {"$cond": [{"$regexMatch": {"input": "$make_model_combined", "regex": safe_search, "options": "i"}}, 10, 0]},
                        # Same name ignoring spaces/punctuation (np300 == NP 300)
                        *([{"$cond": [_blob_contains("make_model_blob", squashed_query), 40, 0]}] if squashed_query else []),
                        # Known catalog rename (NP 300 -> Navara (Frontier))
                        *[{"$cond": [_blob_contains("make_model_blob", a), 30, 0]} for a in alias_needles],
                    ]
                }
            }
        },
        {
            "$sort": {
                "relevance_score": -1,
                "make": 1,
                "model": 1
            }
        },
    ]
    return stages


def find_non_aces_by_name(search_argument: str, year: int) -> List[StandarizedVehicles]:
    """
    Find NonAces vehicles by searching make and model fields with regex
    
    Args:
        search_argument: Search text for make/model
        year: Vehicle year (mandatory filter)
        
    Returns:
        List of matching vehicles
    """
    try:
        standarized_vehicles: List[StandarizedVehicles] = []

        stages = _name_search_stages(search_argument, year)
        if stages is None:
            return []

        pipeline = [
            *stages,
            {
                "$limit": 100
            },
            {
                "$project": {
                    "_id": 1,
                    "trim_id": 1,
                    "trim": 1,
                    "make_id": 1,
                    "make": 1,
                    "model_id": 1,
                    "model": 1,
                    "generation_id": 1,
                    "generation": 1,
                    "body_id": 1,
                    "body": 1,
                    "drive_id": 1,
                    "drive": 1,
                    "gearbox_id": 1,
                    "gearbox": 1,
                    "engine_type_id": 1,
                    "engine_type": 1,
                    "engine_volume": 1,
                    "engine_power": 1,
                    "year": 1,
                    "image": 1,
                    "relevance_score": 1,
                    "make_model_combined": 1
                }
            }
        ]
        
        # Execute aggregation pipeline
        result = list(database.db["NonAcesVehicles"].aggregate(pipeline))

        standarized_vehicles = [_doc_to_standarized(doc) for doc in result]

        return standarized_vehicles
        
    except Exception as e:
        print(f"MongoDB aggregation error: {str(e)}")
        raise Exception(f"Error searching NonAces vehicles: {str(e)}")


def _text(value) -> str:
    """Catalog rows sometimes hold numbers (generation 5, Mazda 6): always hand out strings."""
    return "" if value is None else str(value)


def _doc_to_standarized(doc: dict) -> StandarizedVehicles:
    return StandarizedVehicles(
        VehicleId=doc.get("trim_id", 0),
        BaseId=doc.get("make_id", 0),
        VehiculoAno=doc.get("year", 0),
        VehiculoComentarios="",
        VehiculoDescripcion=f'{doc.get("year")}, {doc.get("make")}, {doc.get("model")}, {doc.get("generation")}, {doc.get("trim")}, {doc.get("gearbox")}',
        VehiculoFabricante=_text(doc.get("make")),
        VehiculoInternalId=doc.get("trim_id", 0),
        VehiculoModelo=_text(doc.get("model")),
        VehiculoSubModelo=_text(doc.get("generation")),
        VehiculoTipo="Carro",
        nonAcesVehicle=True,
    )


def search_non_aces_models_page(
    search_argument: str, year: int, skip: int = 0, limit: int = 20
) -> Tuple[List[StandarizedVehicles], int]:
    """One vehicle per make+model (best-ranked trim), paged in the database.

    Returns (page, total_models). Deduplicating before paging is what makes infinite scroll
    consistent: the old flow cut at 100 trims first, which silently dropped whole models.
    """
    stages = _name_search_stages(search_argument, year)
    if stages is None:
        return [], 0

    pipeline = [
        *stages,
        {"$group": {
            "_id": {"make": {"$toLower": "$make"}, "model": {"$toLower": "$model"}},
            "doc": {"$first": "$$ROOT"},
            "score": {"$max": "$relevance_score"},
        }},
        {"$sort": {"score": -1, "doc.make": 1, "doc.model": 1}},
        {"$facet": {
            "items": [{"$skip": max(0, skip)}, {"$limit": max(1, limit)}],
            "total": [{"$count": "n"}],
        }},
    ]
    try:
        facet = list(database.db["NonAcesVehicles"].aggregate(pipeline))
    except Exception as e:
        print(f"MongoDB aggregation error: {str(e)}")
        raise Exception(f"Error searching NonAces vehicles: {str(e)}")

    if not facet:
        return [], 0
    items = [_doc_to_standarized(row["doc"]) for row in facet[0].get("items", [])]
    total = (facet[0].get("total") or [{"n": 0}])[0]["n"]
    return items, total


_MODEL_CACHE: Dict[int, Tuple[float, List[StandarizedVehicles]]] = {}
_MODEL_CACHE_TTL_SECONDS = 600


def list_non_aces_models(year: int) -> List[StandarizedVehicles]:
    """One representative vehicle per make+model for the year (cached): the fuzzy-match vocabulary."""
    now = time.monotonic()
    cached = _MODEL_CACHE.get(year)
    if cached and now - cached[0] < _MODEL_CACHE_TTL_SECONDS:
        return cached[1]

    make_text = _text_expr("make")
    model_text = _text_expr("model")
    pipeline = [
        {"$match": {"year": year, "is_active": 1}},
        {"$addFields": {"make": make_text, "model": model_text}},
        {"$group": {
            "_id": {"make": {"$toLower": "$make"}, "model": {"$toLower": "$model"}},
            "doc": {"$first": "$$ROOT"},
        }},
        {"$sort": {"doc.make": 1, "doc.model": 1}},
    ]
    rows = list(database.db["NonAcesVehicles"].aggregate(pipeline))
    vehicles = [_doc_to_standarized(row["doc"]) for row in rows]
    _MODEL_CACHE[year] = (now, vehicles)
    return vehicles


def find_non_aces_by_name_simple(search_argument: str, year: int):
    """
    Simple search for NonAces vehicles using basic regex
    
    Args:
        search_argument: Search text
        year: Vehicle year
        
    Returns:
        List of matching vehicles
    """
    try:
        search_pattern = {"$regex": search_argument, "$options": "i"}
        
        query = {
            "year": year,
            "is_active": 1,
            "$or": [
                {"make": search_pattern},
                {"model": search_pattern}
            ]
        }
        
        result = list(database.db["NonAcesVehicles"].find(query).limit(100))
        return result
        
    except Exception as e:
        print(f"MongoDB query error: {str(e)}")
        raise Exception(f"Error searching NonAces vehicles: {str(e)}")