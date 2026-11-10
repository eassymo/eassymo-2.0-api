from app.repositories.AcesVehiclesRepository import AcesVehiclesRepository
from app.repositories.NonAcesVehiclesRepository import (
    list_non_aces_models,
    search_non_aces_models_page,
)
from app.utils import vehicle_fuzzy
from app.utils.regex_sanitize import MAX_SEARCH_LENGTH
from app.schemas.StandarizedVehicles import StandarizedVehicles
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union
from models import Vehiculos

ACES_MAX_YEAR = 2017
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_SUGGESTIONS = 3
# Offer "did you mean" next to real results only when there are very few of them.
SUGGEST_NEXT_TO_RESULTS_BELOW = 3
SUGGESTION_MIN_SCORE_WITH_RESULTS = 0.9


@dataclass
class VehicleSearchResult:
    vehicles: List[Any]
    total: int
    skip: int
    limit: int
    # "exact": matched what was typed · "fuzzy": nothing matched, these are the closest vehicles
    # (probable typo) · "none": nothing close either.
    match: str
    query: str
    suggestions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def has_more(self) -> bool:
        return self.skip + len(self.vehicles) < self.total

    def meta(self) -> Dict[str, Any]:
        return {
            "match": self.match,
            "query": self.query,
            "total": self.total,
            "skip": self.skip,
            "limit": self.limit,
            "has_more": self.has_more,
            "suggestions": self.suggestions,
        }


def _parse_year(year: str) -> int:
    if not year or not year.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Year is required")
    try:
        return int(year)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Year must be a valid integer")


def _suggestions_from(query: str, ranked, min_score: float, exclude=frozenset()) -> List[Dict[str, Any]]:
    """Distinct "did you mean" terms from ranked (make, model) candidates, best first."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for (make, model), score in ranked:
        if score < min_score or (make.lower(), model.lower()) in exclude:
            continue
        label = vehicle_fuzzy.suggestion_label(query, make, model)
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"term": label, "make": make, "model": model if label != make else None, "score": round(score, 2)})
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


class AcesVehiclesService:

    @staticmethod
    def _vocabulary(mysql_db: Session, year: int) -> List[Any]:
        if year <= ACES_MAX_YEAR:
            return AcesVehiclesRepository.list_models(mysql_db, year)
        return list_non_aces_models(year)

    @staticmethod
    def search_vehicles(
        mysql_db: Session,
        search_argument: str,
        year: str,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> VehicleSearchResult:
        """Typo-tolerant, paged vehicle search (one row per make+model).

        1. Exact/tokenised catalog search (separator-insensitive, aliases).
        2. When nothing matches, fuzzy-rank the year's make/model vocabulary so typos
           ("nisan sentr", "kai", "bolkswagen") still return the closest vehicles.
        3. Always offer up to 3 "did you mean" terms when the query looks mistyped.
        """
        term = (search_argument or "").strip()
        year_int = _parse_year(year)
        skip = max(0, skip)
        limit = min(max(1, limit), MAX_PAGE_SIZE)

        if not term or len(term) > MAX_SEARCH_LENGTH:
            return VehicleSearchResult([], 0, skip, limit, "none", term)

        try:
            if year_int <= ACES_MAX_YEAR:
                page, total = AcesVehiclesRepository.search_models_page(mysql_db, term, year_int, skip, limit)
            else:
                page, total = search_non_aces_models_page(term, year_int, skip, limit)

            if total > 0:
                suggestions: List[Dict[str, Any]] = []
                if skip == 0 and total < SUGGEST_NEXT_TO_RESULTS_BELOW:
                    vocabulary = AcesVehiclesService._vocabulary(mysql_db, year_int)
                    ranked = vehicle_fuzzy.rank_candidates(
                        term, [(v.VehiculoFabricante, v.VehiculoModelo) for v in vocabulary], limit=10
                    )
                    shown = {(v.VehiculoFabricante.lower(), v.VehiculoModelo.lower()) for v in page}
                    suggestions = _suggestions_from(term, ranked, SUGGESTION_MIN_SCORE_WITH_RESULTS, shown)
                return VehicleSearchResult(page, total, skip, limit, "exact", term, suggestions)

            vocabulary = AcesVehiclesService._vocabulary(mysql_db, year_int)
            by_pair = {(v.VehiculoFabricante, v.VehiculoModelo): v for v in vocabulary}
            ranked = vehicle_fuzzy.rank_candidates(term, list(by_pair.keys()), limit=200)
            if not ranked:
                return VehicleSearchResult([], 0, skip, limit, "none", term)

            window = ranked[skip:skip + limit]
            vehicles = [by_pair[pair] for pair, _ in window]
            suggestions = _suggestions_from(term, ranked, vehicle_fuzzy.MIN_CANDIDATE_SCORE)
            return VehicleSearchResult(vehicles, len(ranked), skip, limit, "fuzzy", term, suggestions)

        except HTTPException:
            raise
        except Exception as e:
            print(f"Service error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error while searching for vehicles: {str(e)}",
            )
    
    @staticmethod
    def find_aces_vehicles(
        mysql_db: Session,
        search_argument: str,
        year: str,
        allow_fuzzy: bool = False,
    ) -> Union[List[Vehiculos], List[StandarizedVehicles]]:
        """Vehicles that match what was typed (first page), for callers that only need a list.

        Strict by default: when nothing matches it returns [] instead of the closest vehicles.
        Callers that auto-accept a lone hit (the WhatsApp catalog mapper) must not receive guesses;
        pass allow_fuzzy=True only when a human will confirm the result.
        """
        result = AcesVehiclesService.search_vehicles(
            mysql_db, search_argument, year, 0, MAX_PAGE_SIZE
        )
        if result.match == "fuzzy" and not allow_fuzzy:
            return []
        return result.vehicles

    @staticmethod
    def find_vehicle_by_id(mysql_db: Session, id: str) -> Vehiculos:
        try:
            vehicle = AcesVehiclesRepository.find_by_id(mysql_db, id)

            return vehicle
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error while searchig for vehicle with id {id}"
            )
    

    @staticmethod
    def find_non_aces_engines(vehicle_model: str, vehicle_maker: str, vehicle_year: str) -> List[str]:
        try:

            v_year = int(vehicle_year)

            engines = AcesVehiclesRepository.find_engines(vehicle_model=vehicle_model, vehicle_maker=vehicle_maker, vehicle_year=v_year)

            return engines
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error while searching for non aces engines {id}"
            )