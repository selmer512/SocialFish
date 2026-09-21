# Phase 02: Campaign And Target Management

This phase turns the prototype into a usable campaign management workflow for the Cybersecurity Team. It adds UI-first creation, editing, target selection, CSV upload, and reusable campaign records across email, SMS, and voice channels.

## Tasks

- [x] Review the Phase 01 simulation tables, service functions, routes, and templates, then reuse those patterns for all campaign and target management work.

  Notes for follow-on tasks:
  - Reuse `core/db_migration.py` for schema changes; Phase 01 uses `CREATE TABLE IF NOT EXISTS`, `_ensure_columns`, deterministic seeding through `SIMULATION_DEMO_SLUG`, UTC ISO timestamps, and rerunnable migrations compatible with `database.db`.
  - Extend `core/simulation_service.py` instead of adding route-local SQL; current helpers accept a SQLite connection, return plain dictionaries/lists, normalize booleans, raise `ValueError` for displayable validation failures, and commit inside write helpers.
  - Keep authenticated UI/API routes in `SocialFish.py` beside `/simulations`, `/api/simulations/metrics`, `/api/simulations/events`, `/ai-settings`, and `/api/ai-settings`; reuse `_request_data`, `_optional_int`, `_form_bool`, Flask `flash`, and `@flask_login.login_required`.
  - Match `templates/admin/simulations.html` and `templates/admin/ai_settings.html`: Bootstrap 4 admin cards, Font Awesome icons, safety language for authorized internal training, table-responsive layouts, and UI-first controls.
  - Add tests in the existing `unittest` style using temporary SQLite databases, `migrate_db`, mocked `sys.argv` before importing `SocialFish`, Flask `test_client`, and assertions for rendered UI, JSON payloads, idempotency, and secret-safe responses.

- [x] Extend the simulation schema for practical campaign management:
  - Add campaign fields for name, description, objective, training owner, status, start/end dates, selected channels, landing/training URL, and audit timestamps
  - Add target fields for display name, email, phone number, department, manager, source, active state, and import batch ID
  - Add import batch tracking for uploaded CSV files, validation errors, row counts, and timestamps
  - Keep all schema changes idempotent and compatible with an existing `database.db`

  Notes for follow-on tasks:
  - `core/db_migration.py` now expands `simulation_campaigns` with `objective`, `training_owner`, `selected_channels`, `landing_url`, `training_url`, `start_date`, `end_date`, and `archived_at` while preserving the Phase 01 `channel`, `started_at`, and `completed_at` fields for compatibility.
  - `simulation_targets` now supports `display_name`, `manager`, `source`, `active`, `import_batch_id`, and `archived_at`, with existing delivery metric columns left intact.
  - `simulation_import_batches` tracks CSV upload metadata, row counts, validation errors, status, and audit timestamps.
  - `tests/test_simulation_migration.py` covers idempotent migration from both a blank database and an existing Phase 01 schema.

- [x] Implement campaign and target services:
  - Add create, update, archive, list, and detail functions for campaigns
  - Add manual target create/update/archive functions
  - Add CSV parsing and validation functions for target imports using standard library CSV handling where possible
  - Normalize phone and email validation errors into messages that can be displayed in the UI

  Notes for follow-on tasks:
  - `core/simulation_service.py` now exposes campaign CRUD/detail helpers: `create_campaign`, `update_campaign`, `archive_campaign`, `get_campaign`, `get_campaign_detail`, and an expanded `list_campaigns(include_archived=False)`.
  - Target management helpers now include `create_target`, `update_target`, `archive_target`, `get_target`, and `list_targets(..., include_archived=False)`; archived targets are hidden by default but remain available for history/metrics when requested.
  - CSV imports use standard library `csv.DictReader` through `parse_target_csv` and `import_targets_csv`, producing row-numbered `{"row": ..., "message": ...}` validation errors for UI flash/panel rendering.
  - Email addresses are normalized to lowercase, phone numbers are normalized to compact E.164-like digits/leading `+`, and channel-specific contact requirements are enforced for email, SMS, and voice.
  - `tests/test_simulation_service.py` covers campaign CRUD/archive/detail, manual target validation/archive, CSV parse errors, duplicate contact handling, and import batch accounting.

- [ ] Add authenticated campaign management routes:
  - `GET /simulations/campaigns` lists campaigns with channel, status, target count, and key metrics
  - `GET /simulations/campaigns/new` renders the create campaign form
  - `POST /simulations/campaigns` creates a campaign from GUI input
  - `GET /simulations/campaigns/<id>` renders a detail page with targets, events, and edit actions
  - `POST /simulations/campaigns/<id>` updates campaign metadata
  - `POST /simulations/campaigns/<id>/archive` archives a campaign without deleting historical metrics

- [ ] Add authenticated target management routes:
  - `POST /simulations/campaigns/<id>/targets` adds a single target from the UI
  - `POST /simulations/campaigns/<id>/targets/upload` imports a CSV from the UI and records an import batch
  - `POST /simulations/targets/<id>` updates a target
  - `POST /simulations/targets/<id>/archive` archives a target while preserving events
  - Return clear success/error responses that the existing Flask flash pattern can display

- [ ] Build campaign and target UI templates:
  - Create list, create, and detail templates under `templates/admin/` using the existing Bootstrap style
  - Include channel checkboxes for email, SMS, and voice
  - Include manual target entry and CSV upload flows on the campaign detail page
  - Include import validation feedback with row numbers and reasons
  - Keep all configuration available through the UI and avoid CLI instructions for campaign setup

- [ ] Add CSV import sample guidance inside the UI:
  - Render expected columns and optional columns directly on the upload panel
  - Provide a generated downloadable sample CSV route that does not require a static file
  - Document accepted columns in a structured Markdown feature note at `docs/features/simulation-target-import.md` with YAML front matter and wiki-links to `[[Simulation-Campaigns]]` and `[[AI-Provider-Configuration]]`

- [ ] Add automated coverage for campaign and target workflows:
  - Test campaign creation, update, archive, and listing
  - Test manual target creation and validation failures
  - Test CSV upload with valid rows, invalid rows, and duplicate contacts
  - Test that archived records remain available in metrics/history queries

- [ ] Run the campaign workflow verification:
  - Run the new tests or smoke script
  - Start the app and use automated HTTP requests to create a campaign, add one manual target, import a CSV fixture, and fetch the campaign detail page
  - Fix any import, template, route, or database errors discovered during verification
