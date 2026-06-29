from app.repositories import GuaranteeRepository as guaranteeRepository
from app.schemas.Brand import Brand
from pymongo.errors import PyMongoError


def insert(payload: Brand):
    try:
        if not __verify_if_guarantee_exists(payload.label):
            guaranteeRepository.insert(payload)
        else:
            return payload.label

        return payload.label
    except PyMongoError as err:
        return {"message": f'Error while creating brand Error: {err}'}


def __verify_if_guarantee_exists(label: str):
    found_guarantee = list(guaranteeRepository.find_by_label(label))
    return found_guarantee is not None and len(found_guarantee) > 0


def find_guarantee_by_label(label: str):
    try:
        found_guarantees = guaranteeRepository.find_by_label(label)
        return __format_guarantees(found_guarantees)
    except PyMongoError as err:
        return {"message": f'Error while searching labels: {err}'}


def __format_guarantees(guarantees):
    formatted_guarantees = []
    for guarantee in guarantees:
        formatted_guarantees.append({
            **guarantee,
            "_id": str(guarantee["_id"])
        })
    return formatted_guarantees
