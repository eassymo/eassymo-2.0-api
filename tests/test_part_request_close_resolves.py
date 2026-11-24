"""Closing a request instead of choosing settles the 'choose another offer' decision (review focus 5)."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import NotificationService, PartRequestService as svc, PickupCodeService

DOC = {"_id": "req-1", "creatorGroup": "buyer-1", "isActive": True, "last_cancellation": {"order_id": "o1"}}


def _run(uid="buyer-uid", member=True, doc=DOC):
    with patch.object(svc.partRequestRepository, "find_one_by_id", return_value=dict(doc) if doc else None), \
         patch.object(svc.partRequestRepository, "edit_part_request") as edit, \
         patch.object(PickupCodeService, "_user_in_group", return_value=member), \
         patch.object(NotificationService, "resolve_decisions") as resolve:
        result = None
        try:
            result = svc.close_part_request("req-1", uid)
        finally:
            _run.edit, _run.resolve = edit, resolve
    return result


def test_close_resolves_decision_and_unsets_last_cancellation():
    _run()
    data = _run.edit.call_args.args[1]
    assert _run.edit.call_args.args[0] == "req-1"
    assert data["isActive"] is False and data["last_cancellation"] is None
    _run.resolve.assert_called_once_with("request:req-1:choose")


def test_only_the_buyer_group_can_close():
    with pytest.raises(HTTPException) as exc:
        _run(member=False)
    assert exc.value.status_code == 403
    _run.edit.assert_not_called()


def test_missing_request_is_404():
    with pytest.raises(HTTPException) as exc:
        _run(doc=None)
    assert exc.value.status_code == 404
