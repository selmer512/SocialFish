# Phase 05: Metrics And Reporting

This phase modernizes reporting so the Cybersecurity Team can understand campaign performance across email, SMS, and voice from the UI. It adds normalized metrics, dashboard views, exports, and report documentation around delivery, opens, forwards, deletes, link clicks, attachment opens, and training engagement.

## Tasks

- [x] Review existing reporting routes, templates, PDF/report helpers, and Phase 01-04 simulation services before adding new dashboards so reporting remains integrated with the current app.

  Review notes, 2026-09-23:
  - Legacy capture reporting is wired through `/report`, `templates/admin/report.html`, `core/genReport.py`, and `core/report.py`; the older PDF path uses `pylatex`, queries the `creds` table, and is separate from simulation data.
  - Simulation reporting already starts in `core/simulation_service.py` through `get_campaign_metrics`, `get_campaign_detail`, `list_simulation_events`, and target rollup fields. The current `/api/simulations/metrics` endpoint accepts `campaign_id` only and returns aggregate/channel counts derived from `simulation_targets`, not raw event counts or rates.
  - Phase 01-04 simulation routes in `SocialFish.py` are centered on `/simulations`, `/simulations/campaigns`, delivery job routes, tracking endpoints, provider webhooks, and AI Builder routes. Future dashboards should extend these Flask/Bootstrap/Jinja patterns rather than adding a separate frontend stack.
  - Delivery/tracking events are normalized through `VALID_SIMULATION_EVENTS` and `record_simulation_event`, with aliases for `open`/`opened`, `forward`/`forwarded`, `delete`/`deleted`, `link_click`/`link_clicked`, and `attachment_open`/`attachment_opened`. Dry-run delivery writes queued/sent/delivered events and provider metadata without external sends.
  - Existing coverage lives in `tests/test_simulation_service.py`, `tests/test_simulation_routes.py`, and `tests/test_simulation_smoke.py`; future metrics work should expand those tests around filters, event-derived counts/rates, exports, and empty campaign states.

- [x] Implement normalized metrics aggregation:
  - Add service functions for campaign-level, channel-level, department-level, and target-level metrics
  - Calculate counts and rates for queued, sent, delivered, failed, opened, forwarded, deleted, link clicked, attachment opened, and voice responses
  - Handle missing events and dry-run events consistently
  - Keep raw events queryable while using aggregation helpers for UI/reporting

- [x] Add reporting API endpoints:
  - `GET /api/simulations/campaigns/<id>/metrics` returns campaign metrics
  - `GET /api/simulations/campaigns/<id>/targets/metrics` returns target-level metrics
  - `GET /api/simulations/metrics/overview` returns portfolio-level metrics across active campaigns
  - Include date range and channel filters using safe defaults when filters are absent

  Completion notes, 2026-09-23:
  - Added authenticated JSON endpoints for campaign metrics, campaign target metrics, and active-campaign portfolio overview metrics.
  - Extended normalized metrics helpers with optional channel, date range, department, delivery status, and active-campaign filters while preserving the existing `/api/simulations/metrics` default behavior.
  - Added route coverage for filtered campaign/target/overview metrics and invalid channel filter errors.

- [x] Build the metrics dashboard UI:
  - Add a Simulation Metrics page available from the admin navigation
  - Show portfolio summary cards, channel comparison tables, campaign trend tables, and target risk summaries
  - Add filters for campaign, channel, date range, department, and delivery status
  - Use existing Bootstrap and static conventions without introducing a disconnected frontend stack

  Completion notes, 2026-09-23:
  - Added a server-rendered `/simulations/metrics` dashboard using the existing Flask, Bootstrap, and Jinja conventions.
  - Wired Simulation Metrics into the admin easy-access buttons and Simulation Center actions.
  - Added portfolio summary cards, channel comparison, campaign trend, department summary, and target risk tables with campaign, channel, date range, department, and delivery status filters.
  - Added route coverage for the dashboard shell and filtered campaign reporting render.

- [x] Enhance campaign detail reporting:
  - Add a metrics tab or section to campaign detail pages
  - Show delivery funnel counts, per-channel status, and target activity history
  - Include clear distinctions between dry-run, simulated, and real-provider events
  - Link from summary metrics to filtered target/event tables

  Completion notes, 2026-09-23:
  - Added a Campaign Metrics section to campaign detail pages with delivery funnel rows, per-channel status rows, and per-target activity history.
  - Added event source labeling for dry-run, simulated, and real-provider events without exposing provider secret material.
  - Linked funnel rows to the target/event tables and channel rows to filtered Simulation Metrics views.
  - Added service and route coverage for campaign detail reporting rollups, event source classification, and rendered reporting UI.

- [x] Add export functionality:
  - Add CSV export for campaign target metrics
  - Add JSON export for campaign events
  - Add a simple HTML report view suitable for printing or saving to PDF from the browser
  - Ensure exports omit provider secrets and redact sensitive fields where appropriate

  Completion notes, 2026-09-23:
  - Added campaign target metrics CSV exports, campaign events JSON exports, and printable campaign report pages.
  - Linked export actions from campaign detail pages and reused normalized metrics helpers for exported target rows.
  - Added recursive event metadata redaction for secrets, tokens, credentials, passwords, and API keys before JSON export.
  - Added route coverage for CSV, JSON, print report rendering, and redaction behavior.

- [x] Add structured reporting documentation while implementing dashboards:
  - Create `docs/features/simulation-metrics.md` with YAML front matter using type `reference`, tags for `metrics`, `reporting`, and `simulations`
  - Include wiki-links to `[[Simulation-Delivery-Tracking]]`, `[[Simulation-Campaigns]]`, and `[[AI-Scenario-Generation]]`
  - Document the event taxonomy, metric formulas, filters, export formats, and dry-run interpretation

  Completion notes, 2026-09-23:
  - Added `docs/features/simulation-metrics.md` with structured reference front matter and the requested wiki-links.
  - Documented reporting surfaces, normalized event taxonomy, metric formulas, filters, CSV/JSON/print export formats, and dry-run interpretation.

- [ ] Add automated metrics and reporting coverage:
  - Test aggregation math for each tracked event type
  - Test date range, campaign, channel, department, and status filters
  - Test CSV and JSON exports
  - Test that report views render for seeded and empty campaign states

- [ ] Run metrics verification:
  - Run the metrics/reporting tests
  - Use automated HTTP requests to fetch overview metrics, campaign metrics, CSV export, JSON export, and printable report pages
  - Fix any aggregation, filtering, route, export, or template failures discovered during verification
