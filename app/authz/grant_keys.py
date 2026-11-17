"""Grant keys checked by code. Must match the `grants` collection (seeded from scripts/data/grants_catalog.json)."""

NETWORK_CONFIGURE_AGRUPADOR = "network.configure_agrupador"
STORE_EDIT_PROFILE = "store.edit_profile"
STORE_CONFIGURE_CATALOG = "store.configure_catalog"
STORE_MANAGE_FILTERS = "store.manage_filters"
STORE_MANAGE_CALLCENTER = "store.manage_callcenter"
STORE_MANAGE_COMMISSIONERS = "store.manage_commissioners"
NOTIFICATIONS_CONFIGURE = "notifications.configure"
TEAM_VIEW = "team.view"
TEAM_INVITE = "team.invite"
TEAM_ASSIGN_ROLES = "team.assign_roles"
TEAM_MANAGE_MEMBERS = "team.manage_members"
NETWORK_VIEW = "network.view"
NETWORK_INVITE = "network.invite"
NETWORK_MANAGE_LISTS = "network.manage_lists"
RELATIONSHIPS_MANAGE = "relationships.manage"
REQUESTS_VIEW = "requests.view"
REQUESTS_VIEW_ALL = "requests.view_all"
REQUESTS_CREATE = "requests.create"
REQUESTS_EDIT = "requests.edit"
REQUESTS_APPROVE = "requests.approve"
REQUESTS_INVITE_SELLERS = "requests.invite_sellers"
STORE_MANAGE_VEHICLES = "store.manage_vehicles"
OFFERS_VIEW_RECEIVED = "offers.view_received"
OFFERS_ACCEPT = "offers.accept"
OFFERS_VIEW_INCOMING = "offers.view_incoming"
OFFERS_VIEW_ALL = "offers.view_all"
OFFERS_CREATE = "offers.create"
OFFERS_EDIT = "offers.edit"
OFFERS_APPROVE = "offers.approve"
MEDIA_CAPTURE_IMAGES = "media.capture_images"
ORDERS_VIEW = "orders.view"
ORDERS_VIEW_ALL = "orders.view_all"
ORDERS_CHANGE_STATUS = "orders.change_status"
ORDERS_RECEIVE = "orders.receive"
ORDERS_CHANGE_DELIVERY_TIME = "orders.change_delivery_time"
ORDERS_ASSIGN_DELIVERY = "orders.assign_delivery"
SHIPPING_PREPARE = "shipping.prepare"
DELIVERIES_PERFORM = "deliveries.perform"
KITTING_CONFIGURE = "kitting.configure"
POS_VIEW = "pos.view"
POS_VIEW_ALL = "pos.view_all"
POS_CREATE = "pos.create"
POS_QUOTE = "pos.quote"
POS_SHARE = "pos.share"
POS_CLOSE_SALE = "pos.close_sale"
POS_MANAGE_CUSTOMER = "pos.manage_customer"
CHAT_PUBLIC = "chat.public"
CHAT_PRIVATE = "chat.private"
WHATSAPP_CREATE_DRAFT = "whatsapp.create_draft"
WHATSAPP_POS_INTAKE = "whatsapp.pos_intake"
PRICES_VIEW = "prices.view"
REPORTS_VIEW = "reports.view"
REVIEWS_SUBMIT = "reviews.submit"
REVIEWS_DISPUTE = "reviews.dispute"
EASSYMO_SYNONYMS = "eassymo.synonyms"
EASSYMO_SENSITIVITIES = "eassymo.sensitivities"
EASSYMO_UOM = "eassymo.uom"
EASSYMO_PRICING = "eassymo.pricing"

ALL_KEYS: frozenset[str] = frozenset({
    NETWORK_CONFIGURE_AGRUPADOR,
    STORE_EDIT_PROFILE,
    STORE_CONFIGURE_CATALOG,
    STORE_MANAGE_FILTERS,
    STORE_MANAGE_CALLCENTER,
    STORE_MANAGE_COMMISSIONERS,
    NOTIFICATIONS_CONFIGURE,
    TEAM_VIEW,
    TEAM_INVITE,
    TEAM_ASSIGN_ROLES,
    TEAM_MANAGE_MEMBERS,
    NETWORK_VIEW,
    NETWORK_INVITE,
    NETWORK_MANAGE_LISTS,
    RELATIONSHIPS_MANAGE,
    REQUESTS_VIEW,
    REQUESTS_VIEW_ALL,
    REQUESTS_CREATE,
    REQUESTS_EDIT,
    REQUESTS_APPROVE,
    REQUESTS_INVITE_SELLERS,
    STORE_MANAGE_VEHICLES,
    OFFERS_VIEW_RECEIVED,
    OFFERS_ACCEPT,
    OFFERS_VIEW_INCOMING,
    OFFERS_VIEW_ALL,
    OFFERS_CREATE,
    OFFERS_EDIT,
    OFFERS_APPROVE,
    MEDIA_CAPTURE_IMAGES,
    ORDERS_VIEW,
    ORDERS_VIEW_ALL,
    ORDERS_CHANGE_STATUS,
    ORDERS_RECEIVE,
    ORDERS_CHANGE_DELIVERY_TIME,
    ORDERS_ASSIGN_DELIVERY,
    SHIPPING_PREPARE,
    DELIVERIES_PERFORM,
    KITTING_CONFIGURE,
    POS_VIEW,
    POS_VIEW_ALL,
    POS_CREATE,
    POS_QUOTE,
    POS_SHARE,
    POS_CLOSE_SALE,
    POS_MANAGE_CUSTOMER,
    CHAT_PUBLIC,
    CHAT_PRIVATE,
    WHATSAPP_CREATE_DRAFT,
    WHATSAPP_POS_INTAKE,
    PRICES_VIEW,
    REPORTS_VIEW,
    REVIEWS_SUBMIT,
    REVIEWS_DISPUTE,
    EASSYMO_SYNONYMS,
    EASSYMO_SENSITIVITIES,
    EASSYMO_UOM,
    EASSYMO_PRICING,
})

EASSYMO_PREFIX = "eassymo."
