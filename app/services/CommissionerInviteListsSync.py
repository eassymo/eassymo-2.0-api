"""List mutations for commissioner ↔ invited-group relationships — no commissioner invite imports."""

from typing import Iterable

from app.repositories import ListsRepository as listsRepository


def strip_invited_from_commissionables_list(
    inviting_user_uid: str,
    commissioner_group_id: str,
    invited_group_id: str,
) -> None:
    user_lists = list(
        listsRepository.find(
            {"user_uid": inviting_user_uid, "group_id": commissioner_group_id},
        ),
    )
    commissionable_list = [
        u for u in user_lists if u.get("name") == "Comisionables"
    ]
    if not commissionable_list:
        return
    cid = str(commissionable_list[0]["_id"])
    listsRepository.remove_group_from_list(cid, invited_group_id)


def strip_commissioner_from_all_comisionistas_lists(
    invited_group_id: str,
    commissioner_group_id: str,
) -> None:
    docs: Iterable[dict] = listsRepository.find(
        {"group_id": invited_group_id, "name": "Comisionistas"},
    )
    for doc in docs:
        cid = str(doc["_id"])
        listsRepository.remove_group_from_list(cid, commissioner_group_id)
