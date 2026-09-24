# Phase 08: Polish Documentation And Release Readiness

This phase consolidates the modernization into a maintainable release candidate. It documents dependencies and features, tightens tests, checks the UI-first workflows, and leaves the project ready for continued internal cybersecurity awareness platform development.

## Tasks

- [x] Review all files changed in Phases 01-07 and identify duplicated helpers, inconsistent route names, unused imports, missing login guards, and mismatched template styles before applying cleanup.

  Review notes:
  - Duplicated helpers: JSON/text normalization repeats across `core/simulation_service.py`, `core/ai_generation.py`, `core/delivery_adapters.py`, `core/directory_connectors.py`, and `core/audit_service.py`; request/list/dict parsing also lives in `SocialFish.py`. Consolidation candidates include `_clean_text`/`_normalize_text`, `_json_list`, `_json_dict`, `_safe_json_dumps`, and provider/connector selection helpers.
  - Route naming inconsistencies: simulation admin routes mostly live under `/simulations`, while settings and audit routes use `/ai-settings`, `/api/ai-settings`, `/api/delivery-settings`, `/audit-log`, and `/integrations/directory`. `templates/admin/simulations.html` links to `/api/simulations/metrics`, but the implemented overview API is `/api/simulations/metrics/overview`.
  - Unused imports found by an AST pass: `SocialFish.py` imports `leave_room`, `colorama`, `os`, and `Path` without use; `core/delivery_adapters.py` imports `Sequence` without use; `core/directory_connectors.py` imports `List` without use.
  - Login guards: authenticated simulation, AI settings, directory, metrics, delivery status, audit, and export surfaces have `flask_login.login_required`. Public simulation tracking endpoints and provider webhooks are intentionally unauthenticated and should retain token/signature validation instead of a login guard.
  - Template style drift: the new simulation templates are full HTML documents rather than extending a shared admin layout, and they rely heavily on inline `style` attributes and hard-coded paths. Breadcrumbs also alternate between `/creds`, `/simulations`, `/simulations/campaigns`, `/audit-log`, and `/integrations/directory`, so cleanup should standardize navigation without breaking existing URLs.

- [x] Consolidate simulation services and utilities:
  - Move duplicated database, validation, redaction, metrics, and provider-selection logic into shared helpers where the existing project structure supports it
  - Keep route handlers thin and focused on request/response behavior
  - Preserve backwards compatibility for existing SocialFish routes
  - Avoid broad rewrites outside the simulation modernization surface

  Completion notes:
  - Added `core/simulation_utils.py` for shared JSON parsing, cursor row mapping, timestamp generation, text normalization, redaction, boolean coercion, choice validation, and enabled-provider selection.
  - Reused those helpers from `core/simulation_service.py`, `core/audit_service.py`, `core/ai_generation.py`, `core/delivery_adapters.py`, `core/directory_connectors.py`, and simulation-related route helpers in `SocialFish.py`.
  - Added `tests/test_simulation_utils.py` to lock the shared helper behavior.
  - Verified with `python -m py_compile SocialFish.py core\simulation_utils.py core\simulation_service.py core\audit_service.py core\delivery_adapters.py core\directory_connectors.py core\ai_generation.py` and `python -m unittest discover tests`.

- [x] Update dependency documentation and configuration:
  - Review `requirements.txt`, `Dockerfile`, `docker-compose.yml`, setup instructions, and imports introduced by the modernization work
  - Add only necessary dependencies and pin versions where the existing project already pins comparable packages
  - Document every newly required dependency in `docs/reference/dependencies.md` with YAML front matter using type `reference`, tags for `dependencies` and `operations`
  - Include wiki-links to feature docs that rely on each dependency

  Completion notes:
  - Added `docs/reference/dependencies.md` with structured front matter, dependency-to-feature mapping, and wiki-links for simulation, AI, delivery, metrics, directory, and audit docs.
  - Aligned `requirements.txt` and `setup.py` by removing stale unused entries (`pydantic`, `python-dotenv`, `cryptography`) and the duplicate `Flask-SocketIO` line while preserving runtime/browser/tunnel dependencies used by current imports.
  - Updated `Dockerfile` to Python 3.12 and direct `requirements.txt` installation so `datetime.UTC` imports in modernization modules work in containers.
  - Removed the obsolete Compose `version` field while preserving the existing service, port, logging, and startup command.

- [x] Create a structured feature index:
  - Create `docs/features/simulation-platform-index.md` with YAML front matter using type `reference`, tags for `simulations`, `ai`, `metrics`, and `operations`
  - Link to `[[Simulation-Campaigns]]`, `[[Simulation-Target-Import]]`, `[[AI-Scenario-Generation]]`, `[[Simulation-Delivery-Tracking]]`, `[[Simulation-Metrics]]`, `[[Entra-Directory-Integration]]`, and `[[Simulation-Safety-Audit]]`
  - Summarize the UI locations, data flows, and safe operating assumptions for each feature

  Completion notes:
  - Added `docs/features/simulation-platform-index.md` with structured front matter, required feature wiki-links, a UI/data-flow/safety feature map, an end-to-end Mermaid flow, operating modes, and a safe operating checklist.
  - Verified the index content against the existing feature references and admin templates for current UI route names.

- [x] Add or update developer-facing run documentation:
  - Update existing setup or quick-start documentation with GUI-first instructions for launching the app and accessing the new simulation pages
  - Document dry-run delivery, mock AI generation, mock Entra sync, and how to move from mock mode to configured providers through the UI
  - Keep commands limited to app startup and tests; do not require CLI configuration for feature use
  - Add troubleshooting notes for common SQLite, dependency, and template import issues

  Completion notes:
  - Added `docs/reference/developer-runbook.md` with structured front matter, wiki-links, local startup steps, GUI route map, dry-run/mock/provider-mode guidance, test commands, and SQLite/dependency/template troubleshooting.
  - Updated the README quick-start simulation section from prototype language to GUI-first Simulation Platform instructions, including `/simulations`, campaigns, AI builder, AI settings, directory integration, metrics, and audit routes.
  - Kept operational commands limited to app startup, Docker startup, dependency/browser setup, unit tests, and Python compile checks; provider feature use is documented through the UI.

- [ ] Add regression test coverage across the full simulation workflow:
  - Campaign creation with authorization statement
  - Manual target entry and CSV upload
  - Mock AI generation and draft save
  - Dry-run delivery start and tracking events
  - Metrics dashboard and exports
  - Mock directory sync
  - Audit log entries and unauthenticated route protection

- [ ] Add a UI smoke runner or script if one does not already exist:
  - Start the Flask app with test credentials in a controlled local process
  - Log in through the normal `/neptune` flow using automated HTTP requests or browser automation available in the repo
  - Visit the main simulation pages and assert expected page titles or stable text
  - Stop the local process cleanly after verification

- [ ] Run the full release-readiness verification:
  - Run all available automated tests and smoke scripts
  - Run Python syntax/import checks for changed modules
  - Start the app locally and verify the authenticated UI routes for simulations, AI settings, campaign detail, metrics, directory integration, and audit log return HTTP 200
  - Fix any failures discovered during verification

- [ ] Produce a final implementation summary as structured Markdown:
  - Create `docs/reports/simulation-modernization-summary.md` with YAML front matter using type `report`, tags for `release`, `simulations`, and `modernization`
  - Link to all feature documents with wiki-links
  - Summarize completed features, known limitations, mock/provider modes, verification commands, and recommended next technical steps
