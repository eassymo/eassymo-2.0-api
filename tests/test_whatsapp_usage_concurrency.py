"""Optional integration test against a throwaway Mongo. Runs only when
TEST_MONGO_URI is set; never connects to anything otherwise."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

TEST_MONGO_URI = os.environ.get("TEST_MONGO_URI")

pytestmark = pytest.mark.skipif(not TEST_MONGO_URI, reason="TEST_MONGO_URI not set")


def test_twenty_concurrent_reserves_with_limit_five_reserve_exactly_five():
    from pymongo import ASCENDING, MongoClient

    from app.repositories import WhatsappUsageRepository as repo

    client = MongoClient(TEST_MONGO_URI)
    db_name = f"wa_usage_test_{uuid.uuid4().hex[:8]}"
    col = client[db_name]["WhatsappStoreUsage"]
    try:
        col.create_index([("group_id", ASCENDING)], unique=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with patch.object(repo, "_usage", return_value=col), patch.object(repo, "ensure_indexes"):
            doc = repo.ensure_window("g1", "normal", 28800, now)
            ws = doc["window_start"]

            def reserve(i):
                return repo.try_reserve(
                    "g1", f"u{i % 3}", f"b{i}", limit=5, token_ceiling=10**9, seller_cap=None, window_start=ws
                )

            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(pool.map(reserve, range(20)))
        assert results.count("reserved") == 5
        assert results.count("blocked_quota") == 15
        assert col.find_one({"group_id": "g1"})["solicitudes_used"] == 5
    finally:
        client.drop_database(db_name)
        client.close()
