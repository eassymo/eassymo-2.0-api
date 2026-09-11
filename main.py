import os

from fastapi import HTTPException
from app.routers import UserRouter as userRouter
from app.routers import RolesRouter as rolesRouter
from app.routers import CensusRouter as censusRouter
from app.routers import NetworkRouter as networkRouter
from app.routers import GroupRouter as groupRouter
from app.routers import ListsRouter as listRouter
from app.routers import GroupCarRouter as groupCarRouter
from app.routers import PartRequestRouter as partRequestRouter
from app.routers import OfferRouter as offerRouter
from app.routers import BrandRouter as brandRouter
from app.routers import GuaranteeRouter as guaranteeRouter
from app.routers import PhotoRouter as photoRouter
from app.routers import OrderRouter as orderRouter
from app.routers import ChatRouter as chatRouter
from app.routers import WhatsappRouter as whatsAppRouter
from app.routers import InviteRouter as inviteRouter
from app.routers import PartRequestInviteRouter as partRequestInviteRouter
from app.routers import TeamMemberInviteRouter as teamMemberInviteRouter
from app.routers import UserRolesRouter as userRolesRouter
from app.routers import CallCenterConnectionRouter as callCenterConnectionRouter
from app.routers import CallCenterRouter as callCenterRouter
from app.routers import CallCenterManagementListRouter as callCenterManagementListRouter
from app.routers import CommissionerRoutes as commissionerRoutes
from app.routers import CommissionerInviteRoutes as commissionerInviteRoutes
from app.routers import CommissionerFilterRoutes as commissionerFilterRoutes
from app.routers import AcesVehiclesRoutes as acesVehiclesRoutes
from app.routers import PreloadedFiltersRoutes as preloadedFiltersRoutes
from app.routers import RequestStatusByGroupRoutes as RequestStatusByGroupRoutes
from app.routers import VehiculoRouter as vehiculoRouter
from app.routers import EstandarizadorRouter as estandarizadorRouter
from app.routers import GroupConfigRouter as groupConfigRouter
from app.routers import CategoriasRouter as categoriasRouter
from app.routers import PendingCartRouter as pendingCartRouter
from app.routers import DeliveryRouter as deliveryRouter
from app.routers import AdminRouter as adminRouter
from app.routers import MostradorFolioRouter as mostradorFolioRouter
from app.routers import ReviewRouter as reviewRouter
from app.routers import PushRouter as pushRouter
from app.routers import NotificationRouter as notificationRouter


import app.utils.firebase_admin

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
from app.middleware.auth_middleware import verify_token
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

_IS_PROD = os.getenv("ENVIRONMENT", "").lower() in ("production", "prod") or os.getenv(
    "RAILWAY_ENVIRONMENT", ""
).lower() == "production"

app = FastAPI(
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)


@app.get("/health", tags=["Health"])
async def healthcheck():
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.exception_handler(RequestValidationError)
async def part_request_body_validation_handler(
    request: Request, exc: RequestValidationError
):
    path = request.url.path.rstrip("/")
    if path == "/partRequest" and request.method in ("POST", "PUT"):
        return JSONResponse(
            status_code=400,
            content={"detail": jsonable_encoder(exc.errors())},
        )
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )

# Add a middleware to verify all protected routes


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_paths = ["/health"]
    if not _IS_PROD:
        public_paths.extend(["/docs", "/redoc", "/openapi.json"])

    # Prefix-based public paths (delivery invite pages + public/guest mostrador views)
    public_prefixes = [
        "/delivery-invite/",
        "/mostrador/public/",
        "/mostrador/tube/",
        "/delivery/guest-orders",
        "/whatsAppMessage/inbound",
    ]

    # Guest delivery flow — X-Guest-Token replaces Firebase auth on these paths
    guest_token_paths = frozenset({
        "/order/change-status",
        "/delivery/confirm-pickup",
        "/photo/guest",
    })

    path = request.url.path

    if path in public_paths:
        return await call_next(request)

    if any(path.startswith(prefix) for prefix in public_prefixes):
        return await call_next(request)

    if path in guest_token_paths and request.headers.get("X-Guest-Token"):
        return await call_next(request)

    try:
        await verify_token(request)
        response = await call_next(request)
        return response
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"detail": str(e.detail)}
        )

CORS_ALLOW_ORIGINS = [
    "https://www.eassymo.mx",
    "https://eassymo.mx",
    "https://www.eassymo.com",
    "https://eassymo.com",
    "https://eassymo-2-0-client.vercel.app",
    "https://eassymo-2-0-client-nw5q0qylv-fernando-francos-projects-1618c379.vercel.app",
]

CORS_LOCALHOST_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
CORS_EASSYMO_REGEX = r"https://(www\.)?eassymo\.(mx|com)$"
CORS_ORIGIN_REGEX = rf"({CORS_LOCALHOST_REGEX})|({CORS_EASSYMO_REGEX})"

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(userRouter.userRouter)
app.include_router(rolesRouter.rolesRouter)
app.include_router(censusRouter.censusRouter)
app.include_router(networkRouter.networkRouter)
app.include_router(groupRouter.groupRouter)
app.include_router(listRouter.listRouter)
app.include_router(groupCarRouter.groupCarRouter)
app.include_router(partRequestRouter.partRequestRouter)
app.include_router(offerRouter.offerRouter)
app.include_router(brandRouter.brandRouter)
app.include_router(guaranteeRouter.guaranteeRouter)
app.include_router(photoRouter.photoRouter)
app.include_router(orderRouter.orderRouter)
app.include_router(chatRouter.chatRouter)
app.include_router(whatsAppRouter.whatsAppRouter)
app.include_router(inviteRouter.inviteRouter)
app.include_router(partRequestInviteRouter.partRequestInviteRouter)
app.include_router(teamMemberInviteRouter.teamMemberInviteRouter)
app.include_router(userRolesRouter.userRolesRouter)
app.include_router(callCenterConnectionRouter.callCenterConnectionRouter)
app.include_router(callCenterRouter.callCenterRouter)
app.include_router(callCenterManagementListRouter.callCenterManagementListRouter)
app.include_router(commissionerRoutes.commissionerRouter)
app.include_router(commissionerInviteRoutes.commissionerInviteRouter)
app.include_router(commissionerFilterRoutes.commisionerFilterRouter)
app.include_router(acesVehiclesRoutes.AcesVehiclesRouter)
app.include_router(preloadedFiltersRoutes.preloadedFiltersRouter)
app.include_router(RequestStatusByGroupRoutes.requestStatusByGroupRouter)
app.include_router(vehiculoRouter.vehiculoRouter)
app.include_router(estandarizadorRouter.estandarizadorRouter)
app.include_router(groupConfigRouter.groupConfigRouter)
app.include_router(categoriasRouter.categoriasRouter)
app.include_router(pendingCartRouter.pendingCartRouter)
app.include_router(deliveryRouter.deliveryRouter)
app.include_router(adminRouter.adminRouter)
app.include_router(reviewRouter.reviewRouter)
app.include_router(mostradorFolioRouter.mostradorRouter)
app.include_router(pushRouter.pushRouter)
app.include_router(notificationRouter.notificationRouter)