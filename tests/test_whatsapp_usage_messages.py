from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services import WhatsappUsageMessages as msgs
from app.services import WhatsappUsageNotifier as notifier_mod
from app.services.WhatsappUsageNotifier import WhatsappUsageNotifier
from app.services.WhatsappUsageService import UsageSnapshot

MX = ZoneInfo("America/Mexico_City")
UTC = ZoneInfo("UTC")


def _snap(used=40, limit=50, window_seconds=28800):
    return UsageSnapshot(
        tier_id="normal", tier_name="Normal", used=used, limit=limit, tokens_used=0,
        token_ceiling=300000, percent=int(used * 100 / limit), window_start=None,
        window_end=None, window_seconds=window_seconds, state="warning", enforcement="enforce",
    )


NOW = datetime(2026, 11, 18, 10, 0, tzinfo=MX)


def test_format_when_today_tomorrow_and_date():
    assert msgs.format_when(datetime(2026, 11, 18, 23, 40, tzinfo=MX), NOW) == "hoy a las 11:40 pm"
    assert msgs.format_when(datetime(2026, 11, 19, 1, 5, tzinfo=MX), NOW) == "mañana a las 1:05 am"
    assert msgs.format_when(datetime(2026, 11, 20, 15, 40, tzinfo=MX), NOW) == "el 20 nov a las 3:40 pm"
    assert msgs.format_when(datetime(2026, 11, 18, 0, 0, tzinfo=MX), NOW) == "hoy a las 12:00 am"
    assert msgs.format_when(datetime(2026, 11, 18, 12, 30, tzinfo=MX), NOW) == "hoy a las 12:30 pm"
    # UTC inputs convert to Mexico City (UTC-6 in November)
    t = datetime(2026, 11, 19, 5, 40, tzinfo=UTC)  # 11:40 pm on the 18th in MX
    assert msgs.format_when(t, datetime(2026, 11, 18, 16, 0, tzinfo=UTC)) == "hoy a las 11:40 pm"
    # naive values are treated as UTC
    assert msgs.format_when(datetime(2026, 11, 19, 5, 40), datetime(2026, 11, 18, 16, 0)) == "hoy a las 11:40 pm"


def test_format_span_hours_days_singular():
    assert msgs.format_span(3600) == "1 hora"
    assert msgs.format_span(28800) == "8 horas"
    assert msgs.format_span(172800) == "2 días"
    assert msgs.format_span(86400) == "1 día"


def test_warning_message_matches_spec_copy():
    snap = _snap()
    snap.window_end = datetime(2026, 11, 18, 23, 40, tzinfo=MX)
    assert msgs.warning_message(snap, NOW) == (
        "⚠️ Tu tienda lleva 40 de 50 solicitudes. Se renuevan hoy a las 11:40 pm."
    )


def test_block_message_seller_has_no_link_and_manager_has_link():
    snap = _snap(used=50)
    snap.window_end = datetime(2026, 11, 19, 1, 5, tzinfo=MX)
    seller = msgs.block_message(snap, is_manager=False, link="https://x/y", now=NOW)
    assert seller == (
        "Tu tienda llegó al límite de solicitudes de WhatsApp (50 cada 8 horas). "
        "Se renueva mañana a las 1:05 am. Avisa al dueño o encargado si necesitas más ahora."
    )
    assert "https://x/y" not in seller
    manager = msgs.block_message(snap, is_manager=True, link="https://x/y", now=NOW)
    assert manager == (
        "Tu tienda llegó al límite de solicitudes de WhatsApp (50 cada 8 horas). "
        "Se renueva mañana a las 1:05 am.\n\nPide más en Eassymo POS: https://x/y"
    )


def test_guard_notice():
    assert msgs.GUARD_NOTICE == "Estás enviando mensajes muy rápido. Espera un momento y vuelve a intentar."


def test_push_managers_sends_spec_titles_and_navigate_url():
    snap = _snap(used=40)
    snap.window_end = datetime(2026, 11, 18, 23, 40, tzinfo=MX)
    n = WhatsappUsageNotifier()
    with patch.object(n, "manager_uids", return_value=["m1", "m2"]), patch.object(
        notifier_mod.push_service, "send_push_to_uid", return_value=1
    ) as send:
        assert n.push_managers("g1", "Mi Tienda", snap, "warning", NOW) == 2
        send.assert_any_call(
            "m1",
            title="Tu tienda está por llegar al límite",
            body="Mi Tienda lleva 40 de 50 solicitudes de WhatsApp. Se renuevan hoy a las 11:40 pm.",
            data={"navigateToUrl": "/user-configuration/whatsapp-pos"},
        )
        send.reset_mock()
        assert n.push_managers("g1", "Mi Tienda", snap, "limit", NOW) == 2
        send.assert_any_call(
            "m2",
            title="Tu tienda llegó al límite",
            body="El bot no crea borradores nuevos hasta hoy a las 11:40 pm. Toca para pedir más solicitudes.",
            data={"navigateToUrl": "/user-configuration/whatsapp-pos"},
        )


def test_push_managers_counts_only_delivered():
    snap = _snap()
    n = WhatsappUsageNotifier()
    with patch.object(n, "manager_uids", return_value=["m1", "m2"]), patch.object(
        notifier_mod.push_service, "send_push_to_uid", side_effect=[0, 2]
    ):
        assert n.push_managers("g1", "T", snap, "limit", NOW) == 2


def test_push_admins_reads_env_uids(monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_PUSH_UIDS", "a1, a2 ,,a3")
    n = WhatsappUsageNotifier()
    with patch.object(notifier_mod.push_service, "send_push_to_uid", return_value=1) as send:
        assert n.push_admins_credit_request("g1", "Mi Tienda", "u9") == 3
    assert [c.args[0] for c in send.call_args_list] == ["a1", "a2", "a3"]
    assert send.call_args_list[0].kwargs["data"] == {
        "navigateToUrl": "/super-admin/whatsapp/credit-requests",
        "group_id": "g1",
        "requested_by": "u9",
    }
    monkeypatch.delenv("SUPER_ADMIN_PUSH_UIDS")
    with patch.object(notifier_mod.push_service, "send_push_to_uid") as send:
        assert n.push_admins_credit_request("g1", "Mi Tienda", "u9") == 0
        send.assert_not_called()


def test_manager_uids_and_is_manager_use_grant():
    n = WhatsappUsageNotifier()
    role = MagicMock(user_uid="u3")
    with patch.object(notifier_mod.groupRepository, "find_by_id", return_value={"owner": "u1", "users": ["u1", "u2"]}), \
         patch.object(notifier_mod.userRolesRepository, "find", return_value=[role]), \
         patch.object(notifier_mod, "can", side_effect=lambda uid, g, k: uid in ("u1", "u3") and k == "team.manage_members") as c:
        assert n.manager_uids("g1") == ["u1", "u3"]
        assert n.is_manager("u3", "g1") is True
        assert n.is_manager("u2", "g1") is False


def test_push_failure_for_one_uid_does_not_stop_others():
    n = WhatsappUsageNotifier()
    with patch.object(n, "manager_uids", return_value=["m1", "m2"]), patch.object(
        notifier_mod.push_service, "send_push_to_uid", side_effect=[RuntimeError("boom"), 1]
    ) as send:
        assert n.push_managers("g1", "T", _snap(), "limit", NOW) == 1
    assert send.call_count == 2


def test_manager_uids_failure_returns_empty_and_push_managers_zero():
    n = WhatsappUsageNotifier()
    with patch.object(notifier_mod.groupRepository, "find_by_id", side_effect=RuntimeError("db")), patch.object(
        notifier_mod.push_service, "send_push_to_uid"
    ) as send:
        assert n.manager_uids("g1") == []
        assert n.push_managers("g1", "T", _snap(), "limit", NOW) == 0
        send.assert_not_called()


def test_invalid_group_id_does_not_raise():
    from bson.errors import InvalidId

    n = WhatsappUsageNotifier()
    with patch.object(notifier_mod.groupRepository, "find_by_id", side_effect=InvalidId("bad")):
        assert n.manager_uids("not-an-id") == []
    with patch.object(notifier_mod, "can", side_effect=InvalidId("bad")):
        assert n.is_manager("u1", "not-an-id") is False


def test_push_managers_window_end_none_says_pronto():
    snap = _snap()
    snap.window_end = None
    n = WhatsappUsageNotifier()
    with patch.object(n, "manager_uids", return_value=["m1"]), patch.object(
        notifier_mod.push_service, "send_push_to_uid", return_value=1
    ) as send:
        n.push_managers("g1", "Mi Tienda", snap, "warning", NOW)
        n.push_managers("g1", "Mi Tienda", snap, "limit", NOW)
    bodies = [c.kwargs["body"] for c in send.call_args_list]
    assert bodies == [
        "Mi Tienda lleva 40 de 50 solicitudes de WhatsApp. Se renuevan pronto.",
        "El bot no crea borradores nuevos hasta pronto. Toca para pedir más solicitudes.",
    ]


def test_push_requester_resolved_granted_and_declined():
    n = WhatsappUsageNotifier()
    with patch.object(notifier_mod.push_service, "send_push_to_uid", return_value=1) as send:
        assert n.push_requester_resolved("u1", "Mi Tienda", "granted", 20) == 1
        assert n.push_requester_resolved("u1", "Mi Tienda", "declined", None) == 1
    granted, declined = send.call_args_list
    assert granted.args[0] == "u1" and declined.args[0] == "u1"
    assert granted.kwargs["title"] == "Tu solicitud fue revisada"
    assert granted.kwargs["body"] == "Te dimos 20 solicitudes extra para Mi Tienda."
    assert declined.kwargs["body"] == "Por ahora no pudimos darte más solicitudes para Mi Tienda."
    assert granted.kwargs["data"] == {"navigateToUrl": "/user-configuration/whatsapp-pos"}


def test_push_requester_resolved_never_raises():
    n = WhatsappUsageNotifier()
    with patch.object(notifier_mod.push_service, "send_push_to_uid", side_effect=RuntimeError("down")):
        assert n.push_requester_resolved("u1", "Mi Tienda", "granted", 5) == 0
    with patch.object(notifier_mod.push_service, "send_push_to_uid") as send:
        assert n.push_requester_resolved("", "Mi Tienda", "granted", 5) == 0
        send.assert_not_called()
