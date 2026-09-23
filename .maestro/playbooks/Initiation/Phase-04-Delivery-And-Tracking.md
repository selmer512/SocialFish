# Phase 04: Delivery And Tracking

This phase adds simulation delivery orchestration and event tracking for email, SMS, and voice channels. It starts with safe dry-run adapters and UI controls, then prepares clean extension points for real providers without requiring external credentials during execution.

## Tasks

- [x] Review existing mail-sending code, webhook code, tunnel utilities, campaign services, and event tables before implementing delivery so the new workflow reuses existing SocialFish capabilities where appropriate.

  Review completed 2026-09-22:
  - Mail sending currently lives in `core/sendMail.py` and `/mail` in `SocialFish.py`; it is direct SMTP with `sfmail` storing only email, SMTP host, and port, so delivery adapters should not reuse it for dry-run sends but can reuse its SMTP settings shape carefully.
  - Existing webhook code is template/session oriented: `webhooks` and `webhook_logs` tables are created in `core/db_migration.py`, and `/capture/<lure_hash>` posts enabled template webhooks without signature validation. Future provider ingestion routes should be separate from these outbound notification webhooks.
  - Tunnel and lure utilities are already available through `core/tunnel_manager.py`, `/tunnel/setup`, `/lure/generate`, `mitm_config`, `tunnel_sessions`, and `lure_urls`; delivery tracking links can reuse the configured public base URL concept but should use simulation-scoped tokens instead of lure hashes.
  - Campaign services in `core/simulation_service.py` already normalize `email`, `sms`, and `voice` channels, manage campaigns/targets/import batches, preserve archived metrics, and expose AI draft history suitable as message source content.
  - Event tables already include `simulation_events` plus rollup fields on `simulation_targets` for delivered/opened/forwarded/deleted/link-clicked/attachment-opened. Missing delivery orchestration tables include jobs, attempts, message artifacts, tracking tokens, provider references, retry state, and voice response taxonomy.

- [x] Extend the data model for delivery orchestration:
  - Add delivery jobs, delivery attempts, message artifacts, tracking tokens, and channel provider references
  - Track queued, sent, delivered, failed, opened, forwarded, deleted, link clicked, attachment opened, and voice response events
  - Record target, campaign, channel, provider, timestamps, error messages, and retry counts
  - Keep all migrations idempotent and preserve existing data

  Completed 2026-09-22:
  - Added idempotent migration coverage for `simulation_delivery_jobs`, `simulation_delivery_attempts`, `simulation_message_artifacts`, `simulation_tracking_tokens`, and `simulation_channel_providers`.
  - Extended `simulation_events` with delivery job, attempt, tracking token, provider reference, provider event, error, and retry metadata columns.
  - Seeded safe channel provider references for dry-run email/SMS/voice plus disabled real-provider placeholders.
  - Extended service event taxonomy for queued, sent, failed, and voice response events without enabling external delivery.
  - Verified with `python -m unittest discover tests`.

- [x] Implement delivery provider adapters:
  - Add a dry-run email adapter that records send attempts without sending external email
  - Add dry-run SMS and voice adapters that record simulated delivery events without contacting telecom providers
  - Add configuration-ready adapter shells for SMTP/email API, SMS API, and voice API providers using database-managed settings
  - Prevent real provider execution unless the provider is explicitly enabled in the GUI and has the required settings

  Completed 2026-09-22:
  - Added provider-neutral delivery adapter contracts in `core/delivery_adapters.py` with safe dry-run email, SMS, and voice adapters.
  - Added configuration-ready SMTP, email API, SMS API, and voice API shells that validate database-managed settings and refuse real execution until provider-specific sending is implemented.
  - Added delivery provider settings helpers in `core/simulation_service.py` that redact secret placeholders while preserving enabled state, required settings, and UI-managed configuration.
  - Verified dry-run behavior and provider safety checks with `python -m unittest discover tests`.

- [x] Implement delivery orchestration services:
  - Add functions to create delivery jobs from campaigns and active targets
  - Generate per-target tracking tokens for links and attachments
  - Queue per-channel attempts and record provider results
  - Add retry-safe logic so re-running a job does not duplicate completed attempts

  Completed 2026-09-22:
  - Added delivery preview, job creation, job status, and job execution service functions in `core/simulation_service.py`.
  - Delivery jobs now create per-channel message artifacts, per-target open/link/attachment tracking tokens, queued attempts, and delivery events with provider metadata.
  - Dry-run provider execution records provider responses and updates job/target rollups while skipping already delivered attempts on rerun.
  - Verified with focused orchestration tests and `python -m unittest discover tests`.

- [x] Add authenticated delivery routes:
  - `POST /simulations/campaigns/<id>/deliveries/preview` builds a delivery preview from current campaign content and targets
  - `POST /simulations/campaigns/<id>/deliveries/start` starts a dry-run or enabled-provider delivery job from the UI
  - `GET /simulations/deliveries/<job_id>` renders delivery job status
  - `GET /api/simulations/deliveries/<job_id>` returns delivery job status JSON

  Completed 2026-09-22:
  - Added authenticated preview, start, rendered status, and JSON status routes for simulation delivery jobs.
  - Delivery starts now create and run jobs through the existing orchestration service while preserving dry-run safety semantics.
  - Added a delivery status template showing job counters, provider snapshot, attempts, and tracking-token counts.
  - Verified with focused route coverage and `python -m unittest discover tests`.

- [x] Add tracking endpoints for simulation events:
  - Add a pixel or lightweight open-tracking endpoint scoped to simulation tokens
  - Add a redirect endpoint that records link clicks and then redirects to the configured training destination
  - Add an attachment-event endpoint for recording simulated attachment opens in controlled training artifacts
  - Add webhook ingestion routes for future email/SMS/voice providers while validating signatures when configured

  Completed 2026-09-22:
  - Added public simulation tracking endpoints for open pixels, link redirects, and controlled attachment events.
  - Added provider webhook ingestion for delivery providers with optional HMAC SHA-256 signature validation from database-managed provider settings.
  - Added service helpers that resolve tracking tokens, increment token counters, record simulation events, and preserve target rollups.
  - Verified with focused tracking tests and `python -m unittest discover tests`.

- [x] Build delivery UI surfaces:
  - Add delivery preview, start, and status panels on campaign detail pages
  - Show dry-run status clearly so operators know no external messages were sent
  - Show per-target per-channel delivery status and latest event
  - Provide provider setting links back to AI Settings or a provider settings page as appropriate

  Completed 2026-09-23:
  - Added campaign detail delivery preview, dry-run start controls, recent status links, and per-target latest-event display.
  - Added delivery provider configuration forms to AI Settings with dry-run/readiness guidance and write-only secret handling.
  - Verified with `python -m unittest tests.test_simulation_routes` and `python -m unittest discover tests`.

- [x] Add structured feature documentation while implementing delivery:
  - Create `docs/features/simulation-delivery-tracking.md` with YAML front matter using type `reference`, tags for `delivery`, `metrics`, and `simulations`
  - Include wiki-links to `[[Simulation-Campaigns]]`, `[[AI-Scenario-Generation]]`, and `[[Simulation-Metrics]]`
  - Document dry-run behavior, provider readiness checks, tracking endpoints, and event taxonomy

  Completed 2026-09-23:
  - Added `docs/features/simulation-delivery-tracking.md` with reference front matter, requested tags, and wiki-links.
  - Documented dry-run delivery behavior, provider readiness checks, tracking endpoints, status APIs, and the event taxonomy.

- [x] Add automated delivery and tracking coverage:
  - Test dry-run delivery job creation for email, SMS, and voice
  - Test idempotent reruns do not duplicate completed attempts
  - Test open, link-click, attachment-open, and webhook event recording
  - Test disabled or incomplete providers fail safely with clear UI/API errors

  Completed 2026-09-23:
  - Expanded service coverage for dry-run delivery job channel distribution, provider recording, tracking-token events for open/link/attachment, idempotent reruns, webhook event recording, and safe real-provider shell failures.
  - Expanded route coverage for disabled and incomplete provider selections so API payloads and rendered status pages expose failed attempts with clear error messages and no external delivery.
  - Verified with `python -m unittest tests.test_simulation_service`, `python -m unittest tests.test_simulation_routes`, and `python -m unittest discover tests`.

- [x] Run delivery verification:
  - Run the delivery and tracking tests
  - Use automated HTTP requests to create a delivery preview, start a dry-run job, fetch job JSON, call tracking endpoints with generated tokens, and verify metrics update
  - Fix any schema, service, route, or template failures discovered during verification

  Completed 2026-09-23:
  - Ran focused delivery and tracking suites with `python -m unittest tests.test_simulation_service tests.test_simulation_routes`; 44 tests passed.
  - Added and ran `.maestro/playbooks/Working/verify_delivery_http.py`, which uses Flask test-client HTTP requests to preview delivery, start a dry-run job, fetch job JSON, call open/link/attachment tracking endpoints with generated tokens, and verify aggregate metrics and token events update.
  - Ran full regression coverage with `python -m unittest discover tests`; 65 tests passed.
  - No schema, service, route, or template failures remained after verification.
