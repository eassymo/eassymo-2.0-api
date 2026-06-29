from app.repositories import OfferRepository as offerRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import ListsRepository as listRepository
from app.repositories import PartRequestRepository as partRequestRepository
from bson import ObjectId
from typing import List
from app.schemas.FilterSection import FilterSection, FilterItem
from app.schemas.Offer import OfferStatus

from app.schemas.Groups import GroupSchema

from fastapi import HTTPException, status


def build_commissioner_offer_filters(commissioner_id: str):
    try:
        group_data = groupRepository.find_by_id(commissioner_id)

        if group_data == None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f'Group not found with id {commissioner_id}')

        group = GroupSchema(**group_data)

        if not group.is_commissioner:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f'Group {group.name} is not a commissioner')

        groups_list = __get_groups_connected_to_commissioner(commissioner_id)

        part_requests_data = list(partRequestRepository.find(
            {"subscribedSellers": {"$in": groups_list}}, None))

        part_request_ids = [str(part_request_item.get("_id"))
                            for part_request_item in part_requests_data]
        
        filters = []

        ##part_request_related_filters = __build_part_request_related_filters(part_request_ids)

        offers_related_filters = __build_offer_related_filters(
            part_request_ids)
        
        """ for filter in part_request_related_filters:
            filters.append(filter) """

        for filter in offers_related_filters:
            filters.append(filter)

        return filters

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=e)


def __get_groups_connected_to_commissioner(commissioner_id: str):
    try:
        user_lists = list(listRepository.find_by_user_and_group(
            {"group_id": commissioner_id}))

        groups_list = []
        for user_list in user_lists:
            groups = user_list.get("groups", [])
            groups_list.extend(groups)

        return groups_list
    except HTTPException as e:
        raise HTTPException(e)


def __build_part_request_related_filters(part_request_ids: List[str]) -> List[FilterSection]:
    request_object_ids = [ObjectId(request_id)
                          for request_id in part_request_ids]

    filters = {
        "_id": {"$in": request_object_ids}}

    available_makers = partRequestRepository.distinct(
        'vehicleInformation.maker', filters)

    available_makers_filter_items = [FilterItem(
        id=f'{maker}_{idx}',
        description=maker,
        value=maker
    ) for idx, maker in enumerate(available_makers)]

    available_models = partRequestRepository.distinct(
        'vehicleInformation.model', filters)

    available_models_filter_items = [FilterItem(
        id=f'{model}_{idx}',
        description=model,
        value=model
    ) for idx, model in enumerate(available_models)]

    available_years = partRequestRepository.distinct(
        'vehicleInformation.year', filters)
    available_years_filter_items = [FilterItem(
        id=f'{year}_{idx}',
        description=year,
        value=year
    ) for idx, year in enumerate(available_years)]

    available_parts = partRequestRepository.distinct(
        'part.tipoParteDescripcion', filters)
    available_parts_filter_items = [FilterItem(
        id=f'{part}_{idx}',
        description=part,
        value=part
    ) for idx, part in enumerate(available_parts)]

    car_makers_filter_section = FilterSection(
        id="car-makers",
        filterSectionTitle="Fabricantes",
        filters=available_makers_filter_items
    )

    car_models_filter_section = FilterSection(
        id="car-models",
        filterSectionTitle="Modelo Vehículo",
        filters=available_models_filter_items
    )

    years_filter_section = FilterSection(
        id="years-filters",
        filterSectionTitle="Años",
        filters=available_years_filter_items
    )

    parts_filter_section = FilterSection(
        id="parts_filters",
        filterSectionTitle="Partes",
        filters=available_parts_filter_items
    )

    return [car_makers_filter_section, car_models_filter_section, years_filter_section, parts_filter_section]


def __build_offer_related_filters(part_request_ids: List[str]) -> List[FilterSection]:

    filters = {
        "request_id": {"$in": part_request_ids}
    }

    prices_found = offerRepository.distinct('price', filters)

    prices_found = sorted(prices_found)

    prices_filter_section = FilterSection(
        id="prices",
        filterSectionTitle="Rango de Precios",
        filters=[
            FilterItem(
                id="min_price",
                description="Precio Mínimo",
                value=prices_found[0],
            ),
            FilterItem(
                id="max_price",
                description="Precio Máximo",
                value=prices_found[len(prices_found)-1]
            )
        ]
    )

    """  brands_list = offerRepository.distinct('brand', filters)

    brands_filter_section = FilterSection(
        id="brands_filter_section",
        filterSectionTitle="Marcas",
        filters=[FilterItem(
            id=f'{brand}-{idx}',
            description=brand,
            value=brand
        ) for idx, brand in enumerate(brands_list)]
    ) """


    status_list = offerRepository.distinct('status', filters)

    # Map status enum values to Spanish descriptions
    status_translations = {
        OfferStatus.created.value: "Creado",
        OfferStatus.workshop_approval_pending.value: "Pendiente de Aprobación del Taller",
        OfferStatus.pending_approval.value: "Pendiente de Aprobación",
        OfferStatus.selected.value: "Seleccionado",
        OfferStatus.rejected.value: "Rechazado"
    }

    status_filter_items = [FilterItem(
        id=f'status-{idx}',
        description=status_translations.get(status, status),
        value=status
    ) for idx, status in enumerate(status_list)]

    status_filter_section = FilterSection(
        id='status-filter-section',
        filterSectionTitle="Status",
        filters=status_filter_items
    )

    return [prices_filter_section, status_filter_section]
