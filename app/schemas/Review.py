from datetime import datetime
from enum import Enum
from typing import Dict, Literal, Optional

from bson import ObjectId
from pydantic import BaseModel, Field, root_validator


class ReviewStatus(str, Enum):
    PENDING_REVEAL = "pending_reveal"
    VISIBLE = "visible"
    DISPUTED = "disputed"
    HIDDEN_BY_ADMIN = "hidden_by_admin"


class TransactionType(str, Enum):
    ORDER = "order"
    MOSTRADOR = "mostrador"


class ReviewerRole(str, Enum):
    BUYER = "buyer"
    SELLER = "seller"


class ReviewSubRatings(BaseModel):
    # Legacy (mapped on write to role-specific keys)
    communication: Optional[int] = Field(None, ge=1, le=5)
    timeliness: Optional[int] = Field(None, ge=1, le=5)
    as_described: Optional[int] = Field(None, ge=1, le=5)
    # Taller rates refaccionaria
    part_correct: Optional[int] = Field(None, ge=1, le=5)
    on_time: Optional[int] = Field(None, ge=1, le=5)
    handoff: Optional[int] = Field(None, ge=1, le=5)
    # Refaccionaria rates taller
    request_clarity: Optional[int] = Field(None, ge=1, le=5)
    reliable_pickup: Optional[int] = Field(None, ge=1, le=5)


class ReputationSummary(BaseModel):
    score_avg: float = Field(0.0)
    score_count: int = Field(0)
    sub_rating_avgs: Dict[str, float] = Field(default_factory=dict)
    sub_rating_counts: Dict[str, int] = Field(default_factory=dict)


class GroupReview(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    transaction_type: TransactionType
    transaction_id: str = Field(..., description="Order _id")
    reviewer_group_id: str
    reviewer_user_id: str
    reviewer_role: ReviewerRole
    reviewed_group_id: str
    score: int = Field(..., ge=1, le=5)
    sub_ratings: Optional[ReviewSubRatings] = None
    comment: Optional[str] = Field(None, max_length=1000)
    status: ReviewStatus = ReviewStatus.PENDING_REVEAL
    visibility_deadline: datetime
    revealed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @root_validator(pre=True)
    def convert_object_id(cls, values):
        if isinstance(values, dict) and "_id" in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.model_dump(by_alias=True, mode="json", exclude_none=True)
        if self.id is None:
            data.pop("_id", None)
        for key in ("transaction_type", "reviewer_role", "status"):
            val = data.get(key)
            if val is not None and hasattr(val, "value"):
                data[key] = val.value
        return data


class DisputeStatus(str, Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_UPHELD = "resolved_upheld"
    RESOLVED_HIDDEN = "resolved_hidden"
    RESOLVED_EDITED = "resolved_edited"


class ReviewDispute(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    review_id: str
    opened_by_group_id: str
    opened_by_user_id: str
    reason: str = Field(..., max_length=1000)
    status: DisputeStatus = DisputeStatus.OPEN
    assigned_admin_uid: Optional[str] = None
    admin_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @root_validator(pre=True)
    def convert_object_id(cls, values):
        if isinstance(values, dict) and "_id" in values and isinstance(values["_id"], ObjectId):
            values["_id"] = str(values["_id"])
        return values

    def toJson(self):
        data = self.model_dump(by_alias=True, mode="json", exclude_none=True)
        if self.id is None:
            data.pop("_id", None)
        status = data.get("status")
        if status is not None and hasattr(status, "value"):
            data["status"] = status.value
        return data


class SubmitReviewRequest(BaseModel):
    transaction_id: str
    score: int = Field(..., ge=1, le=5)
    sub_ratings: Optional[ReviewSubRatings] = None
    comment: Optional[str] = Field(None, max_length=1000)


class OpenDisputeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


class ResolveDisputeRequest(BaseModel):
    action: Literal["uphold", "hide", "edit"]
    admin_notes: Optional[str] = Field(None, max_length=2000)
    score: Optional[int] = Field(None, ge=1, le=5)
    sub_ratings: Optional[ReviewSubRatings] = None
    comment: Optional[str] = Field(None, max_length=1000)
