from datetime import datetime, timezone

from app.utils.datetime_utils import serialize_datetime, utc_timestamp_ms


def test_serialize_datetime_naive_as_utc():
    value = datetime(2026, 9, 4, 17, 55, 0)
    assert serialize_datetime(value) == "2026-09-04T17:55:00.000Z"


def test_serialize_datetime_aware_utc():
    value = datetime(2026, 9, 4, 17, 55, 0, tzinfo=timezone.utc)
    assert serialize_datetime(value) == "2026-09-04T17:55:00.000Z"


def test_utc_timestamp_ms_treats_naive_as_utc():
    naive = datetime(2026, 9, 4, 17, 55, 0)
    aware = datetime(2026, 9, 4, 17, 55, 0, tzinfo=timezone.utc)
    assert utc_timestamp_ms(naive) == utc_timestamp_ms(aware)
