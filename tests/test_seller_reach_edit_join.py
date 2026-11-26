"""Seller reach cap on edit: every doc decided before any write, today's day, no refusal without growth."""
import json
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from app.routers import PartRequestRouter as router
from app.schemas.PartRequest import PartRequestEdit
from app.services import PartRequestService as prs
from app.services import SellerReachService as reach
from app.services.SellerReachService import SellerReachError
from tests.test_seller_reach_create import DAY, NOW, FakeReachRepo, _all_compatible, _sellers


def _doc(doc_id, n_sellers, reach_doc=None, origin=None):
    doc = {
        "_id": ObjectId(doc_id),
        "creatorGroup": "buyer-g",
        "creatorUser": "buyer-u",
        "vehicleId": "veh-1",
        "subscribedSellers": _sellers(n_sellers),
        "partList": [],
        "part": {"name": "p"},
        "fulfillment_type": "pickup",
        "status": "Created",
        "reach": reach_doc,
    }
    if origin:
        doc["origin"] = origin
    return doc


def _edit(doc_id, add=None, comment=None):
    return PartRequestEdit(id=doc_id, subscribedSellers=add, comment=comment, amount=1)


class World:
    def __init__(self, repo, docs):
        self.repo = repo
        self.docs = {str(d["_id"]): d for d in docs}
        self.written = []
        self.write_mock = MagicMock(side_effect=self._write)

    def _write(self, doc_id, data):
        self.written.append((doc_id, data))
        return {**self.docs[doc_id], **data}

    def __enter__(self):
        self.stack = ExitStack()
        p = self.stack.enter_context
        p(patch.object(reach, "repo", self.repo))
        p(patch.object(prs.partRequestRepository, "find_by_id", side_effect=lambda i: [self.docs[i]]))
        p(patch.object(prs.partRequestRepository, "edit_part_request", self.write_mock))
        p(patch.object(prs.groupRepository, "find_by_id", return_value=None))
        p(patch.object(prs, "expand_subscribed_sellers_with_accepted_comisionados", side_effect=lambda s, c=None: list(s)))
        p(patch.object(prs.ArmadoraCompatibilityService, "evaluate_bulk", side_effect=_all_compatible))
        p(patch.object(prs.SistemasCompatibilityService, "evaluate_bulk_for_car_part", side_effect=_all_compatible))
        p(patch.object(prs, "_now", return_value=NOW))
        p(patch("app.services.notification_fanout.fanout_part_request_to_new_sellers"))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


A = "6560000000000000000000a1"
B = "6560000000000000000000b2"
NORMAL = {"tier": "normal", "day": DAY, "audience": 40}


def test_edit_growth_past_50_reserves_slot():
    repo = FakeReachRepo(wide_used=1)
    doc = _doc(A, 40, NORMAL)
    with World(repo, [doc]) as w:
        prs.edit_part_request([_edit(A, add=_sellers(55, "n"))])
    assert w.written[0][1]["reach"] == {"tier": "wide", "day": DAY, "audience": 95}
    assert repo.ids[-1] == A


def test_edit_exhausted_growth_over_20_refused_nothing_written():
    repo = FakeReachRepo(wide_used=2)
    docs = [_doc(A, 10, {"tier": "capped", "day": DAY, "audience": 10}), _doc(B, 10, {"tier": "capped", "day": DAY, "audience": 10})]
    with World(repo, docs) as w, pytest.raises(SellerReachError) as exc:
        prs.edit_part_request([_edit(A, add=_sellers(5, "n")), _edit(B, add=_sellers(30, "m"))])
    assert exc.value.status_code == 409
    assert exc.value.data["request_id"] == B
    w.write_mock.assert_not_called()


def test_edit_refusal_releases_slot_reserved_earlier_in_call():
    repo = FakeReachRepo(wide_used=1, wide_per_day=2)
    docs = [_doc(A, 40, NORMAL), _doc(B, 10, {"tier": "capped", "day": DAY, "audience": 10})]
    # A takes the last slot (wide); B, now exhausted, grows past 20 and is refused.
    with World(repo, docs) as w, pytest.raises(SellerReachError):
        prs.edit_part_request([_edit(A, add=_sellers(20, "n")), _edit(B, add=_sellers(30, "m"))])
    w.write_mock.assert_not_called()
    assert repo.released == [A]


def test_edit_without_seller_change_never_refused():
    repo = FakeReachRepo(wide_used=2)
    doc = _doc(A, 30, {"tier": "capped", "day": DAY, "audience": 30})
    with World(repo, [doc]) as w:
        prs.edit_part_request([_edit(A, comment="nuevo")])
    assert w.written[0][1]["reach"]["tier"] == "capped"


def test_edit_uses_today_not_creation_day():
    repo = FakeReachRepo(wide_used=0)
    doc = _doc(A, 40, {"tier": "normal", "day": "2026-11-24", "audience": 40})
    with World(repo, [doc]) as w, patch.object(repo, "try_reserve_wide", wraps=repo.try_reserve_wide) as spy:
        prs.edit_part_request([_edit(A, add=_sellers(20, "n"))])
    assert spy.call_args.args[1] == "2026-11-25"
    assert w.written[0][1]["reach"]["day"] == "2026-11-25"


def test_edit_legacy_wide_doc_never_limited_and_takes_no_slot():
    repo = FakeReachRepo(wide_used=2)
    doc = _doc(A, 60, None)
    with World(repo, [doc]) as w:
        prs.edit_part_request([_edit(A, add=_sellers(30, "n"))])
    assert w.written[0][1]["reach"]["tier"] == "wide"
    assert repo.ids == ["x", "x"]


def test_edit_mostrador_skips_reach():
    repo = FakeReachRepo(wide_used=2)
    doc = _doc(A, 10, None, origin="mostrador")
    with World(repo, [doc]) as w:
        prs.edit_part_request([_edit(A, add=_sellers(80, "n"))])
    assert "reach" not in w.written[0][1]


def test_router_answers_409_with_code():
    repo = FakeReachRepo(wide_used=2)
    doc = _doc(A, 10, {"tier": "capped", "day": DAY, "audience": 10})
    with World(repo, [doc]):
        resp = router.edit_part_request([_edit(A, add=_sellers(30, "n"))])
    assert resp.status_code == 409
    assert json.loads(resp.body)["code"] == "seller_cap_exceeded"


# ---- join and invites ------------------------------------------------------

from fastapi import HTTPException  # noqa: E402

from app.services import PartRequestInviteService as invites  # noqa: E402
from app.schemas.RequestInvites import RequestInvite  # noqa: E402

PARENT = "parent-1"
C = "6560000000000000000000c3"
EXH_CAPPED_16 = {"tier": "capped", "day": DAY, "audience": 16}
EXH_CAPPED_20 = {"tier": "capped", "day": DAY, "audience": 20}


class JoinWorld:
    def __init__(self, repo, docs):
        self.repo = repo
        self.docs = {str(d["_id"]): d for d in docs}

    def _write(self, doc_id, data):
        self.docs[doc_id].update({k: v for k, v in data.items() if k != "_id"})
        return self.docs[doc_id]

    def __enter__(self):
        self.stack = ExitStack()
        p = self.stack.enter_context
        for d in self.docs.values():
            d["specific_order_uid"] = PARENT
        p(patch.object(reach, "repo", self.repo))
        p(patch.object(prs.partRequestRepository, "find", side_effect=lambda f, proj=None: list(self.docs.values())))
        p(patch.object(prs.partRequestRepository, "edit_part_request", side_effect=self._write))
        p(patch.object(prs, "_now", return_value=NOW))
        p(patch.object(invites.PartRequestRepository, "find", side_effect=lambda f, proj=None: list(self.docs.values())))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


def test_join_skips_full_parts():
    repo = FakeReachRepo(wide_used=2)
    docs = [
        _doc(A, 60, {"tier": "wide", "day": DAY, "audience": 60}),
        _doc(B, 20, EXH_CAPPED_20),
        _doc(C, 16, EXH_CAPPED_16),
    ]
    with JoinWorld(repo, docs) as w:
        out = prs.join_seller_to_part_request(PARENT, "new-seller")
    assert sorted(out["joined_ids"]) == sorted([A, C])
    assert out["full_ids"] == [B]
    assert "new-seller" in w.docs[A]["subscribedSellers"]
    assert "new-seller" not in w.docs[B]["subscribedSellers"]
    assert ("join_skipped", B) in repo.events


def test_join_all_full_raises_request_full():
    repo = FakeReachRepo(wide_used=2)
    docs = [_doc(A, 20, EXH_CAPPED_20), _doc(B, 20, EXH_CAPPED_20)]
    with JoinWorld(repo, docs), pytest.raises(SellerReachError) as exc:
        prs.join_seller_to_part_request(PARENT, "new-seller")
    assert exc.value.code == "request_full"
    assert exc.value.status_code == 409
    assert sorted(exc.value.data["full_ids"]) == sorted([A, B])
    assert "renews_at" in exc.value.data


def test_join_is_idempotent_for_slots():
    repo = FakeReachRepo(wide_used=1)
    doc = _doc(A, 49, {"tier": "normal", "day": DAY, "audience": 49})
    with JoinWorld(repo, [doc]), patch.object(repo, "try_reserve_wide", wraps=repo.try_reserve_wide) as spy:
        first = prs.join_seller_to_part_request(PARENT, "new-seller")
        with pytest.raises(HTTPException) as exc:
            prs.join_seller_to_part_request(PARENT, "new-seller")
    assert first["joined_ids"] == [A]
    assert exc.value.status_code == 403
    assert spy.call_count == 1
    assert len(repo.ids) == 2


def test_join_handles_missing_subscribed_sellers():
    repo = FakeReachRepo(wide_used=0)
    doc = _doc(A, 0)
    doc["subscribedSellers"] = None
    with JoinWorld(repo, [doc]) as w:
        out = prs.join_seller_to_part_request(PARENT, "new-seller")
    assert out["joined_ids"] == [A]
    assert w.docs[A]["subscribedSellers"] == ["new-seller"]


def test_join_writes_only_what_changed_and_keeps_dates_as_dates():
    """Writing the whole toJson() back turned createdAt into ISO text, which broke every date filter on it."""
    repo = FakeReachRepo(wide_used=0)
    created = datetime(2026, 11, 25, 21, 41, 21, tzinfo=timezone.utc)
    doc = _doc(A, 3)
    doc["createdAt"] = created
    with JoinWorld(repo, [doc]) as w, patch.object(prs.partRequestRepository, "edit_part_request", side_effect=w._write) as write:
        prs.join_seller_to_part_request(PARENT, "new-seller")
    payload = write.call_args[0][1]
    assert set(payload) == {"subscribedSellers", "updatedAt", "reach"}
    assert isinstance(payload["updatedAt"], datetime)
    assert w.docs[A]["createdAt"] == created


def test_join_shadow_mode_joins_every_part():
    repo = FakeReachRepo(wide_used=2, enforcement="shadow")
    docs = [_doc(A, 20, EXH_CAPPED_20)]
    with JoinWorld(repo, docs):
        out = prs.join_seller_to_part_request(PARENT, "new-seller")
    assert out == {"joined_ids": [A], "full_ids": []}


def test_join_router_answers_409_request_full():
    repo = FakeReachRepo(wide_used=2)
    with JoinWorld(repo, [_doc(A, 20, EXH_CAPPED_20)]):
        resp = router.join_seller_to_part_request({"specific_order_uid": PARENT, "new_seller_group_id": "s"})
    assert resp.status_code == 409
    assert json.loads(resp.body)["code"] == "request_full"


def test_room_values():
    from app.schemas.PartRequest import PartRequest

    def part(n, tier_doc, slots_used):
        return PartRequest(**{**_doc(A, n, tier_doc), "_id": None}) if False else PartRequest(
            creatorGroup="buyer-g", creatorUser="buyer-u", vehicleId="veh-1",
            subscribedSellers=_sellers(n), partList=[], part={"name": "p"},
            fulfillment_type="pickup", reach=tier_doc)

    with patch.object(reach, "repo", FakeReachRepo(wide_used=2)):
        assert reach.room(part(60, {"tier": "wide"}, 2), NOW) is None
        assert reach.room(part(60, None, 2), NOW) is None  # legacy wide
        assert reach.room(part(16, EXH_CAPPED_16, 2), NOW) == 4
        assert reach.room(part(20, EXH_CAPPED_20, 2), NOW) == 0
        assert reach.room(part(25, {"tier": "capped"}, 2), NOW) == 0
    with patch.object(reach, "repo", FakeReachRepo(wide_used=1)):
        assert reach.room(part(49, {"tier": "normal"}, 1), NOW) is None


def _invite():
    return RequestInvite(parent_request_id=PARENT, inviter_group="buyer-g", inviter_user="buyer-u", invited_group="g2")


def test_invite_refused_when_every_part_full():
    repo = FakeReachRepo(wide_used=2)
    docs = [_doc(A, 20, EXH_CAPPED_20), _doc(B, 20, EXH_CAPPED_20)]
    with JoinWorld(repo, docs), patch.object(invites.PartRequestInviteRepository, "insert") as ins:
        with pytest.raises(SellerReachError) as exc:
            invites.insert(_invite())
    assert exc.value.code == "request_full"
    assert sorted(exc.value.data["full_ids"]) == sorted([A, B])
    ins.assert_not_called()
    assert repo.ids == ["x", "x"]  # nothing reserved


def test_invite_allowed_when_some_part_has_room():
    repo = FakeReachRepo(wide_used=2)
    docs = [_doc(A, 20, EXH_CAPPED_20), _doc(B, 16, EXH_CAPPED_16)]
    with JoinWorld(repo, docs), patch.object(invites.PartRequestInviteRepository, "find", return_value=[]), \
            patch.object(invites.PartRequestInviteRepository, "insert", side_effect=RuntimeError("reached insert")):
        with pytest.raises(Exception, match="reached insert"):
            invites.insert(_invite())


def test_invite_router_answers_409():
    from app.routers import PartRequestInviteRouter as inv_router

    repo = FakeReachRepo(wide_used=2)
    with JoinWorld(repo, [_doc(A, 20, EXH_CAPPED_20)]):
        resp = inv_router.insert(_invite())
    assert resp.status_code == 409
    assert json.loads(resp.body)["code"] == "request_full"


def test_comment_only_edit_with_expansion_growth_not_refused_and_takes_no_slot():
    repo = FakeReachRepo(wide_used=2)
    doc = _doc(A, 15, {"tier": "capped", "day": DAY, "audience": 15})
    extra = _sellers(25, "com")
    with World(repo, [doc]) as w, patch.object(
        prs, "expand_subscribed_sellers_with_accepted_comisionados", side_effect=lambda s, c=None: list(s) + extra
    ):
        prs.edit_part_request([_edit(A, comment="nuevo")])
    assert w.written[0][1]["reach"]["tier"] == "capped"
    assert repo.ids == ["x", "x"]


def test_write_failure_releases_only_unwritten_docs_slots():
    repo = FakeReachRepo(wide_used=0, wide_per_day=2)
    docs = [_doc(A, 40, NORMAL), _doc(B, 40, NORMAL)]
    w = World(repo, docs)
    real = w._write

    def write(doc_id, data):
        if doc_id == B:
            raise RuntimeError("mongo down")
        return real(doc_id, data)

    w.write_mock.side_effect = write
    with w, pytest.raises(Exception):
        prs.edit_part_request([_edit(A, add=_sellers(20, "n")), _edit(B, add=_sellers(20, "m"))])
    assert repo.released == [B]
    assert repo.ids == [A]


def test_join_write_failure_releases_only_unwritten_docs_slots():
    repo = FakeReachRepo(wide_used=0, wide_per_day=2)
    docs = [_doc(A, 49, {"tier": "normal", "day": DAY, "audience": 49}),
            _doc(B, 49, {"tier": "normal", "day": DAY, "audience": 49})]
    w = JoinWorld(repo, docs)
    real = w._write

    def write(doc_id, data):
        if doc_id == B:
            raise RuntimeError("mongo down")
        return real(doc_id, data)

    with w, patch.object(prs.partRequestRepository, "edit_part_request", side_effect=write):
        with pytest.raises(Exception):
            prs.join_seller_to_part_request(PARENT, "new-seller")
    assert repo.released == [B]
    assert repo.ids == [A]


def test_adding_stores_stamps_last_widened_at():
    """The monitor's 30-minute wait to widen again restarts from here."""
    repo = FakeReachRepo(wide_used=0)
    with World(repo, [_doc(A, 10, NORMAL)]) as w:
        prs.edit_part_request([_edit(A, add=_sellers(3, "n"))])
    assert w.written[0][1]["last_widened_at"] == NOW


def test_an_edit_that_adds_no_store_leaves_last_widened_at_alone():
    repo = FakeReachRepo(wide_used=0)
    with World(repo, [_doc(A, 10, NORMAL)]) as w:
        prs.edit_part_request([_edit(A, comment="nuevo")])
    assert "last_widened_at" not in w.written[0][1]
