from app.config import database
from bson import ObjectId


def value_variants(values):
    """Legacy Roles store `value` as a number (212) while UserRoles and the client use
    strings ("212"). Match both forms."""
    out = []
    for v in values:
        s = str(v).strip()
        out.append(s)
        if s.isdigit():
            out.append(int(s))
    return out


def find(filters):
    return database.db["Roles"].find(filters)


def find_by_id(id: str):
    id = ObjectId(id)
    return database.db["Roles"].find_one({"_id": id})


def find_by_value(value: str):
    return database.db["Roles"].find_one({"value": {"$in": value_variants([value])}})


def find_by_values(values):
    return list(database.db["Roles"].find({"value": {"$in": value_variants(values)}}))
