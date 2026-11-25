# Seller offer creator opened by notifications. Keep in sync with the client's
# OFFER_CREATOR_ROUTE (src/common/utils/offer-creator-route.ts); rollback = "/offer-creator-v3".
SELLER_OFFER_CREATOR_ROUTE = "/offer-creator-v4"


def seller_offer_creator_path(request_id: str) -> str:
    request_id = (request_id or "").strip()
    return f"{SELLER_OFFER_CREATOR_ROUTE}/{request_id}" if request_id else "/dashboard-v2"


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


# Orders page opened by notifications. Keep in sync with the client's ORDERS_ROUTE
# (src/common/utils/orders-route.ts); rollback = the v2 orders page.
ORDERS_ROUTE = "/order-management-v3"


def order_management_path(order_id: str, current_role: int | None = None) -> str:
    order_id = (order_id or "").strip()
    if not order_id:
        return ORDERS_ROUTE
    if current_role is not None:
        return f"{ORDERS_ROUTE}/{order_id}?currentRole={current_role}"
    return f"{ORDERS_ROUTE}/{order_id}"


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
