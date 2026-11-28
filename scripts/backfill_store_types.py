"""Backfill store types written with the wrong numbering.

Census `Entity_Type` uses 1 = Refaccionaria, 2 = Taller. Group `type` / `group_store_type` use
1 = BUYER (Taller), 2 = SELLER (Refaccionaria). Until the fix in this release:
- the shop creators copied the census number into `groups.type` when a store claimed its
  directory record (v1/v2: raw copy; v3: census 1 -> 1, census 2 -> 2, anything else -> 1);
- the v3 manual path forced `type = 1` (Taller) from 2026-03-11 to 2026-10-21;
- the API copied `groups.type` into `Census.Entity_Type` for every store created without a
  directory record.

Nothing is written unless you run `apply` with a plan file produced by `plan` and its hash.

Modes:
  python -m scripts.backfill_store_types plan    [--out DIR] [--decisions CSV]
      Dry run (default). Counts per bucket, writes plan.json (before/after per document) and
      review.csv (documents the data cannot settle, with activity signals). No writes.
  python -m scripts.backfill_store_types shadow  [--out DIR] [--since ISO_DATE]
      Logs only the disagreements between stored and expected values to shadow.jsonl. Exits 2
      if a document created at or after --since disagrees (new writes still wrong). No writes.
  python -m scripts.backfill_store_types apply   --plan DIR/plan.json --confirm HASH
      Applies the "fix" items of a reviewed plan. Each update only matches the plan's "before"
      values; conflicts are skipped and reported. Every change is written to rollback.jsonl
      before it is made, and to AdminAuditLog.
  python -m scripts.backfill_store_types rollback --rollback DIR/rollback.jsonl --confirm HASH
      Restores "before" values for documents that still hold the backfill's "after" values.

Review buckets are never applied from the data alone. To settle them, fill review.csv's
`decision` column with 1 (Taller / buyer) or 2 (Refaccionaria / seller) and pass it back with
`plan --decisions review.csv`.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId

from app.utils.store_type import census_type_to_group_type, group_type_to_census_type

ACTOR = "migration:backfill_store_types"
AUDIT_ACTION = "backfill_store_type"
DEFAULT_OUT = os.path.expanduser("~/eassymo-backfills/store-types")

# v3 shop creator went live (e3d8fa9f) and forced manual stores to type 1 until c866bc89.
V3_LAUNCH = datetime(2026, 3, 11, tzinfo=timezone.utc)
MANUAL_CHOICE = datetime(2026, 10, 21, tzinfo=timezone.utc)

FIX, KEEP, REVIEW = "fix", "keep", "review"
_MISSING = object()

# Bucket -> what the plan does with it. Review buckets need an owner decision (review.csv).
BUCKETS = {
    # groups that claimed a directory record (censusReference set)
    "claimed_inverted": FIX,           # type == census Entity_Type (raw copy): 3 - Entity_Type
    "claimed_correct": KEEP,
    "claimed_group_type_odd": FIX,     # census is 1/2, group type is not 1/2: trust the directory
    "claimed_census_odd": REVIEW,      # census Entity_Type not 1/2 (null, 3, ...)
    "claimed_census_missing": REVIEW,  # censusReference points to no row
    # groups created without a directory record
    "manual_forced_buyer": REVIEW,     # v3 window, type 1: refaccionarias were forced to Taller
    "manual_kept": KEEP,               # type chosen by the user (or not 1 in the forced window)
    "manual_type_odd": REVIEW,         # type not 1/2
    # any group the owner settled in review.csv
    "owner_decision": FIX,
    "owner_decision_same": KEEP,
    # Census rows the API created for manual stores (Entity_Type = group type, wrong numbering)
    "app_census_inverted": FIX,
    "app_census_correct": KEEP,
    "app_census_pending": REVIEW,      # its group is still in a review bucket
    "app_census_orphan": REVIEW,       # group_reference_id points to no group
}

SELLER_WORDS = ("REFACC", "AUTOPARTE", "AUTO PARTE", "REFAC ")
BUYER_WORDS = ("TALLER", "MECANIC", "MECÁNIC", "SERVICIO AUTOMOTRIZ")


# ── helpers ──────────────────────────────────────────────────────────────────

def _created_at(doc_id: Any) -> Optional[datetime]:
    return doc_id.generation_time if isinstance(doc_id, ObjectId) else None


def _oid(value: Any) -> Any:
    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else value


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _plan_hash(items: List[dict]) -> str:
    canonical = json.dumps(items, sort_keys=True, default=str).encode()
    return hashlib.sha256(canonical).hexdigest()[:12]


def _file_hash(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:12]


# ── activity signals (only shown for review; never applied on their own) ─────

def _count_by(db, collection: str, field: str, flt: Optional[dict] = None) -> Counter:
    counts = Counter()
    for doc in db[collection].find(flt or {}, {field: 1}):
        if doc.get(field):
            counts[str(doc[field])] += 1
    return counts


def load_signals(db) -> Dict[str, Counter]:
    roles = defaultdict(Counter)
    for row in db["UserRoles"].find({"group": {"$ne": None}}, {"group": 1, "role": 1}):
        role = str(row.get("role") or "")
        if len(role) == 3 and role[0] in "23":
            roles[str(row["group"])]["refa_roles" if role[0] == "2" else "taller_roles"] += 1
    return {
        "offers": _count_by(db, "Offers", "group_id"),
        "requests": _count_by(db, "PartRequests", "creatorGroup"),
        "roles": roles,
    }


def signals_for(group: dict, signals: Dict[str, Any]) -> dict:
    gid = str(group["_id"])
    name = (group.get("name") or "").upper()
    roles = signals["roles"].get(gid, Counter())
    sig = {
        "offers_made": signals["offers"].get(gid, 0),
        "requests_created": signals["requests"].get(gid, 0),
        "refa_roles": roles.get("refa_roles", 0),
        "taller_roles": roles.get("taller_roles", 0),
        "name_says": ("seller" if any(w in name for w in SELLER_WORDS)
                      else "buyer" if any(w in name for w in BUYER_WORDS) else None),
    }
    seller = sig["offers_made"] + sig["refa_roles"] + (1 if sig["name_says"] == "seller" else 0)
    buyer = sig["requests_created"] + sig["taller_roles"] + (1 if sig["name_says"] == "buyer" else 0)
    sig["suggested_type"] = 2 if seller > buyer else 1 if buyer > seller else None
    return sig


# ── classification ───────────────────────────────────────────────────────────

def classify_group(group: dict, census_row: Optional[dict], window=(V3_LAUNCH, MANUAL_CHOICE)) -> dict:
    """Returns {"bucket", "target_type"}. target_type is None when the data cannot settle it."""
    current = group.get("type")
    if group.get("censusReference"):
        if census_row is None:
            return {"bucket": "claimed_census_missing", "target_type": None}
        target = census_type_to_group_type(census_row.get("Entity_Type"))
        if target is None:
            return {"bucket": "claimed_census_odd", "target_type": None}
        if current == target:
            return {"bucket": "claimed_correct", "target_type": target}
        if current in (1, 2):
            return {"bucket": "claimed_inverted", "target_type": target}
        return {"bucket": "claimed_group_type_odd", "target_type": target}

    if current not in (1, 2):
        return {"bucket": "manual_type_odd", "target_type": None}
    created = _created_at(group.get("_id"))
    if current == 1 and created and window[0] <= created < window[1]:
        return {"bucket": "manual_forced_buyer", "target_type": None}
    return {"bucket": "manual_kept", "target_type": current}


def _group_item(group: dict, bucket: str, target: Optional[int], fill_missing: bool, sig: Optional[dict]) -> dict:
    has_gst = "group_store_type" in group
    before = {"type": group.get("type")}
    if has_gst:
        before["group_store_type"] = group.get("group_store_type")
    after = None
    if target is not None:
        after = {"type": target}
        if has_gst or fill_missing:
            after["group_store_type"] = target
    action = BUCKETS[bucket]
    if action != REVIEW and after is not None:
        # Fix only what differs: a "keep" bucket still fixes a group_store_type out of step with type.
        action = FIX if any(before.get(k, _MISSING) != v for k, v in after.items()) else KEEP
    return {
        "collection": "groups",
        "_id": str(group["_id"]),
        "name": group.get("name"),
        "owner": group.get("owner"),
        "created_at": _iso(_created_at(group.get("_id"))),
        "bucket": bucket,
        "action": action,
        "before": before,
        "after": after if action == FIX else None,
        "signals": sig,
    }


def build_plan(db, decisions: Optional[Dict[str, int]] = None, fill_missing_store_type: bool = False,
               window=(V3_LAUNCH, MANUAL_CHOICE), with_signals: bool = True) -> dict:
    decisions = decisions or {}
    signals = load_signals(db) if with_signals else None
    claimed_rows = {str(g["censusReference"]) for g in db["groups"].find(
        {"censusReference": {"$nin": [None, ""]}}, {"censusReference": 1})}
    census_by_id = {str(row["_id"]): row for row in db["Census"].find(
        {"_id": {"$in": [_oid(ref) for ref in claimed_rows]}}, {"Entity_Type": 1})}

    items: List[dict] = []
    final_type: Dict[str, Optional[int]] = {}
    group_ids = set()
    projection = {"type": 1, "group_store_type": 1, "censusReference": 1, "name": 1, "owner": 1}
    for group in db["groups"].find({}, projection):
        gid = str(group["_id"])
        group_ids.add(gid)
        ref = group.get("censusReference")
        verdict = classify_group(group, census_by_id.get(str(ref)) if ref else None, window)
        bucket, target = verdict["bucket"], verdict["target_type"]
        if gid in decisions:
            target = decisions[gid]
            bucket = "owner_decision" if target != group.get("type") else "owner_decision_same"
        needs_signals = signals is not None and (BUCKETS[bucket] == REVIEW or bucket == "claimed_inverted")
        sig = signals_for(group, signals) if needs_signals else None
        item = _group_item(group, bucket, target, fill_missing_store_type, sig)
        items.append(item)
        final_type[gid] = target

    for row in db["Census"].find({"group_reference_id": {"$nin": [None, ""]}},
                                 {"Entity_Type": 1, "group_reference_id": 1, "Entity_Name": 1}):
        if str(row["_id"]) in claimed_rows:
            continue  # a directory record a store claimed: the trusted source, never touched
        gid = str(row["group_reference_id"])
        before = {"Entity_Type": row.get("Entity_Type")}
        if gid not in group_ids:
            bucket, after = "app_census_orphan", None
        elif final_type.get(gid) is None:
            bucket, after = "app_census_pending", None
        else:
            expected = group_type_to_census_type(final_type[gid])
            stored = census_type_to_group_type(row.get("Entity_Type"))
            bucket = "app_census_correct" if stored == final_type[gid] else "app_census_inverted"
            after = {"Entity_Type": expected} if bucket == "app_census_inverted" else None
        items.append({
            "collection": "Census",
            "_id": str(row["_id"]),
            "name": row.get("Entity_Name"),
            "group_reference_id": gid,
            "created_at": _iso(_created_at(row.get("_id"))),
            "bucket": bucket,
            "action": BUCKETS[bucket],
            "before": before,
            "after": after,
        })

    placeholder_roles = db["UserRoles"].count_documents({"role": {"$in": ["1", "2", 1, 2]}})
    return {
        "generated_at": _iso(datetime.now(timezone.utc)),
        "window": [_iso(window[0]), _iso(window[1])],
        "fill_missing_store_type": fill_missing_store_type,
        "decisions": len(decisions),
        "placeholder_user_roles": placeholder_roles,
        "hash": _plan_hash(items),
        "items": items,
    }


def counts(plan: dict) -> Dict[str, Counter]:
    out = defaultdict(Counter)
    for item in plan["items"]:
        out[item["bucket"]][item["action"]] += 1
    return out


def report(plan: dict) -> str:
    c = counts(plan)
    lines = [f"Plan {plan['hash']} ({plan['generated_at']}); forced-buyer window {plan['window'][0]} .. {plan['window'][1]}",
             f"{'bucket':28s} {'fix':>7s} {'keep':>7s} {'review':>7s}"]
    for bucket in BUCKETS:
        if c.get(bucket):
            lines.append(f"{bucket:28s} {c[bucket][FIX]:7d} {c[bucket][KEEP]:7d} {c[bucket][REVIEW]:7d}")
    groups = [i for i in plan["items"] if i["collection"] == "groups"]
    missing = sum(1 for i in groups if "group_store_type" not in i["before"])
    adapted = sum(1 for i in groups if i["action"] == FIX and i.get("signals")
                  and i["signals"]["suggested_type"] == (i["after"] or {}).get("type"))
    lines += [
        f"groups missing group_store_type: {missing} "
        f"({'filled' if plan['fill_missing_store_type'] else 'left as is; --fill-missing-store-type to fill'})",
        f"groups to fix whose activity already matches the new type (owners who adapted, default mode flips): {adapted}",
        f"UserRoles with role '1'/'2' (grant nothing; not touched): {plan['placeholder_user_roles']}",
        f"owner decisions applied: {plan['decisions']}",
    ]
    return "\n".join(lines)


def write_plan(plan: dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "plan.json")
    with open(path, "w") as fh:
        json.dump(plan, fh, indent=1, default=str)
    with open(os.path.join(out_dir, "review.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["group_id", "name", "created_at", "bucket", "current_type", "suggested_type",
                    "offers_made", "requests_created", "refa_roles", "taller_roles", "name_says", "decision"])
        for i in plan["items"]:
            if i["collection"] != "groups" or i["action"] != REVIEW:
                continue
            s = i.get("signals") or {}
            w.writerow([i["_id"], i["name"], i["created_at"], i["bucket"], i["before"].get("type"),
                        s.get("suggested_type"), s.get("offers_made"), s.get("requests_created"),
                        s.get("refa_roles"), s.get("taller_roles"), s.get("name_says"), ""])
    return path


def read_decisions(path: str) -> Dict[str, int]:
    decisions = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            value = (row.get("decision") or "").strip()
            if not value:
                continue
            if value not in ("1", "2"):
                raise SystemExit(f"review.csv: decision for {row['group_id']} must be 1 or 2, got {value!r}")
            decisions[row["group_id"].strip()] = int(value)
    return decisions


# ── shadow ───────────────────────────────────────────────────────────────────

def shadow(db, since: Optional[datetime], window=(V3_LAUNCH, MANUAL_CHOICE)) -> dict:
    """Disagreements only: fix items and review items. No writes.
    `created_since` holds only wrong writes (fix items) newer than `since`: a new store with an unknown type is a
    review case, not proof that the code still writes the wrong numbering."""
    plan = build_plan(db, window=window, with_signals=False)
    rows = [i for i in plan["items"] if i["action"] in (FIX, REVIEW)]
    new = [i for i in rows if i["action"] == FIX and since and i["created_at"]
           and datetime.fromisoformat(i["created_at"]) >= since]
    return {"plan_hash": plan["hash"], "disagreements": rows, "created_since": new}


# ── apply / rollback ─────────────────────────────────────────────────────────

def _audit(db, action: str, item: dict, payload: dict):
    db["AdminAuditLog"].insert_one({
        "admin_uid": ACTOR,
        "action": action,
        "entity_type": item["collection"],
        "entity_id": item["_id"],
        "payload": payload,
        "created_at": datetime.now(timezone.utc),
    })


def _match(item_id: str, values: dict) -> dict:
    return {"_id": _oid(item_id), **values}


def apply_plan(db, plan: dict, rollback_path: str) -> Dict[str, int]:
    result = Counter()
    run_id = f"{plan['hash']}@{_iso(datetime.now(timezone.utc))}"
    with open(rollback_path, "a") as log:
        for item in plan["items"]:
            if item["action"] != FIX or not item.get("after"):
                continue
            flt = _match(item["_id"], item["before"])
            if "group_store_type" not in item["before"] and "group_store_type" in item["after"]:
                flt["group_store_type"] = {"$exists": False}
            if db[item["collection"]].find_one(flt, {"_id": 1}) is None:
                result["conflict"] += 1  # changed since the plan was made: leave it for the next plan
                continue
            entry = {"run": run_id, "collection": item["collection"], "_id": item["_id"],
                     "before": item["before"], "after": item["after"]}
            log.write(json.dumps(entry, default=str) + "\n")
            log.flush()
            os.fsync(log.fileno())
            res = db[item["collection"]].update_one(flt, {"$set": item["after"]})
            if getattr(res, "modified_count", 1):
                _audit(db, AUDIT_ACTION, item, {"run": run_id, "bucket": item["bucket"],
                                                "before": item["before"], "after": item["after"]})
                result[item["collection"]] += 1
            else:
                result["conflict"] += 1
    return dict(result)


def rollback(db, rollback_path: str) -> Dict[str, int]:
    result = Counter()
    with open(rollback_path) as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    for entry in reversed(entries):
        update = {"$set": entry["before"]}
        added = [key for key in entry["after"] if key not in entry["before"]]  # e.g. a filled group_store_type
        if added:
            update["$unset"] = {key: "" for key in added}
        res = db[entry["collection"]].update_one(_match(entry["_id"], entry["after"]), update)
        if getattr(res, "modified_count", 1):
            _audit(db, AUDIT_ACTION + "_rollback", entry, {"run": entry["run"], "before": entry["after"],
                                                         "after": entry["before"]})
            result[entry["collection"]] += 1
        else:
            result["skipped"] += 1  # edited after the backfill: never overwrite newer changes
    return dict(result)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_date(value: str) -> datetime:
    d = datetime.fromisoformat(value)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", nargs="?", default="plan", choices=["plan", "shadow", "apply", "rollback"])
    parser.add_argument("--out", default=None, help=f"output folder (default {DEFAULT_OUT}/<timestamp>)")
    parser.add_argument("--decisions", help="review.csv with the decision column filled (plan)")
    parser.add_argument("--fill-missing-store-type", action="store_true",
                        help="also set group_store_type on groups that lack it (plan)")
    parser.add_argument("--window-start", default=V3_LAUNCH.date().isoformat())
    parser.add_argument("--window-end", default=MANUAL_CHOICE.date().isoformat())
    parser.add_argument("--since", help="release time; shadow exits 2 if newer documents disagree")
    parser.add_argument("--plan", help="plan.json to apply")
    parser.add_argument("--rollback", help="rollback.jsonl to restore")
    parser.add_argument("--confirm", help="plan hash (apply) or rollback file hash (rollback)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    window = (_parse_date(args.window_start), _parse_date(args.window_end))
    out_dir = args.out or os.path.join(DEFAULT_OUT, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    if args.mode == "apply":
        if not args.plan:
            parser.error("apply needs --plan (run `plan` first and review it)")
        with open(args.plan) as fh:
            plan = json.load(fh)
        if _plan_hash(plan["items"]) != plan["hash"]:
            parser.error("plan.json was edited after it was generated; make a new plan")
        if args.confirm != plan["hash"]:
            parser.error(f"pass --confirm {plan['hash']} to apply this plan")
    if args.mode == "rollback":
        if not args.rollback:
            parser.error("rollback needs --rollback rollback.jsonl")
        if args.confirm != _file_hash(args.rollback):
            parser.error(f"pass --confirm {_file_hash(args.rollback)} to roll back this file")

    from app.config import database
    db = database.db
    print(f"Database: {db.name}")

    if args.mode == "plan":
        decisions = read_decisions(args.decisions) if args.decisions else None
        plan = build_plan(db, decisions, args.fill_missing_store_type, window)
        path = write_plan(plan, out_dir)
        print(report(plan))
        print(f"Dry run: nothing written to the database. Plan: {path}; review list: {out_dir}/review.csv")
        print(f"To apply after review: python -m scripts.backfill_store_types apply --plan {path} --confirm {plan['hash']}")
        return 0

    if args.mode == "shadow":
        result = shadow(db, _parse_date(args.since) if args.since else None, window)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "shadow.jsonl")
        with open(path, "w") as fh:
            for row in result["disagreements"]:
                fh.write(json.dumps({**row, "logged_at": _iso(datetime.now(timezone.utc))}, default=str) + "\n")
        by_bucket = Counter(r["bucket"] for r in result["disagreements"])
        print(f"Shadow (no writes): {len(result['disagreements'])} disagreements -> {path}")
        for bucket, n in sorted(by_bucket.items()):
            print(f"  {bucket:28s} {n}")
        if args.since:
            print(f"Created since {args.since}: {len(result['created_since'])}")
        return 2 if result["created_since"] else 0

    if args.mode == "apply":
        rollback_path = os.path.join(os.path.dirname(os.path.abspath(args.plan)), "rollback.jsonl")
        print(f"Applying plan {plan['hash']}; rollback log: {rollback_path}")
        print(apply_plan(db, plan, rollback_path))
        return 0

    print(rollback(db, args.rollback))
    return 0


if __name__ == "__main__":
    sys.exit(main())
