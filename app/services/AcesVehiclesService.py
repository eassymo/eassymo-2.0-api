from app.repositories.AcesVehiclesRepository import AcesVehiclesRepository
from app.repositories.NonAcesVehiclesRepository import find_non_aces_by_name
from app.schemas.StandarizedVehicles import StandarizedVehicles
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from typing import List, Union
from models import Vehiculos

class AcesVehiclesService:
    
    @staticmethod
    def find_aces_vehicles(mysql_db: Session, search_argument: str, year: str) -> Union[List[Vehiculos], List[StandarizedVehicles]]:
        """
        Find vehicles by description using the appropriate repository based on year
        
        Args:
            mysql_db: Database session
            search_argument: Search text
            year: Vehicle year (string)
            
        Returns:
            List of matching vehicles (Vehiculos objects for ACES, dict objects for NonAces)
        """
        try:
            if not search_argument or not search_argument.strip():
                return []

            if not year or not year.strip():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Year is required")
            
            try:
                year_int = int(year)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Year must be a valid integer")

            # Route to appropriate repository based on year
            if year_int <= 2017:
                vehicles = AcesVehiclesRepository.find_vehicle_by_description(mysql_db, search_argument, year_int)
            else:
                vehicles = find_non_aces_by_name(search_argument, year_int)
            
            return vehicles
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"Service error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail=f"Error while searching for vehicles: {str(e)}"
            )

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