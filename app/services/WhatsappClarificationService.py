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


_BLOCKING_SEVERITIES = {"critical", "warning"}
_SEVERITY_EMOJI = {
    "critical": "❗",
    "warning": "⚠️",
    "info": "ℹ️",
}
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def question_severity(question: dict) -> str:
    """Severity stored on the question, or a safe class for older drafts.

    A missing engine question from before this field existed is info, so it
    does not hide the draft.
    """
    stored = str((question or {}).get("severity") or "").strip().lower()
    if stored in _SEVERITY_RANK:
        return stored
    path = str((question or {}).get("path") or "").strip()
    if path in {"vehicle.year", "vehicle.make", "vehicle.model"}:
        return "critical"
    if ".position" in path:
        return "warning"
    return "info"


def question_copy_text(question: dict) -> str:
    return str((question or {}).get("copy_text") or (question or {}).get("prompt") or "").strip()


def question_acknowledged(question: dict) -> bool:
    """True once the seller accepted a warning/info. Critical never counts."""
    if question_severity(question) == "critical":
        return False
    return bool((question or {}).get("acknowledged_at"))


def folio_share_ready(folio: dict) -> bool:
    return not any(
        question_severity(question) in _BLOCKING_SEVERITIES
        and not question_acknowledged(question)
        for question in open_questions(folio)
    )


def alert_lines(folio: dict) -> List[str]:
    ranked: List[tuple] = []
    for question in open_questions(folio):
        text = question_copy_text(question)
        if not text:
            continue
        severity = question_severity(question)
        ranked.append((_SEVERITY_RANK[severity], f"{_SEVERITY_EMOJI[severity]} {text}"))
    ranked.sort(key=lambda item: item[0])
    return [line for _, line in ranked]


def append_alert_lines(body: str, folio: dict) -> str:
    lines = alert_lines(folio)
    if not lines:
        return body
    return f"{(body or '').rstrip()}\n\n" + "\n".join(lines)


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


def _car_phrase(vehicle: Optional[dict]) -> str:
    vehicle = vehicle or {}
    parts = [
        str(vehicle.get(key)).strip()
        for key in ("maker", "model")
        if vehicle.get(key)
    ]
    return " ".join(parts)


def _identity_copy(vehicle: Optional[dict], field: str, reason: str = "") -> str:
    if reason and "¿" in reason:
        return reason.strip()
    car = _car_phrase(vehicle)
    if field == "vehicle.year":
        return f"¿De qué año es el {car}?" if car else "¿De qué año es el vehículo?"
    if field == "vehicle.make":
        model = str((vehicle or {}).get("model") or "").strip()
        return f"¿Cuál es la marca del {model}?" if model else "¿Cuál es la marca del vehículo?"
    model_of = car or "vehículo"
    return f"¿Cuál es el modelo del {model_of}?"


def _alert(
    *,
    path: str,
    copy_text: str,
    severity: str,
    source: str,
    piece_id: Optional[str] = None,
) -> dict:
    text = copy_text.strip()
    return {
        "id": _question_id(),
        "path": path,
        "piece_id": piece_id,
        "prompt": text,
        "copy_text": text,
        "severity": severity,
        "status": "open",
        "asked_message_sid": None,
        "source": source,
    }


def derive_pending_questions(
    folio: dict,
    proposal: WhatsappExtractionProposal,
    *,
    mysql_db: Optional[Session] = None,
) -> List[dict]:
    """Build critical, warning, and info lines for a WhatsApp draft.

    mysql_db is unused: position and unit flags are stored on the piece when
    the catalog is mapped.
    """
    del mysql_db
    questions: List[dict] = []
    seen_paths: set[str] = set()
    vehicle = folio.get("vehicle") or {}
    uncertainty_reason = {
        (item.path or "").strip(): (item.reason or "").strip()
        for item in (proposal.uncertainties or [])
        if (item.path or "").strip() and (item.reason or "").strip()
    }

    def add(question: dict) -> None:
        path = question["path"]
        if path in seen_paths:
            return
        questions.append(question)
        seen_paths.add(path)

    for field in ("vehicle.year", "vehicle.make", "vehicle.model"):
        if not _vehicle_field_missing(vehicle, field):
            continue
        add(
            _alert(
                path=field,
                copy_text=_identity_copy(vehicle, field, uncertainty_reason.get(field, "")),
                severity="critical",
                source="vehicle_field",
            )
        )

    for path, reason in uncertainty_reason.items():
        if path in seen_paths or not reason:
            continue
        if path.startswith("lines") and ".position" in path:
            continue
        if path in {"vehicle.engine", "vehicle.vin"}:
            continue
        if path.startswith("vehicle.") and not _vehicle_field_missing(vehicle, path):
            continue
        if path.startswith("vehicle."):
            add(
                _alert(
                    path=path,
                    copy_text=reason if "¿" in reason else _identity_copy(vehicle, path, reason),
                    severity="critical",
                    source="llm",
                )
            )
            continue
        add(_alert(path=path, copy_text=reason, severity="info", source="llm"))

    car = _car_phrase(vehicle)
    for piece in folio.get("pieces") or []:
        piece_id = str(piece.get("piece_id") or "")
        if not piece_id:
            continue
        name = piece_label(piece)
        if not piece.get("tipoParteId"):
            add(
                _alert(
                    path=f"piece:{piece_id}.catalog",
                    piece_id=piece_id,
                    copy_text=f"No encontramos «{name}» en el catálogo.",
                    severity="info",
                    source="catalog_miss",
                )
            )
        if piece.get("position_required") and _position_missing(piece):
            prompt = _position_prompt(piece)
            if car and "balata" in name.lower():
                prompt = f"¿Las balatas del {car} son delanteras o traseras?"
            elif car:
                prompt = (
                    f"¿Qué posición necesita {name.lower()} del {car}? "
                    "Delantera, trasera, izquierda o derecha."
                )
            add(
                _alert(
                    path=f"piece:{piece_id}.position",
                    piece_id=piece_id,
                    copy_text=prompt,
                    severity="warning",
                    source="catalog_position",
                )
            )
        raw_position = str(piece.get("position") or "").strip()
        if (
            piece.get("position_required")
            and piece.get("position_standardized") is False
            and raw_position
            and raw_position.lower() not in _SKIP_POSITIONS
        ):
            add(
                _alert(
                    path=f"piece:{piece_id}.position_text",
                    piece_id=piece_id,
                    copy_text=f"La posición «{raw_position}» no está en el catálogo.",
                    severity="info",
                    source="position_text",
                )
            )
        raw_unit = str(piece.get("unitOfMeasure") or "").strip()
        if piece.get("unit_standardized") is False and raw_unit:
            add(
                _alert(
                    path=f"piece:{piece_id}.unit",
                    piece_id=piece_id,
                    copy_text=f"La unidad «{raw_unit}» no está en el catálogo.",
                    severity="info",
                    source="unit_text",
                )
            )

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


def forwarded_answer_text(bodies: Sequence[str], folios: Sequence[dict]) -> str:
    """Text left after the questions message and the draft links are removed."""
    phrases = []
    for folio in folios:
        label = vehicle_short_label(folio)
        if label:
            phrases.append(label)
        for question in folio.get("whatsapp_pending_questions") or []:
            for key in ("copy_text", "prompt"):
                text = str(question.get(key) or "").strip()
                if text:
                    phrases.append(text)
        for piece in folio.get("pieces") or []:
            name = piece_label(piece)
            if name and name.lower() != "pieza":
                phrases.append(name)
        vehicle = folio.get("vehicle") or {}
        for key in ("maker", "model"):
            value = str(vehicle.get(key) or "").strip()
            if value:
                phrases.append(value)
    normalized_phrases = sorted(
        {_normalize_text(phrase) for phrase in phrases if _normalize_text(phrase)},
        key=len,
        reverse=True,
    )
    kept: List[str] = []
    for body in bodies:
        raw = re.sub(r"https?://\S+", " ", body or "", flags=re.IGNORECASE)
        text = _normalize_text(raw)
        text = re.sub(r"whatsapp draft\s+[a-f0-9]{32}", " ", text)
        text = re.sub(r"borrador (?:listo|actualizado|ya existe) en eassymo pos", " ", text)
        text = re.sub(r"revisa vehiculo y piezas aqui", " ", text)
        text = re.sub(
            r"son \d+ vehiculos asi que quedo un borrador por cada uno",
            " ",
            text,
        )
        for phrase in normalized_phrases:
            text = text.replace(phrase, " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            kept.append(text)
    return " ".join(kept).strip()


_ANSWER_FILLERS = {
    "son", "es", "para", "el", "la", "las", "los", "de", "del", "que",
    "un", "una", "y", "e", "al", "se", "me", "por", "favor", "porfa",
    "bro", "tambien", "si", "va", "van", "sean", "sea", "ok", "listo",
}


def answer_text_is_only_a_reply(text: str) -> bool:
    """True when the leftover is just a year, a position, or a unit."""
    tokens = _tokenize(text)
    if not tokens:
        return False
    for token in tokens:
        if token in _ANSWER_FILLERS or token in POSITION_ALIASES:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            continue
        if token in {"par", "pares", "juego", "juegos", "pieza", "piezas"}:
            continue
        return False
    return True


def fill_open_questions(folio: dict, answer_text: str) -> Optional[Tuple[dict, List[str]]]:
    """Apply one client reply to every open question it actually answers."""
    questions = [dict(item) for item in (folio.get("whatsapp_pending_questions") or [])]
    pieces = [dict(piece) for piece in (folio.get("pieces") or [])]
    vehicle = dict(folio.get("vehicle") or {})
    details: List[str] = []
    filled = False
    for question in questions:
        if question.get("status") != "open":
            continue
        if str(question.get("path") or "").endswith(".catalog"):
            continue
        trial = {
            **folio,
            "pieces": pieces,
            "vehicle": vehicle,
            "whatsapp_pending_questions": questions,
        }
        patch, ok, detail = apply_answer_to_folio(trial, question, answer_text)
        if not ok:
            continue
        if "pieces" in patch:
            pieces = patch["pieces"]
        if "vehicle" in patch:
            vehicle = patch["vehicle"]
        question["status"] = "answered"
        if detail:
            details.append(detail)
        filled = True
    if not filled:
        return None
    return (
        {
            "pieces": pieces,
            "vehicle": vehicle,
            "whatsapp_pending_questions": questions,
        },
        details,
    )


def resolve_position(text: str) -> Optional[str]:
    for token in _tokenize(text):
        alias = POSITION_ALIASES.get(token)
        if alias:
            return alias
    return None


_MATERIAL_ALIASES = {
    "ceramica": "Cerámicas",
    "ceramicas": "Cerámicas",
    "ceramico": "Cerámicas",
    "ceramicos": "Cerámicas",
}


def resolve_material_note(text: str) -> Optional[str]:
    """Detect a non-position material note such as cerámicas."""
    normalized = _normalize_text(text or "")
    for token in _tokenize(text):
        alias = _MATERIAL_ALIASES.get(token)
        if alias:
            return alias
    if "ceramica" in normalized:
        return "Cerámicas"
    return None


def apply_material_note_to_folio(
    folio: dict,
    question: dict,
    answer_text: str,
) -> Tuple[dict, bool]:
    """Append a material note to the target piece comments without closing the question."""
    note = resolve_material_note(answer_text)
    if not note:
        return {}, False
    piece_id = question.get("piece_id")
    if not piece_id:
        return {}, False
    pieces = [dict(p) for p in (folio.get("pieces") or [])]
    for piece in pieces:
        if str(piece.get("piece_id")) != str(piece_id):
            continue
        existing = (piece.get("comments") or "").strip()
        if note.lower() in existing.lower():
            return {"pieces": pieces}, True
        piece["comments"] = f"{existing} · {note}".strip(" · ") if existing else note
        return {"pieces": pieces}, True
    return {}, False


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
                piece["position_standardized"] = True
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
                piece["position_standardized"] = True
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
