"""Viewer-aware chat message display for part-request multi-seller chats."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional

ChatPartyType = Literal["buyer", "self", "other_seller", "named_seller"]
ChatEntityType = Literal["request", "order"]


def _norm(value: Optional[str]) -> str:
    return str(value or "").strip()


def classify_message_party(
    message_group_id: Optional[str],
    creator_group_id: Optional[str],
    viewer_group_id: Optional[str],
) -> ChatPartyType:
    msg_group = _norm(message_group_id)
    creator = _norm(creator_group_id)
    viewer = _norm(viewer_group_id)

    if creator and msg_group == creator:
        return "buyer"
    if viewer and msg_group == viewer:
        return "self"
    return "other_seller"


def _anonymous_key(group_id: str) -> str:
    digest = hashlib.sha256(group_id.encode("utf-8")).hexdigest()
    return digest[:8]


def _mask_message_for_seller_viewer(
    message: Dict[str, Any],
    creator_group_id: str,
    viewer_group_id: str,
) -> Dict[str, Any]:
    out = dict(message)
    meta = dict(out.get("metaData") or {})
    party = classify_message_party(
        out.get("groupId"),
        creator_group_id,
        viewer_group_id,
    )

    if party == "other_seller":
        out["partyType"] = "anonymous_seller"
        out["anonymousKey"] = _anonymous_key(_norm(out.get("groupId")))
        out["metaData"] = {
            **meta,
            "groupName": "",
            "senderName": "",
        }
        return out

    if party == "buyer":
        out["partyType"] = "buyer"
        out["metaData"] = {
            **meta,
            "groupName": "",
            "senderName": meta.get("senderName") or "",
        }
        return out

    out["partyType"] = "self"
    return out


def mask_chat_for_viewer(
    chat_json: Optional[Dict[str, Any]],
    *,
    entity_type: ChatEntityType,
    creator_group_id: Optional[str],
    viewer_group_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not chat_json:
        return chat_json

    creator = _norm(creator_group_id)
    viewer = _norm(viewer_group_id)

    if entity_type != "request" or not creator or not viewer or viewer == creator:
        return chat_json

    out = dict(chat_json)
    messages: List[Dict[str, Any]] = []
    for message in out.get("messages") or []:
        if not isinstance(message, dict):
            continue
        messages.append(_mask_message_for_seller_viewer(message, creator, viewer))
    out["messages"] = messages
    return out
