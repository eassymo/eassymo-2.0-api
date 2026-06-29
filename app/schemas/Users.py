from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import List, Optional, Union
from enum import Enum
from bson import ObjectId
from app.schemas.Groups import GroupSchema


class UserRoles(Enum):
    ADMIN_BUYER_SHOP = "322"
    ADMIN_SELLER_SHOP = "212"
    SELLER_SHOP = "213"
    STORAGE_SHOP = "214"
    DEALER_SHOP = "215"
    MECHANIC_CAR_REPAIR = "326"
    BUYER_CAR_REPAIR = "327"
    STORAGE_CAR_REPAIR = "324"

class UserSchema(BaseModel):
    id: str = Field(alias="_id", default=None)
    name: str = Field(None, max_length=100,
                      description="Display name of the user")
    email: EmailStr = Field("",
                            description="User Email address")
    phone: str = Field(None, max_length=13)
    phoneExtention: Optional[str] = Field(None, max_length=4)
    uid: str = Field(
        None, description="Equivalence id that links the record with the firebase record")
    location: object = Field(None)
    roles: List[UserRoles] = Field(None)
    groups: Optional[Union[List[str], List[GroupSchema]]] = Field(
        None, description="groups linked to this user")

    @model_validator(mode='before')
    @classmethod
    def convert_objectId(cls, values):
        if values is None:
            return {}
        if '_id' in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def add_group_to_user(self, group_id: str):
        current_groups = self.groups
        current_groups.append(group_id)
        self.groups = list(set(current_groups))

    def remove_group_from_user(self, group_id: str):
        current_groups = self.groups
        current_groups.remove(group_id)
        self.groups = list(set(current_groups))

    def toJson(self):
        data = self.model_dump(by_alias=True)

        user_roles = []

        if self.roles != None:
            for role in self.roles:
                user_roles.append(role.value)
        
        data["roles"] = user_roles
        return data
