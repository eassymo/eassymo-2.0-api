# ADR-001: Mongo source of truth, RTDB as realtime bus

## Status

Accepted

## Date

2026-09-02

## Context

Eassymo needs live updates for part-request/order chat, in-app notifications, and (later) typing indicators. Today chat and notifications are dual-written: Mongo for persistence and unread state, Firebase RTDB for live listeners. Client code also writes notifications and chat messages directly to RTDB, which creates split-brain risk, weak security rules, and scaling limits (embedded message arrays, unbounded inbox growth).

Constraints:

- FastAPI on uvicorn (Railway); we must not host a connection fleet on the API process.
- Firebase Auth and FCM remain.
- Team size favors incremental migration without a big-bang outage.

## Options Considered

### Option A: Keep RTDB as live store (status quo)

- Pros: No migration; live updates work today.
- Cons: Dual-write, open chat rules, client-authored inboxes, bad chat node shape.

### Option B: Mongo source of truth; RTDB as server-written event/presence bus

- Pros: Single write path; RTDB holds tiny ephemeral events; typing fits naturally; sockets stay off API.
- Cons: Migration work; RTDB rules redesign; ACL grants required for chat secrecy.

### Option C: Discard RTDB; managed bus (Ably/Pusher)

- Pros: Cleaner vendor split; better presence APIs.
- Cons: New vendor and cost; larger migration than B.

### Option D: WebSockets on FastAPI

- Pros: No Firebase realtime bill.
- Cons: Redis + sticky sessions; idle connections on API; wrong fit for current deploy model.

## Decision

We choose **Option B**:

1. **Mongo** is the only source of truth for chat messages and notification records.
2. **RTDB** carries **events** and **presence** only, written by the **Admin SDK** (API), not clients.
3. Clients subscribe to narrow channels; they fetch history from REST.
4. **FCM** remains for background push.
5. Legacy RTDB paths (`notifications/`, `part-request-chats/`, etc.) are retired in phases; client writes are locked last.

## RTDB path contract

| Path | Purpose | Client read | Client write |
|------|---------|-------------|--------------|
| `events/inbox/{uid}/{eventId}` | New notification signal | Owner uid only | None |
| `events/chat/{type}/{entityId}/{eventId}` | New message signal | If `acl/chats/.../{uid}` | None |
| `acl/chats/{type}/{entityId}/{uid}` | Chat access grant | Owner uid only | None |
| `presence/chat/{type}/{entityId}/{uid}` | Typing indicator | If ACL granted | Own uid only |

Event payloads stay small (ids, type, minimal fields). Full documents live in Mongo.

Implementation entry point: `app/services/realtime_bus.py`.

## Consequences

- All notification creates move server-side over time; no trusted client inbox writes.
- Chat send is API-only; RTDB publishes `message.created` after Mongo commit.
- RTDB publish failures are logged and do not roll back Mongo (same as FCM today).
- Phased rollout: new paths and bus first, cutover chat/notifications, migrate legacy inbox, lock rules last.
- Evaluator gate required before production rules lockdown.

## Supersedes

N/A (initial ADR for realtime architecture).
