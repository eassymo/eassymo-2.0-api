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
import app.utils.firebase_admin

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
from app.middleware.auth_middleware import verify_token
from fastapi.responses import JSONResponse

app = FastAPI()

# Add a middleware to verify all protected routes


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # List of paths that don't require authentication
    public_paths = [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/users/create"
    ]

    if request.url.path in public_paths:
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
