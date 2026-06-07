from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request, status

from app.repositories import CensusRepository as censusRepository
from app.repositories import CommissionerInviteRepository as commissionerInviteRepository
from app.repositories import GroupRepository as groupRepository
from app.schemas.CommissionerInvite import (
    CommissionerInviteSchema,
    CommissionerInviteStatus,
    CommissionerInviteStatusHistoryEntry,
)
from app.schemas.Groups import GroupSchema
from app.schemas.Notification import Notification, NotificationType
from app.services import ListsService as listsService
from app.services import CommissionerInviteListsSync as commissionerInviteListsSync
from app.utils.notifications import send_notification


def _token_from_request(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        return authorization.replace("Bearer ", "")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authorization token missing",
    )


def create_invite(request: Request, census_id: str):
    token = _token_from_request(request)
    user = request.state._state.get("user")
    group_selected = request.state._state.get("groupSelected")

    if not user or not user.get("uid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not authenticated")
    if not group_selected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Missing groupSelected header context"
        )

    cg_raw = groupRepository.find_by_id(group_selected)
    if not cg_raw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commissioner group not found")

    commissioner_group = GroupSchema(**cg_raw)

    if not commissioner_group.is_commissioner:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo grupos tipo comisionado pueden enviar esta invitación",
        )

    try:
        census_doc = censusRepository.find_by_id(census_id)
    except Exception:
        census_doc = None

    if not census_doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Census record not found")

    invited_gid = census_doc.get("group_reference_id")
    if not invited_gid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Este registro de censo no está enlazado a un grupo registrado",
        )

    if str(invited_gid) == str(group_selected):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No puedes enviarte una invitación de comisionado a tu propio grupo",
        )

    invited_raw = groupRepository.find_by_id(str(invited_gid))
    invited_name = ""
    if invited_raw:
        ig = GroupSchema(**invited_raw)
        invited_name = ig.name or ""

    recent = commissionerInviteRepository.find_recent_pair_any_status(
        group_selected, str(invited_gid)
    )
    if recent:
        st = str(recent.get("status") or "").strip().upper()
        if st == CommissionerInviteStatus.PENDING.value:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ya existe una solicitud pendiente para este grupo",
            )
        if st == CommissionerInviteStatus.ACCEPTED.value:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Este taller ya está en tus comisionables",
            )

    now_hist = CommissionerInviteStatusHistoryEntry(
        status=CommissionerInviteStatus.PENDING
    )

    invite = CommissionerInviteSchema(
        commissioner_group_id=str(group_selected),
        commissioner_group_name=commissioner_group.name or "",
        initiating_user_uid=str(user["uid"]),
        invited_group_id=str(invited_gid),
        invited_group_name=invited_name,
        census_id=str(census_id),
        status=CommissionerInviteStatus.PENDING,
        status_history=[now_hist],
    )

    inserted = commissionerInviteRepository.insert(invite.to_insert_document())
    invite.id = str(inserted.inserted_id)

    navigate = f"/commissioner-invite/{invite.id}"

    invitation_meta: Dict[str, Any] = {
        "inviteId": invite.id,
        "commissionerGroupId": invite.commissioner_group_id,
        "commissionerGroupName": invite.commissioner_group_name,
        "invitedGroupId": invite.invited_group_id,
        "invitedGroupName": invite.invited_group_name,
    }

    recipients = groupRepository.find_users_by_group_id(str(invited_gid))
    if not recipients or not recipients.get("users"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "El grupo destino no tiene usuarios para notificar",
        )

    for uid in recipients.get("users", []):
        owner_id = uid
        if isinstance(uid, dict):
            owner_id = uid.get("_id") or uid.get("uid")

        notification = Notification(
            type=NotificationType.COMMISSIONER_INVITE,
            message=f'{invite.commissioner_group_name or "Un comisionado"} quiere agregarte como comisionado. Revisa los detalles y responde.',
            owner=owner_id,
            ownerGroup=str(invited_gid),
            visibleRoles=None,
            navigateToUrl=navigate,
            read=False,
            metaData={**invitation_meta},
        )

        send_notification(notification, token)

    return invitation_meta


def list_invites(
    commissioner_group_id: Optional[str],
    invited_group_id: Optional[str],
    status_filter: Optional[str],
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {}
    if commissioner_group_id:
        filters["commissioner_group_id"] = commissioner_group_id
    if invited_group_id:
        filters["invited_group_id"] = invited_group_id
    if status_filter:
        filters["status"] = status_filter

    out: List[Dict[str, Any]] = []
    for doc in commissionerInviteRepository.find(filters):
        out.append(CommissionerInviteSchema.from_mongo(doc).toJson())

    return out


def find_by_id_public(invite_id: str, request_group_id: Optional[str]):
    raw = commissionerInviteRepository.find_by_id(invite_id)
    if not raw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitación no encontrada")

    inv = CommissionerInviteSchema.from_mongo(raw)

    if not request_group_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Se requiere grupo seleccionado para ver esta invitación",
        )

    if request_group_id not in (
        inv.commissioner_group_id,
        inv.invited_group_id,
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No tienes permiso para ver esta invitación",
        )

    return inv.toJson()


def respond_invite(
    request: Request,
    invite_id: str,
    new_status_raw: str,
):
    token = _token_from_request(request)
    user = request.state._state.get("user")
    group_selected = request.state._state.get("groupSelected")

    if not group_selected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Missing groupSelected header context"
        )

    upper = str(new_status_raw).upper()
    try:
        new_status = CommissionerInviteStatus[upper]
    except KeyError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            'status debe ser "ACCEPTED" o "REJECTED"',
        )

    if new_status not in (
        CommissionerInviteStatus.ACCEPTED,
        CommissionerInviteStatus.REJECTED,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Estado de respuesta no válido",
        )

    raw = commissionerInviteRepository.find_by_id(invite_id)
    if not raw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitación no encontrada")

    inv = CommissionerInviteSchema.from_mongo(raw)

    if str(group_selected) != str(inv.invited_group_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo el grupo invitado puede responder",
        )

    if inv.status != CommissionerInviteStatus.PENDING:
        return inv.toJson()

    inv.append_status(new_status)

    commissionerInviteRepository.update_by_id(invite_id, inv.to_update_document())

    if new_status == CommissionerInviteStatus.ACCEPTED:
        listsService.add_comisionado_group_to_commissionables_list(
            inviting_user_uid=inv.initiating_user_uid,
            commissioner_group_id=inv.commissioner_group_id,
            invited_group_id=inv.invited_group_id,
        )
        responder_uid = (user or {}).get("uid")
        listsService.add_commissioner_group_to_comisionistas_lists_for_invited_group(
            invited_group_id=inv.invited_group_id,
            commissioner_group_id=inv.commissioner_group_id,
            responding_user_uid=responder_uid,
        )

        comm_users = groupRepository.find_users_by_group_id(inv.commissioner_group_id)
        for uid in (comm_users or {}).get("users", []):
            owner_id = uid
            if isinstance(uid, dict):
                owner_id = uid.get("_id") or uid.get("uid")
            notification = Notification(
                type=NotificationType.COMMISSIONER_INVITE_ACCEPTED,
                message=f'{inv.invited_group_name or "El taller"} ha aceptado trabajar como comisionado.',
                owner=owner_id,
                ownerGroup=inv.commissioner_group_id,
                visibleRoles=None,
                navigateToUrl="/commissioner/comisionados",
                read=False,
                metaData={
                    "inviteId": invite_id,
                    "invitedGroupId": inv.invited_group_id,
                    "commissionerGroupId": inv.commissioner_group_id,
                },
            )
            send_notification(notification, token)

    else:
        comm_users = groupRepository.find_users_by_group_id(inv.commissioner_group_id)
        for uid in (comm_users or {}).get("users", []):
            owner_id = uid
            if isinstance(uid, dict):
                owner_id = uid.get("_id") or uid.get("uid")
            notification = Notification(
                type=NotificationType.COMMISSIONER_INVITE_REJECTED,
                message=f'{inv.invited_group_name or "El grupo"} rechazó la invitación de comisionado.',
                owner=owner_id,
                ownerGroup=inv.commissioner_group_id,
                visibleRoles=None,
                navigateToUrl="/commissioner/comisionados",
                read=False,
                metaData={
                    "inviteId": invite_id,
                    "invitedGroupId": inv.invited_group_id,
                    "commissionerGroupId": inv.commissioner_group_id,
                },
            )
            send_notification(notification, token)

    return inv.toJson()


def revoke_accepted_relationship(request: Request, commissioner_group_id: str):
    """
    Invited group ends an active ACCEPTED commissioner relationship:
    revoke invite, strip lists on both sides (Comisionables + Comisionistas).
    """
    token = _token_from_request(request)
    group_selected = request.state._state.get("groupSelected")
    if not group_selected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Missing groupSelected header context",
        )

    cg = commissioner_group_id.strip()
    if not cg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "commissioner_group_id requerido")

    raw = commissionerInviteRepository.find_latest_accepted_invite(cg, str(group_selected))
    if not raw:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No hay relación activa con ese comisionado",
        )

    inv = CommissionerInviteSchema.from_mongo(raw)
    if str(inv.invited_group_id) != str(group_selected):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo el grupo invitado puede finalizar esta relación",
        )
    invite_id_done = raw.get("_id")
    invite_id_str = str(invite_id_done) if invite_id_done is not None else ""

    inv.append_status(CommissionerInviteStatus.REVOKED)
    commissionerInviteRepository.update_by_id(invite_id_str, inv.to_update_document())

    commissionerInviteListsSync.strip_invited_from_commissionables_list(
        inv.initiating_user_uid,
        inv.commissioner_group_id,
        inv.invited_group_id,
    )
    commissionerInviteListsSync.strip_commissioner_from_all_comisionistas_lists(
        inv.invited_group_id,
        inv.commissioner_group_id,
    )

    comm_users = groupRepository.find_users_by_group_id(inv.commissioner_group_id)
    shop_label = inv.invited_group_name or "El taller"
    for uid in (comm_users or {}).get("users", []):
        owner_id = uid
        if isinstance(uid, dict):
            owner_id = uid.get("_id") or uid.get("uid")
        notification = Notification(
            type=NotificationType.COMMISSIONER_INVITE_REJECTED,
            message=f"{shop_label} dejó de trabajar como comisionado para tu grupo.",
            owner=owner_id,
            ownerGroup=inv.commissioner_group_id,
            visibleRoles=None,
            navigateToUrl="/commissioner/comisionados",
            read=False,
            metaData={
                "inviteId": invite_id_str,
                "invitedGroupId": inv.invited_group_id,
                "commissionerGroupId": inv.commissioner_group_id,
            },
        )
        send_notification(notification, token)

    return inv.toJson()
