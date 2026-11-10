import re
import unicodedata
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.repositories.VehiculoPartesRepository import VehiculoPartesRepository
from app.repositories.VehiculoSensibilidadesRepository import VehiculoSensibilidadesRepository
from app.schemas.VehiculoPartesSearch import HistoricoBusquedaInput, SearchPartesPaginatorRequest
from app.schemas.WhatsappExtraction import ExtractionLine, ExtractionVehicle, WhatsappExtractionProposal
from app.services.AcesVehiclesService import AcesVehiclesService
from app.services.EstandarizadorService import get_unidades_medida_by_parte
from app.services.VehiculoPartesService import search_partes_paginator
from app.utils import part_fuzzy, vehicle_fuzzy

POSITION_NO_APLICA = "No aplica"

VEHICLE_MATCHED = "matched"
VEHICLE_AMBIGUOUS = "ambiguous"
VEHICLE_UNRECOGNIZED = "unrecognized"
VEHICLE_UNCHECKED = "unchecked"
# The catalog fixed an obvious typo on its own ("mazda3" -> Mazda 3); the seller is told, not asked.
VEHICLE_CORRECTED = "corrected"
# A close match exists but it is a guess: the seller confirms it with "sí".
VEHICLE_SUGGESTED = "suggested"

VEHICLE_AUTO_CORRECT_SCORE = 0.9
VEHICLE_SUGGEST_SCORE = 0.75
STRAY_MIN_LENGTH = 4
STRAY_SUGGEST_SCORE = 0.8

PART_MATCHED = "matched"
PART_CORRECTED = "corrected"
PART_SUGGESTED = "suggested"
PART_NONE = "none"

POSITION_ALIASES: Dict[str, str] = {
    "delantera": "Delantera",
    "delanteras": "Delantera",
    "delantero": "Delantera",
    "delanteros": "Delantera",
    "frontal": "Delantera",
    "front": "Delantera",
    "trasera": "Trasera",
    "traseras": "Trasera",
    "trasero": "Trasera",
    "traseros": "Trasera",
    "posterior": "Trasera",
    "izquierda": "Izquierda",
    "izquierdo": "Izquierda",
    "izq": "Izquierda",
    "derecha": "Derecha",
    "derecho": "Derecha",
    "der": "Derecha",
    "superior": "Superior",
    "inferior": "Inferior",
}

POSITION_STRIP_TOKENS = set(POSITION_ALIASES.keys()) | {
    "pa",
    "para",
    "del",
    "de",
    "la",
    "las",
    "el",
    "los",
    "un",
    "una",
    "juego",
    "juegos",
    "par",
    "pares",
    "set",
    "pieza",
    "piezas",
    "pza",
    "pzas",
}

UNIT_ALIASES: Dict[str, str] = {
    "pieza": "Pieza",
    "piezas": "Pieza",
    "pza": "Pieza",
    "pzas": "Pieza",
    "par": "Par",
    "pares": "Par",
    "juego": "Juego",
    "juegos": "Juego",
    "set": "Set",
    "litro": "Litro",
    "litros": "Litro",
}

VEHICLE_STOPWORDS = {
    "te",
    "encargo",
    "encarga",
    "pa",
    "para",
    "porfa",
    "porfavor",
    "tambien",
    "y",
    "el",
    "la",
    "las",
    "los",
    "de",
    "del",
    "un",
    "una",
    "unos",
    "unas",
    "auto",
    "carro",
    "ano",
    "año",
    "piezas",
    "pieza",
    "refaccion",
    "refacciones",
    "hola",
    "ok",
    "jaja",
    *POSITION_STRIP_TOKENS,
}


@dataclass
class MappedPieceLine:
    tipo_parte_id: Optional[str]
    tipo_parte_descripcion: Optional[str]
    categoria_id: Optional[int]
    sub_categoria_id: Optional[int]
    name: str
    qty: int
    unit_of_measure: str
    position: str
    position_suggested: bool
    catalog_matched: bool
    position_required: bool = False
    position_standardized: bool = True
    unit_standardized: bool = True
    part_status: str = PART_NONE
    # Close catalog parts to confirm with the seller (only when nothing was matched)
    suggestions: List[dict] = field(default_factory=list)
    # What the seller wrote when the catalog silently corrected it
    corrected_from: Optional[str] = None


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(value: str) -> List[str]:
    return [token for token in _normalize_text(value).split() if token]


_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_STANDALONE_YEAR_RE = re.compile(r"^\s*((?:19|20)\d{2})\s*$")
_MIN_VEHICLE_YEAR = 1980
_MAX_VEHICLE_YEAR = 2035


def _plausible_vehicle_year(year: str) -> bool:
    try:
        value = int(year)
    except (TypeError, ValueError):
        return False
    return _MIN_VEHICLE_YEAR <= value <= _MAX_VEHICLE_YEAR


def _make_in_bodies(make: str, bodies: Sequence[str]) -> bool:
    """True when the customer wrote this brand (or a shortening such as "chevy")."""
    words = _tokenize(make)
    if not words:
        return False
    stem = words[0][:4]
    return any(
        token.startswith(stem)
        for body in bodies or []
        for token in _tokenize(body)
    )


def year_from_bodies(bodies: Sequence[str]) -> Optional[str]:
    """Recover a vehicle year GLM often drops when it arrives as its own bubble."""
    standalone: List[str] = []
    mentioned: List[str] = []
    for body in bodies or []:
        text = (body or "").strip()
        stand = _STANDALONE_YEAR_RE.fullmatch(text)
        if stand and _plausible_vehicle_year(stand.group(1)):
            standalone.append(stand.group(1))
        for match in _YEAR_RE.findall(text):
            if _plausible_vehicle_year(match):
                mentioned.append(match)

    unique_standalone = list(dict.fromkeys(standalone))
    if len(unique_standalone) == 1:
        return unique_standalone[0]
    unique_mentioned = list(dict.fromkeys(mentioned))
    if len(unique_mentioned) == 1:
        return unique_mentioned[0]
    return None


def _singularize(token: str) -> str:
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def strip_position_tokens(part_name: str, position_hint: Optional[str] = None) -> str:
    tokens = _tokenize(part_name)
    filtered = [token for token in tokens if token not in POSITION_STRIP_TOKENS]
    cleaned = " ".join(filtered).strip()
    if cleaned:
        return cleaned
    if position_hint:
        hint_tokens = set(_tokenize(position_hint))
        fallback = [token for token in tokens if token not in hint_tokens]
        return " ".join(fallback).strip() or part_name.strip()
    return part_name.strip()


def _score_catalog_item(query: str, description: str) -> float:
    query_norm = _normalize_text(query)
    desc_norm = _normalize_text(description)
    if not query_norm or not desc_norm:
        return 0.0

    query_tokens = [_singularize(token) for token in _tokenize(query_norm)]
    desc_tokens = [_singularize(token) for token in _tokenize(desc_norm)]
    if not query_tokens:
        return 0.0

    if query_norm == desc_norm:
        return 100.0

    query_stem = query_tokens[0]
    desc_stem = desc_tokens[0] if desc_tokens else ""
    if query_stem and query_stem == desc_stem:
        return 90.0 - min(len(desc_norm) - len(query_norm), 20)

    if desc_norm.startswith(query_norm):
        return 80.0 - min(len(desc_norm) - len(query_norm), 20)

    if query_norm in desc_norm:
        return 60.0 - min(len(desc_norm) - len(query_norm), 30)

    if query_stem and query_stem in desc_tokens:
        return 55.0

    return 0.0


# A runner-up this close means the name fits several catalog parts ("terminal" is a steering
# terminal and a wheel terminal): that is a question for the seller, not a pick for the bot.
_AMBIGUOUS_GAP = 15.0


def _catalog_payload(item: dict) -> dict:
    return {
        "tipoParteId": item.get("tipoParteId"),
        "tipoParteDescripcion": item.get("tipoParteDescripcion"),
        "categoriaId": item.get("categoriaId"),
        "subCategoriaId": item.get("subCategoriaId"),
        "tipoParteSensiblePosicion": bool(item.get("tipoParteSensiblePosicion")),
    }


def _pick_catalog_match(mysql_db: Session, search_term: str) -> Optional[dict]:
    if mysql_db is None or not search_term.strip():
        return None

    payload = SearchPartesPaginatorRequest(
        historicoBusqueda=HistoricoBusquedaInput(criterio=search_term),
        page=0,
        itemsPerPage=8,
    )
    result = search_partes_paginator(mysql_db, payload)
    historico = result.get("historicoBusqueda") or {}
    details = historico.get("details") or []
    items = (details[0].get("partes") if details else None) or []
    if not items:
        return None

    scored = sorted(
        (
            (
                _score_catalog_item(search_term, item.get("tipoParteDescripcion") or ""),
                item,
            )
            for item in items
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best_item = scored[0]
    if best_score < 55.0:
        return None
    # Only an exact name is allowed to win against a close runner-up
    if best_score < 100.0 and len(scored) > 1 and scored[1][0] >= best_score - _AMBIGUOUS_GAP:
        return None

    return _catalog_payload(best_item)


_PART_VOCABULARY_TTL_SECONDS = 600
_part_vocabulary_cache: Dict[str, Any] = {"at": 0.0, "parts": []}


def _part_vocabulary(mysql_db: Session) -> List[dict]:
    now = time.monotonic()
    if _part_vocabulary_cache["parts"] and now - _part_vocabulary_cache["at"] < _PART_VOCABULARY_TTL_SECONDS:
        return _part_vocabulary_cache["parts"]
    parts = VehiculoPartesRepository.list_active_parts_with_tags(mysql_db)
    _part_vocabulary_cache.update(at=now, parts=parts)
    return parts


@dataclass
class PartResolution:
    status: str
    match: Optional[dict] = None
    suggestions: List[dict] = field(default_factory=list)
    corrected_from: Optional[str] = None


def resolve_part(mysql_db: Session, terms: Sequence[str]) -> PartResolution:
    """Match what the seller called a part to one catalog part, or say how close we got.

    1. The strict catalog search (exact/prefix, one clear winner).
    2. Typo/slang-tolerant ranking over the whole catalog: fixed silently only when it is clearly
       one part ("balatsa" -> Balatas); otherwise the closest parts are offered to confirm.
    Nothing is ever picked from a near tie.
    """
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if mysql_db is None or not cleaned:
        return PartResolution(PART_NONE)

    try:
        vocabulary = _part_vocabulary(mysql_db)
    except Exception:
        vocabulary = []

    # An exact catalog name always wins, however many longer names contain it ("Embrague" among 31)
    for term in cleaned:
        exact = part_fuzzy.exact_matches(term, vocabulary)
        if len(exact) == 1:
            return PartResolution(PART_MATCHED, match=_catalog_payload(exact[0]))

    for term in cleaned:
        synonym_free = " ".join(part_fuzzy.PART_SYNONYMS.get(tok, tok) for tok in _tokenize(term))
        for candidate in dict.fromkeys([term, synonym_free]):
            match = _pick_catalog_match(mysql_db, candidate)
            if match and vocabulary:
                # Not an exact name: accept it only when it is the single closest catalog part
                closest = part_fuzzy.unique_closest(candidate, vocabulary)
                if not closest or closest.get("tipoParteId") != match.get("tipoParteId"):
                    match = None
            if match:
                return PartResolution(PART_MATCHED, match=match)

    if not vocabulary:
        return PartResolution(PART_NONE)

    best_ranked: list = []
    best_term = cleaned[0]
    for term in cleaned:
        ranked = part_fuzzy.rank_parts(term, vocabulary, limit=4)
        if ranked and (not best_ranked or ranked[0].score > best_ranked[0].score):
            best_ranked, best_term = ranked, term
    if not best_ranked:
        return PartResolution(PART_NONE)

    if part_fuzzy.can_auto_correct(best_ranked):
        return PartResolution(
            PART_CORRECTED, match=_catalog_payload(best_ranked[0].part), corrected_from=best_term
        )
    suggestions = [
        _catalog_payload(r.part)
        for r in best_ranked
        if r.score >= part_fuzzy.SUGGEST_MIN_SCORE
    ][:3]
    if suggestions:
        return PartResolution(PART_SUGGESTED, suggestions=suggestions)
    return PartResolution(PART_NONE)


def _load_position_names(mysql_db: Session, tipo_parte_id: Optional[int]) -> List[str]:
    if mysql_db is None:
        return []
    if tipo_parte_id:
        rows = VehiculoSensibilidadesRepository.find_posiciones_by_tipo_parte(
            mysql_db, tipo_parte_id
        )
        if rows:
            return [row.PosicionNombre or "" for row in rows if row.PosicionNombre]
    rows = VehiculoSensibilidadesRepository.find_all_posiciones(mysql_db)
    return [row.PosicionNombre or "" for row in rows if row.PosicionNombre]


def _position_candidates(
    line: ExtractionLine,
    leftover_tokens: Sequence[str],
) -> List[str]:
    candidates: List[str] = []
    if line.position:
        candidates.append(line.position)
    candidates.extend(leftover_tokens)
    candidates.extend(_tokenize(line.part_name))
    return candidates


def _written_position(line: ExtractionLine, leftover_tokens: Sequence[str]) -> str:
    written = (line.position or "").strip()
    if written:
        return written
    if leftover_tokens:
        return " ".join(leftover_tokens)
    return ""


def _map_position(
    mysql_db: Session,
    *,
    tipo_parte_id: Optional[int],
    position_sensitive: bool,
    candidates: Sequence[str],
    written: str = "",
) -> tuple[str, bool, bool, bool]:
    """Return position, suggested, required, standardized."""
    official = _load_position_names(mysql_db, tipo_parte_id)
    official_by_norm = {_normalize_text(name): name for name in official if name}

    for candidate in candidates:
        for token in _tokenize(candidate):
            alias = POSITION_ALIASES.get(token)
            if alias and (not official or alias in official):
                return alias, True, position_sensitive, True
            norm = _normalize_text(token)
            if norm in official_by_norm:
                return official_by_norm[norm], True, position_sensitive, True

    if not position_sensitive:
        return POSITION_NO_APLICA, False, False, True

    kept = (written or "").strip()
    if kept and _normalize_text(kept) not in {"", "no aplica", "n a", "na"}:
        return kept, False, True, False

    return POSITION_NO_APLICA, False, True, True


_GENERIC_UNIT_HINTS = {"pieza", "piezas", "pza", "pzas"}


def _part_unit_labels(mysql_db: Session, tipo_parte_id: int) -> List[str]:
    """Standardized units for this part, from findUnidadesMedidaByParte."""
    units_payload = get_unidades_medida_by_parte(
        mysql_db, tipo_parte_id, fallback_to_all=False
    )
    return [
        (item.get("etiquetaDefecto") or "").strip()
        for item in (units_payload.get("lstUnidadesMedida") or [])
        if (item.get("etiquetaDefecto") or "").strip()
    ]


def _match_unit_label(mapped: str, labels: Sequence[str]) -> Optional[str]:
    mapped_norm = _normalize_text(mapped)
    if not mapped_norm:
        return None
    for label in labels:
        if _normalize_text(label) == mapped_norm:
            return label
    for label in labels:
        if mapped_norm in _normalize_text(label):
            return label
    return None


def _map_unit(
    mysql_db: Session,
    *,
    tipo_parte_id: Optional[int],
    unit_hint: Optional[str],
) -> tuple[str, bool]:
    """Return the unit and whether it is one of the part's standardized units.

    The request form defaults a part to the first unit returned by
    findUnidadesMedidaByParte. The bot does the same when the message does not
    name a unit, or when it only says the generic "pieza". A unit the customer
    wrote that is not in that list is kept as written.
    """
    default = "Pieza"
    hint = (unit_hint or "").strip()
    hint_norm = _normalize_text(hint)
    alias = UNIT_ALIASES.get(hint_norm)
    mapped = alias or hint
    generic = not hint or hint_norm in _GENERIC_UNIT_HINTS

    if mysql_db is not None and tipo_parte_id:
        labels = _part_unit_labels(mysql_db, tipo_parte_id)
        if labels:
            if not generic:
                matched = _match_unit_label(mapped, labels)
                if matched:
                    return matched, True
                return hint, False
            matched_generic = _match_unit_label(mapped or default, labels) if hint else None
            if matched_generic:
                return matched_generic, True
            return labels[0], True

    if generic or alias == default:
        return default, True
    return mapped, bool(alias)


def _hit_make_model(hit: Any) -> tuple[str, str]:
    make = str(getattr(hit, "VehiculoFabricante", None) or "").strip()
    model = str(getattr(hit, "VehiculoModelo", None) or "").strip()
    return make, model


def _unique_vehicle_hits(hits: Sequence[Any]) -> List[Any]:
    unique: Dict[tuple[str, str], Any] = {}
    for hit in hits or []:
        make, model = _hit_make_model(hit)
        if not make and not model:
            continue
        key = (_normalize_text(make), _normalize_text(model))
        if key not in unique:
            unique[key] = hit
    return list(unique.values())


def vehicle_search_term_groups(
    proposal: WhatsappExtractionProposal,
    bodies: Sequence[str],
) -> tuple[List[str], List[str]]:
    """(terms from what the model read as the car, stray words from the chat).

    Stray words are weak evidence: a customer's first name can equal a model ("Rio"), so a car found
    only through them is offered for confirmation, never accepted.
    """
    vehicle_terms: List[str] = []
    vehicle = proposal.vehicle
    if vehicle:
        if vehicle.make and vehicle.model:
            vehicle_terms.append(f"{vehicle.make} {vehicle.model}")
        if vehicle.model:
            vehicle_terms.append(vehicle.model)
        if vehicle.make:
            vehicle_terms.append(vehicle.make)
    for evidence in proposal.evidence or []:
        if (evidence.path or "").startswith("vehicle") and evidence.raw:
            vehicle_terms.append(evidence.raw)

    part_tokens = set()
    for line in proposal.lines or []:
        part_tokens.update(_tokenize(line.part_name))
        if line.raw:
            part_tokens.update(_tokenize(line.raw))
        if line.position:
            part_tokens.update(_tokenize(line.position))

    stray_terms: List[str] = []
    for body in bodies or []:
        for token in _tokenize(body):
            if (
                token in VEHICLE_STOPWORDS
                or token.isdigit()
                or token in part_tokens
                or len(token) < 3
            ):
                continue
            stray_terms.append(token)

    def dedupe(terms: Sequence[str], seen: set) -> List[str]:
        ordered: List[str] = []
        for term in terms:
            key = _normalize_text(term)
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(term.strip())
        return ordered

    seen: set = set()
    return dedupe(vehicle_terms, seen), dedupe(stray_terms, seen)


def unexplained_tokens(
    proposal: WhatsappExtractionProposal, bodies: Sequence[str]
) -> List[str]:
    """Words of the chat that are neither filler, numbers nor part/position names.

    Unlike stray search terms this does not exclude the model's `raw` quotes: those repeat the whole
    bubble, car included, so a mistyped car word ("sibic") would otherwise count as "explained".
    """
    explained = set()
    for line in proposal.lines or []:
        explained.update(_tokenize(line.part_name))
        if line.position:
            explained.update(_tokenize(line.position))
    out: List[str] = []
    for body in bodies or []:
        for token in _tokenize(body):
            if token in VEHICLE_STOPWORDS or token.isdigit() or token in explained or len(token) < 3:
                continue
            if token not in out:
                out.append(token)
    return out


def vehicle_search_terms(
    proposal: WhatsappExtractionProposal,
    bodies: Sequence[str],
) -> List[str]:
    vehicle_terms, stray_terms = vehicle_search_term_groups(proposal, bodies)
    return [*vehicle_terms, *stray_terms]


_WORD_YEAR_RE = re.compile(r"\b(dos\s*mil|mil\s*novecientos)\b")


def year_is_grounded(year: str, bodies: Sequence[str]) -> bool:
    """True when the seller really wrote this year: as digits, or spelled out ("dos mil quince").

    A two-digit or spelled-short year ("08", "doce") is a guess the model made, not data.
    """
    for body in bodies or []:
        if re.search(rf"(?<!\d){re.escape(str(year))}(?!\d)", body or ""):
            return True
        if _WORD_YEAR_RE.search(_normalize_text(body or "")):
            return True
    return False


def vehicle_is_written(vehicle: ExtractionVehicle, bodies: Sequence[str]) -> bool:
    """True when the car the model read is actually in the text (allowing typos and spacing).

    A nickname the model "decoded" ("Lupita" -> Tsuru) or a hallucination has no support in the words
    the seller wrote, so it must be confirmed instead of trusted.
    """
    text_tokens = [t for body in bodies or [] for t in vehicle_fuzzy.tokenize(body)]
    squashed_text = "".join(text_tokens)
    if not text_tokens:
        return True
    for value in (vehicle.model, vehicle.make):
        value = (value or "").strip()
        if not value:
            continue
        folded = vehicle_fuzzy.fold(value)
        if folded and folded in squashed_text:
            return True
        words = vehicle_fuzzy.tokenize(value)
        if words and all(
            any(vehicle_fuzzy.token_similarity(w, t) >= 0.75 or vehicle_fuzzy.token_similarity(t, w) >= 0.75 for t in text_tokens)
            for w in words
        ):
            return True
        if vehicle_fuzzy.rank_candidates(
            " ".join(text_tokens), [(vehicle.make or "", vehicle.model or "")], limit=1
        ):
            return True
    return False


def _inferred_from_nickname(proposal: WhatsappExtractionProposal, bodies: Sequence[str]) -> bool:
    """The model said which words of the message it decoded into the car (evidence kind «inferred»)."""
    squashed = "".join(t for body in bodies or [] for t in vehicle_fuzzy.tokenize(body))
    return any(
        (item.path or "").startswith("vehicle")
        and (item.kind or "").lower() == "inferred"
        and vehicle_fuzzy.fold(item.raw)
        and vehicle_fuzzy.fold(item.raw) in squashed
        for item in (proposal.evidence or [])
    )


def _hit_tokens(hit: Any) -> set:
    make, model = _hit_make_model(hit)
    return set(_tokenize(f"{make} {model}"))


def _prefer_whole_word_hits(unique: List[Any], term: str) -> List[Any]:
    """Drop hits that only contain the term inside another word ("rio" inside "Patriot")."""
    wanted = set(_tokenize(term))
    if not wanted:
        return unique
    whole = [hit for hit in unique if wanted <= _hit_tokens(hit)]
    return whole or unique


def _single_family(unique: List[Any], model: str) -> Optional[Any]:
    """One brand, every hit a variant of the model named ("Silverado" -> 1500/2500/3500)."""
    wanted = _tokenize(model)
    if not wanted or not unique:
        return None
    makes = {_normalize_text(_hit_make_model(hit)[0]) for hit in unique}
    if len(makes) != 1:
        return None
    for hit in unique:
        if _tokenize(_hit_make_model(hit)[1])[: len(wanted)] != wanted:
            return None
    return unique[0]


def _exact_model_hit(unique: List[Any], model: str) -> Optional[Any]:
    wanted = _normalize_text(model)
    exact = [hit for hit in unique if _normalize_text(_hit_make_model(hit)[1]) == wanted]
    return exact[0] if len(exact) == 1 else None


def _trim_variants(term: str, make: Optional[str]) -> List[str]:
    """"Jetta A6" -> "Jetta": generation/trim words the catalog does not carry in the model name."""
    tokens = term.split()
    brand = _normalize_text(make or "")
    variants: List[str] = []
    for k in range(len(tokens) - 1, 0, -1):
        variant = " ".join(tokens[:k])
        if _normalize_text(variant) == brand:
            continue
        if k == 1 and len(_normalize_text(variant)) < 3:
            continue
        variants.append(variant)
    return variants


class WhatsappCatalogMapper:
    def map_line(self, mysql_db: Session, line: ExtractionLine) -> MappedPieceLine:
        raw_tokens = _tokenize(line.part_name)
        position_tokens = [token for token in raw_tokens if token in POSITION_ALIASES]
        search_term = strip_position_tokens(line.part_name, line.position)
        terms = [search_term]
        # A position word can be part of the catalog name itself ("Rótula Inferior")
        with_position = " ".join(x for x in (line.part_name, line.position) if x and x.strip())
        if _normalize_text(with_position) not in {_normalize_text(t) for t in terms}:
            terms.append(with_position)
        resolution = resolve_part(mysql_db, terms)
        catalog = resolution.match

        tipo_parte_id = catalog.get("tipoParteId") if catalog else None
        position_sensitive = bool(catalog and catalog.get("tipoParteSensiblePosicion"))
        position, position_suggested, position_required, position_standardized = _map_position(
            mysql_db,
            tipo_parte_id=int(tipo_parte_id) if tipo_parte_id else None,
            position_sensitive=position_sensitive,
            candidates=_position_candidates(line, position_tokens),
            written=_written_position(line, position_tokens),
        )

        unit, unit_standardized = _map_unit(
            mysql_db,
            tipo_parte_id=int(tipo_parte_id) if tipo_parte_id else None,
            unit_hint=line.unit,
        )

        official_name = (
            catalog.get("tipoParteDescripcion") if catalog else line.part_name.strip()
        )

        return MappedPieceLine(
            tipo_parte_id=str(tipo_parte_id) if tipo_parte_id else None,
            tipo_parte_descripcion=catalog.get("tipoParteDescripcion") if catalog else None,
            categoria_id=catalog.get("categoriaId") if catalog else None,
            sub_categoria_id=catalog.get("subCategoriaId") if catalog else None,
            name=official_name,
            qty=line.quantity or 1,
            unit_of_measure=unit,
            position=position,
            position_suggested=position_suggested and position != POSITION_NO_APLICA,
            catalog_matched=bool(catalog),
            position_required=position_required,
            position_standardized=position_standardized,
            unit_standardized=unit_standardized,
            part_status=resolution.status,
            suggestions=resolution.suggestions,
            corrected_from=resolution.corrected_from,
        )

    def map_lines(
        self, mysql_db: Session, lines: Sequence[ExtractionLine]
    ) -> List[MappedPieceLine]:
        return [self.map_line(mysql_db, line) for line in lines]

    def map_vehicle(
        self,
        mysql_db: Session,
        proposal: WhatsappExtractionProposal,
        bodies: Sequence[str],
    ) -> Optional[ExtractionVehicle]:
        return self.map_vehicle_result(mysql_db, proposal, bodies)[0]

    def _strict_unique(self, mysql_db: Session, term: str, year: str) -> Optional[List[Any]]:
        """Unique make+model hits for the term; None when the lookup itself failed."""
        try:
            hits = AcesVehiclesService.find_aces_vehicles(mysql_db, term, year)
        except Exception:
            return None
        return _prefer_whole_word_hits(_unique_vehicle_hits(hits), term)

    def _fuzzy_vehicle(self, mysql_db: Session, terms: Sequence[str], year: str):
        """Best "did you mean" over the model's own terms: (suggestion, runner_up_score) or None."""
        best = None
        for term in list(terms)[:2]:
            try:
                result = AcesVehiclesService.search_vehicles(mysql_db, term, year, 0, 5)
            except Exception:
                continue
            if result.match != "fuzzy" or not result.suggestions:
                continue
            top = result.suggestions[0]
            second = result.suggestions[1]["score"] if len(result.suggestions) > 1 else 0.0
            if best is None or top["score"] > best[0]["score"]:
                best = (top, second)
        return best

    def _fuzzy_stray_vehicle(self, mysql_db: Session, stray_terms: Sequence[str], year: str) -> Optional[dict]:
        """A stray word that is a clear typo of one car or brand of that year (never a short or common word)."""
        best: Optional[dict] = None
        for term in [t for t in stray_terms if len(t) >= STRAY_MIN_LENGTH][:3]:
            try:
                result = AcesVehiclesService.search_vehicles(mysql_db, term, year, 0, 5)
            except Exception:
                continue
            if result.match != "fuzzy" or not result.suggestions:
                continue
            top = result.suggestions[0]
            if top["score"] < STRAY_SUGGEST_SCORE:
                continue
            second = result.suggestions[1]["score"] if len(result.suggestions) > 1 else 0.0
            if second > top["score"] - 0.1:
                continue
            if best is None or top["score"] > best["score"]:
                best = {"make": top.get("make"), "model": top.get("model"), "score": top["score"], "typed": term}
        return best

    def map_vehicle_result(
        self,
        mysql_db: Session,
        proposal: WhatsappExtractionProposal,
        bodies: Sequence[str],
        ground_year: bool = True,
    ) -> tuple[Optional[ExtractionVehicle], str]:
        """Resolve the vehicle and say how the catalog lookup went.

        ground_year=True (a full seller message) also verifies the model's reading against what was
        written: an unwritten year or car is asked, not trusted. Pass False when the data comes from a
        draft that already holds it.

        Status is one of VEHICLE_MATCHED, VEHICLE_CORRECTED (an obvious typo fixed, the seller is
        told), VEHICLE_SUGGESTED (a close match to confirm; the vehicle comes back without the
        doubtful make/model and with `suggestion` set), VEHICLE_AMBIGUOUS, VEHICLE_UNRECOGNIZED
        (the car was named, the year known and the catalog has nothing for it) or VEHICLE_UNCHECKED
        (no year or no database, so no lookup could say either way).
        """
        vehicle = proposal.vehicle or ExtractionVehicle()
        year = (vehicle.year or "").strip() or None
        if not year:
            year = year_from_bodies(bodies)
        if not year:
            return proposal.vehicle, VEHICLE_UNCHECKED

        resolved = ExtractionVehicle(
            make=vehicle.make,
            model=vehicle.model,
            year=year,
            engine=vehicle.engine,
            vin=vehicle.vin,
        )
        if ground_year and not year_is_grounded(year, bodies):
            # The seller never wrote this year (a two-digit "doce", or the model guessed it): ask.
            resolved.year = None
            resolved.suggestion = {"year": year}
            return resolved, VEHICLE_UNCHECKED
        if mysql_db is None:
            return resolved, VEHICLE_UNCHECKED

        vehicle_terms, stray_terms = vehicle_search_term_groups(proposal, bodies)
        named_model = _normalize_text(vehicle.model or "")
        if named_model:
            # A model was named: only searches that include it can place the
            # car. A brand alone (or a word from the chat) says nothing about
            # the model, and an invented brand must not hide an unknown model.
            vehicle_terms = [t for t in vehicle_terms if named_model in _normalize_text(t)]
            stray_terms = [t for t in stray_terms if named_model in _normalize_text(t)]

        searched = False
        ambiguous = False
        lookups = [
            *[(t, False) for t in vehicle_terms],
            *[(v, False) for t in vehicle_terms[:1] for v in _trim_variants(t, vehicle.make)],
            *[(t, True) for t in stray_terms],
        ]
        for term, stray in lookups:
            unique = self._strict_unique(mysql_db, term, year)
            if unique is None:
                continue
            searched = True
            if len(unique) > 1:
                pick = _exact_model_hit(unique, vehicle.model or "") if vehicle.model else None
                family = _single_family(unique, vehicle.model) if vehicle.model else None
                if pick is None and family is not None:
                    pick = family
                    unique = [pick]
                elif pick is not None:
                    unique = [pick]
            if len(unique) > 1:
                ambiguous = True
            if len(unique) != 1:
                continue
            make, model = _hit_make_model(unique[0])
            if not make and not model:
                continue
            keep_typed_model = vehicle.model and _single_family(unique, vehicle.model) is not None \
                and _normalize_text(model) != _normalize_text(vehicle.model)
            found = ExtractionVehicle(
                make=make or resolved.make,
                model=(vehicle.model if keep_typed_model else model) or resolved.model,
                year=year,
                engine=resolved.engine,
                vin=resolved.vin,
            )
            if (vehicle.make or vehicle.model) and not stray and ground_year \
                    and not vehicle_is_written(vehicle, bodies) and not vehicle_is_written(found, bodies):
                # The catalog knows this car, but the seller never wrote it. A nickname the model
                # explained ("Jettita" -> Jetta) is offered to confirm; anything else is a guess the
                # model made up, and repeating it as a question would only plant it.
                found.make = found.model = None
                if _inferred_from_nickname(proposal, bodies):
                    found.suggestion = {"make": make or vehicle.make, "model": model or vehicle.model, "year": year}
                    return found, VEHICLE_SUGGESTED
                return found, VEHICLE_UNCHECKED
            if stray and (vehicle.make or vehicle.model):
                # The model read a car but the catalog only found one through a stray word of the
                # chat: a guess to confirm. When the model dropped the car entirely, that word is
                # the only signal there is, so it is accepted (a unique whole-word hit).
                found.suggestion = {"make": found.make, "model": found.model, "year": year}
                found.make = found.model = None
                return found, VEHICLE_SUGGESTED
            return found, VEHICLE_MATCHED
        if ambiguous:
            return resolved, VEHICLE_AMBIGUOUS

        if vehicle_terms and (vehicle.make or vehicle.model):
            fuzzy = self._fuzzy_vehicle(mysql_db, vehicle_terms, year)
            if fuzzy:
                top, second = fuzzy
                make, model = top.get("make"), top.get("model")
                typed = " ".join(x for x in (vehicle.make, vehicle.model) if x)
                clear = top["score"] >= VEHICLE_AUTO_CORRECT_SCORE and second <= top["score"] - 0.1
                if clear:
                    return (
                        ExtractionVehicle(
                            make=make or resolved.make,
                            model=model or resolved.model,
                            year=year,
                            engine=resolved.engine,
                            vin=resolved.vin,
                            corrected_from=typed or None,
                        ),
                        VEHICLE_CORRECTED,
                    )
                if top["score"] >= VEHICLE_SUGGEST_SCORE:
                    same_make = _normalize_text(make or "") == _normalize_text(vehicle.make or "")
                    return (
                        ExtractionVehicle(
                            make=resolved.make if same_make or not model else None,
                            model=None,
                            year=year,
                            engine=resolved.engine,
                            vin=resolved.vin,
                            suggestion={"make": make, "model": model, "year": year, "typed": typed},
                        ),
                        VEHICLE_SUGGESTED,
                    )

        if not vehicle.make and not vehicle.model:
            # The model read no car, yet the message has an unexplained word. If it is a typo of a car
            # of that year, offer it ("sibic" -> Honda Civic) as a question; never apply it.
            guess = self._fuzzy_stray_vehicle(mysql_db, unexplained_tokens(proposal, bodies), year)
            if guess:
                return (
                    ExtractionVehicle(
                        year=year,
                        engine=resolved.engine,
                        vin=resolved.vin,
                        suggestion={
                            "make": guess["make"], "model": guess["model"], "year": year, "typed": guess["typed"],
                        },
                    ),
                    VEHICLE_SUGGESTED,
                )

        if searched and (vehicle.make or vehicle.model):
            if vehicle.make and not _make_in_bodies(vehicle.make, bodies):
                # The customer never said this brand and the catalog has no
                # such model: the brand was a guess, not data.
                resolved = ExtractionVehicle(
                    make=None,
                    model=resolved.model,
                    year=year,
                    engine=resolved.engine,
                    vin=resolved.vin,
                )
            return resolved, VEHICLE_UNRECOGNIZED
        return resolved, VEHICLE_UNCHECKED
