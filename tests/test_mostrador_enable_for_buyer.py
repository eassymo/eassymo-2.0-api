from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import WhatsappClarificationService as clarify


def _q(qid, severity, path="vehicle.engine", **extra):
    return {
        "id": qid,
        "path": path,
        "prompt": f"prompt {qid}",
        "copy_text": f"copy {qid}",
        "severity": severity,
        "status": "open",
        **extra,
    }


def _draft(folio_id, questions=None, **extra):
    return {
        "_id": folio_id,
        "origin_group_id": "shop-1",
        "status": "draft",
        "whatsapp_pending_questions": questions or [],
        **extra,
    }


# ---- share readiness -------------------------------------------------------


def test_acknowledged_warning_stops_blocking_the_buyer():
    warning = _q("w", "warning", path="piece:p1.position")
    assert clarify.folio_share_ready({"whatsapp_pending_questions": [warning]}) is False
    warning["acknowledged_at"] = "2026-10-26T12:00:00Z"
    assert clarify.folio_share_ready({"whatsapp_pending_questions": [warning]}) is True


def test_critical_stays_blocking_even_with_an_acknowledgment_stamp():
    critical = _q("c", "critical", path="vehicle.year", acknowledged_at="2026-10-26T12:00:00Z")
    assert clarify.question_acknowledged(critical) is False
    assert clarify.folio_share_ready({"whatsapp_pending_questions": [critical]}) is False


# ---- enable_for_buyer ------------------------------------------------------


@pytest.fixture
def svc():
    with patch("app.dependencies.group_auth.assert_group_membership") as member, patch(
        "app.services.MostradorFolioService.folioRepository"
    ) as repo, patch("app.services.MostradorFolioService.mark_customer_ready") as ready:
        from app.services import MostradorFolioService as service

        yield service, repo, ready, member


def test_clean_draft_enables_without_acknowledgment(svc):
    service, repo, ready, member = svc
    repo.find_by_id.return_value = _draft("a")

    out = service.enable_for_buyer(["a"], acknowledged=False, caller_uid="seller")

    assert out == {"results": [{"folio_id": "a", "status": "enabled"}]}
    member.assert_called_once_with("seller", "shop-1")
    ready.assert_called_once_with("a")
    repo.edit.assert_not_called()


def test_warnings_require_the_acknowledgment_and_write_nothing_without_it(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.side_effect = lambda fid: {
        "a": _draft("a"),
        "b": _draft("b", [_q("w", "warning", path="piece:p.position")]),
    }[fid]

    with pytest.raises(HTTPException) as err:
        service.enable_for_buyer(["a", "b"], acknowledged=False, caller_uid="seller")

    assert err.value.status_code == 400
    ready.assert_not_called()
    repo.edit.assert_not_called()


def test_info_also_needs_the_acknowledgment(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.return_value = _draft("a", [_q("i", "info")])
    with pytest.raises(HTTPException) as err:
        service.enable_for_buyer(["a"], acknowledged=False, caller_uid="seller")
    assert err.value.status_code == 400
    ready.assert_not_called()


def test_acknowledged_enable_stamps_each_open_question_then_marks_ready(svc):
    service, repo, ready, _ = svc
    answered = {**_q("old", "warning"), "status": "answered"}
    repo.find_by_id.return_value = _draft(
        "a", [_q("w", "warning", path="piece:p.position"), _q("i", "info"), answered]
    )

    out = service.enable_for_buyer(["a"], acknowledged=True, caller_uid="seller")

    assert out["results"] == [{"folio_id": "a", "status": "enabled"}]
    patch_doc = repo.edit.call_args.args[1]
    stamped = {q["id"]: q for q in patch_doc["whatsapp_pending_questions"]}
    assert stamped["w"]["acknowledged_at"] is not None
    assert stamped["i"]["acknowledged_at"] is not None
    assert "acknowledged_at" not in stamped["old"]
    ready.assert_called_once_with("a")


def test_critical_draft_is_skipped_and_reported_while_the_rest_enable(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.side_effect = lambda fid: {
        "ok": _draft("ok", [_q("w", "warning", path="piece:p.position")]),
        "bad": _draft("bad", [_q("c", "critical", path="vehicle.year"), _q("w2", "warning")]),
    }[fid]

    out = service.enable_for_buyer(["ok", "bad"], acknowledged=True, caller_uid="seller")

    assert out["results"] == [
        {"folio_id": "ok", "status": "enabled"},
        {"folio_id": "bad", "status": "blocked", "blocked_by": ["copy c"]},
    ]
    ready.assert_called_once_with("ok")
    assert [call.args[0] for call in repo.edit.call_args_list] == ["ok"]


def test_blocked_draft_alone_does_not_demand_an_acknowledgment(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.return_value = _draft("bad", [_q("c", "critical", path="vehicle.year")])
    out = service.enable_for_buyer(["bad"], acknowledged=False, caller_uid="seller")
    assert out["results"][0]["status"] == "blocked"
    ready.assert_not_called()


def test_already_enabled_draft_is_left_alone(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.return_value = _draft("a", [_q("w", "warning")], customer_ready=True)
    out = service.enable_for_buyer(["a"], acknowledged=False, caller_uid="seller")
    assert out["results"] == [{"folio_id": "a", "status": "already_enabled"}]
    ready.assert_not_called()
    repo.edit.assert_not_called()


def test_other_shop_cannot_enable_a_draft(svc):
    service, repo, ready, member = svc
    repo.find_by_id.return_value = _draft("a")
    member.side_effect = HTTPException(status_code=403, detail="nope")
    with pytest.raises(HTTPException) as err:
        service.enable_for_buyer(["a"], acknowledged=True, caller_uid="intruder")
    assert err.value.status_code == 403
    ready.assert_not_called()


def test_missing_folio_and_empty_selection_are_rejected(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.return_value = None
    with pytest.raises(HTTPException) as missing:
        service.enable_for_buyer(["nope"], acknowledged=True, caller_uid="seller")
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as empty:
        service.enable_for_buyer([], acknowledged=True, caller_uid="seller")
    assert empty.value.status_code == 400


def test_duplicate_ids_are_enabled_once(svc):
    service, repo, ready, _ = svc
    repo.find_by_id.return_value = _draft("a")
    service.enable_for_buyer(["a", "a", " a "], acknowledged=False, caller_uid="seller")
    ready.assert_called_once_with("a")


def test_sibling_summary_exposes_acknowledged_and_ready_flags():
    from app.services import MostradorFolioService as service

    doc = _draft("a", [_q("w", "warning", acknowledged_at="2026-10-26T12:00:00Z")])
    alerts = service._alert_payloads(doc)
    assert alerts == [
        {"id": "w", "severity": "warning", "copy_text": "copy w", "acknowledged": True}
    ]
