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
from app.routers import PendingCartRouter as pendingCartRouter
from app.routers import DeliveryRouter as deliveryRouter


import app.utils.firebase_admin

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
from app.middleware.auth_middleware import verify_token
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

app = FastAPI()


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
    public_paths = [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/users/create",
        "/delivery/guest-orders",
    ]

    # Prefix-based public paths (delivery invite pages)
    public_prefixes = [
        "/delivery-invite/",
    ]

    path = request.url.path

    if path in public_paths:
        return await call_next(request)

    if any(path.startswith(prefix) for prefix in public_prefixes):
        return await call_next(request)

    # Allow guest token auth to pass through for change-status
    if path == "/order/change-status" and request.headers.get("X-Guest-Token"):
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

origins = [
    "https://www.eassymo.mx",
    "https://eassymo-2-0-client.vercel.app",
    "https://eassymo-2-0-client-nw5q0qylv-fernando-francos-projects-1618c379.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(pendingCartRouter.pendingCartRouter)
app.include_router(deliveryRouter.deliveryRouter)