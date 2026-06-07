from typing import Any, Dict

from app.repositories import GroupConfigRepository as groupConfigRepository
from app.schemas.GroupConfig import (
    ArmadorasConfigUpdate,
    GroupConfig,
    default_group_config,
)


def get_by_group_id(group_id: str) -> GroupConfig:
    doc = groupConfigRepository.find_by_group_id(group_id)
    if doc is None:
        return default_group_config(group_id)
    return GroupConfig(**doc)


def upsert_armadoras(
    group_id: str, payload: ArmadorasConfigUpdate
) -> GroupConfig:
    armadoras_payload: Dict[str, Any] = {
        "is_exclusive": payload.is_exclusive,
        "selected": [
            {
                "ensambladoraId": item.ensambladoraId,
                "ensambladoraNombre": item.ensambladoraNombre,
            }
            for item in payload.selected
        ],
    }
    doc = groupConfigRepository.upsert_armadoras(group_id, armadoras_payload)
    return GroupConfig(**doc)
