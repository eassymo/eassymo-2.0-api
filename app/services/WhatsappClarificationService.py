"""Derive, ask, and apply non-blocking WhatsApp clarifications on POS drafts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from app.repositories import MostradorFolioRepository as folioRepository
from app.repositories import WhatsappInboundRepository as inbound_repo
from app.schemas.WhatsappExtraction import WhatsappExtractionProposal
from app.services.WhatsappCatalogMapper import (
    POSITION_ALIASES,
    _normalize_text,
    _tokenize,
)

_WAMID_RE = re.compile(r"wamid\.[A-Za-z0-9+/=_-]+")
_VEHICLE_FIELD_LABELS = {
    "vehicle.make": "marca",
    "vehicle.model": "modelo",
    "vehicle.year": "año",
    "vehicle.engine": "motor",
    "vehicle.vin": "VIN",
}
_SKIP_POSITIONS = {"", "no aplica", "n/a", "na"}


def extract_whatsapp_message_id(channel_metadata: str) -> Optional[str]:
    raw = (channel_metadata or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        blob = json.dumps(payload)
    except (json.JSONDecodeError, TypeError):
        blob = raw
    match = _WAMID_RE.search(blob)
    return match.group(0) if match else None


def folio_code_of(folio: dict) -> str:
    return str(folio.get("folio_code") or "").strip()


def vehicle_short_label(folio: dict) -> str:
    vehicle = folio.get("vehicle") or {}
    parts = [
        str(vehicle.get(key)).strip()
        for key in ("maker", "model", "year")
        if vehicle.get(key)
    ]
    return " ".join(parts)


def piece_label(piece: dict) -> str:
    return (
        (piece.get("name") or piece.get("tipoParteDescripcion") or "Pieza").strip()
    )


def open_questions(folio: dict) -> List[dict]:
    return [
        item
        for item in (folio.get("whatsapp_pending_questions") or [])
        if (item or {}).get("status") == "open"
    ]


def _question_id() -> str:
    return uuid4().hex[:12]


def _position_missing(piece: dict) -> bool:
    position = (piece.get("position") or "").strip()
    if position and position.lower() not in _SKIP_POSITIONS:
        return False
    return bool(piece.get("tipoParteId"))


def _position_prompt(piece: dict) -> str:
    name = piece_label(piece).lower()
    if "balata" in name:
        return "¿Son delanteras o traseras?"
    return "¿Qué posición necesitas (delantera, trasera, izquierda, derecha)?"


def _vehicle_field_missing(vehicle: Optional[dict], field: str) -> bool:
    if not vehicle:
        return True
    key_map = {
        "vehicle.make": "maker",
        "vehicle.model": "model",
        "vehicle.year": "year",
        "vehicle.engine": "engine",
        "vehicle.vin": "vin",
    }
    mapped = key_map.get(field)
    if not mapped:
        return False
    return not str(vehicle.get(mapped) or "").strip()


def derive_pending_questions(
    folio: dict,
    proposal: WhatsappExtractionProposal,
    *,
    mysql_db: Optional[Session] = None,
) -> List[dict]:
    """Build new pending questions from extraction + mapped pieces."""
    questions: List[dict] = []
    seen_paths: set[str] = set()
    vehicle = folio.get("vehicle") or {}
    has_vehicle_label = bool(vehicle_short_label(folio))

    for uncertainty in proposal.uncertainties or []:
        path = (uncertainty.path or "").strip()
        reason = (uncertainty.reason or "").strip()
        if not path or not reason or path in seen_paths:
            continue
        if has_vehicle_label and path.startswith("vehicle."):
            continue
        if path.startswith("lines") and ".position" in path:
            continue
        questions.append(
            {
                "id": _question_id(),
                "path": path,
                "piece_id": None,
                "prompt": reason,
                "status": "open",
                "asked_message_sid": None,
                "source": "llm",
            }
        )
        seen_paths.add(path)

    for piece in folio.get("pieces") or []:
        piece_id = str(piece.get("piece_id") or "")
        if not piece_id or not _position_missing(piece):
            continue
        if not piece.get("tipoParteId"):
            continue
        path = f"piece:{piece_id}.position"
        if path in seen_paths:
            continue
        questions.append(
            {
                "id": _question_id(),
                "path": path,
                "piece_id": piece_id,
                "prompt": _position_prompt(piece),
                "status": "open",
                "asked_message_sid": None,
                "source": "catalog_position",
            }
        )
        seen_paths.add(path)

    for field, label in _VEHICLE_FIELD_LABELS.items():
        if has_vehicle_label and field.startswith("vehicle."):
            if not _vehicle_field_missing(vehicle, field):
                continue
            if field in {"vehicle.make", "vehicle.model", "vehicle.year"}:
                continue
        path = field
        if path in seen_paths:
            continue
        if field == "vehicle.engine" and not _vehicle_field_missing(vehicle, field):
            continue
        if field == "vehicle.engine" and _vehicle_field_missing(vehicle, field):
            questions.append(
                {
                    "id": _question_id(),
                    "path": path,
                    "piece_id": None,
                    "prompt": f"¿Cuál es el {label} del vehículo?",
                    "status": "open",
                    "asked_message_sid": None,
                    "source": "vehicle_field",
                }
            )
            seen_paths.add(path)

    return questions


def merge_pending_questions(
    existing: Sequence[dict], new_items: Sequence[dict]
) -> List[dict]:
    merged = [dict(item) for item in (existing or [])]
    open_paths = {
        (item.get("path") or "")
        for item in merged
        if item.get("status") == "open"
    }
    for item in new_items:
        path = item.get("path") or ""
        if path in open_paths:
            continue
        merged.append(dict(item))
        if item.get("status") == "open":
            open_paths.add(path)
    return merged


def format_clarify_header(folio: dict, question: dict) -> str:
    code = folio_code_of(folio) or "—"
    vehicle = vehicle_short_label(folio)
    piece_id = question.get("piece_id")
    piece_name = ""
    if piece_id:
        for piece in folio.get("pieces") or []:
            if str(piece.get("piece_id")) == str(piece_id):
                piece_name = piece_label(piece)
                break
    parts = [code]
    if vehicle:
        parts.append(vehicle)
    if piece_name:
        parts.append(piece_name.lower())
    return " · ".join(parts)


def format_clarify_message(
    folio: dict,
    question: dict,
    *,
    multi_draft_hint: bool = False,
) -> str:
    header = format_clarify_header(folio, question)
    lines = [header, question.get("prompt") or ""]
    if multi_draft_hint:
        lines.append(
            "Si tienes varios borradores abiertos, responde con el enlace del borrador, "
            "la pregunta y tu respuesta."
        )
    return "\n".join(line for line in lines if line)


def map_evidence_sids(
    session_messages: Sequence[dict],
    proposal: WhatsappExtractionProposal,
    bodies: Sequence[str],
) -> Dict[str, List[str]]:
    """Map inbound message SIDs to extraction evidence paths."""
    evidence_bodies: set[str] = set()
    for item in proposal.evidence or []:
        raw = (item.raw or "").strip()
        if raw:
            evidence_bodies.add(_normalize_text(raw))
    for line in proposal.lines or []:
        if line.raw:
            evidence_bodies.add(_normalize_text(line.raw))
        if line.part_name:
            evidence_bodies.add(_normalize_text(line.part_name))
    vehicle = proposal.vehicle
    if vehicle:
        for value in (
            vehicle.make,
            vehicle.model,
            vehicle.year,
            vehicle.engine,
            vehicle.vin,
        ):
            if value:
                evidence_bodies.add(_normalize_text(str(value)))

    indexed_bodies: Dict[int, str] = {}
    for index, body in enumerate(bodies, start=1):
        indexed_bodies[index] = _normalize_text(body)

    result: Dict[str, List[str]] = {}
    for message in session_messages or []:
        sid = message.get("message_sid")
        body = (message.get("body") or "").strip()
        if not sid or not body:
            continue
        norm_body = _normalize_text(body)
        paths: List[str] = []
        if norm_body in evidence_bodies:
            paths.append("content")
        for index, indexed in indexed_bodies.items():
            prefix = f"[{index}]"
            if body.startswith(prefix) or indexed == norm_body:
                paths.append(f"burst:{index}")
        if paths:
            result[sid] = paths
    return result


def content_message_sids(
    session_messages: Sequence[dict],
    evidence_map: Dict[str, List[str]],
) -> List[str]:
    sids: List[str] = []
    for message in session_messages or []:
        sid = message.get("message_sid")
        body = (message.get("body") or "").strip()
        if not sid or not body:
            continue
        if sid in evidence_map:
            sids.append(sid)
    return sids


def resolve_position(text: str) -> Optional[str]:
    for token in _tokenize(text):
        alias = POSITION_ALIASES.get(token)
        if alias:
            return alias
    return None


def resolve_vehicle_patch(text: str, field_path: str) -> Optional[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if field_path == "vehicle.engine":
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*l?\b", cleaned.lower())
        if match:
            return match.group(1)
        return cleaned
    if field_path == "vehicle.year":
        match = re.search(r"\b((?:19|20)\d{2})\b", cleaned)
        return match.group(1) if match else None
    return cleaned


def apply_answer_to_folio(
    folio: dict,
    question: dict,
    answer_text: str,
) -> Tuple[dict, bool, Optional[str]]:
    """Return updated folio dict fields, success flag, and confirmation detail."""
    path = question.get("path") or ""
    pieces = [dict(p) for p in (folio.get("pieces") or [])]
    vehicle = dict(folio.get("vehicle") or {})
    detail: Optional[str] = None

    if path.endswith(".position") and question.get("piece_id"):
        position = resolve_position(answer_text)
        if not position:
            return folio, False, None
        for piece in pieces:
            if str(piece.get("piece_id")) == str(question.get("piece_id")):
                piece["position"] = position
                piece["position_suggested"] = False
                detail = f"{piece_label(piece)} · {position}"
                break
        else:
            return folio, False, None
        return {"pieces": pieces}, True, detail

    if path.startswith("vehicle."):
        key_map = {
            "vehicle.make": "maker",
            "vehicle.model": "model",
            "vehicle.year": "year",
            "vehicle.engine": "engine",
            "vehicle.vin": "vin",
        }
        field = key_map.get(path)
        if not field:
            return folio, False, None
        value = resolve_vehicle_patch(answer_text, path)
        if not value:
            return folio, False, None
        vehicle[field] = value
        detail = value
        return {"vehicle": vehicle}, True, detail

    if ".unit" in path or "unit" in path:
        unit_map = {
            "par": "Par",
            "pares": "Par",
            "juego": "Juego",
            "juegos": "Juego",
            "pieza": "Pieza",
            "piezas": "Pieza",
        }
        for token, unit in unit_map.items():
            if token in _tokenize(answer_text):
                piece_id = question.get("piece_id")
                if piece_id:
                    for piece in pieces:
                        if str(piece.get("piece_id")) == str(piece_id):
                            piece["unitOfMeasure"] = unit
                            detail = unit
                            return {"pieces": pieces}, True, detail
                return folio, False, None

    position = resolve_position(answer_text)
    if position and question.get("piece_id"):
        for piece in pieces:
            if str(piece.get("piece_id")) == str(question.get("piece_id")):
                piece["position"] = position
                piece["position_suggested"] = False
                detail = f"{piece_label(piece)} · {position}"
                return {"pieces": pieces}, True, detail

    return folio, False, None


def mark_question_answered(folio: dict, question_id: str) -> List[dict]:
    updated: List[dict] = []
    for item in folio.get("whatsapp_pending_questions") or []:
        row = dict(item)
        if row.get("id") == question_id and row.get("status") == "open":
            row["status"] = "answered"
        updated.append(row)
    return updated


def attach_asked_sid(
    questions: Sequence[dict], question_id: str, message_sid: str
) -> List[dict]:
    updated: List[dict] = []
    for item in questions or []:
        row = dict(item)
        if row.get("id") == question_id:
            row["asked_message_sid"] = message_sid
        updated.append(row)
    return updated


def find_folio_by_clarify_sid(message_sid: str) -> Optional[dict]:
    if not message_sid:
        return None
    return folioRepository.find_by_clarify_message_sid(message_sid)


def find_drafts_with_open_questions(
    *,
    origin_group_id: str,
    creator_uid: Optional[str] = None,
) -> List[dict]:
    return folioRepository.find_drafts_with_open_questions(
        origin_group_id=origin_group_id,
        creator_uid=creator_uid,
    )


def load_inbound(message_sid: str) -> Optional[dict]:
    return inbound_repo.find_by_message_sid(message_sid)


def linked_reaction_stamp(folio_code: str, method: str) -> dict:
    return {
        "emoji": "🔗",
        "method": method,
        "folio_code": folio_code,
        "at": datetime.now(timezone.utc).isoformat(),
    }
