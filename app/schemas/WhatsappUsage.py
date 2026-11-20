from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.services.whatsapp_usage_math import MIN_WINDOW_SECONDS


class TierIn(BaseModel):
    name: str = Field(min_length=1)
    solicitudes_per_window: int = Field(ge=1)
    window_seconds: int = Field(ge=MIN_WINDOW_SECONDS)
    token_ceiling_per_window: int = Field(ge=1)
    burst_messages_per_minute: int = Field(ge=1)
    warn_at_percent: int = Field(ge=1, le=100)
    per_seller_cap_percent: Optional[int] = Field(default=None, ge=1, le=100)
    enforcement: Literal["shadow", "enforce"]
    active: bool = True


class GrantIn(BaseModel):
    amount: int = Field(ge=1)
    reason: str


class CreditRequestIn(BaseModel):
    note: Optional[str] = None


class SettingsPatch(BaseModel):
    enforcement_enabled: Optional[bool] = None
    shadow_all: Optional[bool] = None
    price_per_1k_prompt_tokens: Optional[float] = Field(default=None, ge=0)
    price_per_1k_completion_tokens: Optional[float] = Field(default=None, ge=0)
    error_alert_threshold: Optional[int] = Field(default=None, ge=0)
