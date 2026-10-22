from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RelationshipDirection(str, Enum):
    COMPRANDO = "comprando"
    VENDIENDO = "vendiendo"


class RelationshipAnswer(str, Enum):
    BIEN = "bien"
    REGULAR = "regular"
    PUEDE_MEJORAR = "puede_mejorar"


class ReminderCadence(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    OFF = "off"


class SubmitPerceptionRequest(BaseModel):
    counterpart_group_id: str
    direction: RelationshipDirection
    answer: RelationshipAnswer


class SaveReminderPrefsRequest(BaseModel):
    cadence: ReminderCadence
    weekday: int = Field(4, ge=0, le=6)
    hour: int = Field(17, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)


class RelationshipReminderPrefs(BaseModel):
    uid: str
    cadence: ReminderCadence = ReminderCadence.WEEKLY
    weekday: int = Field(4, ge=0, le=6)
    hour: int = Field(17, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    last_sent_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
