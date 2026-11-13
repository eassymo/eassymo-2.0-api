from unittest.mock import MagicMock, patch

from app.repositories import WhatsappInboundRepository as repo


def test_used_group_ids_by_creator_queries_resolved_messages_only():
    col = MagicMock()
    col.distinct.return_value = ["g1", None, "g2"]
    with patch.object(repo, "_col", return_value=col):
        result = repo.used_group_ids_by_creator("uid-1")

    assert result == ["g1", "g2"]
    col.distinct.assert_called_once_with(
        "resolved_group_id",
        {"resolved_creator_uid": "uid-1", "identity_status": "resolved"},
    )
