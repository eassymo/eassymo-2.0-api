from app.repositories import PartRequestRepository as partRequestRepository
from app.repositories import OfferRepository as offerRepository
from app.repositories import GroupRepository as groupRepository
from app.repositories import ListsRepository as listRepository
from app.repositories import OrderRepository as orderRepository
from pymongo.errors import PyMongoError
from fastapi import HTTPException, status
from app.schemas.Groups import GroupSchema
from app.schemas.Offer import Offer, OfferStatus
from app.schemas.Order import Order
from app.schemas.PartRequest import PartRequest
from typing import List, Dict, Any
from app.services import OfferService as offerService
from app.factories.NotificationsCreator import (
    create_offer_selected_notification, create_offer_selected_by_commissioner_to_origin_group_notification)
from app.schemas.Notification import Notification
from app.utils.notifications import send_notification


def get_commissioner_offers(commissioner_id: str):
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

        part_requests: List[PartRequest] = []

        for part_request_data in part_requests_data:
            part_request = PartRequest(**part_request_data)
            part_requests.append(
                part_request
            )

            creator_group_data = groupRepository.find_by_id(
                part_request.creatorGroup, {"name": 1})

            if creator_group_data != None:
                creator_group = GroupSchema(**creator_group_data)
                part_request.group_info = creator_group

        if len(part_requests) == 0:
            return []

        offers_data = list(
            offerRepository.find_by_request_ids(part_request_ids, None, {
                "status": {
                    "$in": [
                        OfferStatus.pending_approval.value,
                        OfferStatus.rejected.value,
                        OfferStatus.selected.value
                    ]
                }
            })
        )

        offers: List[Offer] = []

        if len(offers_data) > 0:
            offers = [Offer(**offer) for offer in offers_data]

        specific_orders_uids_dicts = {}
        for offer in offers:
            for part_request in part_requests:
                if offer.request_id == part_request.id:

                    if not specific_orders_uids_dicts.get(f'{part_request.specific_order_uid}-{part_request.id}'):
                        specific_orders_uids_dicts[f'{part_request.specific_order_uid}-{part_request.id}'] = [
                            offer.toJson()
                        ]
                    else:
                        specific_orders_uids_dicts[f'{part_request.specific_order_uid}-{part_request.id}'].append(
                            offer.toJson())

                    offer.request_info = part_request.toJson()

        for order_uid, offers_list in specific_orders_uids_dicts.items():
            if len(offers_list) > 1:
                sorted_offers = sorted(
                    offers_list, key=lambda x: x.get('price', float('inf')))

                for index, offer in enumerate(sorted_offers):
                    offer['ranking'] = index + 1

                specific_orders_uids_dicts[order_uid] = sorted_offers

        formatted_response: List[Dict[str, Any]] = []

        for order_uid in specific_orders_uids_dicts:
            formatted_response.append({
                "specific_order_id": order_uid,
                "offers": specific_orders_uids_dicts.get(order_uid)
            })

        return formatted_response
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(e)


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


def accept_commissioner_offer(offer_id: str, user_token: str, group_selected: str, new_price: float):
    try:
        offer_data = offerRepository.find_offer_by_id(offer_id)

        if offer_data == None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f'No offer was found with id {offer_id}')
        offer = Offer(**offer_data)

        if new_price < offer.price:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f'The price should be equal or higher than the original offer price')

        part_request_data = list(
            partRequestRepository.find_by_id(offer.request_id))

        if part_request_data == None or len(part_request_data) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f'No request was found with id {offer.request_id}')

        part_request: PartRequest = PartRequest(**part_request_data[0])

        if group_selected != part_request.commissioner_group:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail=f'This commissioner is not authorized to accept this offer')

        group_selected_data = groupRepository.find_by_id(group_selected)

        group: GroupSchema
        if group_selected_data != None:
            group = GroupSchema(**group_selected_data)

        part_request_offers_list = list(
            offerRepository.find({"request_id": offer.request_id}))

        rejected_ids: List[str] = []

        for offer_data_item in part_request_offers_list:
            offer_item = Offer(**offer_data_item)

            offer_item.commissioner_price = new_price

            offer_item.update_status(OfferStatus.rejected)
            edited_offer = offerService.edit_offer(offer_item.id, offer_item)

            rejected_ids.append(edited_offer["_id"])

        # once we accept the offer we must generate the order
        offerService.change_offer_status(
            offer.request_id, offer_id=offer.id, status=OfferStatus.selected.value, user_token=user_token)

        oder_data = orderRepository.find_one({"offer._id": offer.id})

        if offer_data != None:
            order = Order(**oder_data)

            __build_and_send_offer_group_notifications(
                offer.group_id, order, store_name=group.name, user_token=user_token)
            __build_and_send_request_creator_accepted_offer_notification(
                request_group=part_request.creatorGroup,
                order=order,
                store_name=group.name,
                user_token=user_token
            )

            return {
                "status": offer.status,
                "offerId": offer.id,
                "orderId": order.id
            }

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Error while creating order')
    except HTTPException as e:
        raise HTTPException(e)


def __build_and_send_offer_group_notifications(
    offer_creator_group_id: str,
    order: Order,
    store_name: str,
    user_token: str
):
    try:
        offer_creator_user_list = groupRepository.find_users_by_group_id(
            offer_creator_group_id)

        if offer_creator_user_list == None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail='Cannot find users to notify')

        for user_id in offer_creator_user_list.get("users"):
            build_and_send_notification(
                user_id=user_id,
                group_id=offer_creator_group_id,
                order_id=order.id,
                part_name=order.part_request.part.get("tipoParteDescripcion"),
                store_name=store_name,
                user_token=user_token,
            )
    except HTTPException as e:
        raise HTTPException(e)


def build_and_send_notification(
    user_id: str,
    group_id: str,
    order_id: str,
    store_name: str,
    part_name: str,
    user_token: str
) -> None:
    try:
        if isinstance(user_id, dict):
            owner_id = user_id.get("_id") or user_id.get(
                "uid") or user_id.get("id")
        else:
            owner_id = user_id

        if not owner_id:
            print(f"⚠️ Warning: Invalid user_id format: {user_id}")
            return

        # meta_data = {"order": offer_id}

        notification: Notification

        notification = create_offer_selected_notification(
            order_id=order_id,
            owner=user_id,
            store_name=store_name,
            owner_group=group_id,
            part_name=part_name,
            navigate_to_url='/order-management',
            meta_data={}
        )

        send_notification(notification, user_token)

    except Exception as error:
        print(f"❌ Critical error in notification system: {error}")
        print(
            f"📧 Failed notification - User: {user_id}, Part: {part_name}, Store: {store_name}")


def __build_and_send_request_creator_accepted_offer_notification(
    request_group: str,
    order: Order,
    store_name: str,
    user_token: str
):
    try:
        request_creator_user_list = groupRepository.find_users_by_group_id(
            request_group)

        if request_creator_user_list == None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail='Cannot find users from request origin to notify')

        for user_id in request_creator_user_list.get("users"):

            build_and_accepted_offer_notification_for_req_creator(
                user_id=user_id,
                group_id=request_group,
                order_id=order.id,
                part_name=order.part_request.part.get("tipoParteDescripcion"),
                store_name=store_name,
                user_token=user_token
            )

    except Exception as e:
        print(f"❌ Critical error in notification system: {e}")


def build_and_accepted_offer_notification_for_req_creator(
        user_id: str,
        group_id: str,
        order_id: str,
        store_name: str,
        part_name: str,
        user_token: str
):
    try:
        if not user_id:
            print(f"⚠️ Warning: Invalid user_id format: {user_id}")
            return

        notification: Notification

        notification = create_offer_selected_by_commissioner_to_origin_group_notification(
            order_id=order_id,
            owner=user_id,
            store_name=store_name,
            owner_group=group_id,
            part_name=part_name,
            navigate_to_url='/order-management',
            meta_data={}
        )

        send_notification(notification, user_token)
    except Exception as e:
        print(f"❌ Critical error in notification system: {e}")


def get_commissioner_orders(commissioner_id: str):
    try:
        orders_found = list(orderRepository.find(
            {"part_request.commissioner_group": commissioner_id}))
        if orders_found is not None and len(orders_found) > 0:
            orders: List[Order] = []
            for order_data in orders_found:
                orders.append(Order(**order_data))

            return [order.toJson() for order in orders]

        return []
    except (PyMongoError, HTTPException) as e:
        raise HTTPException(e)
