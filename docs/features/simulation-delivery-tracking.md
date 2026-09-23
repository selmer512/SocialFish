---
type: reference
title: Simulation Delivery Tracking
created: 2026-09-23
tags:
  - delivery
  - metrics
  - simulations
related:
  - '[[Simulation-Campaigns]]'
  - '[[AI-Scenario-Generation]]'
  - '[[Simulation-Metrics]]'
---

# Simulation Delivery Tracking

Simulation delivery tracking coordinates safe message delivery workflows for [[Simulation-Campaigns]] across email, SMS, and voice channels. It uses approved campaign content, including drafts from [[AI-Scenario-Generation]], to create delivery jobs, record per-target attempts, and feed engagement results into [[Simulation-Metrics]] without requiring external provider credentials for the default dry-run path.

## Dry-Run Delivery Behavior

Dry-run providers are the default execution path for delivery jobs. They record the same job, attempt, artifact, token, and event data that a real provider integration would use, but they do not send external email, SMS messages, or phone calls.

When an operator starts a dry-run delivery, the service:

- Builds a delivery preview from the current campaign, active targets, latest approved draft content, and enabled channel providers.
- Creates one delivery job with a provider snapshot for the selected channels.
- Stores channel-specific message artifacts so later events can be traced back to the delivered content.
- Creates per-target tracking tokens for open, link, and attachment events.
- Queues one delivery attempt per active target and channel.
- Runs the dry-run adapter, marks the attempt delivered, and records provider metadata showing `dry_run: true` and `external_delivery: false`.

Delivery reruns are retry-safe at the job level. Attempts already marked `sent` or `delivered` are skipped, while failed attempts are retried only when their retry count remains below the configured `max_retries`.

## Provider Readiness Checks

Delivery provider settings are managed in the database through the GUI. Provider responses returned to pages and APIs intentionally exclude secret material; secrets are represented only by whether a credential placeholder is configured.

Supported provider shapes are:

| Provider shape | Channels | Runtime behavior |
| --- | --- | --- |
| Dry run | Email, SMS, voice | Enabled seeded providers execute offline and record simulated delivery events. |
| SMTP | Email | Validates channel, enabled state, and SMTP settings, then fails closed until UI-managed credential retrieval is implemented. |
| Email API | Email | Validates channel, enabled state, required settings, and secret presence, then fails closed until provider-specific send logic is implemented. |
| SMS API | SMS | Validates channel, enabled state, required settings, and secret presence, then fails closed until provider-specific send logic is implemented. |
| Voice API | Voice | Validates channel, enabled state, required settings, and secret presence, then fails closed until provider-specific call logic is implemented. |

Disabled providers cannot run. Incomplete non-dry-run providers raise clear configuration errors before external execution can occur.

## Tracking Endpoints

Public tracking endpoints are scoped to simulation tracking tokens rather than lure hashes or template webhooks:

| Endpoint | Method | Recorded event | Response behavior |
| --- | --- | --- | --- |
| `/simulations/track/open/<token>` | `GET` | `opened` | Returns a no-cache transparent GIF pixel. Unknown tokens are ignored and still return the pixel. |
| `/simulations/track/link/<token>` | `GET` | `link_click` | Redirects to the token destination URL, falling back to `/` when the token or destination is invalid. |
| `/simulations/track/attachment/<token>` | `GET`, `POST` | `attachment_open` | Returns JSON for valid controlled training artifact events, or a `404` JSON error for invalid tokens. |
| `/api/simulations/providers/<channel>/<provider_key>/webhook` | `POST` | Provider-supplied event type, or token-derived event type | Records future provider events and validates an HMAC SHA-256 signature when `webhook_secret` or `signature_secret` is configured for the provider. |

Tracking tokens store first-seen and last-seen timestamps, event counts, token type, channel, campaign, target, delivery job, and message artifact references. Link tokens also store the campaign training URL or landing URL as their redirect destination.

## Delivery Status APIs

Authenticated operators can inspect delivery workflow state through the campaign page, the delivery status page, and JSON APIs:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/simulations/campaigns/<campaign_id>/deliveries/preview` | `POST` | Builds a preview from current campaign content, active targets, selected providers, and mode without creating delivery records. |
| `/simulations/campaigns/<campaign_id>/deliveries/start` | `POST` | Creates a job, artifacts, tracking tokens, and attempts, then runs the job through dry-run or enabled provider adapters. |
| `/simulations/deliveries/<job_id>` | `GET` | Renders the delivery status page with job counters, attempts, provider snapshot, and tracking token counts. |
| `/api/simulations/deliveries/<job_id>` | `GET` | Returns the same delivery status data as JSON for automated verification and future integrations. |

## Event Taxonomy

Simulation delivery and tracking events are written to `simulation_events` and update target rollup fields when the event type maps to a target metric.

| Event type | Target effect |
| --- | --- |
| `queued` | Sets `delivery_status` to `queued`. |
| `sent` | Sets `delivery_status` to `sent`. |
| `delivered` | Sets `delivery_status` to `delivered` and records `delivered_at`. |
| `failed` | Sets `delivery_status` to `failed`. |
| `open` or `opened` | Marks the target opened and records `opened_at`. |
| `forward` or `forwarded` | Marks the target forwarded and records `forwarded_at`. |
| `delete` or `deleted` | Marks the target deleted and records `deleted_at`. |
| `link_click` or `link_clicked` | Marks the target link-clicked and records `link_clicked_at`. |
| `attachment_open` or `attachment_opened` | Marks the target attachment-opened and records `attachment_opened_at`. |
| `voice_response` | Records a voice response event with response metadata and a `responded` delivery status. |

Each event can carry delivery job, attempt, tracking token, provider reference, provider event ID, error message, retry count, timestamp, channel, target, campaign, and metadata fields. This keeps provider ingestion, token tracking, and manual simulation metrics on one auditable event stream.
