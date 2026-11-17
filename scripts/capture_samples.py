"""Find the sample records the frame capture needs and print them as `.env.capture` lines.

Sign up the two test accounts in the app first (Firebase test phone numbers): one creates a
refaccionaria (vendedor), the other a taller (comprador). Then, in the app: the taller creates a
request, the refaccionaria quotes it and opens a POS folio, and the taller accepts the offer so
an order exists. Re-run this script; it reports anything still missing.

Read-only, and refuses to run on any database whose name doesn't contain "STAGING".
Usage: python -m scripts.capture_samples --vendedor-uid <uid> --comprador-uid <uid>
"""
import argparse
from typing import Dict, List, Optional, Tuple

HOW_TO_CREATE = {
    "CAPTURE_REQUEST": "as the taller, create a part request",
    "CAPTURE_PARENT_REQUEST": "as the taller, create a part request",
    "CAPTURE_VEHICLE": "as the taller, create a part request for a vehicle",
    "CAPTURE_OFFER": "as the refaccionaria, quote the taller's request",
    "CAPTURE_ORDER": "as the taller, accept the refaccionaria's offer",
    "CAPTURE_FOLIO": "as the refaccionaria, create a folio in Mostrador / POS",
    "CAPTURE_DRAFT_TOKEN": "as the refaccionaria, share the POS folio",
}


def assert_staging(db_name: str) -> None:
    if "STAGING" not in (db_name or "").upper():
        raise SystemExit(f"Refusing to run on database '{db_name}': capture samples must come from staging.")


def _latest(coll, query) -> Optional[dict]:
    docs = list(coll.find(query).sort("_id", -1).limit(1))
    return docs[0] if docs else None


def _group_of(db, uid: str) -> Optional[str]:
    group = _latest(db["groups"], {"owner": uid})
    return str(group["_id"]) if group else None


def find_samples(db, vendedor_uid: str, comprador_uid: str) -> Tuple[Dict[str, str], List[str]]:
    seller, buyer = _group_of(db, vendedor_uid), _group_of(db, comprador_uid)
    if not seller or not buyer:
        missing_owner = "vendedor" if not seller else "comprador"
        raise SystemExit(f"No group owned by the {missing_owner} test account: sign it up in the app first.")
    found: Dict[str, str] = {}

    request = _latest(db["PartRequests"], {"creatorGroup": buyer})
    if request:
        found["CAPTURE_REQUEST"] = str(request["_id"])
        found["CAPTURE_PARENT_REQUEST"] = str(request.get("parent_request_uid") or request["_id"])
        vehicle = (request.get("vehicleInformation") or {}).get("_id")
        if vehicle:
            found["CAPTURE_VEHICLE"] = str(vehicle)

    offer = _latest(db["Offers"], {"group_id": seller})
    if offer:
        found["CAPTURE_OFFER"] = str(offer["_id"])

    order = _latest(db["Orders"], {"offer.group_id": seller})
    if order:
        found["CAPTURE_ORDER"] = str(order["_id"])

    folio = _latest(db["MostradorFolios"], {"origin_group_id": seller})
    if folio:
        found["CAPTURE_FOLIO"] = str(folio["_id"])
        if folio.get("share_token"):
            found["CAPTURE_DRAFT_TOKEN"] = str(folio["share_token"])

    missing = [key for key in HOW_TO_CREATE if key not in found]
    return found, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendedor-uid", required=True)
    parser.add_argument("--comprador-uid", required=True)
    args = parser.parse_args()
    from app.config import database

    assert_staging(database.db.name)
    found, missing = find_samples(database.db, args.vendedor_uid, args.comprador_uid)
    print("# paste into eassymo-2.0-client/.env.capture")
    for key, value in found.items():
        print(f"{key}={value}")
    for key in missing:
        print(f"# missing {key}: {HOW_TO_CREATE[key]}")


if __name__ == "__main__":
    main()
