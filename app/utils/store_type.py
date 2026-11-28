"""Census and group store types use opposite numbers. Convert here, never inline.

- Census / directory `Entity_Type` and role `entity_types`: 1 = Refaccionaria, 2 = Taller.
- Group `type` / `group_store_type` / `group_role` (`GroupRole`): 1 = BUYER (Taller), 2 = SELLER (Refaccionaria).
"""
from typing import Any, Optional

from app.schemas.Groups import GroupRole

CENSUS_REFACCIONARIA = 1
CENSUS_TALLER = 2

_GROUP_TO_CENSUS = {
    GroupRole.SELLER.value: CENSUS_REFACCIONARIA,
    GroupRole.BUYER.value: CENSUS_TALLER,
}
_CENSUS_TO_GROUP = {census: group for group, census in _GROUP_TO_CENSUS.items()}


def _as_int(value: Any) -> Optional[int]:
    """1, 2, "1", "2" (and BSON doubles 1.0, 2.0) are the shapes stored for these fields. Anything else is unknown."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def group_type_to_census_type(group_type: Any) -> Optional[int]:
    """Group type (1 buyer / 2 seller) to census Entity_Type (1 refa / 2 taller); None when unknown."""
    return _GROUP_TO_CENSUS.get(_as_int(group_type))


def census_type_to_group_type(entity_type: Any) -> Optional[int]:
    """Census Entity_Type (1 refa / 2 taller) to group type (1 buyer / 2 seller); None when unknown."""
    return _CENSUS_TO_GROUP.get(_as_int(entity_type))
