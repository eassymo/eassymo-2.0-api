from typing import Any, Dict, List, Optional, Set, Tuple

from app.repositories import GroupConfigRepository as groupConfigRepository


def _normalize_requirements(
    part_categories: List[Dict[str, Any]],
) -> List[Tuple[int, int]]:
    seen: Set[str] = set()
    requirements: List[Tuple[int, int]] = []

    for item in part_categories or []:
        if not isinstance(item, dict):
            continue
        categoria_id = item.get("categoria_id")
        sub_categoria_id = item.get("sub_categoria_id")
        if categoria_id is None or sub_categoria_id is None:
            continue
        try:
            cat = int(categoria_id)
            sub = int(sub_categoria_id)
        except (TypeError, ValueError):
            continue
        key = f"{cat}:{sub}"
        if key in seen:
            continue
        seen.add(key)
        requirements.append((cat, sub))

    return requirements


def _build_coverage(selected: List[Dict[str, Any]]) -> Dict[int, Optional[Set[int]]]:
    coverage: Dict[int, Optional[Set[int]]] = {}

    for item in selected or []:
        if not isinstance(item, dict):
            continue
        categoria_id = item.get("categoriaId")
        if categoria_id is None:
            continue
        try:
            cat = int(categoria_id)
        except (TypeError, ValueError):
            continue

        sub_ids_raw = item.get("subCategoriaIds") or []
        if not sub_ids_raw:
            coverage[cat] = None
            continue

        sub_set: Set[int] = set()
        for sub_id in sub_ids_raw:
            try:
                sub_set.add(int(sub_id))
            except (TypeError, ValueError):
                continue
        coverage[cat] = sub_set

    return coverage


def _build_exclusion_reason(selected: List[Dict[str, Any]]) -> str:
    labels: List[str] = []
    for item in selected or []:
        if not isinstance(item, dict):
            continue
        cat_id = item.get("categoriaId")
        sub_ids = item.get("subCategoriaIds") or []
        if sub_ids:
            labels.append(f"categoría {cat_id} ({len(sub_ids)} subcategorías)")
        elif cat_id is not None:
            labels.append(f"categoría {cat_id}")

    summary = ", ".join(labels[:6])
    if len(labels) > 6:
        summary += f" (+{len(labels) - 6} más)"

    return (
        "Modo exclusivo — esta tienda solo atiende: "
        f"{summary or 'categorías seleccionadas'}."
    )


def _seller_covers_requirement(
    coverage: Dict[int, Optional[Set[int]]],
    categoria_id: int,
    sub_categoria_id: int,
) -> bool:
    if categoria_id not in coverage:
        return False

    allowed_subs = coverage[categoria_id]
    if allowed_subs is None:
        return True

    return sub_categoria_id in allowed_subs


def _part_to_category_payload(car_part: Any) -> Optional[Dict[str, Any]]:
    if not car_part or not isinstance(car_part, dict):
        return None

    categoria_id = car_part.get("categoriaId")
    sub_categoria_id = car_part.get("subCategoriaId")

    categoria = car_part.get("categoria")
    if categoria_id is None and isinstance(categoria, dict):
        categoria_id = categoria.get("categoriaId")

    sub_categoria = car_part.get("subCategoria")
    if sub_categoria_id is None and isinstance(sub_categoria, dict):
        sub_categoria_id = sub_categoria.get("subCategoriaId")

    if categoria_id is None or sub_categoria_id is None:
        return None

    try:
        return {
            "categoria_id": int(categoria_id),
            "sub_categoria_id": int(sub_categoria_id),
        }
    except (TypeError, ValueError):
        return None


def evaluate_group(
    group_id: str,
    config_doc: Optional[Dict[str, Any]],
    requirements: List[Tuple[int, int]],
) -> Dict[str, Any]:
    if not requirements:
        return {"group_id": group_id, "compatible": True}

    sistemas = (config_doc or {}).get("sistemas") or {}
    is_exclusive = bool(sistemas.get("is_exclusive"))
    selected = sistemas.get("selected") or []

    # Open mode with no saved specialization accepts every category.
    if not is_exclusive and not selected:
        return {"group_id": group_id, "compatible": True}

    coverage = _build_coverage(selected)

    for categoria_id, sub_categoria_id in requirements:
        if not _seller_covers_requirement(coverage, categoria_id, sub_categoria_id):
            selected_sistemas = [
                {
                    "categoriaId": int(item.get("categoriaId") or 0),
                    "subCategoriaIds": [
                        int(sub_id)
                        for sub_id in (item.get("subCategoriaIds") or [])
                        if sub_id is not None
                    ],
                }
                for item in selected
                if isinstance(item, dict)
            ]
            return {
                "group_id": group_id,
                "compatible": False,
                "reason": _build_exclusion_reason(selected),
                "selected_sistemas": selected_sistemas,
            }

    return {"group_id": group_id, "compatible": True}


def evaluate_bulk(
    group_ids: List[str],
    part_categories: List[Dict[str, Any]],
) -> Dict[str, Any]:
    requirements = _normalize_requirements(part_categories)

    unique_ids: List[str] = []
    seen: set[str] = set()
    for group_id in group_ids or []:
        normalized_id = str(group_id).strip()
        if not normalized_id or normalized_id in seen:
            continue
        seen.add(normalized_id)
        unique_ids.append(normalized_id)

    if not requirements:
        return {"compatible": unique_ids, "excluded": []}

    configs = groupConfigRepository.find_by_group_ids(unique_ids)
    compatible: List[str] = []
    excluded: List[Dict[str, Any]] = []

    for group_id in unique_ids:
        result = evaluate_group(group_id, configs.get(group_id), requirements)
        if result.get("compatible"):
            compatible.append(group_id)
        else:
            excluded.append(
                {
                    "group_id": group_id,
                    "reason": result["reason"],
                    "selected_sistemas": result.get("selected_sistemas", []),
                }
            )

    return {"compatible": compatible, "excluded": excluded}


def filter_compatible_group_ids(
    group_ids: List[str],
    part_categories: List[Dict[str, Any]],
) -> List[str]:
    return evaluate_bulk(group_ids, part_categories)["compatible"]


def filter_compatible_group_ids_for_part(
    group_ids: List[str],
    car_part: Any,
) -> List[str]:
    return evaluate_bulk_for_car_part(group_ids, car_part)["compatible"]


def evaluate_bulk_for_car_part(
    group_ids: List[str],
    car_part: Any,
) -> Dict[str, Any]:
    category_payload = _part_to_category_payload(car_part)
    if category_payload is None:
        unique_ids: List[str] = []
        seen: set[str] = set()
        for group_id in group_ids or []:
            normalized_id = str(group_id).strip()
            if not normalized_id or normalized_id in seen:
                continue
            seen.add(normalized_id)
            unique_ids.append(normalized_id)
        return {"compatible": unique_ids, "excluded": []}
    return evaluate_bulk(group_ids, [category_payload])
