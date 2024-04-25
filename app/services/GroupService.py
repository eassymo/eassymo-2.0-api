from app.repositories import GroupRepository as groupRepository
from app.repositories import CensusRepository as censusRepository
from app.repositories import UserRepository as userRepository
from app.schemas.Groups import GroupSchema
from app.schemas.Census import CensusSchema
from pymongo.errors import PyMongoError
from fastapi import HTTPException


def create_group(group: GroupSchema, censusReference: str, user_id: str):

    group_data = {
        **group.model_dump(),
        "since": str(group.since),
        "censusReference": censusReference,
        "type": group.type,
        "group_store_type": group.type,
        "users": [user_id],
        "owner": user_id
    }

    created_group = groupRepository.insert(group_data)
    created_group_id = str(created_group.inserted_id)
    userRepository.add_user_group(user_id, created_group_id)

    if censusReference is not None:
        census_json = censusRepository.find_by_id(censusReference)
        census_data = CensusSchema(**census_json)
        census_data.Entity_Status = "1"
        censusRepository.update(
            censusReference, {"group_reference_id": created_group_id})

    if censusReference is None:
        census_data = CensusSchema(
            Census_Country="Mexico",
            Entity_Address_City=group.city,
            Entity_Address_Short=group.address,
            Entity_Name=group.name,
            Entity_Type=group.type,
            Entity_Visible="1",
            Entity_Status="1",
            group_reference_id=created_group_id
        )
        census_json = census_data.model_dump()
        censusRepository.insert(census_json)

    group_data["_id"] = str(group_data["_id"])

    return {"message": "ok", "body": group_data}


def find_by_user_id(uid: str):
    try:
        group_list = list(groupRepository.find_by_user(uid))
        return {"message": "ok", "body": group_list}
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail="Error while finding groups")