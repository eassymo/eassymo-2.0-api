from app.config import database
from app.schemas.StandarizedVehicles import StandarizedVehicles
from typing import List


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

        search_pattern = {"$regex": search_argument, "$options": "i"}
        
        pipeline = [
            {
                "$match": {
                    "year": year,
                    "is_active": 1
                }
            },
            {
                "$addFields": {
                    "make_model_combined": {
                        "$concat": ["$make", " ", "$model"]
                    }
                }
            },
            {
                "$match": {
                    "$or": [
                        {"make": search_pattern},
                        {"model": search_pattern},
                        {"make_model_combined": search_pattern},
                        {"generation": search_pattern},
                        {"trim": search_pattern}
                    ]
                }
            },
            {
                "$addFields": {
                    "relevance_score": {
                        "$add": [
                            # Exact make match gets highest score
                            {"$cond": [{"$eq": [{"$toLower": "$make"}, search_argument.lower()]}, 100, 0]},
                            # Exact model match gets high score
                            {"$cond": [{"$eq": [{"$toLower": "$model"}, search_argument.lower()]}, 90, 0]},
                            # Make starts with search gets medium score
                            {"$cond": [{"$regexMatch": {"input": "$make", "regex": f"^{search_argument}", "options": "i"}}, 50, 0]},
                            # Model starts with search gets medium score
                            {"$cond": [{"$regexMatch": {"input": "$model", "regex": f"^{search_argument}", "options": "i"}}, 45, 0]},
                            # Contains match gets low score
                            {"$cond": [{"$regexMatch": {"input": "$make_model_combined", "regex": search_argument, "options": "i"}}, 10, 0]}
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

        for non_aces_vehicle in result:
            standarized_vehicles.append(
                StandarizedVehicles(
                    VehicleId=non_aces_vehicle.get("trim_id", 0),
                    BaseId=non_aces_vehicle.get("make_id", 0),
                    VehiculoAno=non_aces_vehicle.get("year", 0),
                    VehiculoComentarios="",
                    VehiculoDescripcion=f'{non_aces_vehicle.get("year")}, {non_aces_vehicle.get("make")}, {non_aces_vehicle.get("model")}, {non_aces_vehicle.get("generation")}, {non_aces_vehicle.get("trim")}, {non_aces_vehicle.get("gearbox")}',
                    VehiculoFabricante=non_aces_vehicle.get("make", ""),
                    VehiculoInternalId=non_aces_vehicle.get("trim_id", 0),
                    VehiculoModelo=non_aces_vehicle.get("model", ""),
                    VehiculoSubModelo=non_aces_vehicle.get("generation", ""),
                    VehiculoTipo="Carro",
                    nonAcesVehicle=True
                )
            )

        return standarized_vehicles
        
    except Exception as e:
        print(f"MongoDB aggregation error: {str(e)}")
        raise Exception(f"Error searching NonAces vehicles: {str(e)}")


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