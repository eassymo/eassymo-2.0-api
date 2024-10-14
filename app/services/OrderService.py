from app.repositories import OrderRepository as orderRepository
from fastapi import HTTPException
from app.schemas.Order import Order, OrderStatus
from app.schemas.Groups import GroupSchema
from app.schemas.PartRequest import PartRequest
from bson import ObjectId


def find(order_id: str, group_id: str, current_role: str):
    if group_id == None:
        raise HTTPException(status_code=400, detail="Group id is required")
    try:
        filters = {}
        response_obj = {
            "orders": [],
            "sales": []
        }

        if (order_id != None and len(order_id) > 0):
            order_id = ObjectId(order_id)
            filters["_id"] = order_id

        if (current_role != None and current_role == "1"):
            filters["group"] = group_id

        if (current_role != None and current_role == "2"):
            filters["offer.group_id"] = group_id

        orders = list(orderRepository.find(filters))

        order_list = []

        for order_data in orders:
            order_json = Order(**order_data).toJson()
            offer_group = GroupSchema(**order_data["offer_group"])
            request_group = GroupSchema(**order_data["request_group"])
            order_json = {**order_json, "offer_group": offer_group.toJson(),
                          "request_group": request_group.toJson()}

            order_list.append(order_json)

        response_obj = {
            "orders": order_list if current_role == "1" else [],
            "sales": order_list if current_role == "2" else []
        }

        return response_obj
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while fetching orders {e}')


def change_order_status(order_id: str, new_status: str):
    try:
        order_id = ObjectId(order_id)
        order_found = orderRepository.find_by_id(order_id)
        order = Order(**order_found)

        order.change_status(new_status)

        order_data = order.toJson()

        order_data.pop("_id")

        edited_order = orderRepository.edit(order_id, order_data)

        return Order(**edited_order).toJson()

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error while changing order status {e}')
