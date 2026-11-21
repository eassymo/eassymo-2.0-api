"""The store's pickup code: 4 digits, created at assignment, visible only to the selling group while
the order waits for collection, checked on the server with a 5-try lock and a 15-try retirement."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import PickupCodeService as codes

NOW = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)
SELLER_GROUP = "seller-group"


class FakeRepo:
    """In-memory stand-in for the order_pickup_codes collection."""

    def __init__(self):
        self.docs = {}

    def upsert_code(self, order_id, code):
        self.docs[order_id] = {"order_id": order_id, "code": code, "attempts": 0, "total_attempts": 0, "locked_until": None, "retired": False}

    def find(self, order_id):
        d = self.docs.get(order_id)
        return dict(d) if d else None

    def record_wrong_attempt(self, order_id):
        d = self.docs[order_id]
        d["attempts"] += 1
        d["total_attempts"] += 1
        return dict(d)

    def lock_until(self, order_id, until):
        self.docs[order_id].update(locked_until=until, attempts=0)

    def retire(self, order_id):
        self.docs[order_id]["retired"] = True

    def delete(self, order_id):
        self.docs.pop(order_id, None)


@pytest.fixture
def repo():
    fake = FakeRepo()
    with patch.object(codes, "repo", fake):
        yield fake


def _order(status="WAITING_FOR_COLLECTION"):
    return {"_id": "o1", "status": status, "offer": {"group_id": SELLER_GROUP}, "group": "buyer-group"}


def test_code_is_4_digits():
    for _ in range(200):
        c = codes.generate_code()
        assert len(c) == 4 and c.isdigit()


def test_weak_codes_are_never_generated():
    weak = {"0000", "1111", "1234", "2345", "3456", "4567", "5678", "6789", "4321", "9876", "0123", "3210"}
    with patch.object(codes.secrets, "randbelow", side_effect=[0, 1111, 1234, 4321, 4729]):
        assert codes.generate_code() == "4729"
    assert all(codes.is_weak(c) for c in weak)
    assert not codes.is_weak("4729")


def test_store_code_creates_one_and_reset_replaces_it(repo):
    first = codes.assign_code("o1")
    assert repo.find("o1")["code"] == first
    repo.docs["o1"]["attempts"] = 3
    second = codes.reset_code("o1")
    assert repo.find("o1")["code"] == second
    assert repo.find("o1")["attempts"] == 0 and repo.find("o1")["total_attempts"] == 0


def test_only_selling_group_members_get_the_code(repo):
    code = codes.assign_code("o1")
    with patch.object(codes, "_user_in_group", side_effect=lambda uid, gid: (uid, gid) == ("seller-uid", SELLER_GROUP)):
        assert codes.get_code_for_store(_order(), "seller-uid") == code


def test_buyer_members_riders_and_other_groups_get_none(repo):
    codes.assign_code("o1")
    with patch.object(codes, "_user_in_group", side_effect=lambda uid, gid: (uid, gid) == ("seller-uid", SELLER_GROUP)):
        assert codes.get_code_for_store(_order(), "buyer-uid") is None
        assert codes.get_code_for_store(_order(), "rider-uid") is None
        assert codes.get_code_for_store(_order(), None) is None


def test_no_code_once_the_order_is_dispatched(repo):
    codes.assign_code("o1")
    with patch.object(codes, "_user_in_group", return_value=True):
        assert codes.get_code_for_store(_order("DISPATCHED"), "seller-uid") is None
        assert codes.get_code_for_store(_order("CONFIRMED"), "seller-uid") is None


def test_correct_code_verifies(repo):
    code = codes.assign_code("o1")
    r = codes.verify_code("o1", code, NOW)
    assert r.status == "ok"


def test_wrong_code_reports_tries_left(repo):
    codes.assign_code("o1")
    r = codes.verify_code("o1", "0001", NOW)
    assert (r.status, r.tries_left) == ("wrong", 4)
    r = codes.verify_code("o1", "0002", NOW)
    assert (r.status, r.tries_left) == ("wrong", 3)


def test_five_wrong_tries_lock_for_15_minutes(repo):
    code = codes.assign_code("o1")
    for _ in range(4):
        assert codes.verify_code("o1", "9999" if code != "9999" else "8888", NOW).status == "wrong"
    fifth = codes.verify_code("o1", "9999" if code != "9999" else "8888", NOW)
    assert fifth.status == "locked"
    assert fifth.retry_at == NOW + timedelta(minutes=15)
    # even the right code is refused while locked
    assert codes.verify_code("o1", code, NOW + timedelta(minutes=5)).status == "locked"


def test_a_correct_code_after_the_lock_works(repo):
    code = codes.assign_code("o1")
    bad = "9999" if code != "9999" else "8888"
    for _ in range(5):
        codes.verify_code("o1", bad, NOW)
    assert codes.verify_code("o1", code, NOW + timedelta(minutes=15, seconds=1)).status == "ok"


def test_fifteen_wrong_tries_in_total_retire_the_code_and_alert_the_store(repo):
    code = codes.assign_code("o1")
    bad = "9999" if code != "9999" else "8888"
    t = NOW
    with patch.object(codes, "_alert_store_guessing") as alert:
        for _ in range(3):
            for _ in range(5):
                last = codes.verify_code("o1", bad, t)
            t = t + timedelta(minutes=16)
        assert last.status == "exhausted"
        alert.assert_called_once_with("o1")
        assert codes.verify_code("o1", code, t + timedelta(days=1)).status == "exhausted"


def test_reset_replaces_the_code_and_clears_attempts(repo):
    code = codes.assign_code("o1")
    bad = "9999" if code != "9999" else "8888"
    for _ in range(5):
        codes.verify_code("o1", bad, NOW)
    new = codes.reset_code("o1")
    assert codes.verify_code("o1", new, NOW).status == "ok"


def test_an_order_without_a_code_is_reported_as_none(repo):
    assert codes.verify_code("missing", "1234", NOW).status == "none"
