from models import Vehiculos, Vehiculostipocaja, Vehiculostransmision, Vehiculomotores
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

class AcesVehiclesRepository:
    
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
        
        if not search_term:
            return []
        
        # Build query with multiple search strategies - year filter is mandatory
        query = mysql_db.query(Vehiculos).filter(Vehiculos.VehiculoAno == year)
        
        # Strategy 1: Exact match (case insensitive)
        exact_match = query.filter(
            func.lower(Vehiculos.VehiculoDescripcion) == func.lower(search_term)
        )
        
        # Strategy 2: Contains search (case insensitive)
        contains_match = query.filter(
            func.lower(Vehiculos.VehiculoDescripcion).contains(func.lower(search_term))
        )
        
        # Strategy 3: Word-based search (split by spaces and match all words)
        words = search_term.lower().split()
        word_filters = []
        for word in words:
            word_filters.append(
                func.lower(Vehiculos.VehiculoDescripcion).contains(word)
            )
        
        word_match = query.filter(*word_filters) if word_filters else query.filter(False)
        
        # Strategy 4: MySQL REGEXP for pattern matching
        regex_match = query.filter(
            Vehiculos.VehiculoDescripcion.op('REGEXP')(search_term)
        )
        
        # Combine all strategies with UNION (removes duplicates automatically)
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
            
            # Finally try regex (be careful with user input)
            if len(search_term) > 2:  # Only use regex for longer terms
                regex_results = regex_match.limit(50).all()
                return regex_results
            
            return []
            
        except Exception as e:
            # Fallback to simple contains search if regex fails
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
            vehicle_main = mysql_db.query(Vehiculos).filter(Vehiculos.VehiculoInternalId == int(id)).first()
            
            if not vehicle_main:
                return None
                
            # Optional: Load related data if needed
            # gearboxes = mysql_db.query(Vehiculostipocaja).filter(Vehiculostipocaja.VehiculoInternalId == int(id)).all()
            # transmission_types = mysql_db.query(Vehiculostransmision).filter(Vehiculostransmision.VehiculoInternalId == int(id)).all()
            
            return vehicle_main
            
        except Exception as e:
            print(f"Find by ID failed: {e}")
            return None