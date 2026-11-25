"""Seller reach cap on create: per-part decide before any insert, slot rollback, preview counts."""
import json
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import PartRequestRouter as router
from app.schemas.PartRequest import PartRequest, ReachPlan
from app.schemas.SellerReach import PreviewIn
from app.services import PartRequestService as prs
from app.services import SellerReachService as reach
from app.services.SellerReachService import SellerReachError

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc)
DAY = "2026-11-25"


class FakeReachRepo:
    def __init__(self, wide_used=0, wide_per_day=2, enforcement="enforce"):
        self.settings = {"wide_threshold": 50, "wide_per_day": wide_per_day, "capped_max": 20, "enforcement": enforcement}
        self.ids = ["x"] * wide_used
        self.events = []
        self.released = []

    def get_settings(self):
        return dict(self.settings)

    def get_override(self, group_id):
        return None

    def get_usage(self, group_id, day):
        return {"wide_used": len(self.ids), "wide_request_ids": list(self.ids)}

    def try_reserve_wide(self, group_id, day, request_id, limit):
        if request_id in self.ids:
            return "already_reserved"
        if len(self.ids) >= limit:
            return "exhausted"
        self.ids.append(request_id)
        return "reserved"

    def release_wide(self, group_id, day, request_id):
        self.released.append(request_id)
        if request_id in self.ids:
            self.ids.remove(request_id)

    def write_event(self, kind, group_id, **fields):
        self.events.append((kind, fields.get("request_id")))


def _sellers(n, prefix="s"):
    return [f"{prefix}{i}" for i in range(n)]


def _request(n_parts=1, sellers=None, followers=None, plan=None, commissioner_group=None):
    return PartRequest(
        creatorGroup="buyer-g",
        creatorUser="buyer-u",
        vehicleId="veh-1",
        subscribedSellers=sellers if sellers is not None else _sellers(64),
        subscribedFollowers=followers,
        partList=[{"name": f"part-{i}"} for i in range(n_parts)],
        fulfillment_type="pickup",
        status="Created",
        reach_plan=plan,
        commissioner_group=commissioner_group,
    )


def _all_compatible(candidates, *_):
    return {"compatible": list(candidates), "excluded": []}


class World:
    """Patches every collaborator of insert/preview; records inserted docs."""

    def __init__(self, repo, commissioner_ids=None, insert_fails_at=None):
        self.repo = repo
        self.commissioner_ids = commissioner_ids or []
        self.insert_fails_at = insert_fails_at
        self.inserted = []
        self.deleted = []
        self.insert_mock = MagicMock(side_effect=self._insert)

    def _insert(self, doc):
        if self.insert_fails_at is not None and len(self.inserted) == self.insert_fails_at:
            raise RuntimeError("mongo down")
        self.inserted.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def _find(self, flt, projection):
        ids = flt["_id"]["$in"]
        return [d for d in self.inserted if d["_id"] in ids]

    def _connections(self, creator_group_id, commissioner_group_id):
        return {
            "commissioner_groups_from_lists": [SimpleNamespace(id=i) for i in self.commissioner_ids],
            "users_from_groups": [],
        }

    def __enter__(self):
        self.stack = ExitStack()
        p = self.stack.enter_context
        p(patch.object(reach, "repo", self.repo))
        p(patch.object(prs.groupCarRepository, "find_by_id", return_value=None))
        p(patch.object(prs.groupRepository, "find_by_id", return_value=None))
        p(patch.object(prs, "__find_commissioner_group_connections", side_effect=self._connections))
        p(patch.object(prs, "expand_subscribed_sellers_with_accepted_comisionados", side_effect=lambda s, c=None: list(s)))
        p(patch.object(prs.ArmadoraCompatibilityService, "evaluate_bulk", side_effect=_all_compatible))
        p(patch.object(prs.SistemasCompatibilityService, "evaluate_bulk_for_car_part", side_effect=_all_compatible))
        p(patch.object(prs.partRequestRepository, "insert", self.insert_mock))
        p(patch.object(prs.partRequestRepository, "find", side_effect=self._find))
        p(patch.object(prs.partRequestRepository, "delete_by_ids", side_effect=lambda ids: self.deleted.extend(ids)))
        p(patch("app.services.notification_fanout.fanout_part_request_created"))
        p(patch.object(prs, "_now", return_value=NOW))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


def test_insert_three_parts_with_one_slot_and_plan():
    repo = FakeReachRepo(wide_used=1)
    capped = _sellers(20)
    plan = ReachPlan(wide_part_indexes=[0], capped_sellers=capped)
    with World(repo) as w:
        prs.insert(_request(n_parts=3, plan=plan))
    tiers = [d["reach"]["tier"] for d in w.inserted]
    assert tiers == ["wide", "capped", "capped"]
    assert [d["reach"]["audience"] for d in w.inserted] == [64, 20, 20]
    assert all(d["reach"]["day"] == DAY for d in w.inserted)
    assert w.inserted[1]["subscribedSellers"] == capped
    assert w.inserted[2]["subscribedSellers"] == capped
    assert len(w.inserted[0]["subscribedSellers"]) == 64
    assert "reach_plan" not in w.inserted[0]
    assert repo.ids[-1] == str(w.inserted[0]["_id"])


def test_insert_rejects_capped_sellers_outside_selection():
    plan = ReachPlan(wide_part_indexes=[], capped_sellers=["stranger"])
    with World(FakeReachRepo()) as w, pytest.raises(HTTPException) as exc:
        prs.insert(_request(plan=plan))
    assert exc.value.status_code == 400
    w.insert_mock.assert_not_called()


def test_insert_without_plan_over_limit_refuses_and_inserts_nothing():
    repo = FakeReachRepo(wide_used=2)
    with World(repo) as w, pytest.raises(SellerReachError) as exc:
        prs.insert(_request(sellers=_sellers(30)))
    assert exc.value.status_code == 409
    assert exc.value.code == "seller_cap_exceeded"
    w.insert_mock.assert_not_called()


def test_insert_refusal_on_later_part_releases_earlier_slot():
    repo = FakeReachRepo(wide_used=1)
    with World(repo) as w, pytest.raises(SellerReachError):
        prs.insert(_request(n_parts=2))
    w.insert_mock.assert_not_called()
    assert len(repo.released) == 1
    assert repo.ids == ["x"]


def test_insert_releases_slot_when_insert_fails():
    repo = FakeReachRepo(wide_used=0)
    with World(repo, insert_fails_at=1) as w, pytest.raises(HTTPException) as exc:
        prs.insert(_request(n_parts=2))
    assert exc.value.status_code == 500
    part0_id = str(w.inserted[0]["_id"])
    assert part0_id in repo.released
    assert len(repo.released) == 2  # part 1 reserved before any insert, too
    assert repo.ids == []
    assert w.deleted == [w.inserted[0]["_id"]]  # no part left stamped without its slot
    assert ("wide_released", part0_id) in repo.events


def test_preview_counts_commissioner_expansion():
    repo = FakeReachRepo(wide_used=0)
    payload = PreviewIn(
        group_id="buyer-g",
        vehicle_id="veh-1",
        part_list=[{"name": "a"}],
        subscribed_sellers=_sellers(20),
        commissioner_group="comm-g",
    )
    with World(repo, commissioner_ids=_sellers(3, "c")):
        out = reach.preview(payload, NOW)
    assert out["parts"] == [{"index": 0, "audience": 23, "needs_wide": False}]
    assert out["today"]["wide_left"] == 2
    assert repo.ids == [] and repo.events == []


def test_preview_flags_needs_wide_at_threshold():
    payload = PreviewIn(group_id="buyer-g", vehicle_id="veh-1", part_list=[{"name": "a"}],
                        subscribed_sellers=_sellers(47), commissioner_group="comm-g")
    with World(FakeReachRepo(), commissioner_ids=_sellers(3, "c")):
        out = reach.preview(payload, NOW)
    assert out["parts"][0] == {"index": 0, "audience": 50, "needs_wide": True}


def test_compute_part_audiences_shape():
    with World(FakeReachRepo()):
        parts = prs.compute_part_audiences("buyer-g", "veh-1", [{"name": "a"}, {"name": "b"}],
                                           ["s1", "s2"], ["f1", "s1"], None)
    assert parts == [
        {"index": 0, "subscribed": ["s1", "s2"], "non_compatible": [], "audience": 3},
        {"index": 1, "subscribed": ["s1", "s2"], "non_compatible": [], "audience": 3},
    ]


def test_insert_counts_followers():
    repo = FakeReachRepo(wide_used=0)
    with World(repo) as w:
        prs.insert(_request(sellers=_sellers(45), followers=_sellers(5, "f")))
    assert w.inserted[0]["reach"] == {"tier": "wide", "day": DAY, "audience": 50}


def test_insert_keeps_http_status():
    repo = FakeReachRepo(wide_used=2)
    req = SimpleNamespace(headers={})
    with World(repo) as w:
        resp = router.create(req, _request(sellers=_sellers(30)))
    assert resp.status_code == 409
    body = json.loads(resp.body)
    assert body["code"] == "seller_cap_exceeded"
    assert body["data"]["wide_left"] == 0
    w.insert_mock.assert_not_called()
