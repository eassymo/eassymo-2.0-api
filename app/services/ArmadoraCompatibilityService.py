from typing import Any, Dict, List, Optional

from app.repositories import GroupConfigRepository as groupConfigRepository
from app.utils.armadora_names import normalize_armadora_name


def _build_exclusion_reason(selected: List[Dict[str, Any]], vehicle_maker: str) -> str:
    names = [
        str(item.get("ensambladoraNombre", "")).strip()
        for item in selected
        if isinstance(item, dict) and item.get("ensambladoraNombre")
    ]
    brands = ", ".join(names[:8])
    if len(names) > 8:
        brands += f" (+{len(names) - 8} más)"
    vehicle_part = (
        f" Vehículo: {vehicle_maker.strip()}."
        if vehicle_maker and vehicle_maker.strip()
        else ""
    )
    return f"Modo exclusivo — esta tienda solo atiende: {brands}.{vehicle_part}"


def evaluate_group(
    group_id: str,
    config_doc: Optional[Dict[str, Any]],
    vehicle_maker: Optional[str],
) -> Dict[str, Any]:
    armadoras = (config_doc or {}).get("armadoras") or {}
    is_exclusive = bool(armadoras.get("is_exclusive"))
    selected = armadoras.get("selected") or []

    if not is_exclusive:
        return {"group_id": group_id, "compatible": True}

    maker = (vehicle_maker or "").strip()
    if not maker:
        return {"group_id": group_id, "compatible": True}

    maker_key = normalize_armadora_name(maker)
    selected_keys = {
        normalize_armadora_name(str(item.get("ensambladoraNombre", "")))
        for item in selected
        if isinstance(item, dict) and item.get("ensambladoraNombre")
    }
    selected_keys.discard("")

    if maker_key in selected_keys:
        return {"group_id": group_id, "compatible": True}

    selected_armadoras = [
        {
            "ensambladoraId": int(item.get("ensambladoraId") or 0),
            "ensambladoraNombre": str(item.get("ensambladoraNombre") or ""),
        }
        for item in selected
        if isinstance(item, dict)
    ]

    return {
        "group_id": group_id,
        "compatible": False,
        "reason": _build_exclusion_reason(selected, maker),
        "selected_armadoras": selected_armadoras,
    }


def evaluate_bulk(
    group_ids: List[str], vehicle_maker: Optional[str]
) -> Dict[str, Any]:
    unique_ids: List[str] = []
    seen: set[str] = set()
    for group_id in group_ids or []:
        normalized_id = str(group_id).strip()
        if not normalized_id or normalized_id in seen:
            continue
        seen.add(normalized_id)
        unique_ids.append(normalized_id)

    configs = groupConfigRepository.find_by_group_ids(unique_ids)
    compatible: List[str] = []
    excluded: List[Dict[str, Any]] = []

    for group_id in unique_ids:
        result = evaluate_group(group_id, configs.get(group_id), vehicle_maker)
        if result.get("compatible"):
            compatible.append(group_id)
        else:
            excluded.append(
                {
                    "group_id": group_id,
                    "reason": result["reason"],
                    "selected_armadoras": result.get("selected_armadoras", []),
                }
            )

    return {"compatible": compatible, "excluded": excluded}


def filter_compatible_group_ids(
    group_ids: List[str], vehicle_maker: Optional[str]
) -> List[str]:
    return evaluate_bulk(group_ids, vehicle_maker)["compatible"]
