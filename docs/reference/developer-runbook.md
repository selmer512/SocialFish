---
type: reference
title: Developer Runbook
created: 2026-09-24
tags:
  - developer
  - operations
  - simulations
related:
  - '[[Simulation-Platform-Feature-Index]]'
  - '[[AI-Scenario-Generation]]'
  - '[[Simulation-Delivery-Tracking]]'
  - '[[Entra-Directory-Integration]]'
  - '[[Dependency-Reference]]'
---

# Developer Runbook

This runbook covers local startup, GUI-first simulation workflows, mock/provider modes, and common troubleshooting for the modernized SocialFish simulation platform.

## Local Startup

Install dependencies once, then start the Flask app with a local operator username and password:

```bash
pip install -r requirements.txt
playwright install chromium
python SocialFish.py admin password
```

Open `http://localhost:5000/neptune`, sign in with the same credentials, and use the admin UI for feature configuration. Normal startup initializes `database.db`, runs the database migration path, and seeds mock/dry-run records used by [[Simulation-Platform-Feature-Index]].

For containerized local checks:

```bash
docker compose up
```

## Simulation UI Map

| Workflow | GUI location | Use it for |
| --- | --- | --- |
| Simulation dashboard | `/simulations` | Review campaign status, current activity, metrics entry points, and navigation to simulation tools. |
| Campaign management | `/simulations/campaigns` | Create campaigns, record authorization statements, add targets, review readiness, and launch delivery. |
| AI settings | `/ai-settings` | Enable mock AI, review configured provider shells, and manage write-only provider secret placeholders. |
| AI Scenario Builder | `/simulations/ai-builder` | Generate and save authorized awareness-training drafts through the selected GUI-managed provider. |
| Metrics | `/simulations/metrics` | Review portfolio and campaign metrics, exports, and reporting filters. |
| Directory integration | `/integrations/directory` | Configure mock Entra or future Microsoft Graph settings, preview users, and import approved targets. |
| Audit log | `/audit-log` | Review administrative actions, safety events, exports, and redacted metadata. |

All administrative simulation pages require the `/neptune` login session. Public delivery tracking endpoints are token-scoped and are not used for admin navigation.

## Mock And Provider Modes

### Dry-Run Delivery

Dry-run email, SMS, and voice providers are seeded for local development. Start from a campaign detail page, confirm the authorization statement, active targets, and channel content, then use the delivery preview/start controls. Dry-run delivery creates jobs, attempts, artifacts, tokens, events, and metrics without sending external email, SMS, or voice traffic. See [[Simulation-Delivery-Tracking]].

### Mock AI Generation

Use `/ai-settings` to keep the local mock AI provider enabled, then open `/simulations/ai-builder`. The mock provider is deterministic and offline, but it still exercises request validation, safety checks, audit logging, draft preview, and draft save behavior. See [[AI-Scenario-Generation]].

### Mock Entra Sync

Use `/integrations/directory` to create or update a `mock_entra` provider, load groups, run a preview sync, review the staged users, and import valid users into a selected campaign. Mock Entra uses deterministic groups and users, so no Microsoft tenant credentials or Graph network calls are required. See [[Entra-Directory-Integration]].

### Moving To Configured Providers

Move from mock mode through the UI, not command-line configuration:

1. Open `/ai-settings` or `/integrations/directory`.
2. Select the provider type for the channel or integration.
3. Fill in visible provider settings such as model name, base URL, tenant ID, client ID, consented scopes, channel, or API endpoint.
4. Enter any secret material only in the write-only secret fields or provide an external secret reference where the UI supports it.
5. Save and use the page-level test, preview, or readiness controls before launching a workflow.

Configured OpenAI-compatible, local HTTP model, SMTP, email API, SMS API, voice API, and Microsoft Graph provider shells validate settings and fail closed where credential retrieval or provider-specific execution is not yet implemented. Keep dry-run and mock providers enabled for local regression work.

## Verification Commands

Use the test suite for regression checks:

```bash
python -m unittest discover tests
```

Use Python compile checks when editing route or service modules:

```bash
python -m py_compile SocialFish.py core/simulation_service.py core/ai_generation.py core/delivery_adapters.py core/directory_connectors.py core/audit_service.py
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `sqlite3.OperationalError: no such table ...` | The app did not complete normal startup or is pointing at an unexpected database file. | Start with `python SocialFish.py admin password` from the repository root so `initDB(DATABASE)` and migrations run against `database.db`. |
| Seeded simulation data is missing | An older local database predates the migration, or startup was interrupted. | Restart the app from the repository root and check the console for migration errors before logging in again. |
| `ModuleNotFoundError` for Flask, Playwright, Socket.IO, or tunnel libraries | Dependencies are not installed in the active Python environment. | Run `pip install -r requirements.txt`; run `playwright install chromium` only when using browser automation features. |
| Import or runtime errors involving `datetime.UTC` | The runtime is older than the supported Python baseline. | Use Python 3.11 or newer. Docker uses Python 3.12. |
| `TemplateNotFound` for admin simulation pages | The app is not being started from the repository root or the template tree is incomplete. | Start from the directory containing `SocialFish.py` and confirm `templates/admin/` exists. |
| Delivery readiness blocks launch | Authorization, targets, content, or providers are incomplete. | Use the campaign detail readiness messages, add the missing data in the UI, or choose dry-run providers for local validation. |
| Provider setup appears saved but secrets are not visible | Secret inputs are intentionally write-only. | Use configured indicators, provider test controls, and audit logs rather than expecting secret values to render back. |
