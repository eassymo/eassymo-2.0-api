from app.config import database
from app.schemas.Brand import Brand


def insert(brand: Brand):
    payload = brand.model_dump()
    return database.db["Brands"].insert_one(payload)


def find_by_label(label: str):
    return database.db["Brands"].find({"label": {
        "$regex": label,
        "$options": "i"
    }})
