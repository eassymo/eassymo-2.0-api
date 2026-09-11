from pydantic import BaseModel, Field


class WhatsappIntakeStartDto(BaseModel):
    phone: str = Field(..., min_length=10)


class WhatsappIntakeConfirmDto(BaseModel):
    token: str = Field(..., min_length=8)
