from app.repositories import GroupCarRepository
from app.schemas.GroupVehicle import GroupVehicle
from pymongo.errors import PyMongoError
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder


def insert(group_vehicle: GroupVehicle):
    try:
        vehicle = jsonable_encoder(group_vehicle)
        inserted_id = GroupCarRepository.insert(vehicle).inserted_id
        return str(inserted_id)
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {err}')


def find_by_group(group_id: str):
    try:
        vehicle_list = list(GroupCarRepository.find_by_group(group_id))
        vehicle_list = format_vehicle_list(vehicle_list)
        return vehicle_list
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding group cars{err}')


def format_vehicle_list(vehicle_list):
    formatted_list = []
    for vehicle in vehicle_list:
        formatted_list.append({
            **vehicle,
            "_id": str(vehicle["_id"])
        })
    return formatted_list


def find_by_id(id: str):
    try:
        found_vehicle = GroupCarRepository.find_by_id(id)
        return {**found_vehicle, "_id": str(found_vehicle["_id"])}
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding group vehicle by id {err}')
