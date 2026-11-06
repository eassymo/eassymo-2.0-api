# Firebase Auth Token — Frontend, API, and Microservice Integration

This document describes how **eassymo-2.0-client** (Next.js) and **eassymo-2.0-api** (FastAPI) use Firebase ID tokens, so a new microservice can accept the same credentials without inventing a separate auth scheme.

---

## Overview

Authentication is **Firebase Authentication**. After sign-in, the client obtains a Firebase **ID token** (JWT) and sends it on every protected API request. The API verifies that JWT with the **Firebase Admin SDK** and attaches the decoded claims to the request.

There is no separate session store or custom JWT issuer — the Firebase ID token is the credential.

```mermaid
sequenceDiagram
    participant User
    participant Client as eassymo-2.0-client
    participant Firebase as Firebase Auth
    participant API as eassymo-2.0-api
    participant MS as Your microservice

    User->>Client: Sign in (Google or phone OTP)
    Client->>Firebase: signInWithPopup / signInWithCredential
    Firebase-->>Client: Firebase User session
    Client->>Firebase: user.getIdToken() / getIdToken(true)
    Firebase-->>Client: ID token (JWT)
    Client->>Client: Persist as eassymo-token (cookie + localStorage)
    Client->>API: Authorization: Bearer <token><br/>GroupSelected: <groupId>
    API->>Firebase: auth.verify_id_token(token)
    Firebase-->>API: Decoded claims (uid, email, custom claims, …)
    API-->>Client: Response

    Note over Client,MS: Same token works for any service that verifies<br/>against the same Firebase project
    Client->>MS: Authorization: Bearer <token>
    MS->>Firebase: verify_id_token (Admin SDK)
    Firebase-->>MS: Decoded claims
    MS-->>Client: Response
```

---

## Firebase project

Both apps target the same Firebase project:

| Setting | Value |
|---|---|
| Project ID | `eassymo-416717` |
| Auth domain | `eassymo-416717.firebaseapp.com` |
| Realtime Database | `https://eassymo-416717-default-rtdb.firebaseio.com` |

Client config lives in `eassymo-2.0-client/src/utils/firebase.ts`.  
Server verification uses the Firebase **service account** for this project (see [API setup](#api-setup-firebase-admin-sdk)).

---

## Token type

Use the Firebase **ID token**, not the refresh token or access token from other OAuth flows.

- Issued by Firebase Auth after sign-in
- Short-lived JWT (~1 hour; Firebase SDK refreshes automatically)
- Verified server-side with `firebase_admin.auth.verify_id_token()`

Standard decoded fields your service will see:

| Claim | Description |
|---|---|
| `uid` | Firebase user ID — primary identity key across Eassymo |
| `email` | Present for Google sign-in |
| `phone_number` | Present for phone OTP sign-in |
| `name` | Display name when available |
| `email_verified` | Boolean |
| `super_admin` | Custom claim (`true` for platform admins) — see [Custom claims](#custom-claims) |
| `iss`, `aud`, `exp`, `iat`, `sub` | Standard JWT / Firebase fields |

In MongoDB, the `Users.uid` field links application records to Firebase (`UserSchema.uid` in the API).

---

## Frontend (eassymo-2.0-client)

### Sign-in methods

1. **Google SSO** — `signInWithPopup(auth, provider)` in `src/components/login/login.tsx`
2. **Phone OTP** — `signInWithPhoneNumber` + `signInWithCredential` in `src/components/verification/verification.tsx`

Both flows call Firebase, then immediately fetch and persist the ID token.

### Obtaining the token

After sign-in:

```typescript
// Google login
const tokenResult = await result.user.getIdTokenResult(true);
const token = tokenResult.token;

// Phone OTP
const token = await user.getIdToken(true);
```

For Realtime Database reads and session restore, `src/utils/firebase-auth.ts` exposes:

- `refreshFirebaseAuthToken(user)` — forces refresh via `getIdToken(true)` and persists
- `ensureFirebaseAuthSession()` — waits for `auth.authStateReady()`, then refreshes token

Pass `true` to `getIdToken` / `getIdTokenResult` when you need a freshly minted token (e.g. right after login or after custom-claim changes).

### Where the token is stored

The same token is written to **two places**:

| Storage | Key | Notes |
|---|---|---|
| Cookie | `eassymo-token` | `path=/`, long `max-age` (~100 years) |
| `localStorage` | `eassymo-token` | Mirror for client-side reads |

Helpers:

- `persistFirebaseAuthToken()` in `src/utils/firebase-auth.ts`
- `persistToken()` in `src/common/react-query/clients/eassymo-client.ts`

Logout clears the cookie in `src/utils/logout.ts`.

### Sending the token to the API

All authenticated HTTP calls go through `getClient()` in `src/common/react-query/clients/eassymo-client.ts`:

```typescript
headers['Authorization'] = `Bearer ${token}`;  // token from cookie eassymo-token
```

Optional multi-tenant header (active shop/group context):

```typescript
headers['GroupSelected'] = groupSelected;  // from cookie eassymo-group-selected
```

Base URL: `NEXT_PUBLIC_EASSYMO_API_URL` or default `https://www.eassymo-v2-api.com`.

### Automatic refresh on 401

The Axios response interceptor in `eassymo-client.ts`:

1. On `401`, calls `auth.currentUser.getIdToken(true)`
2. Updates `eassymo-token` in cookie + `localStorage`
3. Retries the original request with the new `Authorization` header

Your microservice should return `401` for expired or invalid tokens so clients can refresh the same way (if you share the same Axios client or copy this pattern).

### Post-login bootstrap

After sign-in, the client calls **`POST /users/create`** (public on the API) with `{ uid, email?, name?, phone? }` to upsert the MongoDB user. That endpoint does not require auth, but the client usually already has the token set.

Group context is saved separately via `saveAuthInfo()` (`eassymo-group-selected` cookie + localStorage keys under `eassymo-2-*`).

### Checking roles on the client

`useIsSuperAdmin()` reads `tokenResult.claims.super_admin === true` from the current Firebase user — UI gating only; **always enforce authorization on the server**.

---

## API (eassymo-2.0-api)

### Global auth middleware

Every request passes through `auth_middleware` in `main.py` except explicitly public routes.

Protected routes require:

```http
Authorization: Bearer <firebase-id-token>
```

Implementation: `verify_token()` in `app/middleware/auth_middleware.py`:

1. Reads `Authorization` header
2. Strips `Bearer ` prefix
3. Calls `verify_firebase_token(token)` → `firebase_admin.auth.verify_id_token()`
4. Sets `request.state.user` to the **full decoded token** (all claims)
5. Sets `request.state.groupSelected` from header `groupselected` (HTTP headers are case-insensitive; the client sends `GroupSelected`)

Route handlers typically read identity with:

```python
uid = request.state.user.get("uid")
```

### Public routes (no Firebase token)

Exact paths in `main.py`:

- `/docs`, `/redoc`, `/openapi.json`
- `POST /users/create`
- `POST /delivery/guest-orders`
- Prefixes: `/delivery-invite/`, `/mostrador/public/`, `/mostrador/tube/`

Special case: `POST /order/change-status` accepts **`X-Guest-Token`** instead of Firebase auth (guest delivery flow). See `docs/delivery-api.md`.

### API setup (Firebase Admin SDK)

Module: `app/utils/firebase_admin.py` (imported at startup from `main.py`).

Credential resolution order:

1. `FIREBASE_SERVICE_ACCOUNT_PATH` — path to JSON file
2. Local `*firebase-adminsdk*.json` in API project root (dev; gated by `ALLOW_LOCAL_FIREBASE_SERVICE_ACCOUNT_FILE`)
3. Individual env vars: `FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`, …
4. `FIREBASE_SERVICE_ACCOUNT_JSON` — full service account JSON string (used in production/Railway)

Also set:

```env
FIREBASE_RTDB_URL=https://eassymo-416717-default-rtdb.firebaseio.com
```

Verification entry point:

```python
from firebase_admin import auth

decoded = auth.verify_id_token(id_token)
uid = decoded["uid"]
```

Errors surface as `401` with `"Invalid Firebase token"` or `"Authorization header missing or invalid"`.

### Custom claims

Platform super-admins have Firebase custom claim `super_admin: true`.

- Set via `scripts/set_super_admin.py` or admin API (`AdminWriteService.manage_super_admin_claim`)
- Checked in API with `require_super_admin` dependency (`app/dependencies/super_admin.py`), which reads `request.state.user.get("super_admin") is True`
- Claim changes require the user to refresh their ID token (`getIdToken(true)`) before the new claim appears

### GroupSelected header

Not part of Firebase — it is **application context**: the MongoDB `_id` of the shop/group the user is acting as.

Many API services read:

```python
group_selected = request.state._state.get("groupSelected")
```

If your microservice is group-scoped the same way, accept the same header from the client:

```http
GroupSelected: 507f1f77bcf86cd799439011
```

Validate that the authenticated `uid` is allowed to operate on that group (the main API does this in service layer logic).

---

## Integrating your microservice

### Minimum requirements

1. **Same Firebase project** (`eassymo-416717`) — use a service account from that project
2. **Verify ID tokens** with Firebase Admin SDK (do not trust client-side decoding alone)
3. **Accept the same header** the frontend already sends:

```http
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
GroupSelected: <optional-group-id>
Content-Type: application/json
```

### Recommended verification flow

```python
# Python example (matches eassymo-2.0-api)
from firebase_admin import auth

def authenticate_request(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authorization header missing or invalid")
    token = authorization.removeprefix("Bearer ")
    try:
        return auth.verify_id_token(token)
    except Exception:
        raise HTTPException(401, "Invalid Firebase token")

# Use decoded["uid"] as the stable user identifier
```

Equivalent libraries exist for Node (`firebase-admin`), Go, Java, etc. — all call the same Firebase token verification.

### Identity mapping

| Layer | Identifier |
|---|---|
| Firebase Auth | `uid` from decoded token |
| MongoDB `Users` collection | `uid` field on user documents |
| API handlers | `request.state.user["uid"]` |

Look up app-specific profile/roles in your database by `uid`, not by email or phone alone (those can change or be absent depending on sign-in method).

### Token lifetime and refresh

- ID tokens expire in about **one hour**
- The web client refreshes via Firebase SDK when it gets a **401**
- Services should **not** issue their own long-lived tokens unless you add a separate B2B auth layer
- For server-to-server calls, use a **service account** or Firebase Admin — not a copied user ID token

### CORS

The main API allows all origins with credentials. If your microservice is called from the browser, allow the same frontend origins and expose `Authorization` / custom headers as needed.

### What not to do

- Do not accept the raw `eassymo-token` cookie name as a custom header — it is the same JWT; use standard `Authorization: Bearer`
- Do not skip signature verification or expiry checks
- Do not treat `GroupSelected` as proof of membership without server-side validation against `uid`

---

## Quick reference

### Authenticated request (from browser)

```http
GET /your-endpoint HTTP/1.1
Host: your-microservice.example.com
Authorization: Bearer <firebase-id-token>
GroupSelected: 664a1b2c3d4e5f6789012345
Content-Type: application/json
```

### Success

Use decoded claims; primary key = `uid`.

### Failure responses (match main API conventions)

| Status | When |
|---|---|
| `401` | Missing header, malformed `Bearer`, expired/invalid token |
| `403` | Valid token but insufficient claims (e.g. missing `super_admin`) |

Main API error shape:

```json
{ "detail": "Invalid Firebase token" }
```

---

## Source file index

| Area | Path |
|---|---|
| Firebase client init | `eassymo-2.0-client/src/utils/firebase.ts` |
| Token persist / RTDB session | `eassymo-2.0-client/src/utils/firebase-auth.ts` |
| HTTP client + Bearer header | `eassymo-2.0-client/src/common/react-query/clients/eassymo-client.ts` |
| Google login | `eassymo-2.0-client/src/components/login/login.tsx` |
| Phone OTP login | `eassymo-2.0-client/src/components/verification/verification.tsx` |
| Super admin UI check | `eassymo-2.0-client/src/common/hooks/use-is-super-admin.ts` |
| Auth middleware | `eassymo-2.0-api/main.py` |
| Token verification | `eassymo-2.0-api/app/middleware/auth_middleware.py` |
| Firebase Admin init | `eassymo-2.0-api/app/utils/firebase_admin.py` |
| Super admin dependency | `eassymo-2.0-api/app/dependencies/super_admin.py` |
| Grant super_admin claim | `eassymo-2.0-api/scripts/set_super_admin.py` |
| Guest auth (separate) | `eassymo-2.0-api/docs/delivery-api.md` |

---

## Related docs

- [Delivery API — guest token flow](./delivery-api.md) — uses `X-Guest-Token` instead of Firebase for specific public/guest endpoints
