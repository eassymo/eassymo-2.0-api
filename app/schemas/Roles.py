from pydantic import BaseModel, Field, EmailStr

class RolesSchema(BaseModel):
    description: str = Field(None, description="This is the description of the role, will be displayed in the FE list")
    value: str = Field(None, description="Value we get from the table")
    display: bool = Field(True, description="Determines if will be displayed")
    entityType: str = Field(None, description="Determines the type of bussiness")