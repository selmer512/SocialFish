---
type: reference
title: Simulation Target CSV Import
created: 2026-09-21
tags:
  - simulations
  - campaign-management
  - csv-import
related:
  - '[[Simulation-Campaigns]]'
  - '[[AI-Provider-Configuration]]'
---

# Simulation Target CSV Import

The campaign detail page supports importing target recipients from CSV for authorized internal training workflows in [[Simulation-Campaigns]]. The upload panel renders the accepted columns directly in the UI and links to a generated sample file at `/simulations/targets/sample.csv`, so no static sample file has to be maintained.

## Accepted Columns

| Column | Required | Notes |
| --- | --- | --- |
| `name` | Yes | Target name. If omitted, the row is rejected. |
| `display_name` | No | Friendly display name. Defaults to `name` when blank. |
| `email` | Conditional | Required when `channel` is `email`; normalized to lowercase. |
| `phone` | Conditional | Required when `channel` is `sms` or `voice`; spaces and common punctuation are normalized. |
| `department` | No | Optional department label for reporting and filtering. |
| `manager` | No | Optional manager name for reporting and follow-up. |
| `channel` | No | One of `email`, `sms`, or `voice`; defaults to the campaign primary channel. |
| `active` | No | Accepts truthy values by default; `0`, `false`, `no`, `off`, and `inactive` mark the target inactive. |

Unknown columns are accepted by the uploader only as validation errors. They are shown with row-numbered feedback on the campaign detail page so operators can correct the source file before retrying.

## Validation Behavior

- A header row is required.
- Each row must include `name` or enough display-name data to derive a name.
- Email targets require a valid email address such as `user@example.com`.
- SMS and voice targets require a 7 to 15 digit phone number, with an optional leading `+`.
- Duplicate contacts in the same file are rejected.
- Duplicate active contacts already present in the campaign are rejected.

## Operational Notes

CSV imports create an import batch record with row counts, imported counts, validation errors, and timestamps. Imported targets remain tied to their batch for auditability, while archived targets and campaign metrics remain available for history views. AI provider settings in [[AI-Provider-Configuration]] are separate from CSV import and are not required to upload targets.
