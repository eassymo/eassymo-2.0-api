from app.repositories import UserRepository as userRepository
from app.schemas.Users import UserSchema
from fastapi.encoders import jsonable_encoder
from pymongo.errors import PyMongoError


def create_user(user: UserSchema):
    user_exists = validate_if_users_exists(user.uid)

    if user_exists != None:
        return user_exists

    user = jsonable_encoder(user)
    userRepository.insert_user(user)
    created_user = userRepository.find_by_uid(user["uid"])
    return created_user


def find_user(uid: str):
    try:
        return userRepository.find_by_uid(uid)
    except PyMongoError as e:
        return 'Error While fetching user'


def update_user(uid: str, user: UserSchema):
    try:
        user_to_be_updated = userRepository.find_by_uid(uid)
        if (user == None):
            return {"message": "No user was found with that uid"}

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
    foundUser = {}
    try:
        foundUser = userRepository.find_by_uid(uid)
    except PyMongoError as e:
        print(f"MongoDB Error: {e}")
    return foundUser
