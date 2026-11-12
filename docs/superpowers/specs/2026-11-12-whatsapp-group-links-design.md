# WhatsApp links per group — design

Status: draft for review · Date: 2026-11-12 · Project 1 of 2 (project 2: permissions and My Team, separate spec)

## 1. Goal

A WhatsApp POS number is linked to a user **in a group**, not to the user account. The same
user can have different access in each group, derived from their role in that group.

Success looks like:

- A user links a number in group A and the same number in group B with independent state.
- A user whose role in a group does not allow WhatsApp POS cannot create drafts there, even if
  they are a member and even if their number is linked in other groups.
- Changing a role, removing a member, or an owner disabling a link takes effect on the next
  inbound message, with no waiting for a sticky store selection to expire.
- Everyone who uses WhatsApp POS today and is still entitled to it keeps working after cutover.

## 2. Decisions already made

| Question | Decision |
| --- | --- |
| Can one number be linked in several of a user's groups? | Yes. The store picker stays, listing only allowed groups. |
| Where do privileges come from? | From the user's role in that group, through one access check (`can`). The owner always passes. |
| Permissions framework (role bundles, individual grants and denies, My Team UI)? | Out of scope. Project 2. This project only introduces the `can` seam it will plug into. |

## 3. Non-goals

- Permission registry, roles as permission bundles, individual grants or denies, My Team changes.
- Owner-facing UI to list or disable links (API only here).
- Fixing the role-name mismatch between client and API (confirmed for this mapping, fully fixed in project 2).
- Removing `users.pos_whatsapp` (left in place, no longer read).
- Changing how drafts are extracted from messages.

## 4. Current behaviour (for reference)

- `users.pos_whatsapp` holds one verified number per user, written by
  `WhatsappIntakeVerificationService.confirm`. A number may belong to only one account.
- `WhatsappSellerIdentityService.resolve` finds the user by number, lists their groups
  (`groupRepository.find_by_user`), resolves directly with one group, otherwise asks in chat
  (`CAMBIAR` changes store, selection is sticky for `WHATSAPP_GROUP_STICKY_HOURS`).
- No role is checked anywhere in this flow.

## 5. Design

### 5.1 Data model

New collection `WhatsappLinks`:

| Field | Type | Notes |
| --- | --- | --- |
| `uid` | str | Owner of the link. |
| `group_id` | str | Group the link applies to. |
| `phone` | str | Canonical `+521XXXXXXXXXX`, same canonicalisation as `_canonical_pos_phone`. |
| `verified_at` | datetime (UTC) | When the number was proven. |
| `status` | `active` or `disabled` | |
| `disabled_by`, `disabled_at` | str, datetime, optional | Set when the owner disables. |
| `created_at`, `updated_at` | datetime (UTC) | |

Indexes: unique `(uid, group_id)`; `phone` for inbound lookup.

Invariants:

- One link per user and group.
- A number belongs to one user account across all groups. Availability checks consult
  `WhatsappLinks` and, until the field is dropped, legacy `users.pos_whatsapp`.
- The same number may appear on several links of the same user. A user may also use different
  numbers in different groups.

New repository `WhatsappLinkRepository` with: `ensure_indexes`, `find(uid, group_id)`,
`find_any_by_phone(phone)` (uses `phone_lookup_variants`), `list_by_uid(uid)`, `upsert(uid, group_id, phone, verified_at)`, `set_status(uid, group_id, status, by)`.

`WhatsappIntakeVerifications` documents gain `group_id`. Open-pending lookup, supersede, the
resend cooldown and the "max 2 distinct numbers per 24h" counter are all scoped to
`(uid, group_id)`. Index becomes `(uid, group_id, status)`. Pre-existing documents have no
`group_id`; they expire within 24h and are ignored.

### 5.2 Access policy (the seam for project 2)

New module `app/services/access_policy.py`:

```python
PERMISSION_WHATSAPP_CREATE_DRAFT = "whatsapp.create_draft"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "212": frozenset({PERMISSION_WHATSAPP_CREATE_DRAFT}),  # ADMIN_SELLER_SHOP
    "213": frozenset({PERMISSION_WHATSAPP_CREATE_DRAFT}),  # SELLER_SHOP
}

def can(uid: str, group_id: str, permission: str) -> bool: ...
```

`can` returns true when the user belongs to the group (`user_belongs_to_group`) and either is the
group owner (`is_group_owner`) or holds an active `UserRoles` row for that group whose role grants
the permission. Everything else is false, including a missing group.

Rules for callers: ask `can(...)`; never compare role codes. Granting a new role access means
adding a line to `ROLE_PERMISSIONS`. Project 2 replaces the internals of `can` (role bundles plus
individual grants and denies) without changing its signature or any call site.

`can` is evaluated at: link start, link confirm, every inbound message resolution, and
immediately before a draft folio is created (see 5.4).

### 5.3 Verification flow

All member endpoints keep their paths under `/users/me/whatsapp-intake/`.

- `GET status`: group from the `GroupSelected` header via `require_group_membership_from_header`.
  Response keeps the existing keys (`pos_whatsapp`, `pos_whatsapp_verified_at`, `verified`,
  `pending`, `can_change`, `next_change_at`), now meaning "this group's link", and adds
  `group_id`, `link_status` (`active`, `disabled` or null), `can_use` (result of `can`) and
  `suggested_phone` (the user's most recently verified number in another group, or null) and
  `group_name`.
- `POST start`: same group resolution. Order of checks: membership, `can` (403
  "Tu rol en esta tienda no permite usar WhatsApp POS."), link not disabled (403
  "El dueño desactivó tu WhatsApp en esta tienda."), number not owned by another account (409,
  existing message), cooldown and distinct-number limits per `(uid, group)`.
  - **Instant link:** if the user already has a link with the same number (any group, any
    status) the new link is created immediately with no template message, and the response is
    `{ linked: true, pos_whatsapp, pos_whatsapp_verified_at }`. Otherwise the existing
    template-and-token flow runs and the response is `{ linked: false, message, masked_phone }`.
- `GET pending/{token}`: group comes from the token record, not the header, because the user
  opens this from a WhatsApp message and the selected group may differ. Checks that the token
  belongs to the caller and that the caller is still a member. Response adds `group_id` and
  `group_name`.
- `POST confirm`: group from the token. Re-checks membership, `can`, link not disabled and number
  availability, then upserts the link for `(uid, token.group_id)`. It no longer writes
  `users.pos_whatsapp`.

Changing the number in a group updates that group's link only.

### 5.4 Inbound routing

`WhatsappSellerIdentityService.resolve` computes the **allowed set** first, on every message:

1. `find_any_by_phone(normalized)` returns links of every status. If they belong to more than one
   `uid`, log an error and return `ambiguous` with a generic message ("No pudimos identificar tu
   cuenta. Contacta a soporte."). This should be impossible given the invariant.
2. Keep links with `status == "active"` whose `can(uid, group_id, "whatsapp.create_draft")` is
   true. Their groups are the candidates; `creator_uid` is the link's `uid`.
3. Outcomes:
   - No links at all: `pending_link` with the existing text, adding "elige tu tienda" to the
     path ("Mi cuenta → WhatsApp para POS, elige tu tienda, confirma tu número…").
   - Links exist but none is active and allowed (disabled by the owner, or role not allowed):
     `pending_link` with "Tu WhatsApp está vinculado, pero no tienes acceso a WhatsApp POS en
     ninguna tienda. Pide acceso al dueño de la tienda."
   - One allowed group: `resolved`, pending association cleared.
   - Several: existing picker and `CAMBIAR` flow over the allowed groups only.

The `WhatsappPendingAssociations` document keeps the sticky selection, prompt cooldown and the
unknown-number marker. Its `candidates` are rewritten from the allowed set on each resolution
instead of being trusted. A sticky `selected_group_id` that is not in the allowed set is cleared
and resolution continues as above, so revocation is immediate.

**Last guard:** at the top of `_flush_session_body` (WhatsappIntakeProcessorService), after
`_ensure_flush_owner` and before `_replay_linked_draft`, it calls `can` and confirms the link is
still active. On failure it sends the "no access" message, creates nothing and skips the model
call. Being at the top of the flush it covers the resume and edit paths as well as new drafts,
and a role change in the middle of a buffered burst.

### 5.5 Owner control (API only)

New router `WhatsappLinksRouter` registered in `main.py`:

- `POST /groups/{group_id}/whatsapp-links/{uid}/disable`
- `POST /groups/{group_id}/whatsapp-links/{uid}/enable`

Both require `assert_group_owner`. Disable sets `status=disabled`, `disabled_by`, `disabled_at`.
Enable sets `status=active` and clears them. A disabled link cannot be reactivated by the member
(`start` and `confirm` refuse). Enabling does not bypass `can`.

### 5.6 Client

- `useWhatsappIntake.ts`: status query key includes the selected group id
  (`getSelectedGroupId()` from `eassymo-client.ts`), so switching groups refetches. Types gain
  the new fields. Confirm and start mutations invalidate by group.
- `whatsapp-pos-settings.tsx`: shows which group the link belongs to; renders three extra
  states: role not allowed (explanation, no form), disabled by owner (explanation, no form),
  and instant link (success without the waiting-for-confirmation UI). Pre-fills the form from
  `suggested_phone` when present.
- `whatsapp-verify-confirm.tsx`: uses `group_name` from the preview ("Vincular a <Tienda>").
- Reuse existing components and the current type scale and colours; no new visual language.
- Legacy `pos_whatsapp` fields on `useCreateUser` and `Group` types are left untouched.

### 5.7 Migration

Script `scripts/migrate_whatsapp_links.py` (same conventions as the other scripts), with
`--dry-run` (default) and `--apply`.

For every user with a non-empty `pos_whatsapp`:

1. Canonicalise the number; values that fail are reported and skipped.
2. For each group in `groupRepository.find_by_user(uid)`: if `can(...)` is true, upsert an
   `active` link with `verified_at` from `pos_whatsapp_verified_at` (or now if absent). Inserts
   only, so reruns never overwrite newer links.
3. Otherwise report the user, group and reason (not owner and no role row, or role not allowed).
4. If one number appears on more than one user, report and skip both.

The report prints masked numbers and counts. **Dry run is reviewed before anything is applied**;
it is where members listed in a group with no role row (legacy) become visible.

The dry run also reads existing links (it reports `would_create` / `would_exist`). Because
`link_repo.find` calls `ensure_indexes`, it may create the `(uid, group_id)` unique index if
missing. Check for duplicate `(uid, group_id)` rows first; there should be none, since the
collection is new.

Cutover: `--apply`, deploy, `--apply` again (idempotent, catches users who linked on the old code
in between). Rollback: redeploy the previous version; `users.pos_whatsapp` is untouched. Links
created after cutover are not visible to the old code, which is accepted.

## 6. Error handling and edge cases

- Member removed from a group, role removed, group deleted: `can` is false, so the link is
  inert but kept; it works again if access is restored.
- Ownership transfer: the new owner passes `can`; the previous owner needs a role.
- Concurrent `start` for the same `(uid, group)`: unique index plus existing supersede logic.
- Missing `GroupSelected` on member endpoints: 400 from the existing header helper.
- Token for a group the caller no longer belongs to: 403 on preview and confirm.

## 7. Testing (TDD, mocked repositories as in `tests/test_whatsapp_intake.py`)

API:

- `test_access_policy`: owner passes; role in table passes; role not in table fails; no role row
  fails; non-member fails; inactive role row fails.
- `test_whatsapp_links`: link scoped per group; same number in two groups of one user; number
  owned by another account returns 409 (including a legacy `pos_whatsapp` owner); instant link
  skips the template; limits and cooldown are per `(uid, group)`; disabled link blocks start and
  confirm; confirm uses the token's group.
- `test_whatsapp_seller_identity`: zero links; links but none allowed; one allowed; several allowed
  (picker lists only allowed); sticky selection dropped when access is revoked; `ambiguous` on two uids.
- `test_whatsapp_links_router`: disable and enable are owner-only.
- Draft guard: no folio is created when `can` turns false mid-burst.
- `test_migrate_whatsapp_links`: idempotent; dry run writes nothing; reports skips.
- Update `tests/test_whatsapp_intake.py` where it assumes `users.pos_whatsapp`.

Client: update `whatsapp-verify-confirm.test.tsx`; add tests for the three new settings states
and for per-group query keys; refresh Cypress fixtures that carry `pos_whatsapp` if they exercise
this screen.

## 8. Open items to confirm during review

1. **Role mapping.** The proposed table allows owner, `212` and `213`. The API enum names `212`
   ADMIN_SELLER_SHOP and `213` SELLER_SHOP; the client's role dictionary labels `322` and `212`
   the other way round. This spec follows the API. Confirm which codes are the parts-store side.
2. **Legacy members.** Members listed in a group with no role row lose access under the role
   rule. The dry run quantifies this; decide then whether to backfill roles first.
3. **Instant link.** Reusing a previously verified number in another group skips re-verification.
   Confirm this is acceptable.
4. **Spanish copy** in section 5.3 and 5.4, including the implemented instant-link message
   "Vinculamos este número a tu tienda." and the membership 403 "No perteneces a esta tienda."
   (to confirm).

## 9. Follow-up: project 2

Permission registry, roles as bundles of permissions, individual grants and denies per member,
My Team role and permission UI, owner list and disable UI for WhatsApp links, role-name cleanup,
and replacing the internals of `can`. Separate spec, plan and implementation after this ships.
