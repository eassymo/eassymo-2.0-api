def seller_offer_creator_path(request_id: str) -> str:
    request_id = (request_id or "").strip()
    return f"/offer-creator-v3/{request_id}" if request_id else "/dashboard-v2"


def buyer_offer_review_path(
    request_id: str,
    parent_request_uid: str | None = None,
) -> str:
    parent = (parent_request_uid or "").strip()
    if parent:
        return f"/dynamic-offer-selector/{parent}"
    request_id = (request_id or "").strip()
    if request_id:
        return f"/multiple-offer-viewer/{request_id}"
    return "/dashboard-v2"


def order_management_v2_path(order_id: str) -> str:
    order_id = (order_id or "").strip()
    return f"/order-management-v2/{order_id}" if order_id else "/order-management-v2"


def buyer_offer_notification_meta(
    request_id: str,
    parent_request_uid: str | None = None,
    offer_id: str | None = None,
) -> dict:
    meta: dict = {
        "requestId": request_id,
        "parentRequestUid": (parent_request_uid or "").strip(),
    }
    if offer_id:
        meta["offerId"] = offer_id
    return meta
