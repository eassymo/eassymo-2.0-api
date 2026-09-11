import logging
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.config.database import MySQLSessionLocal
from app.repositories import GroupRepository as groupRepository
from app.repositories import WhatsappInboundRepository as inbound_repo
from app.schemas.VehiculoPartesSearch import SearchPartesPaginatorRequest, HistoricoBusquedaInput
from app.schemas.WhatsappExtraction import ExtractionIntent, WhatsappExtractionProposal
from app.services import MostradorFolioService as folio_service
from app.services.LlmExtractionService import LlmExtractionService, LlmRateLimitError
from app.services.WhatsappSellerIdentityService import WhatsappSellerIdentityService
from app.services.WhatsappService import WhatsappService
from app.services.VehiculoPartesService import search_partes_paginator

logger = logging.getLogger(__name__)


def _store_confirmation_message(store_name: str) -> str:
    return (
        f"Tienda confirmada: {store_name}.\n"
        "Las siguientes solicitudes van a esta tienda.\n\n"
        "Envía auto y piezas (ej: Jetta 2015, filtro de aire) para crear un borrador.\n"
        "Si te equivocaste, escribe CAMBIAR, MENU o ATRAS para volver a la lista de tiendas."
    )


class WhatsappIntakeProcessorService:
    def __init__(self) -> None:
        self.identity_service = WhatsappSellerIdentityService()
        self.llm_service = LlmExtractionService()
        self.whatsapp_service = WhatsappService()
        self.client_base_url = folio_service._resolve_client_base_url()
        self.extract_enabled = os.getenv(
            "WHATSAPP_INTAKE_EXTRACT", "true"
        ).lower() in ("1", "true", "yes")

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

    def _search_catalog_part(self, mysql_db, part_name: str) -> Optional[dict]:
        if mysql_db is None or not part_name.strip():
            return None
        payload = SearchPartesPaginatorRequest(
            historicoBusqueda=HistoricoBusquedaInput(criterio=part_name),
            page=0,
            itemsPerPage=5,
        )
        result = search_partes_paginator(mysql_db, payload)
        historico = result.get("historicoBusqueda") or {}
        details = historico.get("details") or []
        items = (details[0].get("partes") if details else None) or []
        if not items:
            return None
        if len(items) == 1:
            catalog = items[0]
        else:
            top = items[0]
            if (top.get("tipoParteDescripcion") or "").lower() == part_name.lower():
                catalog = top
            else:
                return None
        return {
            "tipoParteId": catalog.get("tipoParteId"),
            "tipoParteDescripcion": catalog.get("tipoParteDescripcion"),
            "categoriaId": catalog.get("categoriaId"),
            "subCategoriaId": catalog.get("subCategoriaId"),
        }

    def _lines_to_pieces(
        self, mysql_db, proposal: WhatsappExtractionProposal
    ) -> List[dict]:
        pieces: List[dict] = []
        uncertainty_notes = [
            f"{u.path}: {u.reason}" for u in (proposal.uncertainties or [])
        ]
        for idx, line in enumerate(proposal.lines):
            catalog = self._search_catalog_part(mysql_db, line.part_name)
            comments_parts: List[str] = []
            if line.raw:
                comments_parts.append(line.raw)
            if not catalog:
                comments_parts.append("Sin match de catálogo automático")
            if uncertainty_notes:
                comments_parts.extend(uncertainty_notes[:2])

            piece = {
                "piece_id": uuid4().hex,
                "tipoParteId": str(catalog["tipoParteId"]) if catalog else None,
                "tipoParteDescripcion": (
                    catalog.get("tipoParteDescripcion") if catalog else line.part_name
                ),
                "categoriaId": catalog.get("categoriaId") if catalog else None,
                "subCategoriaId": catalog.get("subCategoriaId") if catalog else None,
                "name": line.part_name,
                "qty": line.quantity or 1,
                "unitOfMeasure": line.unit or "Pieza",
                "position": line.position or "No aplica",
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

    def _draft_preview_link(self, share_token: str, folio_id: str) -> str:
        path = f"/whatsapp-draft/{share_token}" if share_token else f"/pos?folioId={folio_id}"
        if self.client_base_url:
            return f"{self.client_base_url}{path}"
        return path

    def process_inbound(self, payload: Dict[str, Any]) -> None:
        if not self.extract_enabled:
            return

        inbound_id = payload.get("mongo_id")
        message_sid = payload.get("message_sid")
        from_number = payload.get("from_number")
        body = payload.get("body") or ""

        if not from_number or not message_sid:
            return

        existing = inbound_repo.find_by_message_sid(message_sid)
        if existing and existing.get("folio_id"):
            logger.info("Inbound %s already linked to folio", message_sid)
            return

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
            return

        if identity.just_selected:
            store_name = identity.group_name or self._group_name(identity.group_id)
            self.whatsapp_service.send_text_message(
                from_number,
                _store_confirmation_message(store_name),
            )
            return

        store_name = identity.group_name or self._group_name(identity.group_id)

        try:
            proposal = self.llm_service.extract(body, store_name=store_name)
        except LlmRateLimitError as exc:
            logger.error("GLM rate limited for %s: %s", message_sid, exc)
            inbound_repo.update_fields(
                message_sid,
                {"extraction_status": "rate_limited", "extraction_error": str(exc)[:500]},
            )
            self.whatsapp_service.send_text_message(
                from_number,
                "El servicio de interpretación está ocupado por el momento. "
                "Espera unos segundos y reenvía tu mensaje con auto y piezas.",
            )
            return
        except Exception as exc:
            logger.error("GLM extraction failed for %s: %s", message_sid, exc)
            inbound_repo.update_fields(
                message_sid,
                {"extraction_status": "failed", "extraction_error": str(exc)[:500]},
            )
            self.whatsapp_service.send_text_message(
                from_number,
                "Recibimos tu mensaje pero no pudimos interpretarlo automáticamente. "
                "Intenta incluir auto (marca, modelo, año) y las refacciones solicitadas.",
            )
            return

        inbound_repo.update_fields(
            message_sid,
            {
                "extraction_status": "ready",
                "extraction_proposal": proposal.model_dump(mode="json"),
            },
        )

        if proposal.intent != ExtractionIntent.NEW_REQUEST or not self._proposal_has_content(
            proposal
        ):
            clarification = next(
                (item.reason for item in (proposal.uncertainties or []) if item.reason),
                None,
            )
            if clarification:
                self.whatsapp_service.send_text_message(from_number, clarification)
            else:
                self.whatsapp_service.send_text_message(
                    from_number,
                    "Recibido. No detectamos una solicitud de refacciones clara. "
                    "Reenvía auto y piezas (ej: Jetta 2015, filtro de aire).",
                )
            return

        mysql_db = None
        if MySQLSessionLocal is not None:
            mysql_db = MySQLSessionLocal()
        try:
            pieces = self._lines_to_pieces(mysql_db, proposal) if mysql_db else self._lines_to_pieces(None, proposal)
            vehicle = self._vehicle_from_proposal(proposal)
            folio_payload: Dict[str, Any] = {
                "origin_group_id": identity.group_id,
                "source": "whatsapp",
                "whatsapp_intake_id": inbound_id or message_sid,
                "vehicle": vehicle,
                "pieces": pieces,
                "customer": {"type": "guest"},
            }
            created = folio_service.create(
                folio_payload,
                creator_uid=identity.creator_uid,
                group_id=identity.group_id,
            )
        finally:
            if mysql_db is not None:
                mysql_db.close()

        folio_id = str(created.get("_id") or created.get("id") or "")
        share_token = str(created.get("share_token") or "")
        inbound_repo.update_fields(
            message_sid,
            {"folio_id": folio_id, "processing_status": "draft_created"},
        )

        link = self._draft_preview_link(share_token, folio_id)
        self.whatsapp_service.send_text_message(
            from_number,
            f"Borrador listo en Eassymo POS.\nRevisa vehículo y piezas aquí:\n{link}",
        )
