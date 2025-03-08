from app.config import database
from app.schemas.TeamMemberInvite import TeamMemberInvite
from typing import Dict, Any
from bson import ObjectId
from pymongo import ReturnDocument


def insert(team_member_invite: TeamMemberInvite):
    return database.db["TeamMemberInvite"].insert_one(team_member_invite.toJson())


def find(filters: Dict[str, Any]):
    return database.db["TeamMemberInvite"].find(filters).sort({"_id": -1})

def find_by_id(id: str):
    id = ObjectId(id)
    return database.db["TeamMemberInvite"].find_one({"_id": id})

def find_one_and_update(id: str, payload: Dict[str, Any]):
    id = ObjectId(id)
    return database.db["TeamMemberInvite"].find_one_and_update({"_id": id}, {"$set": payload}, return_document=ReturnDocument.AFTER)
