# Delivery API — Frontend Integration Guide

This document covers every new and modified endpoint introduced by the Delivery Person Assignment feature.
It is intended for the frontend team to implement the corresponding UI flows.

---

## Base URL

```
https://api.eassymo.mx   (production)
http://localhost:8000     (local)
```

All responses follow the envelope:

```json
// Success
{ "body": <payload> }

// Error
{ "error": "<message>" }
```

---

## Authentication

| Type | How |
|---|---|
| Firebase (default) | `Authorization: Bearer <firebase-id-token>` header |
| Guest token | `X-Guest-Token: <uuid>` header — **replaces** Firebase auth for the guest flow |
| Public | No header required |

---

## Role Constant

The **Delivery Person** role uses the existing `DEALER_SHOP` value:

```ts
// Update or add in your roles constants file
ROLES_USER.DELIVERY_PERSON = "215"   // same as DEALER_SHOP
```

---

## Order Shape Change

Every `Order` object now includes an optional `delivery_assignment` field. It is `null` until a delivery person is assigned.

```ts
type DeliveryAssignment = {
  type: "group_member" | "guest";
  // group_member only
  user_id?: string;
  // guest only
  guest_token?: string;
  guest_name?: string;
  guest_phone?: string;  // E.164, e.g. "+521234567890"
  assigned_at: string;   // ISO datetime string
};

type Order = {
  // ... existing fields ...
  delivery_assignment: DeliveryAssignment | null;
};
```

---

## New Endpoints

---

### 1. List Delivery Persons

Fetches all registered users with the Delivery Person role that belong to a group.
Used to populate the dropdown when a seller is assigning a registered courier.

```
GET /delivery-persons?group_id=<string>
```

**Auth:** Firebase (requesting user must belong to `group_id`)

**Query params**

| Param | Type | Required | Description |
|---|---|---|---|
| `group_id` | string | YES | The selling group ID |

**Success response `200`**

```json
{
  "body": [
    {
      "_id": "64abc123...",
      "name": "Juan Pérez",
      "phone": "+521234567890",
      "email": "juan@example.com",
      "uid": "firebaseUid"
    }
  ]
}
```

**Error responses**

| Status | Reason |
|---|---|
| 403 | Requesting user does not belong to `group_id` |
| 404 | Requesting user not found |

---

### 2. Assign Delivery & Dispatch Order

Assigns a delivery person to an order **and** advances its status from `READY_TO_BE_DISPATCHED` → `DISPATCHED` in one call.

> **This replaces calling `POST /order/change-status` with `new_status: "DISPATCHED"` directly.**
> That call will no longer work for the DISPATCHED transition.

```
POST /order/assign-delivery
```

**Auth:** Firebase (requesting user must belong to the selling group of the order)

**Request body**

```json
{
  "order_id": "64abc123...",
  "assignment_type": "group_member"
}
```

```json
{
  "order_id": "64abc123...",
  "assignment_type": "guest",
  "guest_name": "Carlos López",
  "guest_phone": "+521234567890"
}
```

**Body fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `order_id` | string | YES | MongoDB `_id` of the order |
| `assignment_type` | `"group_member"` \| `"guest"` | YES | |
| `user_id` | string | Only for `group_member` | Firebase `uid` of the delivery person |
| `guest_name` | string | Only for `guest` | Display name of the courier |
| `guest_phone` | string | Only for `guest` | E.164 phone number |
| `guest_token` | string | NO | Pre-existing guest UUID token. When supplied the backend skips profile creation and validates the token matches `guest_phone`. Omit to let the backend look up or create the profile automatically. |

**What the server does**

- For `group_member`: validates the user has the Delivery Person role in the same group.
- For `guest`: looks up or creates a `GuestDeliveryProfile` by phone, sends a WhatsApp invite to `guest_phone` with the link `https://eassymo.mx/delivery-invite/<token>`.
- Saves `delivery_assignment` on the order and sets `status = "DISPATCHED"`.

**Success response `200`**

```json
{
  "body": { /* full updated Order object */ }
}
```

**Error responses**

| Status | Reason |
|---|---|
| 400 | Order is not in `READY_TO_BE_DISPATCHED` |
| 400 | `order_id` or `assignment_type` missing |
| 403 | Requesting user not in selling group |
| 404 | Order not found |
| 404 | Delivery user not found or missing role |
| 422 | Required fields missing for the chosen `assignment_type` |

---

### 3. Delivery Person — My Orders

Returns all orders assigned to the currently authenticated delivery person.

```
GET /delivery/my-orders
```

**Auth:** Firebase — user must have role `"215"` (Delivery Person)

**Query params**

| Param | Type | Required | Description |
|---|---|---|---|
| `status` | string | NO | Filter by order status (e.g. `DISPATCHED`, `RECIEVED`) |

**Success response `200`**

```json
{
  "body": [
    {
      "_id": "...",
      "order_id": "17-4-25-ab12",
      "status": "DISPATCHED",
      "to_be_delivered_time": "2025-04-17T15:00:00+00:00",
      "delivery_assignment": {
        "type": "group_member",
        "user_id": "firebaseUid",
        "assigned_at": "2025-04-17T14:00:00+00:00"
      },
      "offer_group": { "name": "Refaccionaria XYZ", "address": "..." },
      "request_group": { "name": "Taller ABC", "address": "..." },
      "part_request": { /* items — pricing fields are stripped */ }
    }
  ]
}
```

> Offer pricing fields (`price`, `margin`, `unit_price`, `total_price`) are removed from the response.

**Error responses**

| Status | Reason |
|---|---|
| 403 | User does not have Delivery Person role |

---

### 4. Guest — My Orders

Returns all orders assigned to a guest delivery token. No Firebase auth needed.

```
GET /delivery/guest-orders?token=<uuid>
```

**Auth:** None (public endpoint, guarded by token)

**Query params**

| Param | Type | Required | Description |
|---|---|---|---|
| `token` | string | YES | Guest delivery UUID token |
| `status` | string | NO | Filter by order status |

**Success response `200`**

Same shape as `GET /delivery/my-orders`.

**Error responses**

| Status | Reason |
|---|---|
| 404 | Token not found or guest profile is inactive |

---

### 5. Guest Invite Preview

Returns the invite summary shown on the public landing page before the guest taps "Aceptar".

```
GET /delivery-invite/:token
```

**Auth:** None (public)

**URL params**

| Param | Description |
|---|---|
| `token` | Guest delivery UUID token |

**Success response `200`**

```json
{
  "body": {
    "guest_name": "Carlos López",
    "guest_phone": "+521234567890",
    "orders_count": 2,
    "latest_order": {
      "_id": "...",
      "order_id": "17-4-25-ab12",
      "status": "DISPATCHED",
      "to_be_delivered_time": "...",
      "offer_group": { "name": "Refaccionaria XYZ", "address": "..." },
      "request_group": { "name": "Taller ABC", "address": "..." }
    }
  }
}
```

`latest_order` is `null` when no orders are assigned yet.

**Error responses**

| Status | Reason |
|---|---|
| 404 | Token not found or profile inactive |

---

### 6. Guest Accept Invite

Called when the guest taps "Aceptar entrega". Records the acceptance timestamp and returns all assigned orders.

```
POST /delivery-invite/:token/accept
```

**Auth:** None (public)

**URL params**

| Param | Description |
|---|---|
| `token` | Guest delivery UUID token |

**Request body:** Empty `{}` or omit.

**Success response `200`**

```json
{
  "body": {
    "token": "550e8400-e29b-41d4-a716-446655440000",
    "orders": [
      { /* Order object — same shape as GET /delivery/guest-orders */ }
    ]
  }
}
```

**Error responses**

| Status | Reason |
|---|---|
| 404 | Token not found or profile inactive |

---

## Modified Endpoint

---

### 7. Change Order Status — Delivery Person Guard

The existing `POST /order/change-status` endpoint now enforces restrictions for delivery persons.

```
POST /order/change-status
```

**No change to the request body shape.**

```json
{
  "order_id": "64abc123...",
  "new_status": "RECIEVED"
}
```

#### New behaviour for registered delivery persons (Firebase auth)

If the authenticated user has role `"215"`:
- Only `new_status: "RECIEVED"` is allowed. Any other status returns `403`.
- The order must have `delivery_assignment.user_id` equal to the requesting user's `uid`. Otherwise returns `403`.

#### New behaviour for guest delivery persons (token auth)

Pass the guest token as a header **instead of** a Firebase Bearer token:

```
X-Guest-Token: <uuid>
```

No `Authorization` header is needed when `X-Guest-Token` is present.

- Only `new_status: "RECIEVED"` is allowed.
- The order must have `delivery_assignment.guest_token` matching the provided token.

**Example (guest confirm delivery):**

```ts
fetch("/order/change-status", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Guest-Token": guestToken,   // no Authorization header
  },
  body: JSON.stringify({
    order_id: orderId,
    new_status: "RECIEVED",
  }),
});
```

**Error responses added**

| Status | Reason |
|---|---|
| 403 | Delivery person trying to set a status other than `RECIEVED` |
| 403 | Order not assigned to this user / token |
| 404 | Order not found |
| 404 | Guest token not found or inactive |

---

## Frontend Flows Summary

### Seller dispatches an order

```
1. Show modal: "Assign Delivery Person"
2. Fetch   GET /delivery-persons?group_id=<sellerGroupId>
3. Seller picks registered person  →  POST /order/assign-delivery  { assignment_type: "group_member", user_id }
   OR
   Seller enters guest phone/name  →  POST /order/assign-delivery  { assignment_type: "guest", guest_name, guest_phone }
4. Order status is now DISPATCHED — update local state from response body.
```

### Guest delivery invite page  (`/delivery-invite/:token`)

```
1. Parse token from URL.
2. Fetch   GET /delivery-invite/:token        → show name, order summary
3. Guest taps "Aceptar"
4. Call    POST /delivery-invite/:token/accept → navigate to order list
5. Show    orders from accept response
```

### Guest confirms delivery received

```
POST /order/change-status
Headers: { "X-Guest-Token": token }
Body:    { "order_id": id, "new_status": "RECIEVED" }
```

### Registered delivery person views and confirms

```
1. Fetch   GET /delivery/my-orders?status=DISPATCHED
2. Show order list
3. Tap "Confirmar entrega"
4. POST /order/change-status  (with normal Firebase auth)
   Body: { "order_id": id, "new_status": "RECIEVED" }
```

---

## Status Flow Reference

```
WAITING_FOR_CONFIRMATION
        ↓
    CONFIRMED
        ↓
READY_TO_BE_DISPATCHED
        ↓  ← POST /order/assign-delivery  (replaces direct DISPATCHED change)
   DISPATCHED
        ↓  ← POST /order/change-status { new_status: "RECIEVED" }
    RECIEVED
```

`CANCELED` can be set from any state (existing behaviour — not affected by this feature).
