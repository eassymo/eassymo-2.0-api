import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.repositories.VehiculoSensibilidadesRepository import VehiculoSensibilidadesRepository
from app.schemas.VehiculoPartesSearch import HistoricoBusquedaInput, SearchPartesPaginatorRequest
from app.schemas.WhatsappExtraction import ExtractionLine, ExtractionVehicle, WhatsappExtractionProposal
from app.services.AcesVehiclesService import AcesVehiclesService
from app.services.EstandarizadorService import get_unidades_medida_by_parte
from app.services.VehiculoPartesService import search_partes_paginator

POSITION_NO_APLICA = "No aplica"

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
    if len(scored) > 1 and scored[1][0] >= best_score - 5:
        return None

    return {
        "tipoParteId": best_item.get("tipoParteId"),
        "tipoParteDescripcion": best_item.get("tipoParteDescripcion"),
        "categoriaId": best_item.get("categoriaId"),
        "subCategoriaId": best_item.get("subCategoriaId"),
        "tipoParteSensiblePosicion": bool(best_item.get("tipoParteSensiblePosicion")),
    }


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


def _map_position(
    mysql_db: Session,
    *,
    tipo_parte_id: Optional[int],
    position_sensitive: bool,
    candidates: Sequence[str],
) -> tuple[str, bool]:
    official = _load_position_names(mysql_db, tipo_parte_id)
    official_by_norm = {_normalize_text(name): name for name in official if name}

    for candidate in candidates:
        for token in _tokenize(candidate):
            alias = POSITION_ALIASES.get(token)
            if alias and alias in official:
                return alias, True
            norm = _normalize_text(token)
            if norm in official_by_norm:
                return official_by_norm[norm], True

    if not position_sensitive:
        return POSITION_NO_APLICA, False

    for candidate in candidates:
        norm = _normalize_text(candidate)
        if norm in official_by_norm:
            return official_by_norm[norm], True

    if POSITION_NO_APLICA in official:
        return POSITION_NO_APLICA, False

    return POSITION_NO_APLICA, False


def _map_unit(
    mysql_db: Session,
    *,
    tipo_parte_id: Optional[int],
    unit_hint: Optional[str],
) -> str:
    default = "Pieza"
    if not unit_hint:
        return default

    hint_norm = _normalize_text(unit_hint)
    alias = UNIT_ALIASES.get(hint_norm)
    if alias:
        mapped = alias
    else:
        mapped = unit_hint.strip().title() or default

    if mysql_db is None or not tipo_parte_id:
        return mapped

    units_payload = get_unidades_medida_by_parte(mysql_db, tipo_parte_id)
    labels = [
        (item.get("etiquetaDefecto") or "").strip()
        for item in (units_payload.get("lstUnidadesMedida") or [])
        if (item.get("etiquetaDefecto") or "").strip()
    ]
    if not labels:
        return mapped

    mapped_norm = _normalize_text(mapped)
    for label in labels:
        if _normalize_text(label) == mapped_norm:
            return label
    for label in labels:
        if mapped_norm in _normalize_text(label):
            return label
    return labels[0]


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


def vehicle_search_terms(
    proposal: WhatsappExtractionProposal,
    bodies: Sequence[str],
) -> List[str]:
    terms: List[str] = []
    vehicle = proposal.vehicle
    if vehicle:
        if vehicle.make and vehicle.model:
            terms.append(f"{vehicle.make} {vehicle.model}")
        if vehicle.model:
            terms.append(vehicle.model)
        if vehicle.make:
            terms.append(vehicle.make)
    for evidence in proposal.evidence or []:
        if (evidence.path or "").startswith("vehicle") and evidence.raw:
            terms.append(evidence.raw)

    part_tokens = set()
    for line in proposal.lines or []:
        part_tokens.update(_tokenize(line.part_name))
        if line.raw:
            part_tokens.update(_tokenize(line.raw))
        if line.position:
            part_tokens.update(_tokenize(line.position))

    for body in bodies or []:
        for token in _tokenize(body):
            if (
                token in VEHICLE_STOPWORDS
                or token.isdigit()
                or token in part_tokens
                or len(token) < 3
            ):
                continue
            terms.append(token)

    seen = set()
    ordered: List[str] = []
    for term in terms:
        key = _normalize_text(term)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(term.strip())
    return ordered


class WhatsappCatalogMapper:
    def map_line(self, mysql_db: Session, line: ExtractionLine) -> MappedPieceLine:
        raw_tokens = _tokenize(line.part_name)
        position_tokens = [token for token in raw_tokens if token in POSITION_ALIASES]
        search_term = strip_position_tokens(line.part_name, line.position)
        catalog = _pick_catalog_match(mysql_db, search_term)

        tipo_parte_id = catalog.get("tipoParteId") if catalog else None
        position, position_suggested = _map_position(
            mysql_db,
            tipo_parte_id=int(tipo_parte_id) if tipo_parte_id else None,
            position_sensitive=bool(catalog and catalog.get("tipoParteSensiblePosicion")),
            candidates=_position_candidates(line, position_tokens),
        )

        unit = _map_unit(
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
        vehicle = proposal.vehicle or ExtractionVehicle()
        year = (vehicle.year or "").strip() or None
        if not year:
            year = year_from_bodies(bodies)
        if not year:
            return proposal.vehicle

        resolved = ExtractionVehicle(
            make=vehicle.make,
            model=vehicle.model,
            year=year,
            engine=vehicle.engine,
            vin=vehicle.vin,
        )
        if mysql_db is None:
            return resolved

        for term in vehicle_search_terms(proposal, bodies):
            try:
                hits = AcesVehiclesService.find_aces_vehicles(mysql_db, term, year)
            except Exception:
                continue
            unique = _unique_vehicle_hits(hits)
            if len(unique) != 1:
                continue
            make, model = _hit_make_model(unique[0])
            if not make and not model:
                continue
            return ExtractionVehicle(
                make=make or resolved.make,
                model=model or resolved.model,
                year=year,
                engine=resolved.engine,
                vin=resolved.vin,
            )
        return resolved
