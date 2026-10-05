from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.schemas.Review import OpenDisputeRequest, SubmitReviewRequest
from app.services import ReviewService
from app.dependencies.group_auth import assert_group_membership, require_authenticated_uid
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response

reviewRouter = APIRouter(prefix="/review", tags=["Reviews"])


def _error_response(exception: Exception, *, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
    return JSONResponse(status_code=status_code, content=get_unsuccessful_response(exception))


def _group_selected(request: Request) -> Optional[str]:
    return getattr(request.state, "groupSelected", None)


@reviewRouter.post("", description="Submit a review for a completed transaction")
def submit_review(request: Request, payload: SubmitReviewRequest = Body(...)):
    try:
        reviewer_group_id = _group_selected(request)
        if not reviewer_group_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("GroupSelected header is required"),
            )
        user_uid = request.state.user.get("uid")
        result = ReviewService.submit_review(
            user_uid=user_uid,
            reviewer_group_id=reviewer_group_id,
            payload=payload,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@reviewRouter.get("/pending", description="Transactions awaiting review from the selected group")
def pending_reviews(request: Request):
    try:
        reviewer_group_id = _group_selected(request)
        if not reviewer_group_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("GroupSelected header is required"),
            )
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, reviewer_group_id)
        result = ReviewService.get_pending_reviews(reviewer_group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@reviewRouter.get("/submitted", description="Reviews already submitted by the selected group")
def submitted_reviews(request: Request):
    try:
        reviewer_group_id = _group_selected(request)
        if not reviewer_group_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("GroupSelected header is required"),
            )
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, reviewer_group_id)
        result = ReviewService.get_submitted_reviews(reviewer_group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@reviewRouter.get("/group/{group_id}", description="Visible reviews for a group")
def group_reviews(
    group_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    try:
        result = ReviewService.get_group_reviews(group_id, page=page, page_size=page_size)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@reviewRouter.get("/group/{group_id}/reputation", description="Cached reputation summary for a group")
def group_reputation(group_id: str):
    try:
        result = ReviewService.get_group_reputation(group_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)


@reviewRouter.post("/{review_id}/dispute", description="Open a dispute on a visible review")
def open_dispute(
    request: Request,
    review_id: str,
    payload: OpenDisputeRequest = Body(...),
):
    try:
        group_id = _group_selected(request)
        if not group_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response("GroupSelected header is required"),
            )
        user_uid = request.state.user.get("uid")
        result = ReviewService.open_dispute(
            review_id=review_id,
            user_uid=user_uid,
            group_id=group_id,
            payload=payload,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except HTTPException as e:
        return _error_response(e, status_code=e.status_code)
    except Exception as e:
        return _error_response(e)
