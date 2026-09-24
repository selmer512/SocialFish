# Phase 07: Safety Audit And Access Controls

This phase strengthens the modernization work with auditability, explicit authorized-use guardrails, and practical access control improvements. It focuses on safe operation for an internal Cybersecurity Team while preserving the existing Flask stack and UI.

## Tasks

- [x] Review existing authentication, session handling, admin routes, API routes, secret handling, and database access patterns before making access-control changes.

  Completion notes:
  - Reviewed `SocialFish.py`, `core/config.py`, `core/dbsf.py`, `core/db_migration.py`, `core/simulation_service.py`, and existing simulation route tests.
  - Authentication is centralized through Flask-Login in `SocialFish.py`; admin UI, simulation, AI, delivery, directory, reporting, recorder, and attack-payload routes generally use `@flask_login.login_required`. Public routes intentionally include the victim capture flow, simulation tracking endpoints, provider webhooks, legacy mobile token APIs, and the generic webhook receiver.
  - Session state uses Flask's signed cookie session with `APP_SECRET_KEY` from `SOCIALFISH_SECRET_KEY` or a generated development fallback. Operators are bootstrapped from command-line username/password arguments rather than a persisted user table.
  - Simulation/admin JSON routes mostly normalize IDs through `<int:...>` route converters and `_optional_int`, and newer helper functions return structured `_json_error` responses. Some legacy routes still return plain strings or `{'status':'bad'}` responses, and several JSON APIs accept POSTs without CSRF protection.
  - Database access is SQLite via `g.db = sqlite3.connect(DATABASE)` per request, with migrations in `core/db_migration.py` and simulation helpers reusing parameterized `conn.execute(...)` patterns. Older dashboard/API code also uses parameterized SQL for inserts/updates reviewed here, but the migration/helper layer is the clearest pattern to reuse.
  - Secret handling is already write-only for AI, delivery, and directory provider credentials: settings store `secret_placeholder`/`secret_reference` instead of plaintext secret values, and response helpers remove `secret_placeholder`. Existing export redaction helpers cover sensitive metadata keys. SMTP mail password in `/api/mail` is passed directly to `sendMail` and is not persisted.
  - Existing audit-like tables include `ai_generation_audits`, `directory_sync_audit_events`, and `simulation_events`; the next audit-service task should unify these under a broader administrative audit table without storing raw provider secrets.

- [x] Add an audit event service:
  - Create idempotent tables for administrative audit events, actor identity, action type, entity type, entity ID, channel, IP address, user agent, timestamp, and structured metadata
  - Add helper functions for recording campaign, target, AI provider, generation, delivery, export, and directory sync actions
  - Ensure audit metadata does not store plaintext secrets
  - Reuse existing database connection patterns

  Completion notes:
  - Added `administrative_audit_events` to `core/db_migration.py` with idempotent column checks and indexes for action, entity, campaign, and actor filtering.
  - Added `core/audit_service.py` with generic and workflow-specific recording helpers for campaign, target, AI provider, generation, delivery, export, and directory sync audit events.
  - Added recursive audit metadata redaction for plaintext secret-bearing keys while preserving safe placeholder/reference fields.
  - Added `tests/test_audit_service.py` coverage plus migration schema assertions in `tests/test_simulation_migration.py`.

- [x] Instrument high-value workflows with audit events:
  - Campaign create, update, archive, delivery preview, and delivery start
  - Target manual create, CSV import, archive, directory preview, and directory sync
  - AI provider configuration, AI generation, draft save, and provider test
  - Metrics/report export and report view generation

  Completion notes:
  - Added route-level administrative audit events for campaign create/update/archive, target create/update/archive, CSV import, delivery preview/start, AI provider configuration, AI generation, AI draft save, directory provider create/update/test, directory preview/sync, metrics CSV export, events JSON export, and report views.
  - Centralized actor, IP address, user-agent, channel, and metadata capture through `_audit_context` in `SocialFish.py`, reusing `core/audit_service.py` helpers so metadata redaction continues to strip plaintext secret-shaped fields.
  - Expanded `tests/test_simulation_routes.py` assertions to verify the expected administrative audit action names and redacted secret metadata for key workflows.

- [x] Add operator-facing audit UI:
  - Create an Audit Log page under the authenticated admin UI
  - Add filters for action type, entity type, channel, actor, date range, and campaign
  - Add detail views for structured metadata with sensitive values redacted
  - Add navigation from campaign detail pages to related audit events

  Completion notes:
  - Added authenticated `/audit-log` and `/audit-log/<event_id>` admin views backed by audit-service query helpers.
  - Added filters for action type, entity type, channel, actor, campaign, and date range, plus detail rendering for structured redacted metadata.
  - Added campaign detail navigation to `/audit-log?campaign_id=...` so operators can review related administrative events from a campaign.
  - Added service and route tests covering audit filters, detail lookup, login protection behavior, campaign links, and redacted secret display.

- [x] Add authorized-use safety controls:
  - Add a required campaign authorization statement field for new campaigns
  - Add a campaign readiness check before delivery starts that verifies authorization statement, target count, channel content, and provider readiness
  - Block delivery start when readiness checks fail and show actionable UI messages
  - Keep dry-run delivery available for testing readiness logic

  Completion notes:
  - Added `authorization_statement` to simulation campaign schema, demo seed/backfill, campaign create/update flows, and authenticated campaign forms.
  - Added reusable delivery readiness checks for authorization statement, active targets, channel content, and dry-run/provider settings readiness.
  - Blocked delivery job creation and `/deliveries/start` when readiness fails, returning structured JSON errors or actionable UI flash messages.
  - Added admin UI readiness checklist on campaign detail pages and automated service/route/migration coverage for blocked launches and provider readiness.

- [x] Improve API and form validation:
  - Add CSRF protection where compatible with the existing form stack or document a project-compatible alternative in code comments
  - Validate IDs, channel values, dates, and status transitions in simulation routes
  - Standardize JSON error responses for simulation APIs
  - Ensure routes that should require login consistently use the existing login-required pattern

  Completion notes:
  - Added route-level validation for positive IDs, simulation channels, metric date ranges, delivery status filters, delivery mode/max retries, campaign form dates, and campaign status transitions.
  - Documented the project-compatible CSRF approach in `SocialFish.py`: the current legacy Flask form stack has no Flask-WTF/hidden-token support, so authenticated sessions plus strict route validation remain the compatible guardrail until a template-wide CSRF retrofit.
  - Standardized remaining simulation/admin JSON validation failures through `_json_error` for simulation events, target metrics CSV export, AI provider settings, delivery provider settings, provider webhooks, and delivery validation paths.
  - Added route tests for validation failures, structured error shapes, and unauthenticated access protection.
  - Verified with `python -m unittest discover tests` (95 tests).

- [x] Add structured safety documentation while implementing controls:
  - Create `docs/features/simulation-safety-audit.md` with YAML front matter using type `reference`, tags for `audit`, `safety`, and `access-control`
  - Include wiki-links to `[[Simulation-Campaigns]]`, `[[Simulation-Delivery-Tracking]]`, and `[[Entra-Directory-Integration]]`
  - Document audit events, readiness checks, redaction rules, and authorized-use workflow

  Completion notes:
  - Created `docs/features/simulation-safety-audit.md` with structured reference front matter, required tags, and related wiki-links.
  - Documented the authorized-use workflow, administrative audit event schema and workflow actions, delivery readiness checks, recursive metadata redaction rules, and authenticated admin access-control expectations.

- [ ] Add automated safety and audit coverage:
  - Test audit events are recorded for key campaign, target, AI, delivery, directory, and export workflows
  - Test readiness checks block incomplete campaigns before delivery
  - Test unauthenticated users cannot access new admin pages or APIs
  - Test redaction for secrets and sensitive metadata

- [ ] Run safety verification:
  - Run the safety and audit tests
  - Use automated HTTP requests to confirm protected routes redirect or reject unauthenticated users
  - Use automated HTTP requests to create an incomplete campaign and verify delivery is blocked by readiness checks
  - Fix any validation, authorization, audit, or template failures discovered during verification
