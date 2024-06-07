from app.repositories import PartRequestRepository as partRequestRepository
from app.schemas.PartRequest import PartRequest
from app.repositories import GroupCarRepository as groupCarRepository
from fastapi import HTTPException


def insert(part_request: PartRequest):
    try:
        part_req = part_request.model_dump()
        vehicle_information = groupCarRepository.find_by_id(
            part_req["vehicleId"])
        part_request_payload = {
            **part_req,
            "vehicleInformation": vehicle_information
        }
        part_request_id = partRequestRepository.insert(
            part_request_payload).inserted_id

        return str(part_request_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def find(user_uid: str, group_id: str):
    try:
        found_requests = partRequestRepository.find_by_group_and_user(
            user_uid, group_id)
        
        found_requests_list = list(found_requests)
        return format_part_requests(found_requests_list)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while inserting group vehicle {e}')


def format_part_requests(part_requests):
    formatted_requests = []
    for part_request in part_requests:
        formatted_requests.append({
            **part_request,
            "vehicleInformation": {
                **part_request["vehicleInformation"],
                "_id": str(part_request["vehicleInformation"]["_id"])
            },
            "_id": str(part_request["_id"])
        })
    return formatted_requests
