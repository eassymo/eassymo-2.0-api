"""Usage metering and enforcement inside the WhatsApp intake processor."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.schemas.WhatsappExtraction import (
    ExtractionIntent,
    ExtractionLine,
    ExtractionVehicle,
    WhatsappExtractionProposal,
)
from app.services.LlmExtractionService import LlmRateLimitError
from app.services.WhatsappUsageMessages import GUARD_NOTICE
from app.services.WhatsappUsageService import (
    UsageContext,
    UsageLimitReached,
    UsageSnapshot,
)
from app.services.WhatsappUsageService import WhatsappUsageService as RealUsageService
from tests.test_whatsapp_intake import _collecting_session

PHONE = "+5217779313704"
MOD = "app.services.WhatsappIntakeProcessorService"
LINK_BASE = "https://pos.example"


def _snapshot(used=50, limit=50, state="limit"):
    start = datetime.now(timezone.utc)
    return UsageSnapshot(
        tier_id="normal",
        tier_name="Normal",
        used=used,
        limit=limit,
        tokens_used=0,
        token_ceiling=300000,
        percent=int(used * 100 / limit),
        window_start=start,
        window_end=start + timedelta(hours=8),
        window_seconds=28800,
        state=state,
        enforcement="enforce",
    )


def _proposal():
    return WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aire", quantity=1)],
        vehicle=ExtractionVehicle(make="Volkswagen", model="Jetta", year="2015"),
    )


@pytest.fixture
def env():
    targets = {
        "session_repo": f"{MOD}.session_repo",
        "folio_service": f"{MOD}.folio_service",
        "inbound_repo": f"{MOD}.inbound_repo",
        "whatsapp": f"{MOD}.WhatsappService",
        "llm": f"{MOD}.LlmExtractionService",
        "identity": f"{MOD}.WhatsappSellerIdentityService",
        "usage": f"{MOD}.WhatsappUsageService",
        "notifier": f"{MOD}.WhatsappUsageNotifier",
    }
    patchers = [patch(target) for target in targets.values()]
    patchers.append(patch(f"{MOD}.MySQLSessionLocal", None))
    # No open drafts unless a test says so (follow-up check at the limit).
    patchers.append(patch(f"{MOD}.clarify.find_drafts_with_open_questions", return_value=[]))
    mocks = [p.start() for p in patchers]
    ns = SimpleNamespace(**dict(zip(targets.keys(), mocks)))
    try:
        from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

        ns.inbound_repo.find_by_message_sid.return_value = None
        ns.identity.return_value.is_entitled.return_value = True
        ns.whatsapp.return_value.native_reactions_enabled = False
        ns.whatsapp.return_value.send_text_message.return_value = {}
        ns.llm.return_value.extract.return_value = _proposal()
        folio = {
            "_id": "folio-1",
            "share_token": "share-abc",
            "folio_code": "JETTA1",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        ns.folio_service.create.return_value = folio
        ns.folio_service.update.return_value = folio
        ns.folio_service._normalize_vehicle.return_value = {
            "maker": "Volkswagen",
            "model": "Jetta",
            "year": 2015,
        }
        ns.usage_svc = ns.usage.return_value
        ns.usage_svc.check_burst_guard.return_value = True
        ns.usage_svc.repo.get_settings.return_value = {"notice_cooldown_seconds": 1800}
        ns.usage_svc.repo.claim_notice.return_value = True
        ns.notifier.return_value.is_manager.return_value = False
        ns.notifier.return_value.push_managers.return_value = 1

        service = WhatsappIntakeProcessorService()
        service.extract_enabled = True
        service.client_base_url = LINK_BASE
        service.whatsapp_public_base_url = LINK_BASE
        ns.service = service
        yield ns
    finally:
        for p in reversed(patchers):
            p.stop()


def _flush(ns, body="Jetta 2015, filtro de aire", group_id="g1", sid="SM-1"):
    session = _collecting_session(
        messages=[{"message_sid": sid, "body": body}],
        group_id=group_id,
    )
    ns.service._flush_session_body(PHONE, session)


def _sent(ns):
    return [c.args[1] for c in ns.whatsapp.return_value.send_text_message.call_args_list]


def _meter_calls(ns):
    svc = ns.usage_svc
    return (
        svc.reserve.call_count
        + svc.ensure_tokens_available.call_count
        + svc.record_call.call_count
        + svc.refund.call_count
    )


# --- New requests ---------------------------------------------------------

def test_new_request_reserves_once_and_calls_model(env):
    _flush(env)

    env.usage_svc.reserve.assert_called_once()
    ctx = env.usage_svc.reserve.call_args.args[0]
    assert isinstance(ctx, UsageContext)
    assert (ctx.group_id, ctx.uid) == ("g1", "uid-1")
    env.llm.return_value.extract.assert_called_once()
    env.folio_service.create.assert_called_once()

    sink = env.llm.return_value.extract.call_args.kwargs["usage_sink"]
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "model": "glm", "has_usage": True}
    sink(usage)
    env.usage_svc.record_call.assert_called_once_with(ctx, "extract", usage, counted=True)
    env.usage_svc.refund.assert_not_called()


def test_blocked_store_skips_model_sends_block_message_and_clears_session(env):
    snap = _snapshot()
    env.usage_svc.reserve.side_effect = UsageLimitReached("quota", snap)

    _flush(env)

    env.llm.return_value.extract.assert_not_called()
    env.folio_service.create.assert_not_called()
    env.usage_svc.repo.claim_notice.assert_called_once_with("g1", "blocked_notified_at", 1800, ANY)
    sent = _sent(env)
    assert len(sent) == 1
    assert sent[0].startswith("Tu tienda llegó al límite de solicitudes de WhatsApp (50 cada 8 horas).")
    assert sent[0].endswith("Avisa al dueño o encargado si necesitas más ahora.")
    env.session_repo.delete_session.assert_called_once_with(PHONE)
    env.notifier.return_value.push_managers.assert_called_once_with("g1", ANY, snap, "limit", ANY)


def test_blocked_message_not_repeated_within_cooldown(env):
    env.usage_svc.reserve.side_effect = UsageLimitReached("quota", _snapshot())
    env.usage_svc.repo.claim_notice.return_value = False

    _flush(env)

    assert _sent(env) == []
    env.notifier.return_value.push_managers.assert_not_called()
    env.session_repo.delete_session.assert_called_once_with(PHONE)
    env.llm.return_value.extract.assert_not_called()


def test_manager_block_message_includes_link_seller_does_not(env):
    snap = _snapshot()
    env.usage_svc.reserve.side_effect = UsageLimitReached("quota", snap)
    env.notifier.return_value.is_manager.return_value = True

    _flush(env)

    manager_msg = _sent(env)[0]
    assert manager_msg.endswith(f"\n\nPide más en Eassymo POS: {LINK_BASE}/user-configuration/whatsapp-pos")
    assert "Avisa al dueño" not in manager_msg
    env.notifier.return_value.is_manager.assert_called_with("uid-1", "g1")

    env.whatsapp.return_value.send_text_message.reset_mock()
    env.notifier.return_value.is_manager.return_value = False
    _flush(env)
    seller_msg = _sent(env)[0]
    assert LINK_BASE not in seller_msg
    assert "Avisa al dueño o encargado" in seller_msg


def test_model_failure_refunds_reservation(env):
    env.llm.return_value.extract.side_effect = RuntimeError("bad reply")

    _flush(env)

    env.usage_svc.reserve.assert_called_once()
    ctx = env.usage_svc.reserve.call_args.args[0]
    env.usage_svc.refund.assert_called_once_with(ctx)
    env.folio_service.create.assert_not_called()


def test_rate_limited_refunds_reservation(env):
    env.llm.return_value.extract.side_effect = LlmRateLimitError("429")

    _flush(env)

    ctx = env.usage_svc.reserve.call_args.args[0]
    env.usage_svc.refund.assert_called_once_with(ctx)
    assert any("ocupado" in body for body in _sent(env))


def test_warning_sent_after_draft_when_crossing_threshold(env):
    snap = _snapshot(used=40, limit=50, state="warning")

    def reserve(ctx, *a, **k):
        ctx.reserved = True
        ctx.crossed_warning = True
        ctx.snapshot = snap

    env.usage_svc.reserve.side_effect = reserve

    _flush(env)

    sent = _sent(env)
    assert sent[-1].startswith("⚠️ Tu tienda lleva 40 de 50 solicitudes. Se renuevan ")
    assert any("Borrador" in body for body in sent[:-1])
    env.notifier.return_value.push_managers.assert_called_once_with("g1", ANY, snap, "warning", ANY)
    kinds = [c.args[0]["kind"] for c in env.inbound_repo.insert_outbound.call_args_list]
    assert kinds[-1] == "bot_notice"


def test_meter_exception_fails_open_and_draft_still_created(env):
    env.usage_svc.reserve.side_effect = RuntimeError("mongo down")
    env.usage_svc.record_call.side_effect = RuntimeError("mongo down")

    _flush(env)

    env.llm.return_value.extract.assert_called_once()
    env.llm.return_value.extract.call_args.kwargs["usage_sink"]({"prompt_tokens": 1})
    env.folio_service.create.assert_called_once()
    assert not any("límite" in body for body in _sent(env))


# --- Follow-ups -----------------------------------------------------------

def _resume_setup(ns):
    folio = {"_id": "folio-1", "share_token": "share-abc", "vehicle": {"maker": "Volkswagen"}}
    svc = ns.service
    svc._resolve_resume_token = MagicMock(return_value="share-abc")
    svc._try_fill_forwarded_answers = MagicMock(return_value=False)
    svc._load_folio_by_share_token = MagicMock(return_value=folio)
    svc._can_resume_folio = MagicMock(return_value=(True, None))
    svc._partition_resume_proposal = MagicMock(return_value=(["l1"], []))
    svc._proposal_names_different_vehicle = MagicMock(return_value=False)
    svc._resume_draft_from_proposal = MagicMock()
    return folio


def test_follow_up_burst_never_reserves_and_is_not_blocked_by_quota(env):
    _resume_setup(env)

    _flush(env, body="también un filtro de aceite")

    env.usage_svc.reserve.assert_not_called()
    env.usage_svc.ensure_tokens_available.assert_called_once()
    ctx = env.usage_svc.ensure_tokens_available.call_args.args[0]
    env.llm.return_value.extract.assert_called_once()
    env.service._resume_draft_from_proposal.assert_called_once()

    sink = env.llm.return_value.extract.call_args.kwargs["usage_sink"]
    sink({"prompt_tokens": 3})
    env.usage_svc.record_call.assert_called_once_with(ctx, "extract", {"prompt_tokens": 3}, counted=False)


def test_follow_up_blocked_by_token_ceiling(env):
    _resume_setup(env)
    env.usage_svc.ensure_tokens_available.side_effect = UsageLimitReached("tokens", _snapshot())

    _flush(env, body="también un filtro de aceite")

    env.llm.return_value.extract.assert_not_called()
    env.service._resume_draft_from_proposal.assert_not_called()
    assert _sent(env)[0].startswith("Tu tienda llegó al límite de solicitudes de WhatsApp")
    env.session_repo.delete_session.assert_called_once_with(PHONE)


def test_reasoned_answers_obey_token_ceiling_and_record_uncounted(env):
    from app.services import WhatsappIntakeProcessorService as module

    folio = {
        "_id": "folio-1",
        "whatsapp_pending_questions": [
            {"id": "q1", "path": "pieces.0.position", "prompt": "¿Posición?", "status": "open"},
        ],
    }
    ctx = UsageContext(group_id="g1", uid="uid-1", burst_id="b1")
    token = module._usage_ctx_var.set(ctx)
    try:
        env.llm.return_value.match_answers.return_value = SimpleNamespace(answers=[])
        with patch(f"{MOD}.clarify.open_questions", return_value=folio["whatsapp_pending_questions"]):
            env.service._apply_reasoned_answers(
                from_number=PHONE, folio=folio, answer_text="delantera", quoted_sid=None, burst_id="b1"
            )
            env.usage_svc.ensure_tokens_available.assert_called_once_with(ctx)
            sink = env.llm.return_value.match_answers.call_args.kwargs["usage_sink"]
            sink({"prompt_tokens": 2})
            env.usage_svc.record_call.assert_called_once_with(
                ctx, "match_answers", {"prompt_tokens": 2}, counted=False
            )

            env.usage_svc.ensure_tokens_available.side_effect = UsageLimitReached("tokens", _snapshot())
            env.llm.return_value.match_answers.reset_mock()
            with pytest.raises(UsageLimitReached):
                env.service._apply_reasoned_answers(
                    from_number=PHONE, folio=folio, answer_text="delantera", quoted_sid=None, burst_id="b1"
                )
            env.llm.return_value.match_answers.assert_not_called()
    finally:
        module._usage_ctx_var.reset(token)


# --- Free paths -----------------------------------------------------------

def test_replay_and_commands_do_not_touch_meter(env):
    env.inbound_repo.find_by_message_sid.return_value = {"folio_id": "folio-1"}
    env.folio_service.get.return_value = {"_id": "folio-1", "share_token": "share-abc"}

    _flush(env)

    env.llm.return_value.extract.assert_not_called()
    assert _meter_calls(env) == 0

    env.inbound_repo.find_by_message_sid.return_value = None
    env.identity.return_value.resolve.return_value = MagicMock(
        status="resolved", group_id="g1", group_name="Tienda A",
        creator_uid="uid-1", just_selected=False, message=None,
    )
    env.session_repo.get_by_phone.return_value = None
    for index, body in enumerate(["PEDIDO", "CANCELAR", "LISTO"]):
        env.service.process_inbound({"message_sid": f"SM-c{index}", "from_number": PHONE, "body": body})
    assert _meter_calls(env) == 0
    env.usage_svc.check_burst_guard.assert_not_called()


# --- Burst guard ----------------------------------------------------------

def test_burst_guard_drops_excess_and_notifies_once(env):
    env.identity.return_value.resolve.return_value = MagicMock(
        status="resolved", group_id="g1", group_name="Tienda A",
        creator_uid="uid-1", just_selected=False, message=None,
    )
    env.usage_svc.check_burst_guard.return_value = False
    env.usage_svc.repo.claim_notice.side_effect = [True, False]

    for index in range(2):
        result = env.service.process_inbound(
            {"message_sid": f"SM-{index}", "from_number": PHONE, "body": "otra pieza"}
        )
        assert result is None

    env.usage_svc.check_burst_guard.assert_called_with("g1", PHONE)
    assert _sent(env) == [GUARD_NOTICE]
    env.usage_svc.repo.claim_notice.assert_called_with("g1", "guard_notified_at", 1800, ANY)
    env.session_repo.append_message.assert_not_called()
    env.session_repo.ensure_collecting_session.assert_not_called()


def test_burst_guard_error_fails_open(env):
    env.identity.return_value.resolve.return_value = MagicMock(
        status="resolved", group_id="g1", group_name="Tienda A",
        creator_uid="uid-1", just_selected=False, message=None,
    )
    env.usage_svc.check_burst_guard.side_effect = RuntimeError("mongo down")
    env.session_repo.get_by_phone.return_value = None
    env.session_repo.append_message.return_value = (None, False, False)

    env.service.process_inbound({"message_sid": "SM-1", "from_number": PHONE, "body": "otra pieza"})

    env.session_repo.append_message.assert_called_once()
    assert GUARD_NOTICE not in _sent(env)


# --- Real usage service on an in-memory repo ----------------------------------

class _FakeUsageRepo:
    """In-memory stand-in for WhatsappUsageRepository (enforce tier, limit 5), per store."""

    NORMAL_TIER_ID = "normal"
    NORMAL_TIER_SEED = {
        "name": "Normal", "solicitudes_per_window": 5, "window_seconds": 28800,
        "token_ceiling_per_window": 300000, "burst_messages_per_minute": 30,
        "warn_at_percent": 80, "per_seller_cap_percent": None, "enforcement": "enforce",
        "active": True,
    }

    def __init__(self, **used_by_group):
        now = datetime.now(timezone.utc)
        self.docs = {
            group_id: {"group_id": group_id, "window_start": now, "solicitudes_used": used,
                       "tokens_used": 0, "bursts": []}
            for group_id, used in used_by_group.items()
        }
        self.warned = set()
        self.events = set()

    def used(self, group_id):
        return self.docs[group_id]["solicitudes_used"]

    def get_settings(self):
        return {"enforcement_enabled": True, "shadow_all": False, "notice_cooldown_seconds": 1800}

    def get_store_tier_id(self, group_id):
        return "normal"

    def get_tier(self, tier_id):
        return {**self.NORMAL_TIER_SEED, "tier_id": "normal"}

    def ensure_window(self, group_id, tier_id, window_seconds, now):
        self.docs.setdefault(group_id, {"group_id": group_id, "window_start": now, "solicitudes_used": 0,
                                        "tokens_used": 0, "bursts": []})
        return dict(self.docs[group_id])

    def get_usage(self, group_id):
        doc = self.docs.get(group_id)
        return dict(doc) if doc else None

    def bind_pending_grants(self, group_id, window_start):
        return 0

    def sum_grants(self, group_id, window_start):
        return 0

    def try_reserve(self, group_id, uid, burst_id, **kw):
        doc = self.docs[group_id]
        if burst_id in doc["bursts"]:
            return "duplicate"
        if doc["solicitudes_used"] >= kw["limit"]:
            return "blocked_quota"
        doc["bursts"].append(burst_id)
        doc["solicitudes_used"] += 1
        return "reserved"

    def claim_warning(self, group_id, window_start):
        if group_id in self.warned:
            return False
        self.warned.add(group_id)
        return True

    def insert_event(self, event):
        if event["event_id"] in self.events:
            return False
        self.events.add(event["event_id"])
        return True

    def add_tokens(self, group_id, tokens):
        self.docs[group_id]["tokens_used"] += tokens

    def refund(self, group_id, uid, burst_id):
        doc = self.docs[group_id]
        if burst_id in doc["bursts"]:
            doc["bursts"].remove(burst_id)
            doc["solicitudes_used"] -= 1

    def incr_meter_errors(self):
        raise AssertionError("meter must not fail")

    def claim_notice(self, *a):
        return True


def _real_usage(ns, **used_by_group):
    repo = _FakeUsageRepo(**used_by_group)
    ns.service.usage = RealUsageService(repo=repo, inbound=MagicMock())
    return repo


def _warnings(ns):
    return [body for body in _sent(ns) if body.startswith("⚠️")]


def _blocks(ns):
    return [body for body in _sent(ns) if body.startswith("Tu tienda llegó al límite")]


def test_duplicate_burst_id_flush_reserves_once_and_warns_once(env):
    repo = _real_usage(env, g1=3)
    session = _collecting_session(messages=[{"message_sid": "SM-1", "body": "Jetta 2015, filtro de aire"}])

    env.service._flush_session_body(PHONE, dict(session))
    env.service._flush_session_body(PHONE, dict(session))  # recovery re-flush, new uuid

    assert repo.used("g1") == 4
    assert len(repo.docs["g1"]["bursts"]) == 1
    assert len(_warnings(env)) == 1
    assert _warnings(env)[0].startswith("⚠️ Tu tienda lleva 4 de 5 solicitudes. Se renuevan ")
    pushes = [c for c in env.notifier.return_value.push_managers.call_args_list if c.args[3] == "warning"]
    assert len(pushes) == 1


def test_two_store_seller_charges_only_resolved_store(env):
    # The seller is linked to g1 and g2; this burst resolved to g2.
    repo = _real_usage(env, g1=2, g2=0)
    before_g1 = dict(repo.docs["g1"])

    _flush(env, group_id="g2")

    assert repo.used("g2") == 1
    assert repo.docs["g1"] == before_g1
    env.folio_service.create.assert_called_once()


def _empty_proposal():
    return WhatsappExtractionProposal(intent=ExtractionIntent.NEW_REQUEST, lines=[])


def _open_draft():
    return {"_id": "folio-9", "share_token": "share-9", "vehicle": {"maker": "Volkswagen"}}


def test_loose_clarification_answer_at_limit_is_free_and_not_blocked(env):
    repo = _real_usage(env, g1=5)
    draft = _open_draft()
    env.llm.return_value.extract.return_value = _empty_proposal()
    env.service._answerable_drafts = MagicMock(return_value=[draft])
    env.service._resolve_complement_folio = MagicMock(return_value=(draft, None))
    env.service._handle_complement_or_answer = MagicMock(return_value=True)

    with patch(f"{MOD}.clarify.find_drafts_with_open_questions", return_value=[draft]):
        _flush(env, body="delantera")

    env.service._handle_complement_or_answer.assert_called_once()
    env.llm.return_value.extract.assert_called_once()
    assert _blocks(env) == []
    assert repo.used("g1") == 5
    env.session_repo.delete_session.assert_not_called()


def test_possible_follow_up_at_limit_that_is_a_new_draft_is_blocked(env):
    repo = _real_usage(env, g1=5)
    draft = _open_draft()
    env.service._answerable_drafts = MagicMock(return_value=[draft])
    env.service._find_resend_match_folio = MagicMock(return_value=None)

    with patch(f"{MOD}.clarify.find_drafts_with_open_questions", return_value=[draft]):
        _flush(env)

    env.llm.return_value.extract.assert_called_once()
    env.folio_service.create.assert_not_called()
    assert len(_blocks(env)) == 1
    assert repo.used("g1") == 5
    env.session_repo.delete_session.assert_called_once_with(PHONE)


def test_new_request_at_limit_with_no_open_drafts_is_blocked_before_model(env):
    _real_usage(env, g1=5)
    env.service._answerable_drafts = MagicMock(return_value=[])

    with patch(f"{MOD}.clarify.find_drafts_with_open_questions", return_value=[]):
        _flush(env)

    env.llm.return_value.extract.assert_not_called()
    assert len(_blocks(env)) == 1


def test_resend_of_existing_draft_refunds(env):
    repo = _real_usage(env, g1=2)
    env.service._find_resend_match_folio = MagicMock(return_value=_open_draft())
    env.service._link_resend_to_existing_draft = MagicMock()

    _flush(env)

    env.service._link_resend_to_existing_draft.assert_called_once()
    env.folio_service.create.assert_not_called()
    assert repo.used("g1") == 2


def test_parts_without_vehicle_resuming_last_draft_refund(env):
    repo = _real_usage(env, g1=2)
    env.llm.return_value.extract.return_value = WhatsappExtractionProposal(
        intent=ExtractionIntent.NEW_REQUEST,
        lines=[ExtractionLine(local_id="l1", part_name="filtro de aceite", quantity=1)],
    )
    svc = env.service
    svc._is_full_new_request = MagicMock(return_value=False)
    svc._resolve_complement_folio = MagicMock(return_value=(None, None))
    svc._latest_share_token = MagicMock(return_value="share-9")
    svc._load_folio_by_share_token = MagicMock(return_value=_open_draft())
    svc._bodies_name_other_year = MagicMock(return_value=False)
    svc._can_resume_folio = MagicMock(return_value=(True, None))
    svc._resume_draft_from_proposal = MagicMock()

    _flush(env, body="filtro de aceite")

    svc._resume_draft_from_proposal.assert_called_once()
    env.folio_service.create.assert_not_called()
    assert repo.used("g1") == 2


def test_no_clear_request_refunds_and_sends_no_warning(env):
    repo = _real_usage(env, g1=3)  # this reserve would cross 80%
    env.llm.return_value.extract.return_value = _empty_proposal()
    env.service._resolve_complement_folio = MagicMock(return_value=(None, None))

    _flush(env, body="hola")

    assert any(body.startswith("Recibido. No detectamos") for body in _sent(env))
    assert repo.used("g1") == 3
    assert _warnings(env) == []
    env.notifier.return_value.push_managers.assert_not_called()


def test_token_ceiling_after_reserve_refunds_and_blocks(env):
    repo = _real_usage(env, g1=1)
    env.service._is_full_new_request = MagicMock(return_value=False)

    def ceiling(*a, **k):
        raise UsageLimitReached("tokens", _snapshot())

    env.service._try_complement_before_resume = MagicMock(side_effect=ceiling)

    _flush(env)

    assert repo.used("g1") == 1
    assert len(_blocks(env)) == 1


# --- Final-review fixes: sink counts once, flush crash refunds ---------------

def test_sink_counts_only_the_first_model_call_of_a_burst(env):
    _flush(env)
    ctx = env.usage_svc.reserve.call_args.args[0]
    sink = env.llm.return_value.extract.call_args.kwargs["usage_sink"]
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "has_usage": True}
    sink(usage)  # first call
    sink(usage)  # empty-reply retry
    sink(usage)  # repair
    counted = [c.kwargs["counted"] for c in env.usage_svc.record_call.call_args_list]
    assert counted == [True, False, False]
    assert env.usage_svc.record_call.call_args_list[0].args[0] is ctx


def _reserving(env):
    def reserve(ctx, *a, **k):
        ctx.reserved = True

    env.usage_svc.reserve.side_effect = reserve


def test_flush_crash_after_reserve_refunds_and_reraises(env):
    _reserving(env)
    env.folio_service.create.side_effect = RuntimeError("mongo down")

    with pytest.raises(RuntimeError):
        _flush(env)

    ctx = env.usage_svc.reserve.call_args.args[0]
    env.usage_svc.refund.assert_called_once_with(ctx)


def test_flush_superseded_after_reserve_does_not_refund(env):
    from app.services.WhatsappIntakeProcessorService import _FlushSuperseded

    _reserving(env)
    env.folio_service.create.side_effect = _FlushSuperseded()

    with pytest.raises(_FlushSuperseded):
        _flush(env)

    env.usage_svc.refund.assert_not_called()
