from typing import Any, Dict

from sqlalchemy.orm import Session

from app.repositories import GroupConfigRepository as groupConfigRepository
from app.services.CategoriasService import build_default_sistemas_payload
from app.schemas.GroupConfig import (
    ArmadorasConfigUpdate,
    GroupConfig,
    SistemasConfigUpdate,
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


def upsert_sistemas(
    group_id: str, payload: SistemasConfigUpdate
) -> GroupConfig:
    sistemas_payload: Dict[str, Any] = {
        "is_exclusive": payload.is_exclusive,
        "selected": [
            {
                "categoriaId": item.categoriaId,
                "subCategoriaIds": item.subCategoriaIds,
            }
            for item in payload.selected
        ],
    }
    doc = groupConfigRepository.upsert_sistemas(group_id, sistemas_payload)
    return GroupConfig(**doc)


def initialize_sistemas_for_new_group(group_id: str, mysql_db: Session) -> None:
    sistemas_payload = build_default_sistemas_payload(mysql_db)
    groupConfigRepository.upsert_sistemas(group_id, sistemas_payload)
