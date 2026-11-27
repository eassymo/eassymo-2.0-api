"""The buyer removes one part of a request: its offers move whole to OffersArchive, the part goes inactive with who and
when, and only the stores that quoted it hear about it. A second tap changes nothing."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException

from app.authz import grant_keys as g
from app.routers import PartRequestRouter as router_mod
from app.services import PartRemovalService as svc
from app.services import authz
from tests.asgi_client import AsgiClient

# The real membership check, kept before the fixtures below patch it.
REAL_IN_GROUP = svc._user_in_group

PR_ID = str(ObjectId())
BUYER = str(ObjectId())
STORE_A = str(ObjectId())
STORE_B = str(ObjectId())


@contextmanager
def store_members(groups, users=None, roles=()):
    """Membership as the grant check reads it (app/dependencies/group_auth.py): a group's `users` and `owner`, a user's
    `groups`, and active user_roles rows given as (uid, group_id)."""
    from app.dependencies import group_auth

    group_repo, user_repo, roles_repo = MagicMock(), MagicMock(), MagicMock()
    group_repo.find_by_id.side_effect = lambda gid, *a: groups.get(str(gid))
    user_repo.find_one.side_effect = lambda q: (users or {}).get(q["uid"])
    roles_repo.find.side_effect = lambda q: [
        {"user_uid": u, "group": gid} for u, gid in roles if (u, gid) == (q["user_uid"], q["group"]) and q["active"]]
    with patch.object(group_auth, "groupRepository", group_repo), patch.object(group_auth, "userRepository", user_repo), \
         patch.object(group_auth, "userRolesRepository", roles_repo):
        yield


# Members of the buyer's store who are not in its `users` list, and a member of another store.
MEMBERS = dict(
    groups={BUYER: {"users": ["u1"], "owner": "owner-1"}, STORE_A: {"users": ["a1"]}},
    users={"listed-1": {"groups": [BUYER]}},
    roles=[("role-1", BUYER), ("other-1", STORE_A)],
)
BUYER_MEMBERS_OUTSIDE_USERS = ["owner-1", "listed-1", "role-1"]


def _part(**extra):
    return {"_id": ObjectId(PR_ID), "creatorGroup": BUYER, "isActive": True,
            "part": {"tipoParteDescripcion": "Abrazadera De Manguera De Bomba De Agua"},
            "vehicleInformation": {}, **extra}


def _offer(group_id, price=980, status="Created"):
    return {"_id": ObjectId(), "request_id": PR_ID, "group_id": group_id, "price": price, "status": status}


@pytest.fixture
def env():
    parts, offers, archive, orders = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    groups, group_service, notifications = MagicMock(), MagicMock(), MagicMock()
    parts.find_one_by_id.return_value = _part()
    parts.count_live_others.return_value = (1, 1)  # (live, live and not being removed): another part stays
    offers.find.return_value = []
    orders.find_one.return_value = None
    groups.find_by_id.return_value = {"_id": ObjectId(BUYER), "name": "MOFLES SOLIDARIDAD"}
    group_service.find_users_by_groups_ids_v2.return_value = [
        {"_id": STORE_A, "users": ["a1", "a2"]}, {"_id": STORE_B, "users": ["b1"]}]
    calls, stored, claim = [], {}, {"ok": True}
    archive.upsert.side_effect = lambda doc: calls.append("archive") or stored.update({doc["_id"]: doc})
    archive.find.side_effect = lambda q: [d for d in stored.values() if d["request_id"] == q["request_id"]
                                          and d["discard"]["reason"] == q["discard.reason"]]
    parts.claim_removal.side_effect = lambda *a: calls.append("claim") or claim["ok"]
    parts.release_removal.side_effect = lambda *a: calls.append("release")
    offers.delete_many.side_effect = lambda filters: calls.append("delete")
    parts.edit_part_request.side_effect = lambda pid, data: calls.append("part")
    sent = []
    with patch.object(svc, "partRequestRepository", parts), patch.object(svc, "offerRepository", offers), \
         patch.object(svc, "offerArchiveRepository", archive), \
         patch.object(svc.OfferWithdrawalService, "orderRepository", orders), \
         patch.object(svc, "groupRepository", groups), patch.object(svc, "groupService", group_service), \
         patch.object(svc, "NotificationService", notifications), \
         patch.object(svc, "send_notifications_batch", side_effect=lambda batch: sent.extend(batch)), \
         patch.object(svc, "_user_in_group", side_effect=lambda uid, gid: uid == "u1" and gid == BUYER):
        yield {"parts": parts, "offers": offers, "archive": archive, "orders": orders, "calls": calls, "sent": sent,
               "notifications": notifications, "group_service": group_service, "claim": claim}


def _error(*args):
    with pytest.raises(HTTPException) as exc:
        svc.remove(*args)
    return exc.value.status_code, exc.value.detail


def test_removes_part_and_archives_every_offer(env):
    three = [_offer(STORE_A), _offer(STORE_A), _offer(STORE_B)]
    env["offers"].find.return_value = three

    result = svc.remove(PR_ID, "u1", BUYER)

    assert env["calls"] == ["claim", "archive", "archive", "archive", "delete", "part"]
    archived = [c.args[0] for c in env["archive"].upsert.call_args_list]
    assert [a["_id"] for a in archived] == [o["_id"] for o in three]
    for doc in archived:
        assert doc["discard"]["reason"] == "part_removed"
        assert doc["discard"]["by"] == "u1"
        assert doc["discard"]["previous_status"] == "Created"
        assert doc["discard"]["at"].tzinfo is not None
    assert env["offers"].delete_many.call_args.args[0] == {"_id": {"$in": [o["_id"] for o in three]}}
    pid, data = env["parts"].edit_part_request.call_args.args
    assert pid == PR_ID
    assert data["isActive"] is False
    assert data["removed"]["by"] == "u1" and data["removed"]["at"].tzinfo is not None
    assert data["updatedAt"] == data["removed"]["at"]
    assert result["_id"] == PR_ID
    assert result["discarded_offer_ids"] == [str(o["_id"]) for o in three]


def test_notifies_each_store_with_offers_once(env):
    env["offers"].find.return_value = [_offer(STORE_A, 300), _offer(STORE_A, 420), _offer(STORE_B, 185)]

    result = svc.remove(PR_ID, "u1", BUYER)

    env["group_service"].find_users_by_groups_ids_v2.assert_called_once_with([STORE_A, STORE_B])
    sent = env["sent"]
    assert sorted(n.owner for n in sent) == ["a1", "a2", "b1"]
    by_owner = {n.owner: n for n in sent}
    assert by_owner["a1"].ownerGroup == STORE_A and by_owner["b1"].ownerGroup == STORE_B
    assert by_owner["a1"].body == "Tus 2 ofertas se descartaron"
    assert by_owner["a2"].body == "Tus 2 ofertas se descartaron"
    assert by_owner["b1"].body == "Tu oferta de $185.00 se descartó"
    for n in sent:
        assert n.type.value == "PART_REMOVED"
        assert n.title == "Mofles Solidaridad quitó Abrazadera de manguera de bomba de agua"
        assert n.side == "sell"
        assert n.action == {"label": "Ver solicitud", "href": f"/offer-creator-v4/{PR_ID}"}
        assert n.navigateToUrl == f"/offer-creator-v4/{PR_ID}"
        assert n.metaData == {"requestId": PR_ID}
    assert result["notified_group_ids"] == [STORE_A, STORE_B]


def test_no_offers_notifies_no_one(env):
    result = svc.remove(PR_ID, "u1", BUYER)

    assert env["sent"] == []
    env["group_service"].find_users_by_groups_ids_v2.assert_not_called()
    env["archive"].upsert.assert_not_called()
    env["offers"].delete_many.assert_not_called()
    assert env["calls"] == ["claim", "part"]
    assert result == {"_id": PR_ID, "discarded_offer_ids": [], "notified_group_ids": []}


def test_live_order_is_409_and_changes_nothing(env):
    offers = [_offer(STORE_A), _offer(STORE_B, status="Selected")]
    env["offers"].find.return_value = offers
    env["orders"].find_one.side_effect = lambda q: (
        {"_id": "o1", "status": "CONFIRMED"} if offers[1]["_id"] in q["offer._id"]["$in"] else None)

    assert _error(PR_ID, "u1", BUYER) == (409, "Ya pediste esta pieza. Para quitarla, cancela el pedido primero.")
    assert env["calls"] == ["claim", "release"]
    env["parts"].edit_part_request.assert_not_called()
    assert env["sent"] == []
    env["notifications"].resolve_decisions_prefix.assert_not_called()


def test_canceled_order_does_not_block(env):
    env["offers"].find.return_value = [_offer(STORE_A)]

    svc.remove(PR_ID, "u1", BUYER)

    query = env["orders"].find_one.call_args.args[0]
    assert query["status"] == {"$ne": "CANCELED"}
    env["archive"].upsert.assert_called_once()


def test_not_in_creator_group_is_403(env):
    env["offers"].find.return_value = [_offer(STORE_A)]

    assert _error(PR_ID, "intruder", BUYER) == (403, "Solo quien creó la solicitud puede quitar piezas.")
    assert env["calls"] == []


@pytest.mark.parametrize("part_request_id,found", [(PR_ID, None), ("not-an-id", _part())])
def test_missing_is_404(env, part_request_id, found):
    env["parts"].find_one_by_id.return_value = found

    assert _error(part_request_id, "u1", BUYER) == (404, "Esta pieza ya no existe.")


def test_already_removed_is_idempotent(env):
    env["parts"].find_one_by_id.return_value = _part(isActive=False, removed={"by": "u1", "at": None})
    env["offers"].find.return_value = [_offer(STORE_A)]

    result = svc.remove(PR_ID, "u1", BUYER)

    assert result == {"_id": PR_ID, "discarded_offer_ids": [], "notified_group_ids": []}
    assert env["calls"] == []
    assert env["sent"] == []
    env["offers"].find.assert_not_called()


def test_losing_the_claim_after_the_part_was_removed_is_idempotent(env):
    """A second tap that loses the claim to a removal that finished meanwhile: 200, nothing changed or reported."""
    env["claim"]["ok"] = False
    env["parts"].find_one_by_id.side_effect = [_part(), _part(isActive=False, removed={"by": "u1", "at": None})]
    env["offers"].find.return_value = [_offer(STORE_A)]

    result = svc.remove(PR_ID, "u1", BUYER)

    assert result == {"_id": PR_ID, "discarded_offer_ids": [], "notified_group_ids": []}
    assert env["calls"] == ["claim"]
    assert env["sent"] == []
    env["offers"].find.assert_not_called()


def test_losing_the_claim_while_the_part_is_still_there_is_409(env):
    """Another request holds the claim (still running, or died before releasing it): never report a removal that
    hasn't happened."""
    env["claim"]["ok"] = False
    env["offers"].find.return_value = [_offer(STORE_A)]

    assert _error(PR_ID, "u1", BUYER) == (409, "Esta pieza se está quitando. Intenta de nuevo en un momento.")
    assert env["calls"] == ["claim"]
    assert env["parts"].find_one_by_id.call_count == 2
    assert env["sent"] == []
    env["offers"].find.assert_not_called()
    env["parts"].edit_part_request.assert_not_called()


def test_claim_lets_a_stale_one_be_taken_over(env):
    svc.remove(PR_ID, "u1", BUYER)

    pid, uid, at, stale_before = env["parts"].claim_removal.call_args.args
    assert (pid, uid) == (PR_ID, "u1")
    assert at - stale_before == svc.STALE_CLAIM


@pytest.mark.parametrize("fail_at", ["archive", "delete", "part"])
def test_a_failed_removal_can_be_retried(env, fail_at):
    """The first try dies midway; the retry finishes it, lists every discarded offer and notifies each store."""
    offers = [_offer(STORE_A, 300), _offer(STORE_A, 420), _offer(STORE_B, 185)]
    left = list(offers)
    env["offers"].find.side_effect = lambda q: list(left)
    delete = env["offers"].delete_many.side_effect
    env["offers"].delete_many.side_effect = lambda f: delete(f) or left.clear()
    boom = {"armed": True}

    def fail_once(target, attr):
        original = getattr(env[target], attr).side_effect

        def run(*args):
            if boom["armed"] and (fail_at != "archive" or len(env["archive"].upsert.call_args_list) == 2):
                boom["armed"] = False
                raise RuntimeError("mongo went away")
            return original(*args)
        getattr(env[target], attr).side_effect = run

    fail_once(*{"archive": ("archive", "upsert"), "delete": ("offers", "delete_many"),
                "part": ("parts", "edit_part_request")}[fail_at])

    with pytest.raises(RuntimeError):
        svc.remove(PR_ID, "u1", BUYER)
    assert env["calls"][-1] == "release"
    assert env["sent"] == []

    result = svc.remove(PR_ID, "u1", BUYER)

    assert sorted(result["discarded_offer_ids"]) == sorted(str(o["_id"]) for o in offers)
    assert result["notified_group_ids"] == [STORE_A, STORE_B]
    assert env["parts"].edit_part_request.call_args.args[1]["removed"]["by"] == "u1"
    assert sorted(n.owner for n in env["sent"]) == ["a1", "a2", "b1"]
    assert {n.owner: n.body for n in env["sent"]}["b1"] == "Tu oferta de $185.00 se descartó"


def test_member_acting_for_another_store_is_403(env):
    """The grant is checked in the selected store; the part must belong to that same store."""
    with patch.object(svc, "_user_in_group", return_value=True):
        assert _error(PR_ID, "u1", STORE_A) == (403, "Solo quien creó la solicitud puede quitar piezas.")
    assert env["calls"] == []


@pytest.mark.parametrize("uid", BUYER_MEMBERS_OUTSIDE_USERS)
def test_any_member_the_grant_check_accepts_may_remove(env, uid):
    """Owner, the user's own groups list, an active role: the same membership require_grant uses."""
    with patch.object(svc, "_user_in_group", REAL_IN_GROUP), store_members(**MEMBERS):
        assert svc.remove(PR_ID, uid, BUYER)["_id"] == PR_ID
    assert env["parts"].edit_part_request.call_args.args[1]["removed"]["by"] == uid


def test_member_of_another_store_is_403_with_the_real_check(env):
    with patch.object(svc, "_user_in_group", REAL_IN_GROUP), store_members(**MEMBERS):
        assert _error(PR_ID, "other-1", BUYER) == (403, "Solo quien creó la solicitud puede quitar piezas.")
    assert env["calls"] == []


def test_membership_of_an_invalid_group_id_is_false():
    from app.services import authz as authz_mod
    assert authz_mod.is_member("u1", "not-a-group-id") is False


# ── Last part ────────────────────────────────────────────────────────────────

def test_last_live_part_is_409_and_changes_nothing(env):
    env["parts"].count_live_others.return_value = (0, 0)
    env["offers"].find.return_value = [_offer(STORE_A)]

    assert _error(PR_ID, "u1", BUYER) == (409, "Una solicitud necesita al menos una pieza.")
    assert env["calls"] == ["claim", "release"]
    env["offers"].find.assert_not_called()
    env["archive"].upsert.assert_not_called()
    env["parts"].edit_part_request.assert_not_called()
    assert env["sent"] == []


def test_others_all_being_removed_is_409_in_progress(env):
    env["parts"].count_live_others.return_value = (1, 0)

    assert _error(PR_ID, "u1", BUYER) == (409, "Esta pieza se está quitando. Intenta de nuevo en un momento.")
    assert env["calls"] == ["claim", "release"]
    env["parts"].edit_part_request.assert_not_called()


def test_last_part_count_runs_after_the_claim_with_the_stale_cutoff(env):
    svc.remove(PR_ID, "u1", BUYER)

    part, stale_before = env["parts"].count_live_others.call_args.args
    _, _, at, claim_stale_before = env["parts"].claim_removal.call_args.args
    assert part["_id"] == ObjectId(PR_ID)
    assert stale_before == claim_stale_before == at - svc.STALE_CLAIM


def test_already_removed_short_circuits_before_the_last_part_check(env):
    env["parts"].find_one_by_id.return_value = _part(isActive=False, removed={"by": "u1", "at": None})
    env["parts"].count_live_others.return_value = (0, 0)

    assert svc.remove(PR_ID, "u1", BUYER) == {"_id": PR_ID, "discarded_offer_ids": [], "notified_group_ids": []}
    env["parts"].count_live_others.assert_not_called()


_MISSING = object()


def _matches(doc, filters):
    """Just enough of Mongo's query language for the repository's part queries."""
    for key, want in filters.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in want):
                return False
            continue
        value = doc
        for step in key.split("."):
            value = value.get(step, _MISSING) if isinstance(value, dict) else _MISSING
        if isinstance(want, dict) and want and all(op.startswith("$") for op in want):
            for op, arg in want.items():
                ok = {"$ne": lambda: value != arg,
                      "$in": lambda: (None if value is _MISSING else value) in arg,
                      "$exists": lambda: (value is not _MISSING) == arg,
                      "$lt": lambda: value is not _MISSING and value < arg}[op]()
                if not ok:
                    return False
        elif value != want:
            return False
    return True


class TwoParts:
    """An in-memory PartRequests, two live parts of one order by default. Claims behave like the repository's;
    `count_live_others` is the repository's own, run on these docs."""

    def __init__(self, *groupings):
        groupings = groupings or ({"parent_request_uid": "p-1", "specific_order_uid": "so-1"},) * 2
        self.ids = [str(ObjectId()) for _ in groupings]
        self.docs = {i: {"_id": ObjectId(i), "creatorGroup": BUYER, "isActive": True, "part": {},
                         "vehicleInformation": {}, **grouping} for i, grouping in zip(self.ids, groupings)}
        self.lock = __import__("threading").Lock()

    def find_one_by_id(self, i):
        return dict(self.docs[i])

    def claim_removal(self, i, uid, at, stale_before):
        with self.lock:
            doc = self.docs[i]
            if doc.get("removed") or (doc.get("removing") and doc["removing"]["at"] >= stale_before):
                return False
            doc["removing"] = {"by": uid, "at": at}
            return True

    def release_removal(self, i, uid, at):
        with self.lock:
            if self.docs[i].get("removing") == {"by": uid, "at": at}:
                del self.docs[i]["removing"]

    def count_live_others(self, part, stale_before):
        from app.repositories import PartRequestRepository as repo

        collection = MagicMock()
        collection.count_documents.side_effect = lambda f: sum(1 for d in self.docs.values() if _matches(d, f))
        with self.lock, patch.object(repo.database, "db", {"PartRequests": collection}):
            return repo.count_live_others(part, stale_before)

    def edit_part_request(self, i, data):
        with self.lock:
            self.docs[i].update(data)


def test_concurrent_removals_of_the_last_two_parts_never_both_succeed(env):
    import threading

    store = TwoParts()
    both_claimed = threading.Barrier(2, timeout=5)
    count = store.count_live_others

    def count_after_both_claims(part, stale_before):
        both_claimed.wait()
        return count(part, stale_before)

    for name in ("find_one_by_id", "claim_removal", "release_removal", "edit_part_request"):
        setattr(env["parts"], name, getattr(store, name))
    env["parts"].count_live_others = count_after_both_claims
    outcomes = {}

    def run(i):
        try:
            outcomes[i] = svc.remove(i, "u1", BUYER)
        except HTTPException as e:
            outcomes[i] = (e.status_code, e.detail)

    threads = [threading.Thread(target=run, args=(i,)) for i in store.ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)

    # Each saw the other's claim. Whichever checked after the other had already given up may go ahead; never both.
    succeeded = [i for i in store.ids if isinstance(outcomes[i], dict)]
    assert len(succeeded) <= 1, outcomes
    assert all(outcomes[i] == (409, "Esta pieza se está quitando. Intenta de nuevo en un momento.")
               for i in store.ids if i not in succeeded), outcomes
    assert sum(1 for d in store.docs.values() if d.get("removed")) == len(succeeded)
    assert not any(d.get("removing") for i, d in store.docs.items() if i not in succeeded)  # losers released


def _use(env, store):
    for name in ("find_one_by_id", "claim_removal", "release_removal", "count_live_others", "edit_part_request"):
        setattr(env["parts"], name, getattr(store, name))


def test_after_one_of_two_parts_goes_the_other_is_the_last(env):
    store = TwoParts()
    _use(env, store)
    first, second = store.ids

    assert svc.remove(first, "u1", BUYER)["_id"] == first
    assert _error(second, "u1", BUYER) == (409, "Una solicitud necesita al menos una pieza.")
    assert store.docs[first]["removed"]["by"] == "u1"
    assert "removed" not in store.docs[second] and "removing" not in store.docs[second]


@pytest.mark.parametrize("which", [0, 1])
def test_one_part_per_order_under_one_parent_is_the_last_part(env, which):
    """The edit screen lists a request by its order uid: two orders under one parent batch are two requests."""
    store = TwoParts({"parent_request_uid": "p-1", "specific_order_uid": "so-1"},
                     {"parent_request_uid": "p-1", "specific_order_uid": "so-2"})
    _use(env, store)

    assert _error(store.ids[which], "u1", BUYER) == (409, "Una solicitud necesita al menos una pieza.")
    assert not any(d.get("removed") or d.get("removing") for d in store.docs.values())


def test_two_parts_of_one_order_one_can_go(env):
    store = TwoParts({"parent_request_uid": "p-1", "specific_order_uid": "so-1"},
                     {"parent_request_uid": "p-2", "specific_order_uid": "so-1"})
    _use(env, store)

    assert svc.remove(store.ids[0], "u1", BUYER)["_id"] == store.ids[0]
    assert store.docs[store.ids[0]]["removed"]["by"] == "u1"


@pytest.mark.parametrize("other", [{"status": "Offer_Selected"}, {"status": "Closed"}])
def test_a_sibling_in_any_status_keeps_the_request(env, other):
    """An ordered (or otherwise not open) part still keeps the request alive."""
    store = TwoParts({"specific_order_uid": "so-1", "status": "Created"}, {"specific_order_uid": "so-1", **other})
    _use(env, store)

    assert svc.remove(store.ids[0], "u1", BUYER)["_id"] == store.ids[0]


def test_pos_part_without_parent_groups_by_its_order(env):
    store = TwoParts({"parent_request_uid": "", "specific_order_uid": "so-1"},
                     {"parent_request_uid": "", "specific_order_uid": "so-1"},
                     {"parent_request_uid": "", "specific_order_uid": "so-2"})
    _use(env, store)

    assert svc.remove(store.ids[0], "u1", BUYER)["_id"] == store.ids[0]
    assert _error(store.ids[1], "u1", BUYER) == (409, "Una solicitud necesita al menos una pieza.")
    assert _error(store.ids[2], "u1", BUYER) == (409, "Una solicitud necesita al menos una pieza.")


def test_part_without_order_uid_groups_by_its_parent(env):
    store = TwoParts({"parent_request_uid": "p-1", "specific_order_uid": ""},
                     {"parent_request_uid": "p-1"},
                     {"parent_request_uid": "p-1", "specific_order_uid": "so-1"})  # has an order: not this request
    _use(env, store)

    assert svc.remove(store.ids[0], "u1", BUYER)["_id"] == store.ids[0]
    assert _error(store.ids[1], "u1", BUYER) == (409, "Una solicitud necesita al menos una pieza.")


def test_resolves_pending_quote_decisions(env):
    env["offers"].find.return_value = [_offer(STORE_A)]

    svc.remove(PR_ID, "u1", BUYER)

    env["notifications"].resolve_decisions_prefix.assert_called_once_with(f"request:{PR_ID}:quote:")


# ── Route ────────────────────────────────────────────────────────────────────

HEADERS = {"GroupSelected": BUYER}


@pytest.fixture
def grants():
    return {"keys": frozenset({g.REQUESTS_EDIT})}


@pytest.fixture
def route(grants):
    app = FastAPI()
    app.include_router(router_mod.partRequestRouter)
    with patch.object(authz, "caller_uid", return_value="u1"), \
         patch.object(authz, "effective_grants", side_effect=lambda *a: grants["keys"]), \
         patch.object(svc, "remove") as remove:
        client = AsgiClient(app)
        post = client.post
        client.post = lambda url, json=None, headers=None: post(url, json=json, headers={**HEADERS, **(headers or {})})
        yield client, remove


def test_route_without_the_edit_grant_is_403(route, grants):
    client, remove = route
    grants["keys"] = frozenset({g.REQUESTS_VIEW})

    r = client.post(f"/partRequest/{PR_ID}/remove")

    assert r.status_code == 403 and g.REQUESTS_EDIT in r.text
    remove.assert_not_called()


def test_route_returns_the_removal(route):
    client, remove = route
    remove.return_value = {"_id": PR_ID, "discarded_offer_ids": ["o1"], "notified_group_ids": [STORE_A]}

    r = client.post(f"/partRequest/{PR_ID}/remove")

    assert r.status_code == 200
    assert r.json()["body"] == {"_id": PR_ID, "discarded_offer_ids": ["o1"], "notified_group_ids": [STORE_A]}
    remove.assert_called_once_with(PR_ID, "u1", BUYER)


def test_route_passes_the_service_409_through(route):
    client, remove = route
    remove.side_effect = HTTPException(status_code=409, detail="Ya pediste esta pieza. Para quitarla, cancela el pedido primero.")

    r = client.post(f"/partRequest/{PR_ID}/remove")

    assert r.status_code == 409 and "Ya pediste esta pieza" in r.text


# ── Repositories ─────────────────────────────────────────────────────────────

def test_claim_needs_no_removal_and_no_fresh_claim():
    from datetime import datetime, timedelta, timezone

    from app.repositories import PartRequestRepository as repo

    db = {"PartRequests": MagicMock()}
    db["PartRequests"].find_one_and_update.return_value = None
    now = datetime.now(timezone.utc)
    with patch.object(repo.database, "db", db):
        assert repo.claim_removal(PR_ID, "u1", now, now - timedelta(minutes=2)) is False
        repo.release_removal(PR_ID, "u1", now)
    query, update = db["PartRequests"].find_one_and_update.call_args.args
    assert query == {"_id": ObjectId(PR_ID), "removed": {"$exists": False},
                     "$or": [{"removing": {"$exists": False}}, {"removing.at": {"$lt": now - timedelta(minutes=2)}}]}
    assert update == {"$set": {"removing": {"by": "u1", "at": now}}}
    assert db["PartRequests"].update_one.call_args.args == (
        {"_id": ObjectId(PR_ID), "removing.by": "u1", "removing.at": now}, {"$unset": {"removing": ""}})


def _count_queries(part, live=2, free=1):
    from datetime import datetime, timezone

    from app.repositories import PartRequestRepository as repo

    coll = MagicMock()
    coll.count_documents.side_effect = [live, free]
    stale_before = datetime(2026, 11, 27, tzinfo=timezone.utc)
    with patch.object(repo.database, "db", {"PartRequests": coll}):
        result = repo.count_live_others(part, stale_before)
    return result, [c.args[0] for c in coll.count_documents.call_args_list], stale_before


def test_live_others_share_the_order_uid_even_with_a_parent():
    result, queries, stale_before = _count_queries(_part(parent_request_uid="p-1", specific_order_uid="so-1"))

    live = {"creatorGroup": BUYER, "specific_order_uid": "so-1", "_id": {"$ne": ObjectId(PR_ID)},
            "isActive": {"$ne": False}, "removed": {"$exists": False}}
    assert result == (2, 1)
    assert queries == [live, {**live, "$or": [{"removing": {"$exists": False}},
                                              {"removing.at": {"$lt": stale_before}}]}]


def test_pos_part_without_parent_uid_groups_by_its_order():
    _, queries, _ = _count_queries(_part(parent_request_uid="", specific_order_uid="so-1"))

    assert queries[0] == {"creatorGroup": BUYER, "specific_order_uid": "so-1", "_id": {"$ne": ObjectId(PR_ID)},
                          "isActive": {"$ne": False}, "removed": {"$exists": False}}


@pytest.mark.parametrize("order_uid", ["", None])
def test_part_without_order_uid_groups_by_parent_among_parts_without_one(order_uid):
    _, queries, _ = _count_queries(_part(parent_request_uid="p-1", specific_order_uid=order_uid))

    assert queries[0] == {"creatorGroup": BUYER, "parent_request_uid": "p-1",
                          "specific_order_uid": {"$in": [None, ""]}, "_id": {"$ne": ObjectId(PR_ID)},
                          "isActive": {"$ne": False}, "removed": {"$exists": False}}


@pytest.mark.parametrize("group", [{}, {"parent_request_uid": "", "specific_order_uid": ""}])
def test_part_with_no_group_is_alone(group):
    result, queries, _ = _count_queries(_part(**group))

    assert result == (0, 0) and queries == []


def test_no_live_others_skips_the_second_count():
    result, queries, _ = _count_queries(_part(parent_request_uid="p-1"), live=0)

    assert result == (0, 0) and len(queries) == 1


def test_archive_upsert_replaces_an_earlier_copy():
    from app.repositories import OfferArchiveRepository as repo

    db = {"OffersArchive": MagicMock()}
    doc = _offer(STORE_A)
    with patch.object(repo.database, "db", db):
        repo.upsert(doc)
    db["OffersArchive"].replace_one.assert_called_once_with({"_id": doc["_id"]}, doc, upsert=True)


def test_sister_part_list_leaves_out_removed_parts():
    from app.repositories import PartRequestRepository as repo
    with patch.object(repo, "database") as database:
        repo.find_sister_part_requests("order-1", status="Created")
    filters = database.db["PartRequests"].find.call_args.args[0]
    assert filters == {"specific_order_uid": "order-1", "status": "Created", "removed": {"$exists": False}}


def test_joining_seller_is_never_subscribed_to_removed_parts():
    from app.services import PartRequestService as prs
    with patch.object(prs.partRequestRepository, "find", return_value=[]) as find:
        with pytest.raises(HTTPException):
            prs.join_seller_to_part_request("order-1", "new-seller")
    assert find.call_args.args[0] == {"specific_order_uid": "order-1", "removed": {"$exists": False}}


# ── A part with neither parent uid nor order uid ─────────────────────────────

@pytest.mark.parametrize("order_uid", ["", None])
def test_edit_lists_a_part_without_order_uid_alone(order_uid):
    """The edit screen lists the request's parts from `partList`. With no order uid, the sister query would match every
    buyer's parts without one (the shared "" bucket), so the part is listed alone, as the last-part guard counts it."""
    from app.services import PartRequestService as prs

    doc = {**_part(parent_request_uid="", specific_order_uid=order_uid, status="Created"),
           "createdAt": "2026-11-27T09:00:00Z", "updatedAt": "2026-11-27T09:00:00Z", "group_info": {}}
    with patch.object(prs.partRequestRepository, "find_by_id", return_value=[doc]), \
         patch.object(prs.partRequestRepository, "find_sister_part_requests") as sisters, \
         patch.object(prs.offerRepository, "find", return_value=[]):
        found = prs.find_by_id(PR_ID, None)
    sisters.assert_not_called()
    assert [(p["_id"], p["part"]) for p in found["partList"]] == [(PR_ID, doc["part"])]


@pytest.mark.parametrize("extra", [{"status": "Closed"}, {"removed": {"by": "u1", "at": None}}])
def test_a_part_without_order_uid_that_is_not_open_lists_nothing(extra):
    """Same rule as the sister query: only open parts that weren't removed."""
    from app.services import PartRequestService as prs

    doc = {**_part(parent_request_uid="", specific_order_uid="", status="Created"), **extra,
           "createdAt": "2026-11-27T09:00:00Z", "updatedAt": "2026-11-27T09:00:00Z", "group_info": {}}
    with patch.object(prs.partRequestRepository, "find_by_id", return_value=[doc]), \
         patch.object(prs.partRequestRepository, "find_sister_part_requests") as sisters, \
         patch.object(prs.offerRepository, "find", return_value=[]):
        found = prs.find_by_id(PR_ID, None)
    sisters.assert_not_called()
    assert found["partList"] == []
