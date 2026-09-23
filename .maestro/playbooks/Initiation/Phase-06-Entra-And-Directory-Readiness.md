# Phase 06: Entra And Directory Readiness

This phase prepares SocialFish for Microsoft Entra ID target synchronization without forcing the team to provide tenant credentials during the run. It adds a UI-managed integration model, a safe mock connector, and import-review flows that can later connect to Microsoft Graph.

## Tasks

<!-- MAESTRO:MODEL tier="high" effort="high" reason="Directory integrations touch identity data, consent scopes, and synchronization semantics. This needs careful design so future Microsoft Graph support can be added without exposing secrets or importing targets unexpectedly." -->

- [x] Design the directory integration model:
  - Review target import, campaign target, and provider configuration tables before adding new identity tables
  - Define tables for directory providers, sync jobs, staged directory users, group mappings, and sync audit events
  - Include provider type, tenant metadata, selected groups, last sync state, consent status, enabled state, and encrypted secret references where the current project supports them
  - Keep schema changes idempotent and avoid storing raw OAuth tokens in plain rendered pages or JSON
  - Completed with additive SQLite migrations in `core/db_migration.py` and coverage in `tests/test_simulation_migration.py`; secrets are modeled as `secret_reference` / `secret_placeholder` rather than raw OAuth token fields.

- [x] Implement directory connector interfaces:
  - Add a provider-neutral connector contract for listing groups, previewing users, syncing staged users, and mapping fields to simulation targets
  - Add a mock Entra connector that returns deterministic groups and users for development/testing
  - Add a Microsoft Graph connector shell that validates required settings but does not require real credentials for tests
  - Keep connector selection driven by GUI-managed settings
  - Completed with `core/directory_connectors.py` dataclasses, protocol, mock Entra adapter, and Microsoft Graph shell.
  - Added directory provider settings helpers in `core/simulation_service.py` that redact secrets and select connectors from database/UI-managed provider type.
  - Covered mock groups/users, staged sync previews, field mapping, Microsoft Graph validation, provider selection, and secret redaction in `tests/test_directory_connectors.py`.
  - Verified with `python -m unittest discover tests`.

- [x] Add directory settings routes:
  - `GET /integrations/directory` renders directory provider settings and sync status
  - `POST /api/integrations/directory/providers` creates or updates a provider configuration
  - `POST /api/integrations/directory/providers/<id>/test` tests a provider using mock or configured connector behavior
  - `GET /api/integrations/directory/providers/<id>/groups` lists available groups from the selected connector
  - Completed with authenticated Flask routes in `SocialFish.py`, an initial `templates/admin/directory_integrations.html` settings/status page, and route coverage for mock provider CRUD/test/group listing plus Microsoft Graph safe configuration errors.

- [ ] Add directory sync preview and import routes:
  - `POST /api/integrations/directory/providers/<id>/preview` stages users from selected groups without adding them to campaigns
  - `POST /api/integrations/directory/providers/<id>/sync` imports staged, active users into the central target repository
  - `GET /integrations/directory/sync-jobs/<id>` renders sync job results, validation issues, and imported counts
  - Preserve sync audit history for troubleshooting and compliance review

- [ ] Build directory integration UI:
  - Add an Integrations or Directory page reachable from the admin navigation
  - Include provider configuration, mock mode, group selection, sync preview, import confirmation, and sync history
  - Display required Microsoft Graph permission names as guidance inside the UI without requiring setup outside the app
  - Keep secret inputs write-only and show placeholders instead of stored values

- [ ] Connect directory imports to campaign targeting:
  - Allow campaign target selection from manually created targets, CSV-imported targets, and directory-synced targets
  - Add filters for source, department, and group mapping on campaign detail pages
  - Preserve source metadata on imported targets
  - Prevent duplicate targets when the same email or phone number appears across sources

- [ ] Add structured directory documentation while implementing the UI:
  - Create `docs/features/entra-directory-integration.md` with YAML front matter using type `reference`, tags for `entra`, `directory`, and `targets`
  - Include wiki-links to `[[Simulation-Campaigns]]`, `[[Simulation-Target-Import]]`, and `[[Simulation-Metrics]]`
  - Document mock mode, future Microsoft Graph settings, field mapping, sync preview, and duplicate handling

- [ ] Add automated directory integration coverage:
  - Test mock group listing, preview, staged user validation, sync import, and duplicate prevention
  - Test provider setting secret redaction
  - Test campaign targeting can include directory-synced users
  - Test incomplete Microsoft Graph configuration fails safely with actionable UI/API errors

- [ ] Run directory readiness verification:
  - Run the directory integration tests
  - Use automated HTTP requests to configure a mock provider, list groups, preview users, sync users, and add synced targets to a campaign
  - Fix any schema, connector, route, template, or duplicate-handling failures discovered during verification
