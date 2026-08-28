from fastapi import APIRouter, Body, Depends, status, Request, Header, UploadFile, Form
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from app.config.database import get_mysql_db
from app.schemas.VehiculoPartesSearch import HistoricoBusquedaInput, SearchPartesPaginatorRequest
from app.services import BrandService as brandService
from app.services import GuaranteeService as guaranteeService
from app.services import MostradorFolioService as folioService
from app.services import UploadPictureService as uploadPictureService
from app.services.VehiculoPartesService import search_partes_paginator
from app.utils.ResponseUtils import get_successful_response, get_unsuccessful_response
from app.dependencies.group_auth import assert_group_membership, require_authenticated_uid
from app.utils.firebase_admin import verify_firebase_token
from typing import Annotated, List, Optional

mostradorRouter = APIRouter(prefix="/mostrador", tags=["Mostrador"])


def _err_status(e: Exception) -> int:
    return e.status_code if hasattr(e, "status_code") else status.HTTP_500_INTERNAL_SERVER_ERROR


@mostradorRouter.post("", description="Create a Mostrador folio (Solicitud + -> Nueva)")
def create(request: Request, data: dict = Body(...), groupselected: str = Header(None)):
    try:
        uid = (request.state.user or {}).get("uid") if hasattr(request.state, "user") else None
        response = folioService.create(data, uid, groupselected)
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("", description="List folios for the selected group")
def list_folios(request: Request, groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, str(groupselected))
        response = folioService.list_for_group(groupselected)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/orphans", description="List POS folios without a linked Eassymo customer")
def list_orphan_folios(request: Request, groupselected: str = Header(None)):
    try:
        caller_uid = require_authenticated_uid(request)
        assert_group_membership(caller_uid, str(groupselected))
        response = folioService.list_orphans(groupselected)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/by-folio/{folio_code}", description="Import resolver: load a folio/cart/request by code")
def get_by_folio(folio_code: str):
    try:
        response = folioService.resolve_import(folio_code)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/public/my-folios", description="Guest: list folios tied to Firebase-verified phone")
def list_my_folios(request: Request):
    try:
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=get_unsuccessful_response(Exception("Authorization header missing or invalid")),
            )
        token = authorization.replace("Bearer ", "", 1)
        decoded = verify_firebase_token(token)
        phone = decoded.get("phone_number")
        if not phone:
            return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response([]))
        response = folioService.list_by_verified_phone(phone)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=get_unsuccessful_response(Exception("Invalid Firebase token")),
        )
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get(
    "/public/redirect-info/{folio_id}",
    description="Public: minimal routing fields for a folio (share link resolution)",
)
def redirect_info(folio_id: str):
    try:
        response = folioService.get_redirect_info(folio_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/public/{share_token}", description="Public/customer folio view by share token")
def get_public(share_token: str):
    try:
        response = folioService.get_by_share_token(share_token)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/tube/{tube_token}", description="Temp-shop restricted tube view by tube token")
def get_tube(tube_token: str):
    try:
        response = folioService.get_tube(tube_token)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


# ---- Public (share_token) scoped mutations: usable by a guest customer (no account) ----

@mostradorRouter.post("/public/{share_token}/order", description="Guest: order a piece via share token")
def public_order(share_token: str, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.order_piece(
            folio_id,
            piece_id=data.get("piece_id"),
            option_index=data.get("option_index"),
            delivery_mode=data.get("delivery_mode", "tienda"),
            delivery_address=data.get("delivery_address"),
            delivery_contact=data.get("delivery_contact"),
            allow_when_assigned=True,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.delete("/public/{share_token}/order/{piece_id}", description="Guest: remove a piece order via share token")
def public_unorder(share_token: str, piece_id: str):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.unorder_piece(folio_id, piece_id, allow_when_assigned=True)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post(
    "/public/{share_token}/search-parts",
    description="Guest: catalog part search (same intelligence as POS, gated by valid share token)",
)
def public_search_parts(
    share_token: str,
    data: dict = Body(...),
    mysql_db: Session = Depends(get_mysql_db),
):
    try:
        folioService.folio_id_by_share_token(share_token)
        historico = data.get("historicoBusqueda") or {}
        criterio = (historico.get("criterio") or data.get("criterio") or "").strip()
        if not criterio:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_unsuccessful_response(ValueError("criterio is required")),
            )
        payload = SearchPartesPaginatorRequest(
            historicoBusqueda=HistoricoBusquedaInput(criterio=criterio),
            page=int(data.get("page") or 0),
            itemsPerPage=int(data.get("itemsPerPage") or 20),
        )
        result = search_partes_paginator(mysql_db, payload)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(result))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get(
    "/public/{share_token}/brands",
    description="Guest: brand autocomplete (same catalog as seller offer capture, gated by valid share token)",
)
def public_search_brands(share_token: str, search_param: Optional[str] = None):
    try:
        folioService.folio_id_by_share_token(share_token)
        response = brandService.find_brand_by_label(search_param)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get(
    "/public/{share_token}/guarantees",
    description="Guest: guarantee autocomplete (same catalog as seller offer capture, gated by valid share token)",
)
def public_search_guarantees(share_token: str, search_param: Optional[str] = None):
    try:
        folioService.folio_id_by_share_token(share_token)
        response = guaranteeService.find_guarantee_by_label(search_param)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/public/{share_token}/pieces", description="Guest: add a new piece to the folio")
def public_add_piece(share_token: str, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.add_piece_by_guest(folio_id, data)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.delete("/public/{share_token}/pieces/{piece_id}", description="Guest: remove a piece they added")
def public_remove_piece(share_token: str, piece_id: str):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.remove_guest_piece(folio_id, piece_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post(
    "/public/{share_token}/pieces/{piece_id}/options",
    description="Guest: manually capture options for a piece",
)
def public_submit_piece_options(share_token: str, piece_id: str, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.submit_guest_piece_options(
            folio_id,
            piece_id,
            data.get("options", []),
            shop_id=data.get("shop_id"),
            shop_name=data.get("shop_name"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/public/{share_token}/confirm", description="Guest: confirm ordered pieces via share token")
def public_confirm(share_token: str):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.confirm(folio_id, allow_when_assigned=True)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/public/{share_token}/invite-shop", description="Guest: fan out folio to another shop via share token")
def public_invite_shop(share_token: str, request: Request, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.invite_shop(
            folio_id,
            group_id=data.get("group_id"),
            name=data.get("name"),
            eassymo=bool(data.get("eassymo", True)),
            visible_piece_ids=data.get("visible_piece_ids"),
            client_origin=folioService._client_origin_from_request(request),
            captured_by_buyer=bool(data.get("captured_by_buyer", False)),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post(
    "/public/{share_token}/claim-guest",
    description="Guest: claim an unclaimed folio for this device (no account)",
)
def public_claim_guest(share_token: str, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        response = folioService.claim_guest(
            folio_id,
            guest_device_id=data.get("guest_device_id"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/public/{share_token}/claim-account", description="Guest: provision an Eassymo account via share token")
def public_claim_account(share_token: str, request: Request, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        uid = data.get("uid")
        if not uid and hasattr(request.state, "user"):
            uid = (request.state.user or {}).get("uid")
        response = folioService.claim_account(
            folio_id,
            uid=uid,
            name=data.get("name"),
            phone=data.get("phone"),
            group_name=data.get("group_name"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/public/{share_token}/create-taller-account", description="Guest: create seller shop account without folio reassignment")
def public_create_taller_account(share_token: str, request: Request, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        uid = data.get("uid")
        if not uid and hasattr(request.state, "user"):
            uid = (request.state.user or {}).get("uid")
        response = folioService.create_taller_account(
            folio_id,
            uid=uid,
            name=data.get("name"),
            phone=data.get("phone"),
            group_name=data.get("group_name"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/public/{share_token}/finish-claim", description="Guest: finish folio claim after shop-creator-v3 group creation")
def public_finish_claim(share_token: str, request: Request, data: dict = Body(...)):
    try:
        folio_id = folioService.folio_id_by_share_token(share_token)
        uid = data.get("uid")
        if not uid and hasattr(request.state, "user"):
            uid = (request.state.user or {}).get("uid")
        response = folioService.finish_claim(
            folio_id,
            uid=uid,
            group_id=data.get("group_id"),
            account_kind=data.get("account_kind", "buyer"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


# ---- Tube (tube_token) scoped mutations: temp shop quoting / buyer-proxy capture ----

@mostradorRouter.post("/tube/{tube_token}/options", description="Temp shop: submit options for a piece via tube token")
def tube_options(tube_token: str, data: dict = Body(...)):
    try:
        folio_id, shop, _ = folioService.folio_and_shop_by_tube_token(tube_token)
        response = folioService.submit_shop_options(
            folio_id,
            piece_id=data.get("piece_id"),
            options=data.get("options", []),
            shop_id=(shop or {}).get("tube_token") or tube_token,
            shop_name=(shop or {}).get("name"),
            captured_by_buyer=bool(data.get("captured_by_buyer", False)),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get(
    "/tube/{tube_token}/brands",
    description="Temp shop: brand autocomplete (gated by valid tube token)",
)
def tube_search_brands(tube_token: str, search_param: Optional[str] = None):
    try:
        folioService.require_tube_token(tube_token)
        response = brandService.find_brand_by_label(search_param)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get(
    "/tube/{tube_token}/guarantees",
    description="Temp shop: guarantee autocomplete (gated by valid tube token)",
)
def tube_search_guarantees(tube_token: str, search_param: Optional[str] = None):
    try:
        folioService.require_tube_token(tube_token)
        response = guaranteeService.find_guarantee_by_label(search_param)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=get_successful_response(jsonable_encoder(response)),
        )
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post(
    "/tube/{tube_token}/photos",
    description="Temp shop: upload option photos (gated by valid tube token)",
)
async def tube_upload_photos(
    tube_token: str,
    files: Annotated[List[UploadFile], Form()],
):
    try:
        folioService.require_tube_token(tube_token)
        response = await uploadPictureService.upload_tube_photos(files, tube_token)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/{folio_id}/for-group", description="Invited Eassymo group: visibility-scoped folio view")
def get_for_group(folio_id: str, groupselected: str = Header(None)):
    try:
        response = folioService.get_for_group(folio_id, groupselected)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post(
    "/{folio_id}/claim-owner",
    description="Claim an unclaimed folio for the authenticated user's selected group",
)
def claim_owner(folio_id: str, request: Request, groupselected: str = Header(None)):
    try:
        uid = (request.state.user or {}).get("uid") if hasattr(request.state, "user") else None
        name = (request.state.user or {}).get("name") if hasattr(request.state, "user") else None
        phone = (request.state.user or {}).get("phone_number") if hasattr(request.state, "user") else None
        response = folioService.claim_owner(folio_id, uid, groupselected, name, phone)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.get("/{folio_id}", description="Get a folio by id")
def get_one(folio_id: str):
    try:
        response = folioService.get(folio_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.put("/{folio_id}", description="Patch a folio (pieces and/or top-level fields)")
def patch(folio_id: str, data: dict = Body(...)):
    try:
        if "pieces" in data and len(data.keys()) == 1:
            response = folioService.update_pieces(folio_id, data["pieces"])
        else:
            response = folioService.update(folio_id, data)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/shop-pieces", description="Origin or invited shop: add a piece while bidding")
def add_shop_piece(folio_id: str, data: dict = Body(...), groupselected: str = Header(None)):
    try:
        response = folioService.add_piece_by_shop(folio_id, groupselected, data)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/group-options", description="Invited Eassymo group: submit options for a piece")
def submit_group_options(folio_id: str, data: dict = Body(...), groupselected: str = Header(None)):
    try:
        response = folioService.submit_group_options(
            folio_id,
            piece_id=data.get("piece_id"),
            options=data.get("options", []),
            group_id=groupselected,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post(
    "/{folio_id}/pieces/{piece_id}/options/{option_index}/confirm",
    description="Participant shop confirms a guest-captured option",
)
def confirm_guest_option(
    folio_id: str,
    piece_id: str,
    option_index: int,
    groupselected: str = Header(None),
):
    try:
        response = folioService.confirm_guest_option(
            folio_id,
            piece_id,
            option_index,
            groupselected,
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/options", description="A shop submits/updates its options on a piece (Offer Creator)")
def submit_options(folio_id: str, data: dict = Body(...), groupselected: str = Header(None)):
    try:
        response = folioService.submit_shop_options(
            folio_id,
            piece_id=data.get("piece_id"),
            options=data.get("options", []),
            shop_id=data.get("shop_id") or groupselected,
            shop_name=data.get("shop_name"),
            captured_by_buyer=bool(data.get("captured_by_buyer", False)),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/invite-shop", description="Invite another shop (or temp shop) to quote a folio")
def invite_shop(folio_id: str, request: Request, data: dict = Body(...)):
    try:
        response = folioService.invite_shop(
            folio_id,
            group_id=data.get("group_id"),
            name=data.get("name"),
            eassymo=bool(data.get("eassymo", True)),
            visible_piece_ids=data.get("visible_piece_ids"),
            client_origin=folioService._client_origin_from_request(request),
            captured_by_buyer=bool(data.get("captured_by_buyer", False)),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/share", description="Share a folio with the customer (returns share links + notification)")
def share(folio_id: str, request: Request, data: dict = Body(default={})):
    try:
        response = folioService.share(
            folio_id,
            customer=data.get("customer"),
            channel=data.get("channel", "whatsapp"),
            whatsapp_phone=data.get("whatsapp_phone"),
            client_origin=folioService._client_origin_from_request(request),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/order", description="Order a piece by choosing one of its options")
def order_piece(folio_id: str, data: dict = Body(...)):
    try:
        response = folioService.order_piece(
            folio_id,
            piece_id=data.get("piece_id"),
            option_index=data.get("option_index"),
            delivery_mode=data.get("delivery_mode", "tienda"),
            delivery_address=data.get("delivery_address"),
            delivery_contact=data.get("delivery_contact"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.delete("/{folio_id}/order/{piece_id}", description="Remove the order from a piece")
def unorder_piece(folio_id: str, piece_id: str):
    try:
        response = folioService.unorder_piece(folio_id, piece_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/confirm", description="Confirm ordered pieces -> create in-person Orders")
def confirm(folio_id: str):
    try:
        response = folioService.confirm(folio_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/deliver", description="Mark all ordered pieces as delivered (in-person handoff)")
def deliver_ordered_pieces(folio_id: str):
    try:
        response = folioService.complete_in_person_delivery(folio_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/order/{order_id}/pickup", description="Confirm in-person pickup (signature + received-by)")
def confirm_pickup(order_id: str, data: dict = Body(...)):
    try:
        response = folioService.confirm_pickup(
            order_id,
            signature_url=data.get("delivery_customer_signature_url"),
            received_by_name=data.get("delivery_received_by_name"),
            pictures=data.get("delivery_pictures_seller"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/claim-account", description="Provision an Eassymo taller account for the customer")
def claim_account(folio_id: str, request: Request, data: dict = Body(...)):
    try:
        uid = data.get("uid")
        if not uid and hasattr(request.state, "user"):
            uid = (request.state.user or {}).get("uid")
        response = folioService.claim_account(
            folio_id,
            uid=uid,
            name=data.get("name"),
            phone=data.get("phone"),
            group_name=data.get("group_name"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/create-taller-account", description="Create seller shop account without folio reassignment")
def create_taller_account(folio_id: str, request: Request, data: dict = Body(...)):
    try:
        uid = data.get("uid")
        if not uid and hasattr(request.state, "user"):
            uid = (request.state.user or {}).get("uid")
        response = folioService.create_taller_account(
            folio_id,
            uid=uid,
            name=data.get("name"),
            phone=data.get("phone"),
            group_name=data.get("group_name"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/finish-claim", description="Finish folio claim after shop-creator-v3 group creation")
def finish_claim(folio_id: str, request: Request, data: dict = Body(...)):
    try:
        uid = data.get("uid")
        if not uid and hasattr(request.state, "user"):
            uid = (request.state.user or {}).get("uid")
        response = folioService.finish_claim(
            folio_id,
            uid=uid,
            group_id=data.get("group_id"),
            account_kind=data.get("account_kind", "buyer"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/link-customer", description="Link an existing Eassymo customer by phone")
def link_customer(folio_id: str, data: dict = Body(...)):
    try:
        response = folioService.link_existing_customer(folio_id, phone=data.get("phone"))
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))


@mostradorRouter.post("/{folio_id}/assign-group", description="Assign folio to a buyer business group and materialize PartRequests")
def assign_group(folio_id: str, data: dict = Body(...)):
    try:
        response = folioService.assign_to_group(
            folio_id,
            group_id=data.get("group_id"),
            with_options=bool(data.get("with_options", True)),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=get_successful_response(response))
    except Exception as e:
        return JSONResponse(status_code=_err_status(e), content=get_unsuccessful_response(e))
