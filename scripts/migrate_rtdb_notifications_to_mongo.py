#!/usr/bin/env python3
"""Migrate legacy RTDB notification inboxes into Mongo (ADR-001 Phase 6).

Usage:
  PYTHONPATH=. python scripts/migrate_rtdb_notifications_to_mongo.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import firebase_admin
from firebase_admin import credentials, db as rtdb

from app.services import NotificationService as notification_service


def _init_firebase() -> None:
    if firebase_admin._apps:
        return
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    db_url = os.environ.get("FIREBASE_DATABASE_URL")
    if not cred_path or not db_url:
        raise SystemExit("Set GOOGLE_APPLICATION_CREDENTIALS and FIREBASE_DATABASE_URL")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {"databaseURL": db_url})


def _walk_legacy_inbox(path: str) -> list[Dict[str, Any]]:
    root = rtdb.reference(path).get() or {}
    docs: list[Dict[str, Any]] = []
    for group_id, users in root.items():
        if not isinstance(users, dict):
            continue
        for user_id, notifications in users.items():
            if not isinstance(notifications, dict):
                continue
            for _notif_id, payload in notifications.items():
                if not isinstance(payload, dict):
                    continue
                doc = dict(payload)
                doc.setdefault("owner", user_id)
                doc.setdefault("ownerGroup", group_id)
                if path.startswith("callCenterNotifications/"):
                    doc.setdefault("callcenterId", group_id)
                docs.append(doc)
    return docs


def migrate(*, dry_run: bool) -> int:
    _init_firebase()
    migrated = 0

    for base in ("notifications", "callCenterNotifications"):
        root = rtdb.reference(base).get() or {}
        if not isinstance(root, dict):
            continue
        for group_id, users in root.items():
            if not isinstance(users, dict):
                continue
            for user_id, notifications in users.items():
                if not isinstance(notifications, dict):
                    continue
                for _notif_id, payload in notifications.items():
                    if not isinstance(payload, dict):
                        continue
                    doc = dict(payload)
                    doc.setdefault("owner", user_id)
                    doc.setdefault("ownerGroup", group_id)
                    if base == "callCenterNotifications":
                        doc.setdefault("callcenterId", group_id)
                    migrated += 1
                    if not dry_run:
                        notification_service.create_without_side_effects(doc)

    return migrated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = migrate(dry_run=args.dry_run)
    mode = "would migrate" if args.dry_run else "migrated"
    print(f"{mode} {count} legacy RTDB notifications")


if __name__ == "__main__":
    main()
