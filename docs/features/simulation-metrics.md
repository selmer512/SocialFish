---
type: reference
title: Simulation Metrics
created: 2026-09-23
tags:
  - metrics
  - reporting
  - simulations
related:
  - '[[Simulation-Delivery-Tracking]]'
  - '[[Simulation-Campaigns]]'
  - '[[AI-Scenario-Generation]]'
---

# Simulation Metrics

Simulation Metrics provides normalized reporting for authorized awareness campaigns across email, SMS, and voice channels. It connects delivery and engagement events from [[Simulation-Delivery-Tracking]] with campaign and target data from [[Simulation-Campaigns]], including draft content workflows from [[AI-Scenario-Generation]], so operators can compare campaign performance without reading raw event logs by hand.

## Reporting Surfaces

| Surface | Path | Purpose |
| --- | --- | --- |
| Metrics dashboard | `/simulations/metrics` | Portfolio or campaign reporting with summary cards, channel comparison, campaign trend, department, and target risk tables. |
| Campaign metrics API | `/api/simulations/campaigns/<id>/metrics` | Campaign-level aggregate, channel, department, target, and campaign metadata as JSON. |
| Target metrics API | `/api/simulations/campaigns/<id>/targets/metrics` | Target-level metrics for one campaign as JSON. |
| Portfolio overview API | `/api/simulations/metrics/overview` | Active-campaign portfolio metrics as JSON. |
| Legacy-compatible metrics API | `/api/simulations/metrics?campaign_id=<id>` | Existing aggregate metrics endpoint with the same normalized filters. |
| Target CSV export | `/simulations/campaigns/<id>/targets/metrics.csv` | Downloadable target metrics rows for spreadsheet review. |
| Events JSON export | `/simulations/campaigns/<id>/events.json` | Raw campaign events with provider secrets omitted and sensitive metadata fields redacted. |
| Printable campaign report | `/simulations/campaigns/<id>/report` | Browser-printable HTML report suitable for saving to PDF. |

All reporting routes require an authenticated operator session.

## Event Taxonomy

Metrics are derived from `simulation_events` and target rollup fields. The event stream remains queryable for audit and export, while dashboard and report views use normalized aggregation helpers.

| Raw event type | Normalized metric | Target rollup effect |
| --- | --- | --- |
| `queued` | `queued` | Sets `delivery_status` to `queued`. |
| `sent` | `sent` | Sets `delivery_status` to `sent`. |
| `delivered` | `delivered` | Sets `delivery_status` to `delivered` and records `delivered_at`. |
| `failed` | `failed` | Sets `delivery_status` to `failed`. |
| `open`, `opened` | `opened` | Marks the target opened and records `opened_at`. |
| `forward`, `forwarded` | `forwarded` | Marks the target forwarded and records `forwarded_at`. |
| `delete`, `deleted` | `deleted` | Marks the target deleted and records `deleted_at`. |
| `link_click`, `link_clicked` | `link_clicked` | Marks the target link-clicked and records `link_clicked_at`. |
| `attachment_open`, `attachment_opened` | `attachment_opened` | Marks the target attachment-opened and records `attachment_opened_at`. |
| `voice_response` | `voice_responses` | Records a voice response event and uses a `responded` delivery status. |

Target-linked events are counted once per target and metric, even if repeated raw events exist. If a matching event is missing, aggregation falls back to the target rollup fields so imported, migrated, or dry-run records still report consistently.

## Metric Formulas

Each metric bucket includes counts and rates for campaign-level, channel-level, department-level, and target-level reporting.

| Field | Meaning |
| --- | --- |
| `total_targets` | Count of targets after campaign, channel, department, delivery status, active-campaign, and date filters are applied. |
| `<metric>` | Count of filtered targets with the normalized metric. Untargeted `voice_response` events also contribute to `voice_responses`. |
| `<metric>_rate` | `<metric> / total_targets`, rounded to four decimal places. Empty buckets report `0.0`. |

Tracked count fields are `queued`, `sent`, `delivered`, `failed`, `opened`, `forwarded`, `deleted`, `link_clicked`, `attachment_opened`, and `voice_responses`.

Target risk summaries in the dashboard weight behavior for triage: link clicks are highest, attachment opens and voice responses are next, opens and forwards add medium signal, and failed delivery contributes a small operational signal. Risk labels are `High`, `Medium`, or `Low`.

## Filters

Reporting filters are optional and default to broad, safe views.

| Filter | Query parameter | Behavior |
| --- | --- | --- |
| Campaign | `campaign_id` | Dashboard and legacy metrics can scope to one campaign. Without a campaign, portfolio reporting defaults to active, unarchived campaigns. |
| Channel | `channel` or comma-separated `channels` | Accepts only `email`, `sms`, and `voice`. Invalid values return a `400` error. |
| Date range | `start_date`, `end_date` | Filters events by `occurred_at`. Rollup fallback for engagement timestamps uses the corresponding target timestamp. Delivery-status rollup fallback only applies to `delivered` when a date filter is active. |
| Department | `department` | Uses the target department, treating blank departments as `Unassigned`. |
| Delivery status | `delivery_status` | Matches target delivery status or event delivery status for event-backed metrics. |
| Active campaigns | internal overview filter | Portfolio overview includes only active campaigns that are not archived. |

Filters are echoed back in metrics API responses and in the `X-SocialFish-Export-Filters` header on target CSV exports.

## Export Formats

### Target Metrics CSV

The target metrics CSV includes campaign identity, target identity, contact fields, department, channel, delivery status, count fields, and rate fields. It is intended for internal analysis and spreadsheet review. The response uses `text/csv`, a campaign-specific attachment filename, `Cache-Control: no-store`, and the export filter header.

### Events JSON

The events JSON export preserves raw campaign activity for audit and troubleshooting. Exported events include event identity, campaign and target references, channel, event type, delivery status, delivery job and attempt references, provider reference fields, error details, retry count, timestamps, source labels, and metadata.

Provider secret values are omitted from normal reporting responses. Event metadata is recursively redacted for sensitive key names such as secrets, passwords, tokens, credentials, and API keys before JSON is returned.

### Printable HTML Report

The printable report renders campaign summary metrics, channel metrics, target metrics, and event-source context in a browser-friendly HTML page. Operators can use the browser's print or save-to-PDF flow when they need a static report artifact.

## Dry-Run Interpretation

Dry-run delivery records real SocialFish database artifacts and simulated provider metadata without sending external email, SMS, or voice traffic. Dry-run queued, sent, delivered, opened, link-clicked, attachment-opened, and related events are included in the same metric formulas as provider-backed events so dashboards remain useful in demos and internal rehearsals.

Campaign detail reporting labels event sources so operators can distinguish:

| Source | Interpretation |
| --- | --- |
| Dry-run | Recorded by an offline delivery job with no external traffic. |
| Simulated | Recorded internally by SocialFish simulation workflows. |
| Provider | Received from a configured provider reference or webhook metadata. |

Dry-run metrics should be read as workflow validation and training rehearsal results. They prove that campaign setup, tracking tokens, exports, and dashboards are functioning, but they do not represent external recipient behavior unless a human deliberately triggers the tracking URLs or artifacts.
