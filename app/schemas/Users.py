from pydantic import BaseModel, Field, EmailStr
from typing import List
from enum import Enum

class UserRoles(Enum):
    ADMIN_BUYER_SHOP="322"
    ADMIN_SELLER_SHOP="212"

class UserSchema(BaseModel):
    name: str = Field(None, max_length=100,
                      description="Display name of the user")
    email: EmailStr = Field(None, max_length=60,
                            description="User Email address")
    phone: str = Field(None, max_length=13)
    phoneExtention: str = Field(None, max_length=4)
    uid: str = Field(
        None, description="Equivalence id that links the record with the firebase record")
    location: object = Field(None)
    roles: List[UserRoles] = Field(None)