from app.repositories import GroupCarRepository
from app.schemas.GroupVehicle import GroupVehicle
from pymongo.errors import PyMongoError
from fastapi import HTTPException
from app.repositories import PartRequestRepository


def insert(group_vehicle: GroupVehicle):
    try:
        vehicle = group_vehicle.dict()
        print(vehicle)
        inserted_id = GroupCarRepository.insert(vehicle).inserted_id
        return str(inserted_id)
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {err}')


def find_by_group(group_id: str):
    try:
        vehicle_list = []
        vehicle_list_data = list(GroupCarRepository.find_by_group(group_id))
        for vehicle in vehicle_list_data:
            vehicle_item = GroupVehicle(**vehicle)
            part_requests = list(PartRequestRepository.find(
                {"vehicleId": vehicle_item.id}, None))
            vehicle_item.numberOfRequests = len(part_requests)
            if len(part_requests) > 0:
                vehicle_item.parent_request_id = part_requests[0]["parent_request_uid"]
            vehicle_list.append(vehicle_item.toJson())

        return vehicle_list
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding group cars{err}')


def find_by_id(id: str):
    try:
        found_vehicle = GroupCarRepository.find_by_id(id)
        vehicle = GroupVehicle(**found_vehicle)
        part_requests = list(PartRequestRepository.find(
            {"vehicleId": vehicle.id}, None))
        vehicle.numberOfRequests = len(part_requests)
        if len(part_requests) > 0:
            vehicle.parent_request_id = part_requests[0]["parent_request_uid"]
        return vehicle.toJson()
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while finding group vehicle by id {err}')
