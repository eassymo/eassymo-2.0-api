import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId

from scripts import backfill_store_types as bf

# Census: 1 = Refaccionaria, 2 = Taller.  Group: 1 = BUYER (Taller), 2 = SELLER (Refaccionaria).


def oid_at(year, month, day):
    """A unique ObjectId whose timestamp is that date (the script dates documents by _id)."""
    stamp = ObjectId.from_datetime(datetime(year, month, day, tzinfo=timezone.utc))
    return ObjectId(str(stamp)[:8] + str(ObjectId())[8:])


class Coll:
    """The slice of pymongo the script uses: find/find_one/update_one/insert_one with $in/$nin/$ne/$exists."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    @staticmethod
    def _ok(doc, flt):
        for key, cond in flt.items():
            present, value = key in doc, doc.get(key)
            if isinstance(cond, dict):
                for op, arg in cond.items():
                    if op == "$in" and value not in arg:
                        return False
                    if op == "$nin" and value in arg:
                        return False
                    if op == "$ne" and value == arg:
                        return False
                    if op == "$exists" and present != arg:
                        return False
            elif value != cond:
                return False
        return True

    def find(self, flt=None, projection=None):
        return [dict(d) for d in self.docs if self._ok(d, flt or {})]

    def find_one(self, flt=None, projection=None):
        found = self.find(flt)
        return found[0] if found else None

    def update_one(self, flt, update):
        for d in self.docs:
            if self._ok(d, flt):
                d.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    d.pop(key, None)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def count_documents(self, flt):
        return len(self.find(flt))


class DB(dict):
    def __missing__(self, name):
        self[name] = Coll()
        return self[name]


REFA_ROW, TALLER_ROW, ODD_ROW = ObjectId(), ObjectId(), ObjectId()
G = {name: oid_at(*date) for name, date in {
    "claimed_refa_inverted": (2026, 5, 1),     # v3: census Refa (1) -> type 1 (BUYER): wrong
    "claimed_taller_inverted": (2025, 1, 1),   # v1: census Taller (2) -> type 2 (SELLER): wrong
    "claimed_odd": (2025, 2, 1),               # census type 3
    "claimed_missing": (2025, 3, 1),           # census row deleted
    "manual_forced": (2026, 6, 1),             # v3 forced-buyer window, type 1
    "manual_seller_in_window": (2026, 6, 2),   # type 2 in the window: chosen, keep
    "manual_after": (2026, 11, 1),             # chosen by the user, keep
    "manual_before": (2025, 7, 1),             # v2 type picker, keep
    "manual_odd": (2026, 11, 2),               # type 3
}.items()}
# Census rows the API created along with each manual group (same day).
APP_ROWS = {name: oid_at(*G[name].generation_time.timetuple()[:3])
            for name in ("manual_forced", "manual_after", "manual_before", "manual_seller_in_window")}
ORPHAN_ROW = oid_at(2025, 4, 1)


@pytest.fixture
def db():
    d = DB()
    d["Census"] = Coll([
        {"_id": REFA_ROW, "Entity_Type": 1, "group_reference_id": str(G["claimed_refa_inverted"])},
        {"_id": TALLER_ROW, "Entity_Type": 2, "group_reference_id": str(G["claimed_taller_inverted"])},
        {"_id": ODD_ROW, "Entity_Type": 3, "group_reference_id": str(G["claimed_odd"])},
        # rows the API created for manual stores: Entity_Type = group type (wrong numbering)
        {"_id": APP_ROWS["manual_forced"], "Entity_Type": 1, "group_reference_id": str(G["manual_forced"])},
        {"_id": APP_ROWS["manual_after"], "Entity_Type": 2, "group_reference_id": str(G["manual_after"])},
        {"_id": APP_ROWS["manual_before"], "Entity_Type": 2, "group_reference_id": str(G["manual_before"])},
        {"_id": APP_ROWS["manual_seller_in_window"], "Entity_Type": "1",  # already right, stored as a string
         "group_reference_id": str(G["manual_seller_in_window"])},
        {"_id": ORPHAN_ROW, "Entity_Type": 1, "group_reference_id": str(ObjectId())},
    ])
    d["groups"] = Coll([
        {"_id": G["claimed_refa_inverted"], "name": "Refacciones Sol", "type": 1, "group_store_type": 1,
         "censusReference": str(REFA_ROW), "owner": "o1"},
        {"_id": G["claimed_taller_inverted"], "name": "Taller Luna", "type": 2, "group_store_type": 2,
         "censusReference": str(TALLER_ROW), "owner": "o2"},
        {"_id": G["claimed_odd"], "name": "Flotilla X", "type": 3, "group_store_type": 3,
         "censusReference": str(ODD_ROW)},
        {"_id": G["claimed_missing"], "name": "Sin fila", "type": 1, "group_store_type": 1,
         "censusReference": str(ObjectId())},
        {"_id": G["manual_forced"], "name": "Autopartes Norte", "type": 1, "group_store_type": 1,
         "censusReference": None},
        {"_id": G["manual_seller_in_window"], "name": "Refa Sur", "type": 2, "group_store_type": 2},
        {"_id": G["manual_after"], "name": "Taller Oriente", "type": 2, "group_store_type": 2},
        {"_id": G["manual_before"], "name": "Mecánica Poniente", "type": 1},  # legacy: no group_store_type
        {"_id": G["manual_odd"], "name": "Rara", "type": 3, "group_store_type": 3},
    ])
    d["Offers"] = Coll([{"group_id": str(G["claimed_refa_inverted"])}] * 3
                       + [{"group_id": str(G["manual_forced"])}] * 2)
    d["PartRequests"] = Coll([{"creatorGroup": str(G["claimed_taller_inverted"])}])
    d["UserRoles"] = Coll([
        {"group": str(G["manual_forced"]), "role": "213", "active": True},
        {"group": None, "role": "1", "active": False},
    ])
    return d


def by_id(plan, doc_id):
    return next(i for i in plan["items"] if i["_id"] == str(doc_id))


# ── classification ───────────────────────────────────────────────────────────

def test_claimed_groups_take_their_type_from_the_directory(db):
    plan = bf.build_plan(db)
    refa = by_id(plan, G["claimed_refa_inverted"])
    assert (refa["bucket"], refa["action"]) == ("claimed_inverted", "fix")
    assert refa["before"] == {"type": 1, "group_store_type": 1}
    assert refa["after"] == {"type": 2, "group_store_type": 2}
    taller = by_id(plan, G["claimed_taller_inverted"])
    assert taller["after"] == {"type": 1, "group_store_type": 1}


def test_records_the_data_cannot_settle_go_to_review(db):
    plan = bf.build_plan(db)
    for name, bucket in [("claimed_odd", "claimed_census_odd"), ("claimed_missing", "claimed_census_missing"),
                         ("manual_forced", "manual_forced_buyer"), ("manual_odd", "manual_type_odd")]:
        item = by_id(plan, G[name])
        assert (item["bucket"], item["action"], item["after"]) == (bucket, "review", None), name


def test_manual_groups_outside_the_forced_window_are_kept(db):
    plan = bf.build_plan(db)
    for name in ("manual_seller_in_window", "manual_after", "manual_before"):
        item = by_id(plan, G[name])
        assert (item["bucket"], item["action"]) == ("manual_kept", "keep"), name


def test_missing_group_store_type_is_only_filled_on_request(db):
    assert by_id(bf.build_plan(db), G["manual_before"])["action"] == "keep"
    filled = by_id(bf.build_plan(db, fill_missing_store_type=True), G["manual_before"])
    assert filled["action"] == "fix" and filled["after"] == {"type": 1, "group_store_type": 1}


def test_group_store_type_out_of_step_is_fixed(db):
    gid = oid_at(2025, 8, 1)
    db["groups"].docs.append({"_id": gid, "type": 2, "group_store_type": 1})
    item = by_id(bf.build_plan(db), gid)
    assert item["action"] == "fix" and item["after"] == {"type": 2, "group_store_type": 2}


def test_app_census_rows_follow_the_corrected_group_type(db):
    plan = bf.build_plan(db)
    after = by_id(plan, APP_ROWS["manual_after"])     # Refaccionaria (2) stored as census 2 (Taller)
    assert (after["bucket"], after["after"]) == ("app_census_inverted", {"Entity_Type": 1})
    before = by_id(plan, APP_ROWS["manual_before"])   # Taller (1) stored as census 2: already right
    assert before["bucket"] == "app_census_correct" and before["after"] is None
    assert by_id(plan, APP_ROWS["manual_seller_in_window"])["bucket"] == "app_census_correct"
    assert by_id(plan, APP_ROWS["manual_forced"])["bucket"] == "app_census_pending"
    assert by_id(plan, ORPHAN_ROW)["bucket"] == "app_census_orphan"


def test_directory_rows_a_store_claimed_are_never_in_the_plan(db):
    ids = {i["_id"] for i in bf.build_plan(db)["items"]}
    assert not ids & {str(REFA_ROW), str(TALLER_ROW), str(ODD_ROW)}


def test_owner_decisions_settle_review_groups_and_their_census_row(db):
    # A refaccionaria the v3 manual path forced to type 1: the API copied that 1 into census, which
    # happens to be census Refaccionaria. Deciding "2" fixes the group and leaves the census row alone.
    plan = bf.build_plan(db, decisions={str(G["manual_forced"]): 2})
    group = by_id(plan, G["manual_forced"])
    assert (group["bucket"], group["after"]) == ("owner_decision", {"type": 2, "group_store_type": 2})
    row = by_id(plan, APP_ROWS["manual_forced"])
    assert (row["bucket"], row["after"]) == ("app_census_correct", None)
    # Deciding it really is a taller keeps the group and fixes the census row.
    plan = bf.build_plan(db, decisions={str(G["manual_forced"]): 1})
    assert by_id(plan, G["manual_forced"])["bucket"] == "owner_decision_same"
    row = by_id(plan, APP_ROWS["manual_forced"])
    assert (row["bucket"], row["after"]) == ("app_census_inverted", {"Entity_Type": 2})


def test_signals_suggest_a_type_for_review(db):
    sig = by_id(bf.build_plan(db), G["manual_forced"])["signals"]
    assert sig["offers_made"] == 2 and sig["refa_roles"] == 1 and sig["name_says"] == "seller"
    assert sig["suggested_type"] == 2


def test_report_counts_buckets_and_owners_who_adapted(db):
    plan = bf.build_plan(db)
    text = bf.report(plan)
    assert "claimed_inverted" in text and "manual_forced_buyer" in text
    # Refacciones Sol already made offers while typed as a buyer; Taller Luna created requests.
    assert "default mode flips): 2" in text
    assert "UserRoles with role '1'/'2' (grant nothing; not touched): 1" in text
    assert "groups missing group_store_type: 1" in text


def test_plan_makes_no_writes(db):
    snapshot = {name: [dict(d) for d in coll.docs] for name, coll in db.items()}
    bf.build_plan(db)
    assert {name: coll.docs for name, coll in db.items() if name in snapshot} == snapshot
    assert "AdminAuditLog" not in db or not db["AdminAuditLog"].docs


def test_write_plan_and_read_decisions_round_trip(db, tmp_path):
    plan = bf.build_plan(db)
    bf.write_plan(plan, str(tmp_path))
    saved = json.loads((tmp_path / "plan.json").read_text())
    assert saved["hash"] == bf._plan_hash(saved["items"])
    review = (tmp_path / "review.csv").read_text().splitlines()
    assert len(review) == 1 + 4  # header + four review groups
    # rows end with an empty decision column; the owner fills it in
    (tmp_path / "decisions.csv").write_text(review[0] + "\n" + review[1] + "2\n")
    assert list(bf.read_decisions(str(tmp_path / "decisions.csv")).values()) == [2]
    (tmp_path / "bad.csv").write_text(review[0] + "\n" + review[1] + "3\n")
    with pytest.raises(SystemExit):
        bf.read_decisions(str(tmp_path / "bad.csv"))


# ── shadow ───────────────────────────────────────────────────────────────────

def test_shadow_logs_only_disagreements_and_flags_new_ones(db):
    result = bf.shadow(db, since=datetime(2026, 11, 2, tzinfo=timezone.utc))
    buckets = {r["bucket"] for r in result["disagreements"]}
    assert "claimed_correct" not in buckets and "manual_kept" not in buckets
    assert {"claimed_inverted", "app_census_inverted", "manual_forced_buyer"} <= buckets
    # A new store with an unknown type is a review case, not a wrong write: it never fails the check.
    assert {r["_id"] for r in result["created_since"]} == set()
    assert str(G["manual_odd"]) in {r["_id"] for r in result["disagreements"]}
    # A wrong write after the release does.
    late = oid_at(2026, 11, 20)
    db["groups"].docs.append({"_id": late, "type": 1, "group_store_type": 1, "censusReference": str(REFA_ROW)})
    result = bf.shadow(db, since=datetime(2026, 11, 2, tzinfo=timezone.utc))
    assert {r["_id"] for r in result["created_since"]} == {str(late)}


# ── apply / rollback ─────────────────────────────────────────────────────────

def test_apply_writes_rollback_and_audit_then_rollback_restores(db, tmp_path):
    plan = bf.build_plan(db)
    log = tmp_path / "rollback.jsonl"
    result = bf.apply_plan(db, plan, str(log))
    assert result == {"groups": 2, "Census": 1}
    refa = db["groups"].find_one({"_id": G["claimed_refa_inverted"]})
    assert (refa["type"], refa["group_store_type"]) == (2, 2)
    assert db["Census"].find_one({"_id": APP_ROWS["manual_after"]})["Entity_Type"] == 1
    assert db["Census"].find_one({"_id": REFA_ROW})["Entity_Type"] == 1  # directory row untouched
    assert by_id(bf.build_plan(db), G["claimed_refa_inverted"])["action"] == "keep"  # idempotent
    audit = db["AdminAuditLog"].docs
    assert len(audit) == 3 and {a["action"] for a in audit} == {"backfill_store_type"}
    assert audit[0]["payload"]["before"] and audit[0]["admin_uid"] == bf.ACTOR
    assert len(log.read_text().splitlines()) == 3

    assert bf.rollback(db, str(log)) == {"groups": 2, "Census": 1}
    refa = db["groups"].find_one({"_id": G["claimed_refa_inverted"]})
    assert (refa["type"], refa["group_store_type"]) == (1, 1)
    assert db["Census"].find_one({"_id": APP_ROWS["manual_after"]})["Entity_Type"] == 2


def test_apply_skips_documents_changed_since_the_plan(db, tmp_path):
    plan = bf.build_plan(db)
    db["groups"].update_one({"_id": G["claimed_refa_inverted"]}, {"$set": {"type": 2, "group_store_type": 2}})
    result = bf.apply_plan(db, plan, str(tmp_path / "rollback.jsonl"))
    assert result["conflict"] == 1 and result["groups"] == 1


def test_rollback_removes_a_group_store_type_the_backfill_added(db, tmp_path):
    log = tmp_path / "rollback.jsonl"
    bf.apply_plan(db, bf.build_plan(db, fill_missing_store_type=True), str(log))
    assert db["groups"].find_one({"_id": G["manual_before"]})["group_store_type"] == 1
    bf.rollback(db, str(log))
    restored = db["groups"].find_one({"_id": G["manual_before"]})
    assert restored["type"] == 1 and "group_store_type" not in restored


def test_rollback_never_overwrites_later_edits(db, tmp_path):
    log = tmp_path / "rollback.jsonl"
    bf.apply_plan(db, bf.build_plan(db), str(log))
    db["groups"].update_one({"_id": G["claimed_refa_inverted"]}, {"$set": {"name": "x", "type": 1}})
    result = bf.rollback(db, str(log))
    assert result["skipped"] == 1


# ── CLI guards (no database needed: they fail before connecting) ─────────────

def test_apply_requires_a_plan_and_its_hash(db, tmp_path):
    with pytest.raises(SystemExit):
        bf.main(["apply"])
    plan = bf.build_plan(db)
    path = bf.write_plan(plan, str(tmp_path))
    with pytest.raises(SystemExit):
        bf.main(["apply", "--plan", path, "--confirm", "wrong"])


def test_apply_refuses_an_edited_plan(db, tmp_path):
    plan = bf.build_plan(db)
    path = bf.write_plan(plan, str(tmp_path))
    saved = json.loads(open(path).read())
    saved["items"][0]["after"] = {"type": 1}
    open(path, "w").write(json.dumps(saved))
    with pytest.raises(SystemExit):
        bf.main(["apply", "--plan", path, "--confirm", plan["hash"]])


def test_rollback_requires_the_file_hash(tmp_path):
    log = tmp_path / "rollback.jsonl"
    log.write_text("")
    with pytest.raises(SystemExit):
        bf.main(["rollback", "--rollback", str(log), "--confirm", "nope"])
