from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from pydantic import BaseModel, Field, field_validator


class CommissionerInviteStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class CommissionerInviteStatusHistoryEntry(BaseModel):
    status: CommissionerInviteStatus = Field(...)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(ZoneInfo("UTC")),
    )

    def to_json(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": str(self.timestamp),
        }

    def to_mongo(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
        }


class CommissionerInviteSchema(BaseModel):
    """Invite from a commissioner group to onboard a shop into its Comisionables list."""

    id: Optional[str] = Field(None, alias="_id")
    commissioner_group_id: str = Field(...)
    commissioner_group_name: str = Field("")
    initiating_user_uid: str = Field(
        ...,
        description="Commissioner-side user whose Comisionables list is updated on accept",
    )
    invited_group_id: str = Field(
        ...,
        description="Registered Eassymo group tied to census.group_reference_id",
    )
    invited_group_name: str = Field("")
    census_id: str = Field(..., description="Census Mongo _id as string")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(ZoneInfo("UTC")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(ZoneInfo("UTC")),
    )
    status: CommissionerInviteStatus = Field(
        CommissionerInviteStatus.PENDING,
    )
    status_history: List[CommissionerInviteStatusHistoryEntry] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def convert_oid(cls, v: Any):
        if isinstance(v, ObjectId):
            return str(v)
        return v

    def append_status(self, new_status: CommissionerInviteStatus) -> None:
        now = datetime.now(ZoneInfo("UTC"))
        self.status = new_status
        self.updated_at = now
        self.status_history.append(
            CommissionerInviteStatusHistoryEntry(status=new_status, timestamp=now)
        )

    def to_insert_document(self) -> Dict[str, Any]:
        return {
            "commissioner_group_id": self.commissioner_group_id,
            "commissioner_group_name": self.commissioner_group_name,
            "initiating_user_uid": self.initiating_user_uid,
            "invited_group_id": self.invited_group_id,
            "invited_group_name": self.invited_group_name,
            "census_id": self.census_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "status_history": [h.to_mongo() for h in self.status_history],
        }

    def to_update_document(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "updated_at": self.updated_at,
            "status_history": [h.to_mongo() for h in self.status_history],
        }

    def toJson(self) -> Dict[str, Any]:
        hid = getattr(self, "id", None) or getattr(self, "_id", None)
        return {
            "_id": str(hid) if hid else None,
            "commissioner_group_id": self.commissioner_group_id,
            "commissioner_group_name": self.commissioner_group_name,
            "initiating_user_uid": self.initiating_user_uid,
            "invited_group_id": self.invited_group_id,
            "invited_group_name": self.invited_group_name,
            "census_id": self.census_id,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "status": self.status.value,
            "status_history": [h.to_json() for h in self.status_history],
        }

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> "CommissionerInviteSchema":
        d = dict(doc)
        oid = d.get("_id")
        if oid is not None and not isinstance(oid, str):
            d["_id"] = str(oid)
        hist_raw = d.get("status_history") or []
        history: List[CommissionerInviteStatusHistoryEntry] = []
        for row in hist_raw:
            ts = row.get("timestamp") or row.get("time")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            st = row.get("status")
            history.append(
                CommissionerInviteStatusHistoryEntry(
                    status=CommissionerInviteStatus(st),
                    timestamp=ts,
                )
            )
        created = d.get("created_at")
        updated = d.get("updated_at")
        return cls(
            id=str(oid) if oid is not None else None,
            commissioner_group_id=d["commissioner_group_id"],
            commissioner_group_name=d.get("commissioner_group_name") or "",
            initiating_user_uid=d["initiating_user_uid"],
            invited_group_id=d["invited_group_id"],
            invited_group_name=d.get("invited_group_name") or "",
            census_id=d["census_id"],
            created_at=created if isinstance(created, datetime)
            else datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if created
            else datetime.now(ZoneInfo("UTC")),
            updated_at=updated if isinstance(updated, datetime)
            else datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            if updated
            else datetime.now(ZoneInfo("UTC")),
            status=CommissionerInviteStatus(d.get("status", "PENDING")),
            status_history=history,
        )
