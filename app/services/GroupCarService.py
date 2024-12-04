from app.repositories import GroupCarRepository
from app.schemas.GroupVehicle import GroupVehicle
from pymongo.errors import PyMongoError
from fastapi import HTTPException
from app.repositories import PartRequestRepository
from bson import ObjectId


def insert(group_vehicle: GroupVehicle):
    try:
        vehicle = group_vehicle.toJson()
        vehicle.pop('_id')
        is_repeated: bool = False
        if group_vehicle.licensePlate is not None and len(group_vehicle.licensePlate) > 0:
            is_repeated = _check_if_license_plate_is_unique(
                group_vehicle.licensePlate)

        if not is_repeated:
            inserted_id = GroupCarRepository.insert(vehicle).inserted_id
            return str(inserted_id)
        else:
            raise HTTPException(
                status_code=500, detail=f'License plate is repeated')
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {err}')


def _check_if_license_plate_is_unique(license_plate: str):
    return len(list(GroupCarRepository.find({"licensePlate": license_plate}))) > 0


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


def edit(id: str, payload: GroupVehicle):
    try:
        vehicle_id = ObjectId(id)

        json_payload = payload.toJson()
        json_payload.pop("_id")

        GroupCarRepository.edit(vehicle_id, json_payload).modified_count

        found_vehicle_data = GroupCarRepository.find_by_id(id)

        vehicle = GroupVehicle(**found_vehicle_data)

        return vehicle.toJson()

    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while editing group vehicle {err}')


def remove(id: str):
    try:
        car_id = ObjectId(id)
        deleted_count = GroupCarRepository.soft_remove(car_id).modified_count
        return {"deleted_count": deleted_count}
    except PyMongoError as err:
        raise HTTPException(
            status_code=500, detail=f'Error while deleting the group car {err}')
