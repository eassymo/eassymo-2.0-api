"""Two numberings meet here and are inverted against each other:

- census / directory `Entity_Type` and role `entity_types`: 1 = Refaccionaria, 2 = Taller
- group `type` / `group_store_type` / `group_role`: 1 = BUYER (Taller), 2 = SELLER (Refaccionaria)
"""
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from app.schemas.Groups import GroupRole, GroupSchema
from app.utils.store_type import (
    CENSUS_REFACCIONARIA,
    CENSUS_TALLER,
    census_type_to_group_type,
    group_type_to_census_type,
)


# ── mapper ──────────────────────────────────────────────────────────────────

def test_group_role_names_match_their_values():
    assert GroupRole.BUYER.value == 1
    assert GroupRole.SELLER.value == 2


@pytest.mark.parametrize("group_type,census", [
    (GroupRole.SELLER.value, CENSUS_REFACCIONARIA),
    (GroupRole.BUYER.value, CENSUS_TALLER),
    ("2", CENSUS_REFACCIONARIA),
    ("1", CENSUS_TALLER),
    (2.0, CENSUS_REFACCIONARIA),  # BSON doubles come back as float
    (None, None), (0, None), (3, None), ("x", None), (True, None), (2.5, None),
])
def test_group_type_to_census_type(group_type, census):
    assert group_type_to_census_type(group_type) == census


@pytest.mark.parametrize("census,group_type", [
    (CENSUS_REFACCIONARIA, GroupRole.SELLER.value),
    (CENSUS_TALLER, GroupRole.BUYER.value),
    ("1", GroupRole.SELLER.value),
    ("2", GroupRole.BUYER.value),
    (1.0, GroupRole.SELLER.value),
    (None, None), (3, None), (4, None), ("Refa", None), (False, None), (1.5, None),
])
def test_census_type_to_group_type(census, group_type):
    assert census_type_to_group_type(census) == group_type


def test_round_trip_is_identity_for_known_values():
    for group_type in (1, 2):
        assert census_type_to_group_type(group_type_to_census_type(group_type)) == group_type


# ── GroupService.create_group: manual stores get a census row ────────────────

def _create_manual_group(group_type):
    from app.services import GroupService as svc

    inserted = MagicMock(inserted_id=ObjectId())
    with patch.object(svc, "groupRepository") as groups, \
         patch.object(svc, "userRepository"), \
         patch.object(svc, "listRepository") as lists, \
         patch.object(svc, "censusRepository") as census:
        groups.insert.return_value = inserted
        lists.find.return_value = [{"_id": "existing"}]
        svc.create_group(
            GroupSchema(name="Mi tienda", type=group_type, city="León", state="Gto"),
            censusReference=None,
            user_id="u1",
        )
    return census.insert.call_args.args[0]


def test_manual_refaccionaria_is_written_to_census_as_refaccionaria():
    row = _create_manual_group(GroupRole.SELLER.value)
    assert row["Entity_Type"] == CENSUS_REFACCIONARIA


def test_manual_taller_is_written_to_census_as_taller():
    row = _create_manual_group(GroupRole.BUYER.value)
    assert row["Entity_Type"] == CENSUS_TALLER


def test_manual_group_with_unknown_type_leaves_census_type_empty():
    assert _create_manual_group(3)["Entity_Type"] is None


def test_claimed_group_keeps_the_directory_type():
    from app.services import GroupService as svc

    census_id = str(ObjectId())
    with patch.object(svc, "groupRepository") as groups, \
         patch.object(svc, "userRepository"), \
         patch.object(svc, "listRepository") as lists, \
         patch.object(svc, "censusRepository") as census:
        groups.insert.return_value = MagicMock(inserted_id=ObjectId())
        lists.find.return_value = [{"_id": "existing"}]
        census.find_by_id.return_value = {"Entity_Name": "Refa", "Entity_Type": 1}
        svc.create_group(GroupSchema(name="Refa Sol", type=2), censusReference=census_id, user_id="u1")
    census.insert.assert_not_called()
    (row_id, update), _ = census.update.call_args
    assert row_id == census_id and "Entity_Type" not in update


# ── authz.role_fits_group: role entity_types are census numbers ──────────────

GID = str(ObjectId())


def _fits(group_type, entity_types):
    from app.services import authz

    role = {"value": "r", "grants": ["offers.create"], "entity_types": entity_types}
    with patch.object(authz.RolesRepository, "find_by_value", return_value=role), \
         patch.object(authz.groupRepository, "find_by_id", return_value={"_id": GID, "type": group_type}):
        fitted, _ = authz.role_fits_group(GID, "r")
    return fitted is not None


@pytest.mark.parametrize("group_type,entity_types,fits", [
    (GroupRole.SELLER.value, ["1"], True),    # Refaccionaria gets "(Refa)" roles
    (GroupRole.SELLER.value, ["2"], False),   # ... but not "(Taller)" roles
    (GroupRole.BUYER.value, ["2"], True),     # Taller gets "(Taller)" / Mecánico roles
    (GroupRole.BUYER.value, ["1"], False),
    ("2", ["1"], True),                       # type stored as a string
    (GroupRole.SELLER.value, [1], True),      # entity_types stored as numbers
    (GroupRole.BUYER.value, ["1", "2"], True),
    (GroupRole.SELLER.value, [], True),       # empty = fits every group
    (3, ["1", "2"], False),                   # unknown group type fits no typed role
    (None, ["1"], False),
    (None, [], True),
])
def test_role_fit_compares_census_numbers(group_type, entity_types, fits):
    assert _fits(group_type, entity_types) is fits
