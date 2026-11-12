# WhatsApp Links per Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A WhatsApp POS number is linked to a user in a group, with access derived from the user's role in that group.

**Architecture:** A new `WhatsappLinks` collection (one row per user and group) replaces `users.pos_whatsapp` as the source of truth. A single `can(uid, group_id, permission)` check in `access_policy.py` decides access, and inbound routing, link verification and the draft flush all call it. Verification records become group-scoped, and a migration script seeds links from the legacy field.

**Tech Stack:** FastAPI, pymongo, pytest with `unittest.mock` (API, Python 3.11); Next.js, React Query, MUI, Jest and Testing Library (client).

**Spec:** `docs/superpowers/specs/2026-11-12-whatsapp-group-links-design.md` (API repo). Read it first; section numbers below refer to it.

## Global Constraints

- Repos: API at `eassymo-2.0-api`, client at `eassymo-2.0-client`. Paths below are relative to the repo named in each task.
- Permission string: `whatsapp.create_draft`. Role table: `{"212", "213"}` map to it; the group owner always passes. No other role codes.
- Collection `WhatsappLinks`; `status` is `active` or `disabled`; phones stored canonical `+521XXXXXXXXXX`.
- Limits unchanged but counted per `(uid, group_id)`: max 2 distinct numbers per rolling 24h, 60s resend cooldown, 24h pending TTL.
- A number belongs to one user account; availability checks consult `WhatsappLinks` and legacy `users.pos_whatsapp`.
- `confirm` never writes `users.pos_whatsapp`; the legacy field is no longer read.
- Spanish copy is exact:
  - 403 role: `Tu rol en esta tienda no permite usar WhatsApp POS.`
  - 403 disabled: `El dueño desactivó tu WhatsApp en esta tienda.`
  - 409 (existing): `Este WhatsApp ya está vinculado a otra cuenta.`
  - Unlinked prompt: `No encontramos tu WhatsApp en Eassymo. En la app ve a Mi cuenta → WhatsApp para POS, elige tu tienda, confirma tu número y reenvía tu mensaje.`
  - No access: `Tu WhatsApp está vinculado, pero no tienes acceso a WhatsApp POS en ninguna tienda. Pide acceso al dueño de la tienda.`
  - Ambiguous: `No pudimos identificar tu cuenta. Contacta a soporte.`
- Test commands: API `.venv/bin/python -m pytest <path> -q` from the API repo root; client `npx jest <path>` from the client repo root. Baselines: client `src/components/user-configuration` is 9 suites and 59 tests, all passing.
- Commits: API repo uses `ian.codingmakers@gmail.com`. Client repo uses `admin@eassymo.com`; run `git config user.email` first and stop if it differs. Commit steps run only after the user approves this plan for execution. End commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Reuse the client's existing components, tokens (`NAV_SHELL`, `WA_POS`) and type scale. No new visual language.

## Review Focus

Spec-implied conditions no obvious test covers; each has a test in the task named.

- The same number arriving as `+527779313704`, `+5217779313704` or `7779313704` must hit the same link (Task 5).
- A garbage or unknown `GroupSelected` header returns 4xx, never 500: `groupRepository.find_by_id` raises on a malformed ObjectId (Tasks 2 and 4).
- A link pointing at a deleted group is dropped from candidates and never crashes the picker (Task 5).
- Access revoked while a burst is buffering: no extraction call, no draft (Task 6).
- The owner disables a link while the member's verification token is still open: `confirm` refuses (Task 3).

## File Structure

API (create): `app/repositories/WhatsappLinkRepository.py`, `app/services/access_policy.py`, `app/routers/WhatsappLinksRouter.py`, `app/services/WhatsappLinkMigrationService.py`, `scripts/migrate_whatsapp_links.py`.
API (modify): `app/utils/phone_normalize.py`, `app/repositories/WhatsappIntakeVerificationRepository.py`, `app/repositories/WhatsappPendingAssociationRepository.py`, `app/services/WhatsappIntakeVerificationService.py`, `app/services/WhatsappSellerIdentityService.py`, `app/services/WhatsappIntakeProcessorService.py`, `app/routers/UserRouter.py`, `main.py`, `tests/test_whatsapp_intake.py`.
API (tests, create): `tests/test_whatsapp_link_repository.py`, `tests/test_access_policy.py`, `tests/test_whatsapp_link_verification.py`, `tests/test_user_whatsapp_intake_router.py`, `tests/test_whatsapp_seller_identity.py`, `tests/test_whatsapp_flush_guard.py`, `tests/test_whatsapp_links_router.py`, `tests/test_whatsapp_link_migration.py`.
Client (modify): `src/common/react-query/mutations/useWhatsappIntake.ts`, `src/components/user-configuration/whatsapp-pos-settings/whatsapp-pos-settings.tsx` and its test, `src/components/user-configuration/whatsapp-verify/whatsapp-verify-confirm.tsx` and its test. Client (create): `src/common/react-query/mutations/useWhatsappIntake.test.tsx`.

## Deviations from the spec (fix the spec in Task 12)

1. `GET status` also returns `group_name`, so the client can show which store the link belongs to.
2. The last guard (spec 5.4) sits at the top of `_flush_session_body`, not in `_create_draft_from_proposal`. The session already carries `group_id` and `creator_uid`, and this single point also covers resume and edit paths and skips the model call.

---

### Task 0: Python 3.11 test environment (API)

The project targets Python 3.11 (`Dockerfile`); the machine has only 3.9, which cannot import the app (`str | None` annotations). No `pytest` is installed.

**Files:** none tracked. `.venv` is already in `.gitignore`.

- [ ] **Step 1:** Install Python 3.11 (`brew install python@3.11`), then `python3.11 -m venv .venv` and `.venv/bin/pip install -r requirements.txt pytest` in the API repo.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests -q -x --ignore=tests/whatsapp_messy_corpus.py`. Expected: the existing suite runs. Record the pass and fail counts in the task notes as the baseline; failures that exist now are not this plan's to fix.
- [ ] **Step 3:** `git status --short` shows no new tracked or untracked files.

---

### Task 1: Canonical phone helper and `WhatsappLinkRepository`

**Files:**
- Modify: `app/utils/phone_normalize.py`, `app/services/WhatsappIntakeVerificationService.py` (only the `_canonical_pos_phone` call sites)
- Create: `app/repositories/WhatsappLinkRepository.py`
- Test: `tests/test_whatsapp_link_repository.py`, plus phone cases in `tests/test_whatsapp_intake.py`

**Interfaces:**
- Produces: `canonical_pos_phone(phone: str) -> str` in `phone_normalize.py`; raises `ValueError("Ingresa un WhatsApp válido de 10 dígitos.")`. Same rules as today's `_canonical_pos_phone` (10 digits becomes `+521…`; `52` plus 10 digits becomes `+521…`; otherwise `+<digits>`).
- Produces, in `WhatsappLinkRepository` (collection `WhatsappLinks`, `_col()` helper as in the sibling repos):
  - `ensure_indexes() -> None`: unique `(uid, group_id)`; index on `phone`.
  - `find(uid: str, group_id: str) -> Optional[dict]`
  - `find_any_by_phone(phone: str) -> List[dict]`: filter `{"phone": {"$in": phone_lookup_variants(phone)}}`.
  - `list_by_uid(uid: str) -> List[dict]`
  - `upsert(uid: str, group_id: str, phone: str, verified_at: datetime) -> dict`: `$set` phone, verified_at, updated_at; `$setOnInsert` status `active`, created_at. Never changes an existing status.
  - `insert_if_absent(uid: str, group_id: str, phone: str, verified_at: datetime) -> bool`: `$setOnInsert` only; returns true when a row was created.
  - `set_status(uid: str, group_id: str, status: str, by: Optional[str]) -> bool`: `disabled` sets `disabled_by` and `disabled_at`; `active` clears both; returns whether a row matched.

- [ ] **Step 1: Write failing tests.** `test_canonical_pos_phone_*` for 10 digits, `52`-prefixed 12 digits, `+521…` unchanged, and fewer than 10 digits raising `ValueError`. Repository tests patch `app.repositories.WhatsappLinkRepository._col` with a `MagicMock` and assert: `find_any_by_phone("7779313704")` queries `$in` containing `+5217779313704` and `+527779313704`; `upsert` calls `update_one` with filter `{"uid","group_id"}`, `upsert=True` and `status` only inside `$setOnInsert`; `insert_if_absent` returns true only when `upserted_id` is set; `set_status("u","g","disabled","owner")` sets `disabled_by`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_whatsapp_link_repository.py -q`. Expected: FAIL on import.
- [ ] **Step 3:** Implement the helper and the repository as specified. `WhatsappIntakeVerificationService` switches to `canonical_pos_phone` and wraps `ValueError` into `HTTPException(400, str(error))`; delete `_canonical_pos_phone`.
- [ ] **Step 4:** Run the new tests and `tests/test_whatsapp_intake.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): add WhatsappLinks repository and canonical phone helper` (API repo).

---

### Task 2: Access policy

**Files:**
- Create: `app/services/access_policy.py`
- Test: `tests/test_access_policy.py`

**Interfaces:**
- Consumes: `group_auth.user_belongs_to_group(uid, group_id) -> bool`, `group_auth.is_group_owner(uid, group_id) -> bool`, `UserRolesRepository.find(filters) -> List[UserRoles]` (objects with `.role`).
- Produces: `PERMISSION_WHATSAPP_CREATE_DRAFT = "whatsapp.create_draft"`; `ROLE_PERMISSIONS: Dict[str, frozenset]` (table in Global Constraints); `can(uid: str, group_id: str, permission: str) -> bool`.

Behaviour: false for empty `uid` or `group_id`. False if the user is not a member. True for the owner. Otherwise true when any `UserRolesRepository.find({"user_uid": uid, "group": group_id, "active": True})` row has a role whose set contains `permission`. Any exception from a malformed group id (`bson.errors.InvalidId`) returns false.

- [ ] **Step 1: Write failing tests** (patch `app.services.access_policy.group_auth` and `app.services.access_policy.userRolesRepository`): `test_owner_passes_without_role_row`, `test_listed_role_passes[212,213]`, `test_unlisted_role_fails` (e.g. `"215"`), `test_no_role_row_fails`, `test_non_member_fails`, `test_unknown_permission_fails_for_listed_role`, `test_empty_inputs_fail`, `test_roles_lookup_filters_active_rows` (asserts the filter above), `test_malformed_group_id_returns_false` (membership helper raises `InvalidId`).
- [ ] **Step 2:** Run the file. Expected: FAIL on import.
- [ ] **Step 3:** Implement `access_policy.py`; import `group_auth` and `userRolesRepository` as module attributes so tests can patch them.
- [ ] **Step 4:** Run the file. Expected: PASS.
- [ ] **Step 5: Commit** `feat(access): add can() policy with role-to-permission table`.

---

### Task 3: Group-scoped verification repository and service

**Files:**
- Modify: `app/repositories/WhatsappIntakeVerificationRepository.py`, `app/services/WhatsappIntakeVerificationService.py`, `tests/test_whatsapp_intake.py`
- Test: `tests/test_whatsapp_link_verification.py`

**Interfaces:**
- Consumes: Task 1 (`link_repo`, `canonical_pos_phone`), Task 2 (`can`, `PERMISSION_WHATSAPP_CREATE_DRAFT`), `group_auth.user_belongs_to_group`, `groupRepository.find_by_id` (for `group_name`).
- Import convention (Tasks 3, 5): `from app.services.access_policy import can, PERMISSION_WHATSAPP_CREATE_DRAFT` and `from app.repositories import WhatsappLinkRepository as link_repo`, so tests patch `<module>.can` and `<module>.link_repo`.
- Produces, repository (all scoped by `group_id`; stored documents gain a `group_id` field; index becomes `(uid, group_id, status)`): `find_open(uid, group_id)` replacing `find_open_by_uid`; `supersede_open(uid, group_id)`; `count_distinct_phones(uid, group_id, since)`; `list_starts_since(uid, group_id, since)`.
- Produces, service `WhatsappIntakeVerificationService`:
  - `start(uid: str, group_id: str, phone: str) -> Dict[str, Any]`
  - `confirm(uid: str, token: str) -> Dict[str, Any]` (group comes from the token record)
  - `preview(uid: str, token: str) -> Dict[str, Any]` (adds `group_id`, `group_name`)
  - `get_status(uid: str, group_id: str) -> Dict[str, Any]`

Contract (spec 5.3):
- `start` check order: user exists (404), `can` (403 role copy), existing link not `disabled` (403 disabled copy), number availability (409), then cooldown and limits per `(uid, group)`. If the user already has any link whose phone `phones_match` the canonical number, upsert the link for this group and return `{"linked": True, "pos_whatsapp", "pos_whatsapp_verified_at", "message"}` with no template sent. Otherwise run the existing token flow, storing `group_id` on the record, and return `{"linked": False, "message", "masked_phone"}`.
- Availability: a 409 when any `link_repo.find_any_by_phone` row has a different `uid`, or legacy `users.pos_whatsapp` matches another uid (existing logic kept).
- `confirm`/`preview`: the token must belong to the caller (403, existing) and the caller must still be a member of `token.group_id` (403).
- `confirm` additionally re-checks `can`, link not disabled, and availability, then calls `link_repo.upsert(uid, group_id, phone, verified_at)` and `mark_consumed`. Returns the old shape plus `group_id`, `link_status: "active"`, `can_use: True`. It does not call `userRepository.update_user`.
- `get_status` keeps the existing keys and adds `group_id`, `group_name`, `link_status` (`active`, `disabled` or `None`), `can_use` (result of `can`) and `suggested_phone` (phone of the user's newest-`verified_at` link in another group, else `None`). `pos_whatsapp`, `pos_whatsapp_verified_at` and `verified` describe this group's link.

- [ ] **Step 1: Write failing tests** in `tests/test_whatsapp_link_verification.py`, patching `verify_repo`, `link_repo`, `userRepository`, `can` and `WhatsappService` on the service module:
  - `test_start_scopes_pending_and_limits_to_group`: `find_open`, `supersede_open` and `count_distinct_phones` receive `group_id`; the inserted record has `group_id`.
  - `test_start_rejects_role_without_permission` (403 role copy, no template sent); `test_start_rejects_disabled_link` (403 disabled copy).
  - `test_start_instant_links_number_verified_in_other_group`: no template, `link_repo.upsert` called with the new group, response `linked` true.
  - `test_start_conflicts_when_number_linked_to_other_uid` and `test_start_conflicts_with_legacy_pos_whatsapp_of_other_uid` (409).
  - `test_start_allows_same_number_for_same_user_in_second_group`.
  - `test_confirm_upserts_link_for_token_group_and_skips_user_write` (`userRepository.update_user.assert_not_called()`).
  - `test_confirm_refuses_when_link_disabled_after_start` (Review Focus), `test_confirm_refuses_when_membership_lost`, `test_confirm_refuses_when_role_revoked`.
  - `test_preview_returns_group_name`.
  - `test_status_reports_link_state_can_use_and_suggested_phone`.
- [ ] **Step 2:** Update `tests/test_whatsapp_intake.py`: rename mocks `find_open_by_uid` to `find_open`, pass `group_id` arguments, patch `link_repo`/`can` where `start`/`confirm`/`get_status` run, and replace `test_confirm_writes_user_pos_whatsapp` with a link-upsert assertion. Run both files. Expected: FAIL.
- [ ] **Step 3:** Implement the repository and service changes above. The 400 for an invalid number stays an `HTTPException`.
- [ ] **Step 4:** Run both files. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): scope verification and linking to a group`.

---

### Task 4: Router wiring for member endpoints

**Files:**
- Modify: `app/routers/UserRouter.py`
- Test: `tests/test_user_whatsapp_intake_router.py`

**Interfaces:**
- Consumes: Task 3 service signatures; `group_auth.require_group_membership_from_header(request) -> str` (400 without header, 403 for non-member).
- Produces: `GET /users/me/whatsapp-intake/status` and `POST /users/me/whatsapp-intake/start` resolve the group with `require_group_membership_from_header` and call `get_status(uid, group_id)` / `start(uid, group_id, payload.phone)`. `pending/{token}` and `confirm` are unchanged apart from the service now returning group fields. Paths and request bodies do not change.

- [ ] **Step 1: Write failing tests** calling the route functions directly with a `MagicMock` request (as in `tests/test_authz.py`) and the service patched: `test_status_uses_group_from_header`, `test_start_uses_group_from_header`, `test_missing_group_header_returns_400`, `test_non_member_returns_403`, `test_garbage_group_header_is_4xx_not_500` (membership helper patched to raise `InvalidId`; expect `HTTPException` with 4xx status, not an unhandled exception).
- [ ] **Step 2:** Run the file. Expected: FAIL.
- [ ] **Step 3:** Update the two routes. Make `require_group_membership_from_header` convert `bson.errors.InvalidId` into a 400 `HTTPException`; this is the only change to `group_auth.py` and must not alter existing `tests/test_authz.py` results.
- [ ] **Step 4:** Run the new file and `tests/test_authz.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): resolve intake group from GroupSelected header`.

---

### Task 5: Resolver on links

**Files:**
- Modify: `app/services/WhatsappSellerIdentityService.py`, `app/repositories/WhatsappPendingAssociationRepository.py`, `tests/test_whatsapp_intake.py` (remove the ported tests)
- Test: `tests/test_whatsapp_seller_identity.py`

**Interfaces:**
- Consumes: `link_repo.find_any_by_phone`, `can`, `groupRepository.find_many_by_string_ids(group_ids) -> cursor of group docs`.
- Produces: `WhatsappPendingAssociationRepository.set_candidates(from_number: str, candidates: List[Dict[str, str]]) -> None` (sets `candidates` and `updated_at` only, never `last_inbound_at`, which drives sticky expiry).
- Produces: `WhatsappSellerIdentityService.is_entitled(uid: str, group_id: str) -> bool` (link exists, `status == "active"`, and `can(...)` is true). `SellerIdentityResult` is unchanged.
- `resolve(from_number, body="", inbound_id=None)` keeps its signature. `_find_user_by_verified_whatsapp` and `_groups_for_user` are removed; the module no longer imports `userRepository`.

Algorithm (spec 5.4). Compute on every call: `links = link_repo.find_any_by_phone(normalized)`; if more than one distinct `uid`, log an error and return `ambiguous` with the generic copy. Allowed links are `active` links where `can` holds. Resolve group names through one `find_many_by_string_ids` call; drop allowed links whose group is not found. Candidates are `{"group_id", "name"}` payloads from the allowed links, and `creator_uid` is the link `uid`. Then:
1. No links: `pending_link` with the unlinked prompt; `pending_repo.upsert_pending(normalized, [], inbound_id)` when no pending exists (current behaviour).
2. Links but no candidates: clear any `selected_group_id`, return `pending_link` with the no-access copy (throttled through `claim_identity_prompt` as today).
3. Exactly one candidate: `pending_repo.clear(normalized)` and return `resolved`.
4. Several: if pending exists and its stored candidates differ from the fresh ones, call `set_candidates`; if `pending.selected_group_id` is not among the candidates, call `clear_selected_store`. Then reuse the existing change-store command, sticky selection, stale-sticky and numbered or named selection logic over the fresh candidates. If no pending exists, `upsert_pending(normalized, candidates, inbound_id)` as today.

- [ ] **Step 1: Write failing tests** in `tests/test_whatsapp_seller_identity.py` (patch `link_repo`, `can`, `groupRepository`, `pending_repo` on the module). Port every test in `tests/test_whatsapp_intake.py` whose patches include `WhatsappSellerIdentityService.userRepository` (the `test_identity_*`, `test_change_store_commands_*` and `test_sticky_store_*` groups), re-pointing data sources to links. Add:
  - `test_no_links_prompts_to_link_with_store_choice_in_copy`
  - `test_links_but_role_not_allowed_returns_no_access_copy`
  - `test_disabled_link_returns_no_access_copy`
  - `test_one_allowed_group_resolves_and_clears_pending`
  - `test_several_allowed_groups_list_only_permitted` (one link fails `can`)
  - `test_sticky_group_no_longer_allowed_is_cleared`
  - `test_stale_stored_candidates_are_rewritten` (`set_candidates` called, `upsert_pending` not)
  - `test_two_uids_on_one_number_is_ambiguous`
  - `test_number_format_variants_hit_same_link` (parametrised over `+527779313704`, `+5217779313704`, `7779313704`; the repository mock asserts the variants query)
  - `test_link_to_deleted_group_is_dropped` (Review Focus; no exception, remaining groups listed)
  - `test_is_entitled_requires_active_link_and_permission`
- [ ] **Step 2:** Run the new file. Expected: FAIL.
- [ ] **Step 3:** Implement the repository method and rewrite `resolve` per the algorithm; keep the helper methods for commands and sticky expiry.
- [ ] **Step 4:** Delete the ported tests from `tests/test_whatsapp_intake.py`. Run both files. Expected: PASS, with no test lost (count the removed against the added).
- [ ] **Step 5: Commit** `feat(whatsapp): route inbound messages through group links and role access`.

---

### Task 6: Flush guard

**Files:**
- Modify: `app/services/WhatsappIntakeProcessorService.py` (`_flush_session_body`, around line 2590)
- Test: `tests/test_whatsapp_flush_guard.py`

**Interfaces:**
- Consumes: `self.identity_service.is_entitled(uid, group_id) -> bool` (Task 5), `self._send_bot_message(from_number, message, burst_id=..., kind="bot_error")`, `self._clear_session(from_number)`.
- Produces: at the top of `_flush_session_body`, after `_ensure_flush_owner` and before `_replay_linked_draft`, if `is_entitled(creator_uid, group_id)` is false then send the no-access copy, clear the session, and return without calling the model or creating or editing any folio.

- [ ] **Step 1: Write failing tests** (patch pattern as the flush tests in `tests/test_whatsapp_intake.py`: `session_repo`, `inbound_repo`, `WhatsappService`, `LlmExtractionService`, `WhatsappSellerIdentityService`, `folio_service`): `test_flush_without_entitlement_sends_no_access_and_skips_model_and_folio` (asserts `extract` and `folio_service.create` not called, session cleared, message equals the no-access copy), `test_flush_with_entitlement_proceeds`.
- [ ] **Step 2:** Run the file. Expected: FAIL.
- [ ] **Step 3:** Add the guard. Existing flush tests patch `WhatsappSellerIdentityService` wholesale, so `is_entitled` returns a truthy mock and they keep passing.
- [ ] **Step 4:** Run `tests/test_whatsapp_flush_guard.py` and `tests/test_whatsapp_intake.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): re-check access before flushing a buffered burst`.

---

### Task 7: Owner enable and disable endpoints

**Files:**
- Create: `app/routers/WhatsappLinksRouter.py`
- Modify: `main.py` (import and `app.include_router`)
- Test: `tests/test_whatsapp_links_router.py`

**Interfaces:**
- Consumes: `group_auth.assert_group_owner(caller_uid, group_id)`, `require_authenticated_uid`, `link_repo.find`, `link_repo.set_status`.
- Produces: `whatsappLinksRouter = APIRouter(prefix="/group")`, matching the existing group router prefix, with `POST /group/{group_id}/whatsapp-links/{uid}/disable` and `.../enable`. Both 404 when the link does not exist; both return `get_successful_response({"uid", "group_id", "status"})`.

- [ ] **Step 1: Write failing tests:** `test_owner_can_disable`, `test_owner_can_enable`, `test_non_owner_gets_403`, `test_unknown_link_gets_404`, `test_disable_records_caller_as_disabled_by`.
- [ ] **Step 2:** Run the file. Expected: FAIL.
- [ ] **Step 3:** Implement the router and register it in `main.py`.
- [ ] **Step 4:** Run the file. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): owner can disable or enable a member's link`.

---

### Task 8: Migration

**Files:**
- Create: `app/services/WhatsappLinkMigrationService.py`, `scripts/migrate_whatsapp_links.py`
- Test: `tests/test_whatsapp_link_migration.py`

**Interfaces:**
- Consumes: `userRepository.find(filters, limit=0)` (limit `0` means unlimited; the default is 30), `groupRepository.find_by_user(uid)`, `can`, `link_repo.insert_if_absent`, `canonical_pos_phone`.
- Produces: `migrate(apply: bool) -> Dict[str, Any]` returning `{"created": int, "existing": int, "skipped_no_access": [{"uid","group_id","reason"}], "invalid_phones": [uid], "phone_conflicts": [masked_phone]}`. `scripts/migrate_whatsapp_links.py` is a thin CLI (`--apply`, dry run by default; same `sys.path` header as `scripts/backfill_fulfillment_type.py`) that prints the report with masked numbers.

Rules (spec 5.7): canonicalise each legacy number, reporting failures; a number on more than one user is reported and skipped for all of them; for each group of the user, `can` true creates an active link via `insert_if_absent` with `verified_at` from `pos_whatsapp_verified_at` (now if absent), `can` false is reported with reason `no_role_row` or `role_not_allowed`. A dry run writes nothing.

- [ ] **Step 1: Write failing tests:** `test_dry_run_writes_nothing`, `test_apply_creates_link_per_allowed_group`, `test_second_apply_is_idempotent` (`existing` counts up, nothing overwritten), `test_member_without_role_row_is_reported_not_linked`, `test_invalid_phone_is_reported`, `test_duplicate_number_across_users_skipped`, `test_missing_verified_at_defaults_to_now`, `test_all_users_are_scanned_beyond_default_limit`.
- [ ] **Step 2:** Run the file. Expected: FAIL.
- [ ] **Step 3:** Implement the service and CLI.
- [ ] **Step 4:** Run the file. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): migration script from users.pos_whatsapp to group links`.

---

### Task 9: Client hooks and types (client repo)

**Files:**
- Modify: `src/common/react-query/mutations/useWhatsappIntake.ts`
- Test: `src/common/react-query/mutations/useWhatsappIntake.test.tsx`

**Interfaces:**
- Consumes: `getSelectedGroupId(): string | undefined` and `getClient` from `@common/react-query/clients/eassymo-client`.
- Produces: `WhatsappIntakeStatus` gains `group_id?: string`, `group_name?: string`, `link_status?: 'active' | 'disabled' | null`, `can_use?: boolean`, `suggested_phone?: string | null`. New `WhatsappIntakeStartResult = { linked: boolean; message?: string; masked_phone?: string; pos_whatsapp?: string; pos_whatsapp_verified_at?: string }`. The preview data type gains `group_id?` and `group_name?`.
- `useWhatsappIntakeStatus` query key is `[QUERY_KEYS.USERS, 'whatsapp-intake-status', getSelectedGroupId()]`. Mutations invalidate the prefix `[QUERY_KEYS.USERS, 'whatsapp-intake-status']`. `useStartWhatsappIntake` resolves with `WhatsappIntakeStartResult`; its success toast is `WhatsApp vinculado a esta tienda` when `linked` is true, otherwise the response `message`.

- [ ] **Step 1: Write failing tests** (`renderHook` with a `QueryClientProvider`; mock `eassymo-client`): `test_status_query_key_includes_selected_group` (changing the mocked group id triggers a new request), `test_start_instant_link_shows_linked_toast`, `test_start_pending_shows_server_message`. Mock the toast module the same way other tests in the repo do.
- [ ] **Step 2:** Run `npx jest src/common/react-query/mutations/useWhatsappIntake.test.tsx`. Expected: FAIL.
- [ ] **Step 3:** Implement the changes.
- [ ] **Step 4:** Run the file and `npx tsc --noEmit`. Expected: PASS and no type errors.
- [ ] **Step 5: Commit** `feat(whatsapp): per-group intake status and instant-link result` (client repo; confirm `git config user.email` is `admin@eassymo.com`).

---

### Task 10: Settings screen states (client repo)

**Files:**
- Modify: `src/components/user-configuration/whatsapp-pos-settings/whatsapp-pos-settings.tsx`
- Test: `src/components/user-configuration/whatsapp-pos-settings/whatsapp-pos-settings.test.tsx`

**Interfaces:**
- Consumes: Task 9 types.
- Behaviour:
  - Under the title block, show `Tienda: {group_name}` when `group_name` is present.
  - New mode `no-access` when `can_use === false`: `WhatsappPosLineCard` with `status="unlinked"`, eyebrow `Sin acceso en esta tienda`, subtitle `Tu rol actual no permite usar WhatsApp para el POS en {group_name}.`; no form, no buttons.
  - New mode `disabled` when `link_status === 'disabled'`: eyebrow `Desactivado por el dueño`, subtitle `El dueño de {group_name} desactivó tu WhatsApp. Pídele que lo reactive.`; no form, no buttons. Evaluate `link_status` before `can_use`.
  - In `form` mode, prefill `phone` from `suggested_phone` (last 10 digits) when present, taking precedence over the profile phone.
  - Existing modes and copy are untouched.

- [ ] **Step 1: Write failing tests** (extend the existing file, same mocks): `shows the selected store name`, `renders no-access explanation without form or buttons`, `renders disabled-by-owner explanation without form`, `prefills the form from suggested_phone`, `still renders unlinked form when can_use is true`.
- [ ] **Step 2:** Run the file. Expected: new tests FAIL; the five existing tests still pass.
- [ ] **Step 3:** Implement the modes. Missing `can_use` and `link_status` (an older API) must behave as before.
- [ ] **Step 4:** Run the file. Expected: PASS.
- [ ] **Step 5: Commit** `feat(whatsapp): show per-store link states in POS settings` (client repo).

---

### Task 11: Confirm screen group name (client repo)

**Files:**
- Modify: `src/components/user-configuration/whatsapp-verify/whatsapp-verify-confirm.tsx`
- Test: `src/components/user-configuration/whatsapp-verify/whatsapp-verify-confirm.test.tsx`

**Interfaces:**
- Consumes: Task 9 preview type with `group_name`.
- Behaviour: when the preview has `group_name`, the `WhatsappPosLineCard` subtitle is `Se vinculará en {group_name}.`; otherwise unchanged. The existing selected-group redirect to `/select-group` is untouched.

- [ ] **Step 1: Write failing test:** `shows the store the number will be linked to` (preview mock includes `group_name: 'Refaccionaria Centro'`; expects the subtitle text).
- [ ] **Step 2:** Run the file. Expected: new test FAILs.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx jest src/components/user-configuration`. Expected: all suites pass (baseline 59 tests plus the new ones).
- [ ] **Step 5: Commit** `feat(whatsapp): show target store on the confirm screen` (client repo).

---

### Task 12: Full verification, spec sync and cutover notes

**Files:**
- Modify: `docs/superpowers/specs/2026-11-12-whatsapp-group-links-design.md` (API repo)

- [ ] **Step 1:** Update spec 5.3 (status adds `group_name`) and 5.4 (guard location) to match the Deviations section above.
- [ ] **Step 2:** API: `.venv/bin/python -m pytest tests -q`. Expected: no failures beyond the Task 0 baseline. Client: `npx jest` and `npx tsc --noEmit`. Expected: pass.
- [ ] **Step 3:** Run `.venv/bin/python scripts/migrate_whatsapp_links.py` (dry run) against a development or staging `MONGO_URI` and attach the report to the PR description. If no such database is reachable, say so; do not run it against production.
- [ ] **Step 4:** Add the cutover order to the PR description: run `--apply`, deploy, run `--apply` again; rollback is a redeploy of the previous version, because `users.pos_whatsapp` is untouched. Links created after cutover are invisible to the old code.
- [ ] **Step 5: Commit** `docs(whatsapp): sync group-links spec with implementation` (API repo).
