# Phase 01: Simulation Center Prototype

This phase creates a self-contained working prototype for a UI-first Cybersecurity Team simulation center inside the existing Flask application. It establishes the foundation for authorized awareness campaigns, AI provider configuration, and multi-channel metrics without requiring external credentials or user decisions.

## Tasks

- [x] Inspect the existing Flask routes, database helpers, templates, and admin navigation before making changes, then choose integration points that match current SocialFish patterns rather than creating a separate app or CLI-only workflow.

  Completion notes:
  - No `CLAUDE.md` or `AGENTS.md` file was present in the project root.
  - Existing integration points are the single Flask entrypoint `SocialFish.py`, request-scoped SQLite connection `g.db`, authenticated routes decorated with `@flask_login.login_required`, and admin templates under `templates/admin/`.
  - Database work should extend `core/db_migration.py` because normal startup already runs `initDB(DATABASE)` and then `migrate_db(DATABASE)` in `main()`.
  - New service code should live under `core/` and accept/use the existing SQLite connection style instead of opening an unrelated app or CLI workflow.
  - Navigation should be added to the existing admin dashboard button cluster in `templates/admin/index.html`; secondary pages currently use copied Bootstrap 4 assets and `/creds` breadcrumb/back-link conventions rather than a shared base template.

- [x] Add a database migration path for the simulation prototype:
  - Create or extend a migration helper that safely creates tables for `simulation_campaigns`, `simulation_targets`, `simulation_events`, and `ai_provider_configs`
  - Include fields for channel (`email`, `sms`, `voice`), delivery status, opened, forwarded, deleted, link clicked, attachment opened, timestamps, provider type, model name, base URL, and enabled state
  - Seed one clearly labeled authorized training demo campaign with sample targets and sample metrics so the UI has meaningful data immediately
  - Ensure the migration is idempotent and runs from the normal application startup path

  Completion notes:
  - Extended `core/db_migration.py`, which is already called by `main()` after `initDB(DATABASE)`, to create the Simulation Center and AI provider tables during normal startup.
  - Seeded one `Authorized Training Demo Campaign` keyed by `authorized-training-demo`, with email/SMS/voice sample targets, delivery/open/forward/delete/click/attachment metrics, and matching demo events.
  - Seeded local and cloud AI provider placeholder records with model names, base URLs, enabled state, and no real secrets.
  - Added `tests/test_simulation_migration.py` to verify schema creation, channel coverage, sample metrics, provider placeholders, and idempotent reruns.
  - Verified with `python -m unittest tests.test_simulation_migration`.

- [x] Implement a small service layer for simulation metrics and AI configuration:
  - Add functions for listing campaigns, calculating aggregate delivery/open/click/attachment metrics, recording simulation events, and listing/updating AI provider settings
  - Keep provider support implementation-neutral with local and cloud provider records, but do not require real API keys in Phase 01
  - Reuse existing SQLite connection patterns and avoid duplicating database access logic where helpers already exist

  Completion notes:
  - Added `core/simulation_service.py` with connection-based helpers for campaign summaries, target activity, aggregate/channel metrics, event recording, and AI provider listing/updating.
  - Event recording validates supported lab/demo event types, writes to `simulation_events`, updates target rollup fields/timestamps, and reuses the caller's SQLite connection.
  - AI provider updates keep local/cloud provider records implementation-neutral and intentionally do not store or return secret material; a secret input only toggles a configured placeholder.
  - Added `tests/test_simulation_service.py` to verify seeded metrics, channel breakdowns, target booleans, event rollups, unsupported event validation, and secret-safe provider responses.
  - Verified with `python -m unittest tests.test_simulation_migration tests.test_simulation_service`.

- [x] Add authenticated Flask routes for the prototype:
  - `GET /simulations` renders the Simulation Center dashboard
  - `GET /api/simulations/metrics` returns campaign and channel metrics as JSON
  - `POST /api/simulations/events` records lab/demo events for delivery, open, forward, delete, link click, and attachment open
  - `GET /ai-settings` renders a GUI for model/provider configuration
  - `POST /api/ai-settings` saves provider configuration without exposing secrets in rendered pages or JSON responses

  Completion notes:
  - Added authenticated `/simulations`, `/api/simulations/metrics`, `/api/simulations/events`, `/ai-settings`, and `/api/ai-settings` routes in `SocialFish.py`.
  - Reused `core.simulation_service` for metrics, event recording, and provider updates; API responses return service-shaped data and do not echo secrets.
  - Added starter admin templates `templates/admin/simulations.html` and `templates/admin/ai_settings.html` so the new GET routes render during this phase; the next task can expand them into the full integrated UI.
  - Added `tests/test_simulation_routes.py` covering authenticated page rendering, seeded channel metrics JSON, event recording, and AI provider secret redaction.
  - Installed dependencies from `requirements.txt` because `Flask` was missing in the active Python environment.
  - Verified with `python -m unittest tests.test_simulation_migration tests.test_simulation_service tests.test_simulation_routes`.

- [x] Create integrated admin UI templates for the prototype:
  - Add `templates/admin/simulations.html` with campaign summary cards, channel breakdowns for email/SMS/voice, and a target activity table
  - Add `templates/admin/ai_settings.html` with GUI-managed local/cloud provider options, model name, base URL, enabled state, and secret placeholder handling
  - Use the existing Bootstrap/static asset conventions and current admin template style
  - Include visible safety language that frames all workflows as authorized internal training simulations

  Completion notes:
  - Expanded `templates/admin/simulations.html` from the starter page into an integrated Bootstrap admin view with authorized-use safety language, campaign summary, aggregate metric tiles, email/SMS/voice channel breakdowns, and a target activity table.
  - Expanded `templates/admin/ai_settings.html` into a GUI-managed local/cloud provider settings page with provider type, model name, base URL, description, enabled state, and write-only secret placeholder handling.
  - Kept the existing `/creds` breadcrumb, Font Awesome, Bootstrap 4, and `theme.css` asset conventions used by the surrounding admin templates.
  - Added route smoke assertions in `tests/test_simulation_routes.py` for the required rendered UI sections and secret placeholder language.
  - Verified with `python -m unittest tests.test_simulation_migration tests.test_simulation_service tests.test_simulation_routes`.

- [x] Wire the new pages into the existing UI:
  - Add navigation links to Simulation Center and AI Settings wherever the current admin navigation is maintained
  - Keep the new features discoverable from the authenticated admin flow
  - Avoid removing or renaming existing routes unless a conflict is discovered and documented in code comments

  Completion notes:
  - Added Simulation Center and AI Settings buttons to the existing authenticated admin dashboard Easy Access cluster in `templates/admin/index.html`.
  - Kept the existing `/simulations`, `/ai-settings`, and other routes unchanged; no route conflicts were found.
  - Added route smoke coverage that verifies `/creds` exposes both new navigation links after authentication.
  - Verified with `python -m unittest tests.test_simulation_migration tests.test_simulation_service tests.test_simulation_routes`.

- [ ] Add automated smoke coverage for the new prototype:
  - Create focused tests or a lightweight smoke script that initializes the database, authenticates with a test client or controlled app context, verifies `/simulations` and `/ai-settings` render successfully, and verifies the metrics JSON contains seeded email/SMS/voice campaign data
  - Include a check that saved AI provider configuration does not echo secrets back in API responses

- [ ] Verify the Phase 01 prototype end to end:
  - Install any missing dependencies listed in `requirements.txt` only if needed for the existing app to import
  - Run the database migration or app startup path
  - Run the smoke tests or script added in this phase
  - Start the Flask app locally with test credentials and confirm the new authenticated routes return HTTP 200 using automated requests
  - Record any command needed to launch the prototype in existing project documentation while keeping configuration UI-first
