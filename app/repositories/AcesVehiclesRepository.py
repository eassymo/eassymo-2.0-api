from models import Vehiculos
from app.schemas.StandarizedVehicles import StandarizedVehicles
import time
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, case, func, or_

from app.config.database import db
from app.utils.regex_sanitize import MAX_SEARCH_LENGTH


_MODEL_CACHE: Dict[int, Tuple[float, List[StandarizedVehicles]]] = {}
_MODEL_CACHE_TTL_SECONDS = 600


def _to_standarized(vehicle: Vehiculos) -> StandarizedVehicles:
    return StandarizedVehicles(
        VehiculoInternalId=vehicle.VehiculoInternalId,
        VehicleId=vehicle.VehicleId or 0,
        BaseId=vehicle.BaseId or 0,
        VehiculoDescripcion=vehicle.VehiculoDescripcion or "",
        VehiculoFabricante=vehicle.VehiculoFabricante or "",
        VehiculoModelo=vehicle.VehiculoModelo or "",
        VehiculoSubModelo=vehicle.VehiculoSubModelo or "",
        VehiculoAno=vehicle.VehiculoAno,
        VehiculoTipo=vehicle.VehiculoTipo or "",
        VehiculoComentarios=vehicle.VehiculoComentarios or "",
        nonAcesVehicle=False,
    )


class AcesVehiclesRepository:

    @staticmethod
    def search_models_page(
        mysql_db: Session, search_argument: str, year: int, skip: int = 0, limit: int = 20
    ) -> Tuple[List[Vehiculos], int]:
        """One vehicle per make+model, ranked and paged in SQL. Returns (page, total_models)."""
        term = search_argument.strip().lower()
        if not term or len(term) > MAX_SEARCH_LENGTH:
            return [], 0

        description = func.lower(Vehiculos.VehiculoDescripcion)
        maker = func.lower(Vehiculos.VehiculoFabricante)
        model = func.lower(Vehiculos.VehiculoModelo)

        words = term.split()
        word_match = and_(*[description.contains(w, autoescape=True) for w in words])
        matches = or_(description.contains(term, autoescape=True), word_match)

        rank = case(
            (or_(maker == term, model == term), 0),
            (or_(maker.startswith(term, autoescape=True), model.startswith(term, autoescape=True)), 1),
            else_=2,
        )

        grouped = (
            mysql_db.query(
                func.min(Vehiculos.VehiculoInternalId).label("vid"),
                func.min(rank).label("rank"),
                Vehiculos.VehiculoFabricante.label("maker"),
                Vehiculos.VehiculoModelo.label("model"),
            )
            .filter(Vehiculos.VehiculoAno == year, matches)
            .group_by(Vehiculos.VehiculoFabricante, Vehiculos.VehiculoModelo)
        )

        total = grouped.count()
        rows = (
            grouped.order_by("rank", "maker", "model").offset(max(0, skip)).limit(max(1, limit)).all()
        )
        if not rows:
            return [], total

        ids = [row.vid for row in rows]
        by_id = {
            v.VehiculoInternalId: v
            for v in mysql_db.query(Vehiculos).filter(Vehiculos.VehiculoInternalId.in_(ids)).all()
        }
        return [by_id[i] for i in ids if i in by_id], total

    @staticmethod
    def list_models(mysql_db: Session, year: int) -> List[StandarizedVehicles]:
        """One representative vehicle per make+model for the year (cached): fuzzy vocabulary."""
        now = time.monotonic()
        cached = _MODEL_CACHE.get(year)
        if cached and now - cached[0] < _MODEL_CACHE_TTL_SECONDS:
            return cached[1]

        ids = [
            row.vid
            for row in mysql_db.query(func.min(Vehiculos.VehiculoInternalId).label("vid"))
            .filter(Vehiculos.VehiculoAno == year)
            .group_by(Vehiculos.VehiculoFabricante, Vehiculos.VehiculoModelo)
            .all()
        ]
        vehicles: List[StandarizedVehicles] = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            vehicles.extend(
                _to_standarized(v)
                for v in mysql_db.query(Vehiculos).filter(Vehiculos.VehiculoInternalId.in_(chunk)).all()
            )
        vehicles.sort(key=lambda v: (v.VehiculoFabricante.lower(), v.VehiculoModelo.lower()))
        _MODEL_CACHE[year] = (now, vehicles)
        return vehicles

    @staticmethod
    def find_vehicle_by_description(mysql_db: Session, search_argument: str, year: int) -> List[Vehiculos]:
        """
        Find vehicles by VehiculoDescripcion using text search or regex patterns

        Args:
            mysql_db: Database session
            search_argument: Search text or pattern

        Returns:
            List of matching Vehiculos
        """
        # Remove extra spaces and convert to lowercase for better matching
        search_term = search_argument.strip()

        if not search_term or len(search_term) > MAX_SEARCH_LENGTH:
            return []

        # Build query with multiple search strategies - year filter is mandatory
        query = mysql_db.query(Vehiculos).filter(Vehiculos.VehiculoAno == year)

        # Strategy 1: Exact match (case insensitive)
        exact_match = query.filter(
            func.lower(Vehiculos.VehiculoDescripcion) == func.lower(
                search_term)
        )

        # Strategy 2: Contains search (case insensitive)
        contains_match = query.filter(
            func.lower(Vehiculos.VehiculoDescripcion).contains(
                func.lower(search_term))
        )

        # Strategy 3: Word-based search (split by spaces and match all words)
        words = search_term.lower().split()
        word_filters = []
        for word in words:
            word_filters.append(
                func.lower(Vehiculos.VehiculoDescripcion).contains(word)
            )

        word_match = query.filter(
            *word_filters) if word_filters else query.filter(False)

        # Combine strategies without raw REGEXP (user input is not trusted as a pattern)
        try:
            # Try exact match first
            exact_results = exact_match.limit(50).all()
            if exact_results:
                return exact_results

            # Then try contains match
            contains_results = contains_match.limit(50).all()
            if contains_results:
                return contains_results

            # Then try word-based match
            word_results = word_match.limit(50).all()
            if word_results:
                return word_results

            return []

        except Exception:
            # Fallback to simple contains search if any strategy fails
            return contains_match.limit(50).all()

    @staticmethod
    def find_vehicle_by_description_simple(mysql_db: Session, search_argument: str) -> List[Vehiculos]:
        """
        Simple vehicle search using LIKE pattern matching

        Args:
            mysql_db: Database session
            search_argument: Search text

        Returns:
            List of matching Vehiculos
        """
        if not search_argument.strip():
            return []

        search_pattern = f"%{search_argument.strip()}%"

        return mysql_db.query(Vehiculos).filter(
            Vehiculos.VehiculoDescripcion.like(search_pattern)
        ).limit(100).all()

    @staticmethod
    def find_vehicle_by_regex(mysql_db: Session, regex_pattern: str) -> List[Vehiculos]:
        """
        Find vehicles using MySQL REGEXP

        Args:
            mysql_db: Database session
            regex_pattern: MySQL regex pattern

        Returns:
            List of matching Vehiculos
        """
        try:
            return mysql_db.query(Vehiculos).filter(
                Vehiculos.VehiculoDescripcion.op('REGEXP')(regex_pattern)
            ).limit(100).all()
        except Exception as e:
            print(f"Regex search failed: {e}")
            return []

    @staticmethod
    def find_by_id(mysql_db: Session, id: str) -> Vehiculos:
        """
        Find vehicle by VehiculoInternalId

        Args:
            mysql_db: Database session
            id: VehiculoInternalId as string

        Returns:
            Vehiculos object or None if not found
        """
        try:
            vehicle_main = mysql_db.query(Vehiculos).filter(
                Vehiculos.VehiculoInternalId == int(id)).first()

            if not vehicle_main:
                return None

            # Optional: Load related data if needed
            # gearboxes = mysql_db.query(Vehiculostipocaja).filter(Vehiculostipocaja.VehiculoInternalId == int(id)).all()
            # transmission_types = mysql_db.query(Vehiculostransmision).filter(Vehiculostransmision.VehiculoInternalId == int(id)).all()

            return vehicle_main

        except Exception as e:
            print(f"Find by ID failed: {e}")
            return None

    @staticmethod
    def find_engines(vehicle_model: str, vehicle_maker: str, vehicle_year: int) -> List[str]:
        try:

            results = db['NonAcesVehicles'].distinct('trim', {
                "model": vehicle_model,
                "make": vehicle_maker,
                "year": vehicle_year
            })

            return results

        except Exception as e:
            print(f"Find engines failed {e}")
            return None
