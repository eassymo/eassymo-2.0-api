from pydantic import BaseModel, Field
from typing import Optional

class CensusSchema(BaseModel):
    Census_Country: Optional[str] = Field(None, description="Census country")
    Entity_Type: Optional[int] = Field(None, description="Type of the entity")
    Entity_Class: Optional[int] = Field(None, description="Class of entity")
    Entity_Mode: Optional[int] = Field(None, description="Mode of entity")
    Entity_Visible: Optional[str] = Field(None, description="Determines if is visible Y if it is N if is not")
    Entity_Status: Optional[str] = Field(None, description="Status of entity")
    Entity_Name: Optional[str] = Field(None, description="Social name of the entity")
    Entity_Address_Short: Optional[str] = Field(None, description="Address of the entity")
    Entity_Address_City: Optional[str] = Field(None, description="City")
    Entity_Location_State: Optional[str] = Field(None, description="State")
    Entity_Phone: Optional[int] = Field(None, description="Phone")
    Entity_Location_Lat: Optional[str] = Field(None, description="lat")
    Entity_Location_Lon: Optional[str] = Field(None, description="lng")
    Entity_Stat_Nr1: Optional[int] = Field(None, description="Nr1")
    Entity_Stat_Nr2: Optional[str] = Field(None, description="Nr2")
    Entity_Stat_Activity_Code: int = Field(None, description="Activity Code")
    Entity_Size_Emp: Optional[str] = Field(None, description="Business size")
    Entity_Log_Ref1_Type: Optional[str] = Field(None, description="Ref 1")
    Entity_Log_Ref2_Type: Optional[str] = Field(None, description="Ref 2 type")
    Entity_Log_Ref2_Name: Optional[str] = Field(None, description="Ref 2 name")
    Entity_Log_Ref3_Name: Optional[str] = Field(None, description="Ref 3 name")
    Entity_Log_Ref3_Type: Optional[str] = Field(None, description="Ref 3 type")
    Entity_Address_StType: Optional[str] = Field(None, description="Type")
    Entity_Address_StName: Optional[str] = Field(None, description="St Name")
    Entity_Address_Number: Optional[int] = Field(None, description="Number of address")
    Entity_Address_SectorType: Optional[str] = Field(None, description="Square address")
    Entity_Address_SectorName: Optional[str] = Field(None, description="Square address sector name")
    group_reference_id: Optional[str] = Field(None, description="reference of eassymo group")