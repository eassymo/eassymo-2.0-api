from app.repositories import BrandRepository as brandRepository
from app.schemas.Brand import Brand
from pymongo.errors import PyMongoError


def insert(payload: Brand):
    try:
        brand_exists = __verify_if_brand_exists(payload.label)
        if brand_exists is False:
            brandRepository.insert(payload)
        else:
            return payload.label

        return payload.label
    except PyMongoError as err:
        return {"message": f'Error while creating brand Error: {err}'}


def __verify_if_brand_exists(label: str):
    found_brands = list(brandRepository.find_by_label(label))
    return found_brands is not None and len(found_brands) > 0


def find_brand_by_label(label: str):
    try:
        found_brands = brandRepository.find_by_label(label)
        return __format_brands(found_brands)
    except PyMongoError as err:
        return {"message": f'Error while searching labels: {err}'}


def __format_brands(brands):
    formatted_brands = []
    for brand in brands:
        formatted_brands.append({
            **brand,
            "_id": str(brand["_id"])
        })
    return formatted_brands
