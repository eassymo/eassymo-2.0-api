from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.WhatsappIntakeVerificationService import (
    WhatsappIntakeVerificationService,
    _hash_token,
)

MODULE = "app.services.WhatsappIntakeVerificationService"
ROLE_COPY = "Tu rol en esta tienda no permite usar WhatsApp POS."
DISABLED_COPY = "El dueño desactivó tu WhatsApp en esta tienda."
CONFLICT_COPY = "Este WhatsApp ya está vinculado a otra cuenta."


@pytest.fixture
def mocks():
    names = [
        "verify_repo",
        "link_repo",
        "userRepository",
        "can",
        "WhatsappService",
        "group_auth",
        "groupRepository",
    ]
    patchers = {n: patch(f"{MODULE}.{n}") for n in names}
    m = SimpleNamespace(**{n: p.start() for n, p in patchers.items()})
    m.userRepository.find_one.return_value = {"uid": "uid-1", "name": "Ian"}
    m.verify_repo.find_open.return_value = None
    m.verify_repo.count_distinct_phones.return_value = 0
    m.verify_repo.list_starts_since.return_value = []
    m.link_repo.find.return_value = None
    m.link_repo.find_any_by_phone.return_value = []
    m.link_repo.list_by_uid.return_value = []
    m.can.return_value = True
    m.group_auth.user_belongs_to_group.return_value = True
    m.groupRepository.find_by_id.return_value = {"name": "Tienda A"}
    m.WhatsappService.return_value.send_template_message.return_value = {"message_sid": "SM1"}
    yield m
    for p in patchers.values():
        p.stop()


def _service():
    service = WhatsappIntakeVerificationService()
    service.template_sid = "HXtest"
    return service


def _pending(token="tok", group_id="g1", uid="uid-1"):
    return {
        "uid": uid,
        "group_id": group_id,
        "phone": "+5217779313704",
        "token_hash": _hash_token(token),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "consumed_at": None,
    }


def test_start_scopes_pending_and_limits_to_group(mocks):
    _service().start("uid-1", "g1", "7779313704")

    assert mocks.verify_repo.find_open.call_args.args[:2] == ("uid-1", "g1")
    assert mocks.verify_repo.supersede_open.call_args.args == ("uid-1", "g1")
    assert mocks.verify_repo.count_distinct_phones.call_args.args[:2] == ("uid-1", "g1")
    assert mocks.verify_repo.insert.call_args.args[0]["group_id"] == "g1"
    mocks.can.assert_called_with("uid-1", "g1", "whatsapp.create_draft")


def test_start_returns_unlinked_shape(mocks):
    result = _service().start("uid-1", "g1", "7779313704")
    assert result["linked"] is False
    assert result["masked_phone"] == "***3704"
    assert result["message"]


def test_start_rejects_role_without_permission(mocks):
    mocks.can.return_value = False
    with pytest.raises(HTTPException) as exc:
        _service().start("uid-1", "g1", "7779313704")
    assert exc.value.status_code == 403
    assert exc.value.detail == ROLE_COPY
    mocks.WhatsappService.return_value.send_template_message.assert_not_called()


def test_start_rejects_disabled_link(mocks):
    mocks.link_repo.find.return_value = {"uid": "uid-1", "group_id": "g1", "status": "disabled"}
    with pytest.raises(HTTPException) as exc:
        _service().start("uid-1", "g1", "7779313704")
    assert exc.value.status_code == 403
    assert exc.value.detail == DISABLED_COPY
    mocks.WhatsappService.return_value.send_template_message.assert_not_called()


def test_start_conflicts_when_number_linked_to_other_uid(mocks):
    mocks.link_repo.find_any_by_phone.return_value = [
        {"uid": "uid-2", "group_id": "g9", "phone": "+5217779313704"}
    ]
    with pytest.raises(HTTPException) as exc:
        _service().start("uid-1", "g1", "7779313704")
    assert exc.value.status_code == 409
    assert exc.value.detail == CONFLICT_COPY


def test_start_conflicts_with_legacy_pos_whatsapp_of_other_uid(mocks):
    def find_one(query):
        if "pos_whatsapp" in query:
            return {"uid": "uid-2", "pos_whatsapp": "+5217779313704"}
        return {"uid": "uid-1", "name": "Ian"}

    mocks.userRepository.find_one.side_effect = find_one
    with pytest.raises(HTTPException) as exc:
        _service().start("uid-1", "g1", "7779313704")
    assert exc.value.status_code == 409


def test_start_same_number_in_second_group_still_requires_confirmation(mocks):
    own = {"uid": "uid-1", "group_id": "g2", "phone": "+5217779313704"}
    mocks.link_repo.find_any_by_phone.return_value = [own]
    mocks.link_repo.list_by_uid.return_value = [own]
    result = _service().start("uid-1", "g1", "7779313704")
    assert result["linked"] is False
    mocks.link_repo.upsert.assert_not_called()
    assert mocks.WhatsappService.return_value.send_template_message.called


def test_start_unknown_user_is_404(mocks):
    mocks.userRepository.find_one.return_value = None
    with pytest.raises(HTTPException) as exc:
        _service().start("uid-1", "g1", "7779313704")
    assert exc.value.status_code == 404


def test_confirm_upserts_link_for_token_group_and_skips_user_write(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g7")

    result = _service().confirm("uid-1", "tok")

    args = mocks.link_repo.upsert.call_args.args
    assert args[:3] == ("uid-1", "g7", "+5217779313704")
    assert isinstance(args[3], datetime)
    mocks.userRepository.update_user.assert_not_called()
    mocks.verify_repo.mark_consumed.assert_called_once()
    assert result["pos_whatsapp"] == "+5217779313704"
    assert result["group_id"] == "g7"
    assert result["link_status"] == "active"
    assert result["can_use"] is True
    assert result["verified"] is True


def test_confirm_refuses_when_link_disabled_after_start(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g1")
    mocks.link_repo.find.return_value = {"uid": "uid-1", "group_id": "g1", "status": "disabled"}

    with pytest.raises(HTTPException) as exc:
        _service().confirm("uid-1", "tok")

    assert exc.value.status_code == 403
    assert exc.value.detail == DISABLED_COPY
    mocks.link_repo.upsert.assert_not_called()
    mocks.verify_repo.mark_consumed.assert_not_called()


def test_confirm_refuses_when_membership_lost(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g1")
    mocks.group_auth.user_belongs_to_group.return_value = False

    with pytest.raises(HTTPException) as exc:
        _service().confirm("uid-1", "tok")

    assert exc.value.status_code == 403
    mocks.link_repo.upsert.assert_not_called()


def test_confirm_refuses_when_role_revoked(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g1")
    mocks.can.return_value = False

    with pytest.raises(HTTPException) as exc:
        _service().confirm("uid-1", "tok")

    assert exc.value.status_code == 403
    assert exc.value.detail == ROLE_COPY
    mocks.link_repo.upsert.assert_not_called()


def test_confirm_refuses_when_number_taken_since_start(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g1")
    mocks.link_repo.find_any_by_phone.return_value = [{"uid": "uid-2", "phone": "+5217779313704"}]

    with pytest.raises(HTTPException) as exc:
        _service().confirm("uid-1", "tok")

    assert exc.value.status_code == 409
    mocks.link_repo.upsert.assert_not_called()


def test_preview_returns_group_name(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g7")

    result = _service().preview("uid-1", "tok")

    assert result["group_id"] == "g7"
    assert result["group_name"] == "Tienda A"
    assert result["masked_phone"] == "***3704"
    mocks.groupRepository.find_by_id.assert_called_with("g7")


def test_preview_refuses_when_membership_lost(mocks):
    mocks.verify_repo.find_by_token_hash.return_value = _pending("tok", "g7")
    mocks.group_auth.user_belongs_to_group.return_value = False
    with pytest.raises(HTTPException) as exc:
        _service().preview("uid-1", "tok")
    assert exc.value.status_code == 403


def test_status_reports_link_state_can_use_and_suggested_phone(mocks):
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 6, 1, tzinfo=timezone.utc)
    mocks.link_repo.find.return_value = {
        "uid": "uid-1",
        "group_id": "g1",
        "phone": "+5217779313704",
        "status": "active",
        "verified_at": newer,
    }
    mocks.link_repo.list_by_uid.return_value = [
        {"group_id": "g1", "phone": "+5217779313704", "verified_at": newer},
        {"group_id": "g2", "phone": "+5217779000000", "verified_at": older},
        {"group_id": "g3", "phone": "+5217779222222", "verified_at": datetime(2026, 3, 1, tzinfo=timezone.utc)},
    ]

    result = _service().get_status("uid-1", "g1")

    assert result["group_id"] == "g1"
    assert result["group_name"] == "Tienda A"
    assert result["link_status"] == "active"
    assert result["can_use"] is True
    assert result["pos_whatsapp"] == "+5217779313704"
    assert result["pos_whatsapp_verified_at"] == newer.isoformat()
    assert result["verified"] is True
    assert result["suggested_phone"] == "+5217779222222"
    assert result["pending"] is None


def test_status_without_link(mocks):
    mocks.can.return_value = False
    result = _service().get_status("uid-1", "g1")
    assert result["link_status"] is None
    assert result["can_use"] is False
    assert result["verified"] is False
    assert result["pos_whatsapp"] is None
    assert result["suggested_phone"] is None


def test_status_reports_disabled_link(mocks):
    mocks.link_repo.find.return_value = {
        "phone": "+5217779313704",
        "status": "disabled",
        "verified_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    result = _service().get_status("uid-1", "g1")
    assert result["link_status"] == "disabled"


@pytest.mark.parametrize("method", ["preview", "confirm"])
def test_token_without_group_id_is_treated_as_expired(mocks, method):
    pending = _pending("tok", "g1")
    del pending["group_id"]
    mocks.verify_repo.find_by_token_hash.return_value = pending

    with pytest.raises(HTTPException) as exc:
        getattr(_service(), method)("uid-1", "tok")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Esta confirmación venció. Pide un nuevo mensaje."
    mocks.link_repo.upsert.assert_not_called()
