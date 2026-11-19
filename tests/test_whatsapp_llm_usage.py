"""GLM token usage is reported through an optional sink, one call per completion."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import LlmExtractionService as llm_module

GOOD = json.dumps({"intent": "new_request", "lines": []})


def _svc():
    svc = llm_module.LlmExtractionService.__new__(llm_module.LlmExtractionService)
    svc.api_key = "k"
    svc.base_url = "http://glm.test"
    svc.model = "glm-test"
    svc.max_retries = 3
    svc.retry_base_seconds = 1
    return svc


def _resp(content, usage=None, status=200):
    r = MagicMock()
    r.status_code = status
    body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    if usage is not None:
        body["usage"] = usage
    r.json.return_value = body
    return r


def _usage(p, c):
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}


def test_extract_reports_usage_per_completion():
    svc, seen = _svc(), []
    with patch.object(svc, "_post_chat", return_value=_resp(GOOD, _usage(100, 40))):
        svc.extract("balatas", usage_sink=seen.append)
    assert seen == [{"prompt_tokens": 100, "completion_tokens": 40, "model": "glm-test", "has_usage": True}]


def test_extract_repair_retry_reports_each_completion():
    svc, seen = _svc(), []
    replies = [_resp("not json", _usage(10, 5)), _resp(GOOD, _usage(20, 7))]
    with patch.object(svc, "_post_chat", side_effect=replies):
        svc.extract("balatas", usage_sink=seen.append)
    assert [(s["prompt_tokens"], s["completion_tokens"]) for s in seen] == [(10, 5), (20, 7)]


def test_empty_reply_retry_reports_each_completion():
    svc, seen = _svc(), []
    replies = [_resp("", _usage(10, 5)), _resp(GOOD, _usage(20, 7))]
    with patch.object(svc, "_post_chat", side_effect=replies):
        svc.extract("balatas", usage_sink=seen.append)
    assert len(seen) == 2


def test_429_retries_do_not_report_usage():
    svc, seen = _svc(), []
    replies = [_resp("", status=429), _resp("", status=429), _resp(GOOD, _usage(9, 3))]
    with patch.object(svc, "_post_chat", side_effect=replies), patch.object(llm_module.time, "sleep"):
        svc.extract("balatas", usage_sink=seen.append)
    assert len(seen) == 1 and seen[0]["completion_tokens"] == 3


def test_missing_usage_block_reports_zero_and_flag():
    svc, seen = _svc(), []
    with patch.object(svc, "_post_chat", return_value=_resp(GOOD)):
        svc.extract("balatas", usage_sink=seen.append)
    assert seen == [{"prompt_tokens": 0, "completion_tokens": 0, "model": "glm-test", "has_usage": False}]


def test_extract_without_sink_unchanged():
    svc = _svc()
    with patch.object(svc, "_post_chat", return_value=_resp(GOOD, _usage(1, 1))):
        assert svc.extract("balatas").intent.value == "new_request"


def test_raising_sink_never_breaks_extraction():
    svc = _svc()

    def boom(_):
        raise RuntimeError("sink down")

    with patch.object(svc, "_post_chat", return_value=_resp(GOOD, _usage(1, 1))):
        assert svc.extract("balatas", usage_sink=boom).intent.value == "new_request"


def test_match_answers_reports_usage():
    svc, seen = _svc(), []
    content = '{"answers": []}'
    with patch.object(svc, "_post_chat", return_value=_resp(content, _usage(30, 12))):
        svc.match_answers(["x"], [{"id": "q", "prompt": "?"}], usage_sink=seen.append)
    assert seen[0]["prompt_tokens"] == 30 and seen[0]["has_usage"] is True
