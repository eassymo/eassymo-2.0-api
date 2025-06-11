from app.config import database
from bson import ObjectId
import pymongo
from pymongo.errors import PyMongoError


def insert(data):
    return database.db["Census"].insert_one(data)


def find(filters, limit=20, skip=0):
    try:
        census_filters = {
            **filters
        }

        census_filters.pop("limit", None)
        census_filters.pop("page", None)
        census_filters.pop("show_only_census", None)

        print(census_filters)
        if skip > 0:
            skip = limit * (skip - 1)
        return database.db["Census"].find(census_filters).limit(limit).skip(skip).sort([
            ('group_reference_id', pymongo.DESCENDING),
            ('Entity_Name', pymongo.ASCENDING)
        ])
    except Exception as e:
        raise


def count(filters):
    census_filters = {
        **filters,
        "Entity_Visible": "Y",
        "Entity_Active": "Y"
    }

    census_filters.pop("limit")
    census_filters.pop("page")

    total_count = database.db["Census"].count_documents(census_filters)
    group_count = database.db["Census"].count_documents(
        {**census_filters, "group_reference_id": {"$exists": True}})
    return {
        "total_count": total_count,
        "group_count": group_count
    }


def find_by_id(id):
    mongo_id = ObjectId(id)
    return database.db["Census"].find_one({"_id": mongo_id})


def update(id, body):
    mongo_id = ObjectId(id)
    return database.db["Census"].update_one({"_id": mongo_id}, {"$set": body})


def find_states():
    return database.db["Census"].distinct('Entity_Location_State')


def find_city(state: str):
    return database.db["Census"].distinct("Entity_Address_City", {"Entity_Location_State": state})


def find_with_geospatial(filters, lat, lng, max_distance_meters, limit=20, skip=0):
    """
    Find census documents using geospatial aggregation with distance calculation.
    
    Args:
        filters: MongoDB filters
        lat: Latitude for search center
        lng: Longitude for search center  
        max_distance_meters: Maximum distance in meters
        limit: Number of documents to return
        skip: Number of documents to skip
    
    Returns:
        Aggregation cursor with distance field added
    """
    try:
        # Remove pagination and geospatial fields from filters
        geo_filters = {**filters}
        geo_filters.pop("limit", None)
        geo_filters.pop("page", None) 
        geo_filters.pop("show_only_census", None)
        geo_filters.pop("location", None)  # Remove the $near query we added earlier
        
        # Check if there's a text search - MongoDB doesn't allow $text with $geoNear
        has_text_search = "$text" in geo_filters
        text_search_filter = None
        
        if has_text_search:
            # Extract text search and handle it separately
            text_search_filter = geo_filters.pop("$text")
        
        # Build aggregation pipeline
        # $geoNear must be the first stage
        geoNear_stage = {
            "$geoNear": {
                "near": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                },
                "distanceField": "distance_meters",
                "maxDistance": max_distance_meters,
                "spherical": True,
                "distanceMultiplier": 1
            }
        }
        
        # Add non-text filters to the query parameter of $geoNear
        if geo_filters:
            geoNear_stage["$geoNear"]["query"] = geo_filters
        
        pipeline = [geoNear_stage]
        
        # If there was a text search, add it as a separate $match stage after $geoNear
        # We'll use regex instead of $text search for compatibility
        if has_text_search and text_search_filter:
            search_term = text_search_filter["$search"]
            # Remove quotes if present and create a case-insensitive regex
            clean_search = search_term.strip('"')
            
            # Add regex search on Entity_Name field
            pipeline.append({
                "$match": {
                    "Entity_Name": {
                        "$regex": clean_search,
                        "$options": "i"  # case insensitive
                    }
                }
            })
        
        pipeline.append({
            "$sort": {
                "distance_meters": 1,  # Closest first
                "Entity_Name": 1  # Then by name
            }
        })
        
        if skip > 0:
            pipeline.append({"$skip": limit * (skip - 1)})
        
        pipeline.append({"$limit": limit})
        
        pipeline.append({
            "$addFields": {
                "distance_km": {"$divide": ["$distance_meters", 1000]}
            }
        })
        
        return database.db["Census"].aggregate(pipeline)
        
    except Exception as e:
        raise
