import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException

from app.config.database import MySQLSessionLocal
from app.repositories import GroupRepository as groupRepository
from app.repositories import WhatsappInboundRepository as inbound_repo
from app.repositories import WhatsappIntakeSessionRepository as session_repo
from app.repositories import WhatsappPendingAssociationRepository as pending_repo
from app.repositories.WhatsappIntakeSessionRepository import STATUS_COLLECTING
from app.schemas.WhatsappExtraction import WhatsappExtractionProposal
from app.services import MostradorFolioService as folio_service
from app.services.LlmExtractionService import LlmExtractionService, LlmRateLimitError
from app.services.WhatsappCatalogMapper import WhatsappCatalogMapper
from app.services.WhatsappIntakeCommands import (
    CANCEL_COMMANDS,
    FLUSH_COMMANDS,
    START_BURST_COMMANDS,
    classify_body,
    normalize_command,
)
from app.services.WhatsappSellerIdentityService import (
    CHANGE_STORE_COMMANDS,
    WhatsappSellerIdentityService,
)
from app.services.WhatsappService import WhatsappService
from app.services import WhatsappClarificationService as clarify
from app.utils.phone_normalize import normalize_phone_e164

logger = logging.getLogger(__name__)

_ZW_CHARS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00ad"), None)
_DRAFT_TOKEN_RE = re.compile(
    r"whatsapp-draft[\s/]+(?P<token>[a-f0-9]{32})",
    re.IGNORECASE,
)
_BORRADOR_BOILERPLATE_RE = re.compile(
    r"Borrador (?:listo|actualizado|ya existe) en Eassymo POS\.?\s*"
    r"(?:Revisa veh[ií]culo y piezas aqu[ií]:\s*)?",
    re.IGNORECASE,
)


def _normalize_body_for_token(text: str) -> str:
    return (text or "").translate(_ZW_CHARS).replace("\r", " ").replace("\n", " ")


def _extract_draft_token(bodies: List[str]) -> Optional[str]:
    token: Optional[str] = None
    for body in bodies:
        for match in _DRAFT_TOKEN_RE.finditer(_normalize_body_for_token(body)):
            token = match.group("token").lower()
    return token


def _has_draft_pointer(bodies: List[str]) -> bool:
    blob = " ".join(_normalize_body_for_token(body) for body in bodies).lower()
    return "whatsapp-draft" in blob or "borrador listo" in blob or "borrador actualizado" in blob or "borrador ya existe" in blob


def _strip_draft_boilerplate(bodies: List[str]) -> List[str]:
    cleaned: List[str] = []
    for body in bodies:
        text = _normalize_body_for_token(body)
        text = _DRAFT_TOKEN_RE.sub("", text)
        text = _BORRADOR_BOILERPLATE_RE.sub("", text)
        text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _store_confirmation_message(store_name: str) -> str:
    return (
        f"Tienda confirmada: {store_name}.\n"
        "Las siguientes solicitudes van a esta tienda.\n\n"
        "Envía auto y piezas en un solo mensaje,\n"
        "o escribe PEDIDO para reenviar varios mensajes del cliente.\n"
        "Cuando termines escribe LISTO, o espera unos segundos.\n"
        "Si te equivocaste, escribe CAMBIAR, MENU o ATRAS para volver a la lista de tiendas."
    )


def _collect_burst_message() -> str:
    return (
        "Listo. Reenvía los mensajes del cliente (auto y piezas).\n"
        "Escribe LISTO al terminar, o espera unos segundos."
    )


def _processing_ack_message() -> str:
    return "Procesando tu solicitud…"


def _resolve_whatsapp_public_base_url() -> str:
    whatsapp_base = (os.getenv("WHATSAPP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if whatsapp_base:
        return whatsapp_base
    client_base = folio_service._resolve_client_base_url()
    return client_base if isinstance(client_base, str) else ""


def _cache_bust_version(value: Optional[str]) -> Optional[str]:
    """Return a WhatsApp-safe cache-bust token (digits only, no colons)."""
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():
        return text
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return str(int(dt.timestamp()))
    except (ValueError, TypeError, OverflowError):
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits or None


class WhatsappIntakeProcessorService:
    def __init__(self) -> None:
        self.identity_service = WhatsappSellerIdentityService()
        self.llm_service = LlmExtractionService()
        self.catalog_mapper = WhatsappCatalogMapper()
        self.whatsapp_service = WhatsappService()
        self.client_base_url = folio_service._resolve_client_base_url()
        self.whatsapp_public_base_url = _resolve_whatsapp_public_base_url()
        self.extract_enabled = os.getenv(
            "WHATSAPP_INTAKE_EXTRACT", "true"
        ).lower() in ("1", "true", "yes")
        self.quiet_seconds = max(
            1, int(os.getenv("WHATSAPP_INTAKE_QUIET_SECONDS", "8"))
        )
        self.max_collect_seconds = max(
            self.quiet_seconds,
            int(os.getenv("WHATSAPP_INTAKE_MAX_COLLECT_SECONDS", "45")),
        )

    def _group_name(self, group_id: str) -> str:
        group = groupRepository.find_by_id(group_id, {"name": 1})
        return (group or {}).get("name") or "Tienda"

    def _proposal_has_content(self, proposal: WhatsappExtractionProposal) -> bool:
        vehicle = proposal.vehicle
        has_vehicle = bool(
            vehicle
            and any(
                getattr(vehicle, field, None)
                for field in ("make", "model", "year", "engine", "vin")
            )
        )
        return has_vehicle or len(proposal.lines) > 0

    def _folio_vehicle_label(self, folio: Optional[dict]) -> Optional[str]:
        vehicle = (folio or {}).get("vehicle") or {}
        parts = [
            str(vehicle.get(key)).strip()
            for key in ("year", "maker", "model")
            if vehicle.get(key)
        ]
        return " ".join(parts) if parts else None

    def _drop_known_vehicle_uncertainties(
        self, proposal: WhatsappExtractionProposal, folio: Optional[dict]
    ) -> WhatsappExtractionProposal:
        if not self._folio_vehicle_label(folio):
            return proposal
        proposal.uncertainties = [
            item
            for item in (proposal.uncertainties or [])
            if not (item.path or "").startswith("vehicle")
        ]
        return proposal

    def _lines_to_pieces(
        self,
        mysql_db,
        proposal: WhatsappExtractionProposal,
        *,
        known_vehicle: Optional[dict] = None,
    ) -> List[dict]:
        pieces: List[dict] = []
        has_known_vehicle = bool(self._folio_vehicle_label({"vehicle": known_vehicle} if known_vehicle else None))
        uncertainty_notes = [
            f"{u.path}: {u.reason}"
            for u in (proposal.uncertainties or [])
            if not (has_known_vehicle and (u.path or "").startswith("vehicle"))
        ]
        mapped_lines = self.catalog_mapper.map_lines(mysql_db, proposal.lines)
        for line, mapped in zip(proposal.lines, mapped_lines):
            comments_parts: List[str] = []
            if line.raw:
                comments_parts.append(line.raw)
            if not mapped.catalog_matched:
                comments_parts.append("Sin match de catálogo automático")
            if uncertainty_notes:
                comments_parts.extend(uncertainty_notes[:2])

            piece = {
                "piece_id": uuid4().hex,
                "tipoParteId": mapped.tipo_parte_id,
                "tipoParteDescripcion": mapped.tipo_parte_descripcion or mapped.name,
                "categoriaId": mapped.categoria_id,
                "subCategoriaId": mapped.sub_categoria_id,
                "name": mapped.name,
                "qty": mapped.qty,
                "unitOfMeasure": mapped.unit_of_measure,
                "position": mapped.position,
                "position_suggested": mapped.position_suggested,
                "comments": " · ".join(comments_parts) if comments_parts else None,
                "status": "pendiente",
                "options": [],
            }
            pieces.append(piece)
        return pieces

    def _vehicle_from_proposal(
        self, proposal: WhatsappExtractionProposal
    ) -> Optional[dict]:
        if not proposal.vehicle:
            return None
        v = proposal.vehicle
        vehicle_info = {
            "year": v.year,
            "maker": v.make,
            "model": v.model,
            "engine": v.engine,
            "vin": v.vin,
        }
        return folio_service._normalize_vehicle(vehicle_info)

    def _warn_if_preview_unreachable(self, base_url: str) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            return
        parsed = urlparse(base_url.strip())
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1") or parsed.scheme != "https":
            logger.warning(
                "WhatsApp draft preview base %s is not publicly reachable over HTTPS; "
                "Meta link previews will not load. Set WHATSAPP_PUBLIC_BASE_URL to a "
                "tunnel or production host that shares the same API/DB as this intake.",
                base_url,
            )

    def _draft_preview_link(
        self, share_token: str, folio_id: str, *, version: Optional[str] = None
    ) -> str:
        path = f"/whatsapp-draft/{share_token}" if share_token else f"/pos?folioId={folio_id}"
        version_token = _cache_bust_version(version)
        if version_token:
            path = f"{path}?v={version_token}"
        base = self.whatsapp_public_base_url or self.client_base_url or ""
        if isinstance(base, str):
            base = base.rstrip("/")
        else:
            base = ""
        if base:
            self._warn_if_preview_unreachable(base)
            return f"{base}{path}"
        return path

    def _draft_card_image_url(
        self, share_token: str, *, version: Optional[str] = None
    ) -> Optional[str]:
        """Public PNG Twilio can attach. Empty when the host is not public HTTPS."""
        if not share_token:
            return None
        base = self.whatsapp_public_base_url or ""
        if not isinstance(base, str):
            return None
        base = base.rstrip("/")
        parsed = urlparse(base)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host in ("localhost", "127.0.0.1"):
            return None
        path = f"/api/og/whatsapp-draft?token={share_token}"
        version_token = _cache_bust_version(version)
        if version_token:
            path = f"{path}&v={version_token}"
        return f"{base}{path}"

    def _inbound_doc(self, message_sid: str) -> dict:
        return inbound_repo.find_by_message_sid(message_sid) or {}

    def _is_inbound_reaction_target(self, doc: dict) -> bool:
        if not doc:
            return False
        if doc.get("direction") == "outbound":
            return False
        kind = str(doc.get("kind") or "")
        if kind == "command":
            return False
        if kind.startswith("bot_"):
            return False
        return True

    def _filter_inbound_reaction_sids(self, message_sids: List[str]) -> List[str]:
        filtered: List[str] = []
        for sid in message_sids:
            if not sid:
                continue
            doc = self._inbound_doc(sid)
            if self._is_inbound_reaction_target(doc):
                filtered.append(sid)
        return filtered

    def _enum_value(self, value: Any) -> Any:
        if value is None:
            return None
        return value.value if hasattr(value, "value") and not isinstance(value, str) else value

    def _can_resume_folio(
        self,
        folio: dict,
        *,
        group_id: str,
        creator_uid: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        if self._enum_value(folio.get("source")) != "whatsapp":
            return False, (
                "Este folio no se creó por WhatsApp y no se puede editar aquí. "
                "Ábrelo en Eassymo POS."
            )

        if str(folio.get("origin_group_id") or "") != str(group_id or ""):
            return False, (
                "Este borrador pertenece a otra tienda. "
                "Ábrelo en POS o escribe CAMBIAR para cambiar de tienda."
            )

        creator = folio.get("creator_user")
        if creator and creator_uid and str(creator) != str(creator_uid):
            return False, (
                "Este borrador pertenece a otro vendedor. Ábrelo en Eassymo POS."
            )

        if self._enum_value(folio.get("status")) != "draft":
            return False, (
                "Este borrador ya fue compartido o confirmado y ya no se puede editar "
                "por WhatsApp. Ábrelo en Eassymo POS."
            )

        if folio_service._is_assigned_to_buyer(folio):
            return False, (
                "Este borrador ya fue asignado a un comprador y ya no se puede editar "
                "por WhatsApp. Ábrelo en Eassymo POS."
            )

        if folio_service._has_ordered_pieces(folio):
            return False, (
                "Este borrador ya tiene piezas ordenadas y ya no se puede editar "
                "por WhatsApp. Ábrelo en Eassymo POS."
            )

        return True, None

    def _normalize_piece_key(self, piece: dict) -> Optional[str]:
        name = piece.get("name") or piece.get("tipoParteDescripcion") or ""
        normalized = name.strip().lower()
        return normalized or None

    def _merge_vehicle(
        self,
        existing: Optional[dict],
        new: Optional[dict],
    ) -> Optional[dict]:
        if not new:
            return existing
        if not existing:
            return new

        merged = dict(existing)
        new_has_model = bool(new.get("model"))
        new_has_maker = bool(new.get("maker"))
        new_has_year = bool(new.get("year"))

        for field in (
            "maker",
            "model",
            "year",
            "engine",
            "vin",
            "version",
            "licensePlate",
            "serviceOrder",
        ):
            if not merged.get(field) and new.get(field):
                merged[field] = new[field]

        if new_has_year and new_has_model:
            merged["year"] = new["year"]
            merged["model"] = new["model"]
            if new_has_maker:
                merged["maker"] = new["maker"]

        return merged

    def _merge_pieces(
        self,
        existing_pieces: List[dict],
        new_pieces: List[dict],
    ) -> List[dict]:
        merged_list = [dict(piece) for piece in existing_pieces]
        by_tipo: Dict[str, dict] = {}
        by_name: Dict[str, dict] = {}
        for piece in merged_list:
            tipo_id = piece.get("tipoParteId")
            if tipo_id:
                by_tipo[str(tipo_id)] = piece
            name_key = self._normalize_piece_key(piece)
            if name_key:
                by_name[name_key] = piece

        for new_piece in new_pieces:
            matched = None
            tipo_id = new_piece.get("tipoParteId")
            if tipo_id and str(tipo_id) in by_tipo:
                matched = by_tipo[str(tipo_id)]
            else:
                name_key = self._normalize_piece_key(new_piece)
                if name_key and name_key in by_name:
                    matched = by_name[name_key]

            if matched:
                if new_piece.get("qty") is not None:
                    matched["qty"] = new_piece["qty"]
                if new_piece.get("unitOfMeasure"):
                    matched["unitOfMeasure"] = new_piece["unitOfMeasure"]
                if new_piece.get("position"):
                    matched["position"] = new_piece["position"]
                if new_piece.get("position_suggested") is not None:
                    matched["position_suggested"] = new_piece["position_suggested"]
                if new_piece.get("comments"):
                    old_comments = (matched.get("comments") or "").strip()
                    new_comment = new_piece["comments"].strip()
                    if new_comment and new_comment not in old_comments:
                        matched["comments"] = (
                            f"{old_comments} · {new_comment}" if old_comments else new_comment
                        )
                for field in (
                    "tipoParteId",
                    "tipoParteDescripcion",
                    "categoriaId",
                    "subCategoriaId",
                ):
                    if new_piece.get(field) and not matched.get(field):
                        matched[field] = new_piece[field]
            else:
                merged_list.append(new_piece)
                if tipo_id:
                    by_tipo[str(tipo_id)] = new_piece
                name_key = self._normalize_piece_key(new_piece)
                if name_key:
                    by_name[name_key] = new_piece

        return merged_list

    def _proposal_has_vehicle(self, proposal: WhatsappExtractionProposal) -> bool:
        vehicle = proposal.vehicle
        return bool(
            vehicle
            and any(
                getattr(vehicle, field, None)
                for field in ("make", "model", "year")
            )
        )

    def _inbound_kind(self, body: str) -> str:
        cmd = normalize_command(body)
        if cmd in FLUSH_COMMANDS | START_BURST_COMMANDS | CANCEL_COMMANDS:
            return "command"
        return "content"

    def _outbound_kind(self, body: str) -> str:
        lower = (body or "").lower()
        if "borrador" in lower and "eassymo pos" in lower:
            return "bot_draft"
        if (body or "").startswith("Procesando"):
            return "bot_ack"
        if lower.startswith("🔗 - ") and "vinculado" in lower:
            return "bot_link"
        if "?" in (body or ""):
            return "bot_clarify"
        return "bot_error"

    def _stamp_burst_messages(
        self,
        session: dict,
        *,
        burst_id: str,
        from_number: str,
    ) -> None:
        for message in session.get("messages") or []:
            sid = message.get("message_sid")
            if not sid:
                continue
            inbound_repo.update_fields(
                sid,
                {
                    "burst_id": burst_id,
                    "kind": self._inbound_kind(message.get("body") or ""),
                    "from_number": from_number,
                },
            )

    def _send_bot_message(
        self,
        from_number: str,
        body: str,
        *,
        burst_id: Optional[str] = None,
        kind: Optional[str] = None,
        folio_id: Optional[str] = None,
        media_url: Optional[str] = None,
    ) -> str:
        resolved_kind = kind or self._outbound_kind(body)
        result = self.whatsapp_service.send_text_message(
            from_number,
            body,
            media_url=media_url,
        )
        message_sid = result.get("message_sid") or f"out-{uuid4().hex}"
        outbound: Dict[str, Any] = {
            "message_sid": message_sid,
            "from_number": from_number,
            "body": body,
            "direction": "outbound",
            "kind": resolved_kind,
            "burst_id": burst_id,
            "status": "sent",
        }
        if folio_id:
            outbound["folio_id"] = folio_id
        inbound_repo.insert_outbound(outbound)
        return message_sid

    def _remember_share_token(
        self,
        from_number: str,
        share_token: str,
        message_sids: List[str],
        folio_id: str,
        *,
        processing_status: str,
        proposal: Optional[WhatsappExtractionProposal] = None,
        burst_id: Optional[str] = None,
    ) -> None:
        proposal_payload = (
            proposal.model_dump(mode="json") if proposal is not None else None
        )
        if burst_id:
            inbound_repo.link_burst_to_folio(
                burst_id,
                folio_id,
                share_token,
                processing_status=processing_status,
                extraction_proposal=proposal_payload,
            )
        update_fields: Dict[str, Any] = {
            "folio_id": folio_id,
            "share_token": share_token,
            "processing_status": processing_status,
            "extraction_status": "ready",
        }
        if proposal_payload is not None:
            update_fields["extraction_proposal"] = proposal_payload
        if burst_id:
            update_fields["burst_id"] = burst_id
        for sid in message_sids:
            if sid:
                inbound_repo.update_fields(sid, update_fields)
        try:
            pending_repo.set_last_share_token(
                normalize_phone_e164(from_number), share_token
            )
        except Exception:
            logger.exception("Failed to persist last WhatsApp share token")

    def _latest_share_token(self, from_number: str) -> Optional[str]:
        normalized = normalize_phone_e164(from_number)
        try:
            pending_token = pending_repo.get_last_share_token(normalized)
        except Exception:
            pending_token = None
        return (
            pending_token
            or inbound_repo.find_latest_share_token(from_number)
            or inbound_repo.find_latest_share_token(normalized)
        )

    def _load_folio_by_share_token(self, share_token: str) -> Optional[dict]:
        try:
            return folio_service.get_by_share_token(share_token)
        except HTTPException:
            return None
        except Exception:
            logger.exception("Failed to load folio for share token")
            return None

    def _resolve_resume_token(
        self,
        bodies: List[str],
        from_number: str,
        *,
        allow_last_draft: bool,
    ) -> Optional[str]:
        token = _extract_draft_token(bodies)
        if token:
            return token
        if _has_draft_pointer(bodies) or allow_last_draft:
            return self._latest_share_token(from_number)
        return None

    def _refuse_resume(
        self,
        from_number: str,
        message_sids: List[str],
        message: str,
        *,
        burst_id: Optional[str] = None,
    ) -> None:
        for sid in message_sids:
            if sid:
                inbound_repo.update_fields(
                    sid,
                    {
                        "processing_status": "draft_resume_refused",
                        "extraction_status": "ready",
                        **({"burst_id": burst_id} if burst_id else {}),
                    },
                )
        self._send_bot_message(from_number, message, burst_id=burst_id, kind="bot_error")

    def _extract_proposal_or_fail(
        self,
        *,
        from_number: str,
        store_name: str,
        bodies: List[str],
        message_sids: List[str],
        known_vehicle: str = "",
        burst_id: Optional[str] = None,
    ) -> Optional[WhatsappExtractionProposal]:
        try:
            return self.llm_service.extract(
                bodies, store_name=store_name, known_vehicle=known_vehicle
            )
        except LlmRateLimitError as exc:
            logger.error("GLM rate limited during flush for %s: %s", from_number, exc)
            self._send_extraction_failure(
                from_number,
                message_sids,
                status="rate_limited",
                error=str(exc),
                user_message=(
                    "El servicio de interpretación está ocupado por el momento. "
                    "Espera unos segundos y reenvía tu mensaje con auto y piezas."
                ),
                burst_id=burst_id,
            )
            return None
        except Exception as exc:
            logger.error("GLM extraction failed during flush for %s: %s", from_number, exc)
            self._send_extraction_failure(
                from_number,
                message_sids,
                status="failed",
                error=str(exc),
                user_message=(
                    "Recibimos tu mensaje pero no pudimos interpretarlo automáticamente. "
                    "Intenta incluir auto (marca, modelo, año) y las refacciones solicitadas."
                ),
                burst_id=burst_id,
            )
            return None

    def _latest_original_reply_sid(self, message_sids: List[str]) -> Optional[str]:
        for sid in reversed(message_sids):
            doc = inbound_repo.find_by_message_sid(sid) or {}
            replied = doc.get("original_replied_message_sid")
            if replied:
                return str(replied)
        return None

    def _try_complement_before_resume(
        self,
        *,
        from_number: str,
        bodies: List[str],
        message_sids: List[str],
        group_id: str,
        creator_uid: Optional[str],
        burst_id: Optional[str],
        original_replied_message_sid: Optional[str] = None,
    ) -> bool:
        folio, question = self._resolve_complement_folio(
            from_number=from_number,
            bodies=bodies,
            group_id=group_id,
            creator_uid=creator_uid,
            original_replied_message_sid=original_replied_message_sid,
        )
        if not folio:
            return False
        answer_text = " ".join(_strip_draft_boilerplate(bodies)).strip() or (
            bodies[0].strip() if bodies else ""
        )
        return self._handle_complement_or_answer(
            from_number=from_number,
            folio=folio,
            question=question,
            answer_text=answer_text,
            message_sids=message_sids,
            burst_id=burst_id,
            group_id=group_id,
            creator_uid=creator_uid,
        )

    def _handle_resume(
        self,
        *,
        from_number: str,
        resume_folio: dict,
        group_id: str,
        creator_uid: Optional[str],
        store_name: str,
        bodies: List[str],
        message_sids: List[str],
        burst_id: Optional[str] = None,
        original_replied_message_sid: Optional[str] = None,
    ) -> None:
        can_resume, refuse_message = self._can_resume_folio(
            resume_folio,
            group_id=group_id or "",
            creator_uid=creator_uid,
        )
        if not can_resume:
            self._refuse_resume(
                from_number, message_sids, refuse_message or "", burst_id=burst_id
            )
            return

        extra_bodies = _strip_draft_boilerplate(bodies)
        if not extra_bodies:
            self._send_existing_draft_link(
                from_number, resume_folio, message_sids, burst_id=burst_id
            )
            return

        proposal = self._extract_proposal_or_fail(
            from_number=from_number,
            store_name=store_name,
            bodies=extra_bodies,
            message_sids=message_sids,
            known_vehicle=self._folio_vehicle_label(resume_folio) or "",
            burst_id=burst_id,
        )
        if proposal is None:
            return

        if not self._proposal_has_content(proposal):
            if self._try_complement_before_resume(
                from_number=from_number,
                bodies=extra_bodies or bodies,
                message_sids=message_sids,
                group_id=group_id,
                creator_uid=creator_uid,
                burst_id=burst_id,
                original_replied_message_sid=original_replied_message_sid,
            ):
                return
            self._send_existing_draft_link(
                from_number, resume_folio, message_sids, burst_id=burst_id
            )
            return

        self._resume_draft_from_proposal(
            from_number=from_number,
            folio=resume_folio,
            proposal=proposal,
            message_sids=message_sids,
            bodies=extra_bodies,
            burst_id=burst_id,
        )

    def _is_full_new_request(
        self, proposal: WhatsappExtractionProposal, bodies: List[str]
    ) -> bool:
        if _has_draft_pointer(bodies) or _extract_draft_token(bodies):
            return False
        vehicle = proposal.vehicle
        has_vehicle = bool(
            vehicle
            and vehicle.make
            and vehicle.model
            and vehicle.year
        )
        return has_vehicle and len(proposal.lines or []) > 0

    def _persist_pending_questions(
        self,
        folio: dict,
        proposal: WhatsappExtractionProposal,
        *,
        mysql_db,
    ) -> dict:
        folio_id = str(folio.get("_id") or folio.get("id") or "")
        new_questions = clarify.derive_pending_questions(
            folio, proposal, mysql_db=mysql_db
        )
        merged = clarify.merge_pending_questions(
            folio.get("whatsapp_pending_questions") or [],
            new_questions,
        )
        if merged == (folio.get("whatsapp_pending_questions") or []):
            return folio
        return folio_service.update(folio_id, {"whatsapp_pending_questions": merged})

    def _send_pending_clarifications(
        self,
        *,
        from_number: str,
        folio: dict,
        burst_id: Optional[str],
        group_id: str,
        creator_uid: Optional[str],
    ) -> dict:
        open_items = [
            item
            for item in clarify.open_questions(folio)
            if not item.get("asked_message_sid")
        ]
        if not open_items:
            return folio

        other_drafts = clarify.find_drafts_with_open_questions(
            origin_group_id=group_id,
            creator_uid=creator_uid,
        )
        multi_hint = len(other_drafts) > 1
        folio_id = str(folio.get("_id") or folio.get("id") or "")
        questions = list(folio.get("whatsapp_pending_questions") or [])

        for question in open_items:
            body = clarify.format_clarify_message(
                folio, question, multi_draft_hint=multi_hint
            )
            sid = self._send_bot_message(
                from_number,
                body,
                burst_id=burst_id,
                kind="bot_clarify",
                folio_id=folio_id,
            )
            questions = clarify.attach_asked_sid(questions, question.get("id"), sid)

        return folio_service.update(
            folio_id, {"whatsapp_pending_questions": questions}
        )

    def _apply_chain_reactions(
        self,
        *,
        from_number: str,
        folio: dict,
        message_sids: List[str],
        burst_id: Optional[str],
        react_all: bool = False,
    ) -> None:
        del burst_id
        folio_code = clarify.folio_code_of(folio) or "—"
        for sid in message_sids:
            if not sid:
                continue
            doc = self._inbound_doc(sid)
            if not self._is_inbound_reaction_target(doc):
                continue
            method = "unavailable"
            wamid = doc.get("whatsapp_message_id")
            if wamid and self.whatsapp_service.native_reactions_enabled:
                try:
                    result = self.whatsapp_service.react_to_message(
                        from_number, wamid, emoji="🔗"
                    )
                except Exception:
                    logger.exception("WhatsApp reaction failed for %s", sid)
                    result = {"success": False}
                if result.get("success"):
                    method = "native"
            inbound_repo.update_fields(
                sid,
                {
                    "linked_reaction": clarify.linked_reaction_stamp(
                        folio_code, method
                    ),
                    "evidence_paths": doc.get("evidence_paths") or [],
                },
            )
            if not react_all:
                break

    def _parts_overlap(self, left: str, right: str) -> bool:
        left_norm = (left or "").strip().lower()
        right_norm = (right or "").strip().lower()
        if not left_norm or not right_norm:
            return False
        if left_norm in right_norm or right_norm in left_norm:
            return True
        left_tokens = set(_normalize_body_for_token(left_norm).split())
        right_tokens = set(_normalize_body_for_token(right_norm).split())
        return bool(left_tokens & right_tokens)

    def _proposal_matches_open_draft(
        self,
        proposal: WhatsappExtractionProposal,
        folio: dict,
    ) -> bool:
        vehicle = folio.get("vehicle") or {}
        extracted = proposal.vehicle
        if not extracted or not extracted.make or not extracted.model or not extracted.year:
            return False
        if str(vehicle.get("maker") or "").strip().lower() != str(extracted.make).strip().lower():
            return False
        if str(vehicle.get("model") or "").strip().lower() != str(extracted.model).strip().lower():
            return False
        if str(vehicle.get("year") or "").strip() != str(extracted.year).strip():
            return False

        folio_parts = [
            clarify.piece_label(piece).lower()
            for piece in (folio.get("pieces") or [])
        ]
        proposal_parts = [
            (line.part_name or "").strip().lower()
            for line in (proposal.lines or [])
            if (line.part_name or "").strip()
        ]
        if not folio_parts or not proposal_parts:
            return False
        return any(
            self._parts_overlap(proposal_part, folio_part)
            for proposal_part in proposal_parts
            for folio_part in folio_parts
        )

    def _find_resend_match_folio(
        self,
        *,
        from_number: str,
        proposal: WhatsappExtractionProposal,
        group_id: str,
        creator_uid: Optional[str],
    ) -> Optional[dict]:
        drafts = clarify.find_drafts_with_open_questions(
            origin_group_id=group_id,
            creator_uid=creator_uid,
        )
        if len(drafts) == 1:
            candidate = drafts[0]
            if self._proposal_matches_open_draft(proposal, candidate):
                return candidate
            return None
        if len(drafts) > 1:
            last_token = self._latest_share_token(from_number)
            if last_token:
                folio = self._load_folio_by_share_token(last_token)
                if folio and clarify.open_questions(folio):
                    if self._proposal_matches_open_draft(proposal, folio):
                        return folio
            return None
        last_token = self._latest_share_token(from_number)
        if not last_token:
            return None
        folio = self._load_folio_by_share_token(last_token)
        if not folio:
            return None
        can_resume, _ = self._can_resume_folio(
            folio,
            group_id=group_id,
            creator_uid=creator_uid,
        )
        if not can_resume:
            return None
        if self._enum_value(folio.get("source")) != "whatsapp":
            return None
        if self._enum_value(folio.get("status")) != "draft":
            return None
        if self._proposal_matches_open_draft(proposal, folio):
            return folio
        return None

    def _resend_open_clarification(
        self,
        *,
        from_number: str,
        folio: dict,
        question: dict,
        burst_id: Optional[str],
        folio_id: str,
    ) -> dict:
        body = clarify.format_clarify_message(folio, question)
        sid = self._send_bot_message(
            from_number,
            body,
            burst_id=burst_id,
            kind="bot_clarify",
            folio_id=folio_id,
        )
        questions = clarify.attach_asked_sid(
            folio.get("whatsapp_pending_questions") or [],
            question.get("id"),
            sid,
        )
        return folio_service.update(
            folio_id, {"whatsapp_pending_questions": questions}
        )

    def _link_resend_to_existing_draft(
        self,
        *,
        from_number: str,
        folio: dict,
        message_sids: List[str],
        burst_id: Optional[str],
        group_id: str,
        creator_uid: Optional[str],
    ) -> None:
        can_resume, refuse_message = self._can_resume_folio(
            folio,
            group_id=group_id or "",
            creator_uid=creator_uid,
        )
        if not can_resume:
            self._refuse_resume(
                from_number, message_sids, refuse_message or "", burst_id=burst_id
            )
            return

        folio_id = str(folio.get("_id") or folio.get("id") or "")
        share_token = str(folio.get("share_token") or "")
        self._remember_share_token(
            from_number,
            share_token,
            message_sids,
            folio_id,
            processing_status="draft_resumed",
            burst_id=burst_id,
        )
        react_sids = self._filter_inbound_reaction_sids(message_sids)
        self._apply_chain_reactions(
            from_number=from_number,
            folio=folio,
            message_sids=react_sids,
            burst_id=burst_id,
            react_all=True,
        )
        for sid in message_sids:
            if not sid:
                continue
            inbound_repo.update_fields(
                sid,
                {
                    "folio_id": folio_id,
                    "processing_status": "draft_resumed",
                    "extraction_status": "ready",
                    "burst_id": burst_id,
                },
            )

    def _stamp_evidence_paths(
        self,
        session: dict,
        proposal: WhatsappExtractionProposal,
        bodies: List[str],
    ) -> List[str]:
        evidence_map = clarify.map_evidence_sids(
            session.get("messages") or [], proposal, bodies
        )
        evidence_sids: List[str] = []
        for sid, paths in evidence_map.items():
            inbound_repo.update_fields(sid, {"evidence_paths": paths})
            evidence_sids.append(sid)
        return evidence_sids

    def _finalize_linked_draft(
        self,
        *,
        from_number: str,
        folio: dict,
        proposal: WhatsappExtractionProposal,
        message_sids: List[str],
        burst_id: Optional[str],
        group_id: str,
        creator_uid: Optional[str],
        mysql_db,
        session: Optional[dict] = None,
        bodies: Optional[List[str]] = None,
        processing_status: str,
        headline: str,
        reaction_sids: Optional[List[str]] = None,
    ) -> None:
        folio = self._persist_pending_questions(folio, proposal, mysql_db=mysql_db)
        folio_id = str(folio.get("_id") or folio.get("id") or "")
        share_token = str(folio.get("share_token") or "")
        self._remember_share_token(
            from_number,
            share_token,
            message_sids,
            folio_id,
            processing_status=processing_status,
            proposal=proposal,
            burst_id=burst_id,
        )
        react_targets = reaction_sids or message_sids
        if session and bodies is not None:
            react_targets = self._stamp_evidence_paths(session, proposal, bodies)
        react_targets = self._filter_inbound_reaction_sids(react_targets)
        self._apply_chain_reactions(
            from_number=from_number,
            folio=folio,
            message_sids=react_targets,
            burst_id=burst_id,
        )
        version = str(folio.get("updated_at") or "")
        link = self._draft_preview_link(share_token, folio_id, version=version or None)
        self._send_bot_message(
            from_number,
            f"{headline}\nRevisa vehículo y piezas aquí:\n{link}",
            burst_id=burst_id,
            kind="bot_draft",
            folio_id=folio_id,
            media_url=self._draft_card_image_url(share_token, version=version or None),
        )
        folio = self._send_pending_clarifications(
            from_number=from_number,
            folio=folio,
            burst_id=burst_id,
            group_id=group_id,
            creator_uid=creator_uid,
        )

    def _resolve_complement_folio(
        self,
        *,
        from_number: str,
        bodies: List[str],
        group_id: str,
        creator_uid: Optional[str],
        original_replied_message_sid: Optional[str] = None,
    ) -> Tuple[Optional[dict], Optional[dict]]:
        if original_replied_message_sid:
            folio = clarify.find_folio_by_clarify_sid(original_replied_message_sid)
            if folio:
                for question in clarify.open_questions(folio):
                    if question.get("asked_message_sid") == original_replied_message_sid:
                        return folio, question
                return folio, None

        token = _extract_draft_token(bodies)
        if token:
            folio = self._load_folio_by_share_token(token)
            if folio:
                open_q = clarify.open_questions(folio)
                return folio, open_q[0] if len(open_q) == 1 else None

        drafts = clarify.find_drafts_with_open_questions(
            origin_group_id=group_id,
            creator_uid=creator_uid,
        )
        if len(drafts) == 1:
            open_q = clarify.open_questions(drafts[0])
            return drafts[0], open_q[0] if len(open_q) == 1 else None
        if len(drafts) > 1:
            last_token = self._latest_share_token(from_number)
            if last_token:
                folio = self._load_folio_by_share_token(last_token)
                if folio and clarify.open_questions(folio):
                    open_q = clarify.open_questions(folio)
                    return folio, open_q[0] if len(open_q) == 1 else None
        return None, None

    def _handle_complement_or_answer(
        self,
        *,
        from_number: str,
        folio: dict,
        question: Optional[dict],
        answer_text: str,
        message_sids: List[str],
        burst_id: Optional[str],
        group_id: str,
        creator_uid: Optional[str],
    ) -> bool:
        can_resume, refuse_message = self._can_resume_folio(
            folio,
            group_id=group_id or "",
            creator_uid=creator_uid,
        )
        if not can_resume:
            self._refuse_resume(
                from_number, message_sids, refuse_message or "", burst_id=burst_id
            )
            return True

        folio_id = str(folio.get("_id") or folio.get("id") or "")
        share_token = str(folio.get("share_token") or "")
        self._remember_share_token(
            from_number,
            share_token,
            message_sids,
            folio_id,
            processing_status="draft_resumed",
            burst_id=burst_id,
        )
        react_sids = self._filter_inbound_reaction_sids(message_sids)
        self._apply_chain_reactions(
            from_number=from_number,
            folio=folio,
            message_sids=react_sids,
            burst_id=burst_id,
        )

        if not question:
            open_items = clarify.open_questions(folio)
            if len(open_items) > 1 and not _extract_draft_token([answer_text]):
                self._send_bot_message(
                    from_number,
                    "Tienes varias aclaraciones abiertas. Responde con el enlace "
                    "del borrador, la pregunta y tu respuesta.",
                    burst_id=burst_id,
                    kind="bot_error",
                    folio_id=folio_id,
                )
                return True
            question = open_items[0] if len(open_items) == 1 else None

        if not question:
            self._send_draft_link_message(
                from_number,
                folio,
                headline="Borrador ya existe en Eassymo POS.",
                burst_id=burst_id,
            )
            return True

        patch, ok, detail = clarify.apply_answer_to_folio(folio, question, answer_text)
        if ok:
            updated = folio_service.update(
                folio_id,
                {
                    **patch,
                    "whatsapp_pending_questions": clarify.mark_question_answered(
                        folio, question.get("id")
                    ),
                },
            )
            code = clarify.folio_code_of(updated)
            version = str(updated.get("updated_at") or "")
            link = self._draft_preview_link(
                share_token, folio_id, version=version or None
            )
            self._send_bot_message(
                from_number,
                f"Listo · {code} · {detail or 'actualizado'}.\n{link}",
                burst_id=burst_id,
                kind="bot_draft",
                folio_id=folio_id,
                media_url=self._draft_card_image_url(
                    share_token, version=version or None
                ),
            )
            return True

        material_patch, stored_material = clarify.apply_material_note_to_folio(
            folio, question, answer_text
        )
        if stored_material:
            folio = folio_service.update(folio_id, material_patch)

        self._send_bot_message(
            from_number,
            f"Vinculado a {clarify.folio_code_of(folio)}. "
            f"No pude aplicar: {question.get('prompt')}.",
            burst_id=burst_id,
            kind="bot_error",
            folio_id=folio_id,
        )
        if stored_material:
            self._resend_open_clarification(
                from_number=from_number,
                folio=folio,
                question=question,
                burst_id=burst_id,
                folio_id=folio_id,
            )
        return True

    def _send_draft_link_message(
        self,
        from_number: str,
        folio: dict,
        *,
        headline: str,
        burst_id: Optional[str] = None,
    ) -> None:
        folio_id = str(folio.get("_id") or folio.get("id") or "")
        share_token = str(folio.get("share_token") or "")
        version = str(folio.get("updated_at") or "")
        link = self._draft_preview_link(share_token, folio_id, version=version or None)
        self._send_bot_message(
            from_number,
            f"{headline}\nRevisa vehículo y piezas aquí:\n{link}",
            burst_id=burst_id,
            kind="bot_draft",
            folio_id=folio_id or None,
            media_url=self._draft_card_image_url(share_token, version=version or None),
        )
        if share_token:
            try:
                pending_repo.set_last_share_token(
                    normalize_phone_e164(from_number), share_token
                )
            except Exception:
                logger.exception("Failed to persist last WhatsApp share token")

    def _resume_draft_from_proposal(
        self,
        *,
        from_number: str,
        folio: dict,
        proposal: WhatsappExtractionProposal,
        message_sids: List[str],
        bodies: List[str],
        burst_id: Optional[str] = None,
    ) -> None:
        mysql_db = None
        if MySQLSessionLocal is not None:
            mysql_db = MySQLSessionLocal()
        try:
            proposal = self._drop_known_vehicle_uncertainties(proposal, folio)
            new_pieces = self._lines_to_pieces(
                mysql_db, proposal, known_vehicle=folio.get("vehicle")
            )
            resolved_vehicle = self.catalog_mapper.map_vehicle(
                mysql_db, proposal, bodies
            )
            if resolved_vehicle:
                proposal.vehicle = resolved_vehicle
                proposal.uncertainties = [
                    item
                    for item in (proposal.uncertainties or [])
                    if item.path not in {"vehicle.make", "vehicle.model"}
                    or not resolved_vehicle.make
                    or not resolved_vehicle.model
                ]
            new_vehicle = self._vehicle_from_proposal(proposal)
            merged_vehicle = self._merge_vehicle(folio.get("vehicle"), new_vehicle)
            merged_pieces = self._merge_pieces(folio.get("pieces") or [], new_pieces)

            folio_id = str(folio.get("_id") or folio.get("id") or "")
            patch: Dict[str, Any] = {"pieces": merged_pieces}
            if merged_vehicle is not None:
                patch["vehicle"] = merged_vehicle
            updated = folio_service.update(folio_id, patch)
            self._finalize_linked_draft(
                from_number=from_number,
                folio=updated,
                proposal=proposal,
                message_sids=message_sids,
                burst_id=burst_id,
                group_id=str(folio.get("origin_group_id") or ""),
                creator_uid=folio.get("creator_user"),
                mysql_db=mysql_db,
                session={"messages": [{"message_sid": sid} for sid in message_sids if sid]},
                bodies=bodies,
                processing_status="draft_resumed",
                headline="Borrador actualizado en Eassymo POS.",
            )
        finally:
            if mysql_db is not None:
                mysql_db.close()

    def _send_existing_draft_link(
        self,
        from_number: str,
        folio: dict,
        message_sids: List[str],
        *,
        burst_id: Optional[str] = None,
    ) -> None:
        folio_id = str(folio.get("_id") or folio.get("id") or "")
        share_token = str(folio.get("share_token") or "")
        self._remember_share_token(
            from_number,
            share_token,
            message_sids,
            folio_id,
            processing_status="draft_resumed",
            burst_id=burst_id,
        )
        self._send_draft_link_message(
            from_number,
            folio,
            headline="Borrador ya existe en Eassymo POS.",
            burst_id=burst_id,
        )

    def _buffer_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "message_sid": payload.get("message_sid"),
            "body": payload.get("body") or "",
            "forwarded": bool(payload.get("forwarded")),
            "received_at": datetime.now(timezone.utc),
            "whatsapp_message_id": payload.get("whatsapp_message_id"),
            "original_replied_message_sid": payload.get(
                "original_replied_message_sid"
            ),
            "channel_metadata": payload.get("channel_metadata"),
        }

    def _session_bodies(self, session: dict) -> List[str]:
        bodies: List[str] = []
        for message in session.get("messages") or []:
            body = (message.get("body") or "").strip()
            if not body:
                continue
            if classify_body(body) in FLUSH_COMMANDS | START_BURST_COMMANDS | CANCEL_COMMANDS:
                continue
            bodies.append(body)
        return bodies

    def _session_exceeded_max_wait(self, session: dict) -> bool:
        started_at = session.get("started_at")
        if not started_at:
            return False
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        return elapsed >= self.max_collect_seconds

    def _clear_session(self, from_number: str) -> None:
        session_repo.delete_session(from_number)

    def _open_collect_session(
        self,
        from_number: str,
        *,
        group_id: str,
        creator_uid: Optional[str],
        group_name: str,
    ) -> dict:
        return session_repo.open_session(
            from_number,
            group_id=group_id,
            creator_uid=creator_uid,
            group_name=group_name,
        )

    def _ensure_collect_session(
        self,
        from_number: str,
        *,
        group_id: str,
        creator_uid: Optional[str],
        group_name: str,
    ) -> dict:
        return session_repo.ensure_collecting_session(
            from_number,
            group_id=group_id,
            creator_uid=creator_uid,
            group_name=group_name,
        )

    def _schedule_debounce_result(
        self, from_number: str, generation: int, flush_at
    ) -> Dict[str, Any]:
        return {
            "schedule_debounce": True,
            "from_number": from_number,
            "generation": generation,
            "flush_at": flush_at,
        }

    def _create_draft_from_proposal(
        self,
        *,
        from_number: str,
        group_id: str,
        creator_uid: Optional[str],
        store_name: str,
        proposal: WhatsappExtractionProposal,
        message_sids: List[str],
        primary_intake_id: Optional[str],
        bodies: Optional[List[str]] = None,
        burst_id: Optional[str] = None,
        session: Optional[dict] = None,
    ) -> None:
        mysql_db = None
        if MySQLSessionLocal is not None:
            mysql_db = MySQLSessionLocal()
        try:
            pieces = self._lines_to_pieces(mysql_db, proposal)
            resolved_vehicle = self.catalog_mapper.map_vehicle(
                mysql_db, proposal, bodies or []
            )
            if resolved_vehicle:
                proposal.vehicle = resolved_vehicle
                proposal.uncertainties = [
                    item
                    for item in (proposal.uncertainties or [])
                    if item.path not in {"vehicle.make", "vehicle.model"}
                    or not resolved_vehicle.make
                    or not resolved_vehicle.model
                ]
            vehicle = self._vehicle_from_proposal(proposal)
            folio_payload: Dict[str, Any] = {
                "origin_group_id": group_id,
                "source": "whatsapp",
                "whatsapp_intake_id": primary_intake_id or (message_sids[0] if message_sids else None),
                "vehicle": vehicle,
                "pieces": pieces,
                "customer": {"type": "guest"},
            }
            created = folio_service.create(
                folio_payload,
                creator_uid=creator_uid,
                group_id=group_id,
            )
            self._finalize_linked_draft(
                from_number=from_number,
                folio=created,
                proposal=proposal,
                message_sids=message_sids,
                burst_id=burst_id,
                group_id=group_id,
                creator_uid=creator_uid,
                mysql_db=mysql_db,
                session=session,
                bodies=bodies or [],
                processing_status="draft_created",
                headline="Borrador listo en Eassymo POS.",
            )
        finally:
            if mysql_db is not None:
                mysql_db.close()

    def _send_extraction_failure(
        self,
        from_number: str,
        message_sids: List[str],
        *,
        status: str,
        error: str,
        user_message: str,
        burst_id: Optional[str] = None,
    ) -> None:
        fields: Dict[str, Any] = {
            "extraction_status": status,
            "extraction_error": error[:500],
        }
        if burst_id:
            fields["burst_id"] = burst_id
        for sid in message_sids:
            if sid:
                inbound_repo.update_fields(sid, fields)
        self._send_bot_message(
            from_number, user_message, burst_id=burst_id, kind="bot_error"
        )

    def _flush_session(self, from_number: str, session: dict) -> None:
        burst_id = uuid4().hex
        self._stamp_burst_messages(session, burst_id=burst_id, from_number=from_number)
        message_sids = [
            message.get("message_sid")
            for message in (session.get("messages") or [])
            if message.get("message_sid")
        ]
        bodies = self._session_bodies(session)
        group_id = session.get("group_id")
        creator_uid = session.get("creator_uid")
        store_name = session.get("group_name") or self._group_name(group_id or "")
        primary_intake_id = None
        original_replied_message_sid = self._latest_original_reply_sid(message_sids)
        if session.get("messages"):
            first_sid = session["messages"][0].get("message_sid")
            if first_sid:
                existing = inbound_repo.find_by_message_sid(first_sid)
                if existing and existing.get("_id"):
                    primary_intake_id = str(existing["_id"])
                else:
                    primary_intake_id = first_sid

        try:
            session_repo.finish_session(from_number)
        except Exception:
            logger.exception("Failed to clear intake session for %s", from_number)

        if not bodies:
            self._send_bot_message(
                from_number,
                "No recibimos mensajes para interpretar. "
                "Envía auto y piezas, o escribe PEDIDO para reenviar varios mensajes.",
                burst_id=burst_id,
                kind="bot_error",
            )
            return

        draft_token = self._resolve_resume_token(
            bodies, from_number, allow_last_draft=False
        )
        if draft_token or _has_draft_pointer(bodies):
            token = draft_token or self._latest_share_token(from_number)
            resume_folio = self._load_folio_by_share_token(token) if token else None
            if not resume_folio:
                self._refuse_resume(
                    from_number,
                    message_sids,
                    "No encontramos ese borrador. Ábrelo en Eassymo POS "
                    "o envía auto y piezas para crear uno nuevo.",
                    burst_id=burst_id,
                )
                return
            self._handle_resume(
                from_number=from_number,
                resume_folio=resume_folio,
                group_id=group_id or "",
                creator_uid=creator_uid,
                store_name=store_name,
                bodies=bodies,
                message_sids=message_sids,
                burst_id=burst_id,
                original_replied_message_sid=original_replied_message_sid,
            )
            return

        extract_bodies = bodies
        if not extract_bodies:
            self._send_bot_message(
                from_number,
                "No recibimos mensajes para interpretar. "
                "Envía auto y piezas, o escribe PEDIDO para reenviar varios mensajes.",
                burst_id=burst_id,
                kind="bot_error",
            )
            return

        proposal = self._extract_proposal_or_fail(
            from_number=from_number,
            store_name=store_name,
            bodies=extract_bodies,
            message_sids=message_sids,
            burst_id=burst_id,
        )
        if proposal is None:
            return

        if not self._proposal_has_content(proposal):
            if self._try_complement_before_resume(
                from_number=from_number,
                bodies=extract_bodies,
                message_sids=message_sids,
                group_id=group_id or "",
                creator_uid=creator_uid,
                burst_id=burst_id,
                original_replied_message_sid=original_replied_message_sid,
            ):
                return
            clarification = next(
                (item.reason for item in (proposal.uncertainties or []) if item.reason),
                None,
            )
            fields: Dict[str, Any] = {
                "extraction_status": "ready",
                "extraction_proposal": proposal.model_dump(mode="json"),
                "burst_id": burst_id,
            }
            for sid in message_sids:
                if sid:
                    inbound_repo.update_fields(sid, fields)
            if clarification:
                self._send_bot_message(
                    from_number, clarification, burst_id=burst_id, kind="bot_error"
                )
            else:
                self._send_bot_message(
                    from_number,
                    "Recibido. No detectamos una solicitud de refacciones clara. "
                    "Reenvía auto y piezas (ej: Jetta 2015, filtro de aire).",
                    burst_id=burst_id,
                    kind="bot_error",
                )
            return

        if self._is_full_new_request(proposal, extract_bodies):
            matched = self._find_resend_match_folio(
                from_number=from_number,
                proposal=proposal,
                group_id=group_id or "",
                creator_uid=creator_uid,
            )
            if matched:
                self._link_resend_to_existing_draft(
                    from_number=from_number,
                    folio=matched,
                    message_sids=message_sids,
                    burst_id=burst_id,
                    group_id=group_id or "",
                    creator_uid=creator_uid,
                )
                return
            self._create_draft_from_proposal(
                from_number=from_number,
                group_id=group_id,
                creator_uid=creator_uid,
                store_name=store_name,
                proposal=proposal,
                message_sids=message_sids,
                primary_intake_id=primary_intake_id,
                bodies=extract_bodies,
                burst_id=burst_id,
                session=session,
            )
            return

        if self._try_complement_before_resume(
            from_number=from_number,
            bodies=extract_bodies,
            message_sids=message_sids,
            group_id=group_id or "",
            creator_uid=creator_uid,
            burst_id=burst_id,
            original_replied_message_sid=original_replied_message_sid,
        ):
            return

        if not self._proposal_has_vehicle(proposal):
            last_token = self._latest_share_token(from_number)
            resume_folio = (
                self._load_folio_by_share_token(last_token) if last_token else None
            )
            if resume_folio:
                can_resume, refuse_message = self._can_resume_folio(
                    resume_folio,
                    group_id=group_id or "",
                    creator_uid=creator_uid,
                )
                if can_resume:
                    self._resume_draft_from_proposal(
                        from_number=from_number,
                        folio=resume_folio,
                        proposal=proposal,
                        message_sids=message_sids,
                        bodies=extract_bodies,
                        burst_id=burst_id,
                    )
                    return
                self._refuse_resume(
                    from_number, message_sids, refuse_message or "", burst_id=burst_id
                )
                return
            self._refuse_resume(
                from_number,
                message_sids,
                "Falta el auto (marca, modelo, año). "
                "Reenvía esos datos con las piezas, o reenvía el enlace del borrador.",
                burst_id=burst_id,
            )
            return

        self._create_draft_from_proposal(
            from_number=from_number,
            group_id=group_id,
            creator_uid=creator_uid,
            store_name=store_name,
            proposal=proposal,
            message_sids=message_sids,
            primary_intake_id=primary_intake_id,
            bodies=extract_bodies,
            burst_id=burst_id,
            session=session,
        )

    def flush_if_ready(self, from_number: str, generation: int) -> None:
        session = session_repo.get_by_phone(from_number)
        if not session or session.get("status") != STATUS_COLLECTING:
            return
        if not session.get("group_id"):
            return
        if int(session.get("generation") or 0) != generation:
            return
        acquired = session_repo.try_acquire_flush(from_number, generation)
        if not acquired:
            return
        self._flush_session(from_number, acquired)

    def _attempt_flush(self, from_number: str, generation: int) -> None:
        acquired = session_repo.try_acquire_flush(from_number, generation)
        if acquired:
            self._flush_session(from_number, acquired)

    def _append_and_maybe_flush(
        self,
        *,
        from_number: str,
        payload: Dict[str, Any],
        group_id: str,
        creator_uid: Optional[str],
        group_name: str,
    ) -> Optional[Dict[str, Any]]:
        session = session_repo.get_by_phone(from_number)
        is_new_burst = (
            not session
            or session.get("status") != STATUS_COLLECTING
            or not session.get("messages")
        )
        if not session or session.get("status") != STATUS_COLLECTING:
            session = self._ensure_collect_session(
                from_number,
                group_id=group_id,
                creator_uid=creator_uid,
                group_name=group_name,
            )

        if is_new_burst and group_id:
            self._send_bot_message(
                from_number,
                _processing_ack_message(),
                kind="bot_ack",
            )

        session, should_auto_flush, schedule_debounce = session_repo.append_message(
            from_number,
            self._buffer_message(payload),
            quiet_seconds=self.quiet_seconds,
        )
        if not session:
            return None

        if not session.get("group_id"):
            return None

        generation = int(session.get("generation") or 0)
        if should_auto_flush or self._session_exceeded_max_wait(session):
            self._attempt_flush(from_number, generation)
            return None

        if schedule_debounce:
            return self._schedule_debounce_result(
                from_number,
                generation,
                session.get("flush_at"),
            )
        return None

    def _buffer_pending_store_selection(
        self,
        *,
        from_number: str,
        payload: Dict[str, Any],
        creator_uid: Optional[str],
        reset_session: bool,
    ) -> None:
        if reset_session:
            self._clear_session(from_number)
        self._append_and_maybe_flush(
            from_number=from_number,
            payload=payload,
            group_id="",
            creator_uid=creator_uid,
            group_name="",
        )

    def process_inbound(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.extract_enabled:
            return None

        inbound_id = payload.get("mongo_id")
        message_sid = payload.get("message_sid")
        from_number = payload.get("from_number")
        body = payload.get("body") or ""

        if not from_number or not message_sid:
            return None

        existing = inbound_repo.find_by_message_sid(message_sid)
        if existing and existing.get("folio_id"):
            logger.info("Inbound %s already linked to folio", message_sid)
            return None

        identity = self.identity_service.resolve(from_number, body, inbound_id)
        inbound_repo.update_fields(
            message_sid,
            {
                "identity_status": identity.status,
                "resolved_group_id": identity.group_id,
                "resolved_creator_uid": identity.creator_uid,
            },
        )

        if identity.status != "resolved" or not identity.group_id:
            if identity.message:
                self.whatsapp_service.send_text_message(from_number, identity.message)
            is_change_store = normalize_command(body) in CHANGE_STORE_COMMANDS
            if (
                identity.status == "pending_selection"
                and classify_body(body) == "content"
                and not is_change_store
            ):
                self._buffer_pending_store_selection(
                    from_number=from_number,
                    payload=payload,
                    creator_uid=identity.creator_uid,
                    reset_session=bool(identity.message),
                )
                return None
            self._clear_session(from_number)
            return None

        if identity.just_selected:
            store_name = identity.group_name or self._group_name(identity.group_id)
            session = session_repo.get_by_phone(from_number)
            has_buffered = bool(
                session
                and session.get("status") == STATUS_COLLECTING
                and session.get("messages")
            )
            self.whatsapp_service.send_text_message(
                from_number,
                _store_confirmation_message(store_name),
            )
            if has_buffered:
                self._send_bot_message(
                    from_number,
                    _processing_ack_message(),
                    kind="bot_ack",
                )
                session = self._ensure_collect_session(
                    from_number,
                    group_id=identity.group_id,
                    creator_uid=identity.creator_uid,
                    group_name=store_name,
                )
                generation = int(session.get("generation") or 0)
                self._attempt_flush(from_number, generation)
                return None
            self._clear_session(from_number)
            return None

        store_name = identity.group_name or self._group_name(identity.group_id)
        body_kind = classify_body(body)

        if body_kind == "start":
            self._open_collect_session(
                from_number,
                group_id=identity.group_id,
                creator_uid=identity.creator_uid,
                group_name=store_name,
            )
            self.whatsapp_service.send_text_message(from_number, _collect_burst_message())
            return None

        if body_kind == "cancel":
            session_repo.bump_generation(from_number)
            self._clear_session(from_number)
            self.whatsapp_service.send_text_message(
                from_number,
                "Solicitud cancelada. Escribe PEDIDO o envía auto y piezas cuando quieras crear un borrador.",
            )
            return None

        session = session_repo.get_by_phone(from_number)
        if body_kind == "flush":
            if not session or session.get("status") != STATUS_COLLECTING:
                self.whatsapp_service.send_text_message(
                    from_number,
                    "No hay mensajes en cola. Envía auto y piezas, o escribe PEDIDO para reenviar varios mensajes.",
                )
                return None
            session_repo.append_message(
                from_number,
                self._buffer_message(payload),
                quiet_seconds=self.quiet_seconds,
            )
            session_repo.bump_generation(from_number)
            session = session_repo.get_by_phone(from_number)
            if not session:
                return None
            generation = int(session.get("generation") or 0)
            self._attempt_flush(from_number, generation)
            return None

        if body_kind == "content":
            return self._append_and_maybe_flush(
                from_number=from_number,
                payload=payload,
                group_id=identity.group_id,
                creator_uid=identity.creator_uid,
                group_name=store_name,
            )

        return None
