"""WhatsappSellerIdentityService.resolve over WhatsappLinks + can() (spec 5.4)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.WhatsappSellerIdentityService import WhatsappSellerIdentityService
from app.utils.phone_normalize import phone_lookup_variants

MOD = "app.services.WhatsappSellerIdentityService"
PHONE = "+5217779313704"

UNLINKED_COPY = (
    "No encontramos tu WhatsApp en Eassymo. En la app ve a Mi cuenta → WhatsApp para POS, "
    "elige tu tienda, confirma tu número y reenvía tu mensaje."
)
NO_ACCESS_COPY = (
    "Tu WhatsApp está vinculado, pero no tienes acceso a WhatsApp POS en ninguna tienda. "
    "Pide acceso al dueño de la tienda."
)
AMBIGUOUS_COPY = "No pudimos identificar tu cuenta. Contacta a soporte."

GROUP_NAMES = {"g1": "Tienda A", "g2": "Tienda B", "g3": "Tienda C"}
TWO_CANDIDATES = [
    {"group_id": "g1", "name": "Tienda A"},
    {"group_id": "g2", "name": "Tienda B"},
]


def _link(group_id, uid="uid-1", status="active", phone=PHONE):
    return {"uid": uid, "group_id": group_id, "phone": phone, "status": status}


@pytest.fixture
def env():
    with patch(f"{MOD}.link_repo") as link_repo, patch(f"{MOD}.can") as can, patch(
        f"{MOD}.groupRepository"
    ) as group_repo, patch(f"{MOD}.pending_repo") as pending:
        link_repo.find_any_by_phone.return_value = []
        can.return_value = True
        group_repo.find_many_by_string_ids.side_effect = lambda ids, *a, **k: [
            {"_id": gid, "name": GROUP_NAMES[gid]} for gid in ids if gid in GROUP_NAMES
        ]
        pending.get_by_phone.return_value = None
        pending.claim_identity_prompt.return_value = True
        yield SimpleNamespace(link_repo=link_repo, can=can, group_repo=group_repo, pending=pending)


def _two_links(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1"), _link("g2")]


def _sticky_pending(**overrides):
    base = {
        "selected_group_id": "g1",
        "candidates": list(TWO_CANDIDATES),
        "creator_uid": "uid-1",
    }
    base.update(overrides)
    return base


def _resolve(body="", inbound_id=None, phone=PHONE):
    return WhatsappSellerIdentityService().resolve(phone, body, inbound_id)


# --- Ported from tests/test_whatsapp_intake.py (data source re-pointed to links) ---


def test_identity_pending_link_when_user_not_verified(env):
    result = _resolve("Jetta 2015")

    assert result.status == "pending_link"
    assert "Mi cuenta" in (result.message or "")
    env.pending.upsert_pending.assert_called_once()


def test_identity_pending_selection_for_multiple_groups(env):
    _two_links(env)

    result = _resolve("filtro de aire")

    assert result.status == "pending_selection"
    assert result.candidates is not None
    assert len(result.candidates) == 2


def test_identity_resolves_single_group(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1")]

    result = _resolve("Jetta 2015, filtro")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    env.pending.clear.assert_called_once()


def test_identity_resolves_store_selection_with_just_selected(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = {
        "candidates": list(TWO_CANDIDATES),
        "creator_uid": "uid-1",
    }

    result = _resolve("1")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    assert result.group_name == "Tienda A"
    assert result.just_selected is True
    env.pending.set_selected_store.assert_called_once()


@pytest.mark.parametrize("command", ["cambiar", "menu", "menú", "atras", "atrás"])
def test_change_store_commands_clear_selection_and_resend_list(env, command):
    _two_links(env)
    env.pending.get_by_phone.return_value = _sticky_pending()

    result = _resolve(command)

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    assert "Tienda B" in (result.message or "")
    env.pending.clear_selected_store.assert_called_once()


def test_sticky_store_with_recent_activity_still_resolves_and_touches(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    result = _resolve("balatas delanteras")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    assert result.group_name == "Tienda A"
    env.pending.touch_last_inbound.assert_called_once()


def test_sticky_store_expires_after_inactivity_and_reprompts_selection(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=13),
    )

    result = _resolve("balatas delanteras")

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    assert "Tienda B" in (result.message or "")
    env.pending.clear_selected_store.assert_called_once()
    env.pending.touch_last_inbound.assert_not_called()


def test_sticky_store_without_last_inbound_starts_clock_without_expiring(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = _sticky_pending()

    result = _resolve("balatas delanteras")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    env.pending.clear_selected_store.assert_not_called()
    env.pending.touch_last_inbound.assert_called_once()


def test_change_store_still_works_with_recent_activity(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    result = _resolve("cambiar")

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    env.pending.clear_selected_store.assert_called_once()
    env.pending.touch_last_inbound.assert_not_called()


def test_sticky_store_concurrent_expiry_only_first_prompt_sends_list(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=13),
    )
    env.pending.claim_identity_prompt.return_value = False

    result = _resolve("2020")

    assert result.status == "pending_selection"
    assert result.message is None
    env.pending.clear_selected_store.assert_called_once()
    env.pending.claim_identity_prompt.assert_called_once()
    env.pending.upsert_pending.assert_not_called()


def test_pending_selection_does_not_reprompt_for_content_burst(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = {
        "candidates": list(TWO_CANDIDATES),
        "creator_uid": "uid-1",
    }
    env.pending.claim_identity_prompt.return_value = False

    result = _resolve("Y también unas balatas delanteras")

    assert result.status == "pending_selection"
    assert result.message is None
    env.pending.upsert_pending.assert_not_called()
    env.pending.set_candidates.assert_not_called()


def test_pending_selection_reprompts_after_cooldown(env):
    _two_links(env)
    env.pending.get_by_phone.return_value = {
        "candidates": list(TWO_CANDIDATES),
        "creator_uid": "uid-1",
    }
    env.pending.claim_identity_prompt.return_value = True

    result = _resolve("Te encargo pa una koleos")

    assert result.status == "pending_selection"
    assert "Tienda A" in (result.message or "")
    assert "Tienda B" in (result.message or "")
    env.pending.claim_identity_prompt.assert_called_once()


# --- New behaviour: links + role access ---


def test_no_links_prompts_to_link_with_store_choice_in_copy(env):
    result = _resolve("Jetta 2015", inbound_id="in-1")

    assert result.status == "pending_link"
    assert result.message == UNLINKED_COPY
    env.pending.upsert_pending.assert_called_once_with(PHONE, [], "in-1")


def test_links_but_role_not_allowed_returns_no_access_copy(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1")]
    env.can.return_value = False

    result = _resolve("Jetta 2015")

    assert result.status == "pending_link"
    assert result.message == NO_ACCESS_COPY
    env.can.assert_called_once_with("uid-1", "g1", "whatsapp.create_draft")
    env.pending.clear.assert_not_called()


def test_no_access_copy_is_throttled(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1")]
    env.can.return_value = False
    env.pending.get_by_phone.return_value = _sticky_pending()
    env.pending.claim_identity_prompt.return_value = False

    result = _resolve("Jetta 2015")

    assert result.status == "pending_link"
    assert result.message is None
    env.pending.clear_selected_store.assert_called_once_with(PHONE)
    env.pending.set_candidates.assert_called_once_with(PHONE, [])
    env.pending.upsert_pending.assert_not_called()


def test_disabled_link_returns_no_access_copy(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1", status="disabled")]

    result = _resolve("Jetta 2015")

    assert result.status == "pending_link"
    assert result.message == NO_ACCESS_COPY
    env.can.assert_not_called()


def test_one_allowed_group_resolves_and_clears_pending(env):
    env.link_repo.find_any_by_phone.return_value = [
        _link("g1"),
        _link("g2", status="disabled"),
    ]
    env.pending.get_by_phone.return_value = _sticky_pending(selected_group_id="g2")

    result = _resolve("balatas")

    assert result.status == "resolved"
    assert result.group_id == "g1"
    assert result.group_name == "Tienda A"
    assert result.creator_uid == "uid-1"
    env.pending.clear.assert_called_once_with(PHONE)


def test_several_allowed_groups_list_only_permitted(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1"), _link("g2"), _link("g3")]
    env.can.side_effect = lambda uid, gid, perm: gid != "g2"

    result = _resolve("balatas", inbound_id="in-9")

    expected = [
        {"group_id": "g1", "name": "Tienda A"},
        {"group_id": "g3", "name": "Tienda C"},
    ]
    assert result.status == "pending_selection"
    assert result.candidates == expected
    assert result.creator_uid == "uid-1"
    assert "Tienda B" not in (result.message or "")
    assert "Tienda C" in (result.message or "")
    env.pending.upsert_pending.assert_called_once_with(PHONE, expected, "in-9")
    env.group_repo.find_many_by_string_ids.assert_called_once()
    assert sorted(env.group_repo.find_many_by_string_ids.call_args[0][0]) == ["g1", "g3"]


def test_sticky_group_no_longer_allowed_is_cleared(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g1"), _link("g2"), _link("g3")]
    env.can.side_effect = lambda uid, gid, perm: gid != "g1"
    env.pending.get_by_phone.return_value = _sticky_pending(
        last_inbound_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    result = _resolve("balatas")

    assert result.status == "pending_selection"
    assert result.group_id is None
    assert [c["group_id"] for c in result.candidates] == ["g2", "g3"]
    env.pending.clear_selected_store.assert_called_once_with(PHONE)
    env.pending.touch_last_inbound.assert_not_called()


def test_stale_stored_candidates_are_rewritten(env):
    env.link_repo.find_any_by_phone.return_value = [_link("g2"), _link("g3")]
    env.pending.get_by_phone.return_value = {
        "candidates": list(TWO_CANDIDATES),
        "creator_uid": "uid-1",
    }

    result = _resolve("2")

    fresh = [
        {"group_id": "g2", "name": "Tienda B"},
        {"group_id": "g3", "name": "Tienda C"},
    ]
    env.pending.set_candidates.assert_called_once_with(PHONE, fresh)
    env.pending.upsert_pending.assert_not_called()
    # The numbered choice indexes the fresh list, not the stale stored one.
    assert result.status == "resolved"
    assert result.group_id == "g3"
    env.pending.set_selected_store.assert_called_once_with(PHONE, "g3", "uid-1")


def test_two_uids_on_one_number_is_ambiguous(env):
    env.link_repo.find_any_by_phone.return_value = [
        _link("g1", uid="uid-1"),
        _link("g2", uid="uid-2"),
    ]

    with patch(f"{MOD}.logger") as logger:
        result = _resolve("balatas")

    assert result.status == "ambiguous"
    assert result.message == AMBIGUOUS_COPY
    assert result.group_id is None
    logger.error.assert_called_once()
    env.can.assert_not_called()
    env.pending.clear.assert_not_called()


@pytest.mark.parametrize("incoming", ["+527779313704", "+5217779313704", "7779313704"])
def test_number_format_variants_hit_same_link(env, incoming):
    stored = PHONE

    def find_any_by_phone(phone):
        # Mirror the real repository: query by the lookup variants of the normalized phone.
        assert stored in phone_lookup_variants(phone)
        return [_link("g1", phone=stored)]

    env.link_repo.find_any_by_phone.side_effect = find_any_by_phone

    result = _resolve("balatas", phone=incoming)

    assert result.status == "resolved"
    assert result.group_id == "g1"
    env.link_repo.find_any_by_phone.assert_called_once()


def test_link_to_deleted_group_is_dropped(env):
    env.link_repo.find_any_by_phone.return_value = [
        _link("g1"),
        _link("gone"),
        _link("g2"),
    ]

    result = _resolve("balatas")

    assert result.status == "pending_selection"
    assert result.candidates == TWO_CANDIDATES
    assert "Tienda A" in result.message and "Tienda B" in result.message


def test_is_entitled_requires_active_link_and_permission(env):
    service = WhatsappSellerIdentityService()

    env.link_repo.find.return_value = None
    assert service.is_entitled("uid-1", "g1") is False

    env.link_repo.find.return_value = _link("g1", status="disabled")
    assert service.is_entitled("uid-1", "g1") is False

    env.link_repo.find.return_value = _link("g1")
    env.can.return_value = False
    assert service.is_entitled("uid-1", "g1") is False

    env.can.return_value = True
    assert service.is_entitled("uid-1", "g1") is True
    env.link_repo.find.assert_called_with("uid-1", "g1")
    env.can.assert_called_with("uid-1", "g1", "whatsapp.create_draft")


def test_set_candidates_never_touches_last_inbound_at():
    from app.repositories import WhatsappPendingAssociationRepository as repo

    with patch.object(repo, "_col") as col:
        repo.set_candidates(PHONE, TWO_CANDIDATES)

    (filter_, update), kwargs = col.return_value.update_one.call_args
    assert filter_ == {"from_number": PHONE}
    assert set(update) == {"$set"}
    assert set(update["$set"]) == {"candidates", "updated_at"}
    assert update["$set"]["candidates"] == TWO_CANDIDATES
    assert not kwargs.get("upsert")
