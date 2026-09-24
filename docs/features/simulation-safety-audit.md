---
type: reference
title: Simulation Safety Audit
created: 2026-09-23
tags:
  - audit
  - safety
  - access-control
related:
  - '[[Simulation-Campaigns]]'
  - '[[Simulation-Delivery-Tracking]]'
  - '[[Entra-Directory-Integration]]'
---

# Simulation Safety Audit

Simulation Safety Audit documents the administrative controls that keep SocialFish simulation workflows reviewable, authorized, and bounded to internal awareness training. It connects operator audit trails, readiness checks, and secret redaction rules across [[Simulation-Campaigns]], [[Simulation-Delivery-Tracking]], and [[Entra-Directory-Integration]].

## Authorized-Use Workflow

Operators must record an authorization statement before a campaign can be launched. The statement is stored on the campaign record and is intended to capture the approved internal scope, responsible owner, or other authorization reference used by the Cybersecurity Team.

Campaign delivery follows this workflow:

| Step | Surface | Safety purpose |
| --- | --- | --- |
| Create campaign | `/simulations/campaigns/new` | Captures the campaign name, selected channels, scope, and required authorization statement. |
| Add recipients | Campaign detail, CSV import, or directory sync | Ensures the target list is intentionally staged before delivery. |
| Prepare content | Manual drafts or AI Scenario Builder | Ensures each selected delivery channel has usable training content. |
| Review readiness | Campaign detail and delivery preview | Shows whether authorization, targets, content, and provider settings are ready. |
| Start delivery | `/simulations/campaigns/<id>/deliveries/start` | Blocks launch unless readiness checks pass; dry-run mode remains available for local verification. |
| Review audit log | `/audit-log` and `/audit-log/<id>` | Lets authenticated operators inspect who performed each administrative action and why. |

Delivery blocks return actionable messages instead of creating partial jobs, so operators can repair the specific missing authorization, targeting, content, or provider setup before trying again.

## Audit Events

Administrative audit events are stored in `administrative_audit_events` and recorded through `core/audit_service.py`. Each event includes actor identity, action type, entity type, entity ID, campaign ID when applicable, channel, IP address, user agent, timestamp, and structured redacted metadata.

High-value workflows emit audit events for:

| Workflow area | Example actions | Entity type |
| --- | --- | --- |
| Campaigns | `campaign.create`, `campaign.update`, `campaign.archive` | `campaign` |
| Targets | `target.create`, `target.update`, `target.archive`, `target.import_csv` | `target` |
| AI providers and generation | `ai_provider.configure`, `ai_provider.test`, `generation.create`, `generation.save_draft` | `ai_provider` or `ai_generation` |
| Delivery | `delivery.preview`, `delivery.start` | `delivery` |
| Directory sync | `directory.provider_create`, `directory.provider_update`, `directory.provider_test`, `directory.preview`, `directory.sync` | `directory_sync` |
| Exports and reports | `export.metrics_csv`, `export.events_json`, `export.report_view` | `export` |

The audit log UI supports filtering by action type, entity type, channel, actor, date range, and campaign. Campaign detail pages link directly to related audit events with the campaign filter already applied.

## Readiness Checks

`check_campaign_delivery_readiness` in `core/simulation_service.py` evaluates delivery prerequisites before a job is created. The same check is used by preview and launch routes so the UI and JSON APIs report consistent status.

Readiness currently verifies:

| Check | Requirement | Operator fix |
| --- | --- | --- |
| Authorization statement | Campaign has a non-empty authorization statement. | Add or update the campaign authorization statement. |
| Target count | Campaign has at least one active target. | Add manual, CSV, or directory-synced targets. |
| Channel content | Selected channels have message content available for delivery. | Save channel drafts or update campaign content. |
| Provider readiness | Selected providers are enabled and configured for the requested mode. | Use dry-run providers for testing or complete the real provider configuration. |

When readiness fails, delivery start returns a structured `delivery_readiness_failed` JSON error for API callers or flashes operator-facing messages in the admin UI. Failed readiness does not create delivery jobs, attempts, message artifacts, or tracking tokens.

## Redaction Rules

Audit metadata is recursively sanitized before it is persisted. Keys containing plaintext secret indicators are replaced with `[redacted]`, including API keys, bearer values, client secrets, cookies, credentials, passwords, private keys, refresh tokens, sessions, and generic token or secret fields.

Safe configuration indicators are preserved:

| Preserved key shape | Reason |
| --- | --- |
| `secret_placeholder` | Indicates whether a secret has been configured without revealing the secret. |
| `secret_reference` | Points to an external secret location such as a vault reference. |
| `*_placeholder` | Allows UI state to show configured/missing without exposing secret material. |
| `*_reference` | Allows non-secret references to remain auditable. |

Provider settings returned to pages and JSON responses also remove raw secret placeholders where appropriate and expose only derived safe fields such as whether a secret is configured. This keeps audit and troubleshooting metadata useful without storing plaintext provider credentials.

## Access Control Expectations

Audit log pages, simulation administration pages, provider configuration routes, directory integration routes, and export/report endpoints require the existing authenticated operator session. Public tracking endpoints remain token-scoped for recipient engagement events and do not grant access to administrative audit data.

These controls are additive to the existing Flask-Login pattern: administrative routes use authenticated sessions, simulation APIs validate IDs and state transitions, and audit records preserve enough request context for later review without widening who can view or modify campaign data.
