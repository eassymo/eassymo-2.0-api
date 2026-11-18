from app.utils.notification_routes import SELLER_OFFER_CREATOR_ROUTE, seller_offer_creator_path


def test_seller_notifications_open_the_v4_offer_creator():
    assert SELLER_OFFER_CREATOR_ROUTE == "/offer-creator-v4"
    assert seller_offer_creator_path("req-1") == "/offer-creator-v4/req-1"


def test_seller_path_falls_back_to_dashboard_without_id():
    assert seller_offer_creator_path("  ") == "/dashboard-v2"
