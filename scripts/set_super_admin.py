#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bootstrap script to grant or revoke super_admin Firebase custom claim.

Works with all Firebase auth providers (Google SSO, phone OTP, etc.).
Claims are attached to the Firebase UID, not the login method.

Usage:
  .venv/bin/python3 scripts/set_super_admin.py \
    --service-account ./eassymo-416717-firebase-adminsdk-....json \
    --phone +527772354004 --grant
"""
from __future__ import print_function

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from google.auth.exceptions import RefreshError
except ImportError:
    RefreshError = Exception  # type: ignore


def _resolve_service_account_path(path):
    # type: (str) -> str
    candidate = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(candidate):
        return candidate
    if not candidate.endswith(".json") and os.path.isfile(candidate + ".json"):
        return candidate + ".json"
    raise FileNotFoundError(
        "Service account file not found: {}\n"
        "Tip: include the .json extension, e.g. ...e6f1f31117.json".format(path)
    )


def _init_firebase(service_account_path=None):
    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return

    if service_account_path:
        resolved = _resolve_service_account_path(service_account_path)
        cred = credentials.Certificate(resolved)
        firebase_admin.initialize_app(cred)
        print("Firebase initialized with service account file:")
        print("  {}".format(resolved))
        return

    # Fallback to app env-based init only when no JSON path was passed.
    import app.utils.firebase_admin  # noqa: F401
    print("Firebase initialized with environment variables")


def _normalize_phone(phone):
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if not cleaned.startswith("+"):
        cleaned = "+{}".format(cleaned)
    return cleaned


def _resolve_uid(email, phone, uid):
    # type: (Optional[str], Optional[str], Optional[str]) -> str
    from firebase_admin import auth

    if uid:
        return uid
    if email:
        return auth.get_user_by_email(email.strip()).uid
    if phone:
        return auth.get_user_by_phone_number(_normalize_phone(phone)).uid
    raise ValueError("Provide --uid, --email, or --phone")


def main():
    parser = argparse.ArgumentParser(
        description="Grant or revoke super_admin claim (Google SSO, phone OTP, or any Firebase provider)"
    )
    parser.add_argument(
        "--service-account",
        help="Path to Firebase service account JSON (.json extension optional)",
    )
    parser.add_argument("--email", help="Firebase user email (Google SSO users)")
    parser.add_argument("--phone", help="Firebase user phone in E.164 format, e.g. +5215512345678")
    parser.add_argument("--uid", help="Firebase user uid (from Users.uid in MongoDB)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--grant", action="store_true", help="Grant super_admin claim")
    group.add_argument("--revoke", action="store_true", help="Revoke super_admin claim")
    args = parser.parse_args()

    if not args.email and not args.phone and not args.uid:
        parser.error("Provide one of --uid, --email, or --phone")

    try:
        _init_firebase(args.service_account)
    except FileNotFoundError as exc:
        print("ERROR: {}".format(exc))
        raise SystemExit(1) from exc

    from firebase_admin import auth

    try:
        target_uid = _resolve_uid(args.email, args.phone, args.uid)
        user = auth.get_user(target_uid)
    except RefreshError as exc:
        if "Invalid JWT Signature" in str(exc):
            print("ERROR: Firebase service account credentials are invalid or expired.")
            print("Download a fresh key from Firebase Console -> Project settings -> Service accounts.")
        raise SystemExit(1) from exc
    except Exception as exc:
        print("ERROR: {}".format(exc))
        raise SystemExit(1) from exc

    existing = dict(user.custom_claims or {})

    if args.grant:
        existing["super_admin"] = True
        action = "granted"
    else:
        existing.pop("super_admin", None)
        action = "revoked"

    auth.set_custom_user_claims(target_uid, existing or None)

    providers = [p.provider_id for p in (user.provider_data or [])]
    print("super_admin {}".format(action))
    print("  uid:       {}".format(target_uid))
    print("  email:     {}".format(user.email or "(none - phone-only user)"))
    print("  phone:     {}".format(user.phone_number or "(none)"))
    print("  providers: {}".format(", ".join(providers) or "(unknown)"))
    print("User must sign out and sign back in so the ID token picks up the new claim.")


if __name__ == "__main__":
    main()
