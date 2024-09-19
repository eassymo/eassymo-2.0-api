from app.repositories import UserRepository as userRepository
from app.schemas.Users import UserSchema
from fastapi.encoders import jsonable_encoder
from pymongo.errors import PyMongoError


def create_user(user: UserSchema):
    user_exists = validate_if_users_exists(user.uid)
    print(user_exists)
    if user_exists != None:
        return user_exists

    user = {**jsonable_encoder(user), "groups": []}
    userRepository.insert_user(user)
    created_user = userRepository.find_by_uid(user["uid"])
    return created_user[0] if len(created_user) > 0 else None


def find_user(uid: str):
    try:
        return userRepository.find_by_uid(uid)
    except PyMongoError as e:
        return 'Error While fetching user'


def update_user(uid: str, user: UserSchema):
    try:
        found_user = list(userRepository.find_by_uid(uid))
        if (user == None):
            return {"message": "No user was found with that uid"}

        if (len(found_user) == 0):
            return {"message": "No users found"}

        user_to_be_updated = found_user[0]

        user_to_be_updated["name"] = user.name if user.name is not None else user_to_be_updated.get(
            "name", None)
        user_to_be_updated["email"] = user.email if user.email is not None else user_to_be_updated.get(
            "email", None)
        user_to_be_updated["phone"] = user.phone if user.phone is not None else user_to_be_updated.get(
            "phone", None)
        user_to_be_updated["phoneExtention"] = user.phoneExtention if user.phoneExtention is not None else user_to_be_updated.get(
            "phoneExtention", None)
        user_to_be_updated["location"] = user.location if user.location is not None else user_to_be_updated.get(
            "location", None)

        if user.roles is not None:
            user_to_be_updated["roles"] = [role.value for role in user.roles]
        else:
            user_to_be_updated["roles"] = user_to_be_updated.get("roles", None)

        userRepository.update_user(uid, user_to_be_updated)
        return {"message": "ok", "body": user_to_be_updated}
    except PyMongoError as error:
        return {"message": f'Error while updating user {error}'}


def validate_if_users_exists(uid: str):
    print(uid)
    foundUser = {}
    try:
        user = list(userRepository.find_by_uid(uid))
        print(user)
        if (len(user) > 0):
            foundUser = user[0]
            foundUser = {
                **foundUser,
                "groups": __format_groups(foundUser["groups"])
            }
        else:
            return None
    except PyMongoError as e:
        print(f"MongoDB Error: {e}")
    return foundUser


def __format_groups(groups):
    formatted_groups = []
    for group in groups:
        formatted_groups.append({
            **group,
            "_id": str(group["_id"])
        })
    return formatted_groups
