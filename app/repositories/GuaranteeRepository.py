from app.config import database
from app.schemas.Guarantee import Guarantee


def insert(guarantee: Guarantee):
    payload = guarantee.dict()
    return database.db["Guarantees"].insert_one(payload)


def find_by_label(label: str):
    return database.db["Guarantees"].find({"label": {
        "$regex": label,
        "$options": "i"
    }})
