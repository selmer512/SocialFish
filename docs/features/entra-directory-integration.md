---
type: reference
title: Entra Directory Integration
created: 2026-09-23
tags:
  - entra
  - directory
  - targets
related:
  - '[[Simulation-Campaigns]]'
  - '[[Simulation-Target-Import]]'
  - '[[Simulation-Metrics]]'
---

# Entra Directory Integration

The directory integration page prepares SocialFish to stage Microsoft Entra ID users for authorized awareness training in [[Simulation-Campaigns]]. It currently supports a deterministic mock Entra connector for local development and a Microsoft Graph configuration shell for future tenant-backed sync. Imported directory users become campaign targets alongside manual and CSV targets from [[Simulation-Target-Import]], and their source metadata remains available for filtering and [[Simulation-Metrics]].

## Operator Workflow

| Step | Surface | Result |
| --- | --- | --- |
| Configure provider | `/integrations/directory` | Create or update a UI-managed provider with tenant metadata, selected groups, field mapping, consent status, and secret placeholders. |
| Test provider | `/api/integrations/directory/providers/<id>/test` | Validate the selected connector without exposing secret values in the response. |
| Load groups | `/api/integrations/directory/providers/<id>/groups` | List available groups from the mock connector or fail safely for incomplete Microsoft Graph settings. |
| Preview sync | `/api/integrations/directory/providers/<id>/preview` | Stage users from selected groups and record validation results without adding campaign targets. |
| Import sync | `/api/integrations/directory/providers/<id>/sync` | Import valid, active staged users into the selected campaign target list. |
| Review job | `/integrations/directory/sync-jobs/<id>` | Inspect staged users, imported counts, skipped counts, duplicate counts, validation issues, and audit events. |

All directory routes require an authenticated operator session. Preview jobs are review-only; campaign target rows are created only by the sync import action.

## Mock Mode

Mock mode uses provider type `mock_entra`. It is enabled through the same directory settings page as future Graph providers, so operators can rehearse the full workflow without tenant credentials or network access.

The mock connector returns deterministic groups and users:

| Mock group | Example departments | Purpose |
| --- | --- | --- |
| Finance Awareness Pilot | Finance | Validate group selection, department filters, and campaign import review. |
| Engineering Awareness Pilot | Engineering | Validate multi-user previews and duplicate handling. |
| Operations Awareness Pilot | Operations | Validate small-group previews and sync history. |

Mock users include Entra-like fields such as user principal name, display name, mail, mobile phone, department, manager, job title, office location, group names, and source group IDs. Mock previews are labeled as offline artifacts and do not query an external directory.

## Future Microsoft Graph Settings

Provider type `microsoft_graph` is a configuration-ready shell. It validates required settings and permission consent before any Graph request shape is built, but live group listing and user preview intentionally fail closed until UI-managed credential retrieval is implemented.

Required provider settings include:

| Setting | Notes |
| --- | --- |
| `tenant_id` | Microsoft Entra tenant identifier. |
| `client_id` | Application/client identifier for the future Graph integration. |
| `authority_url` | Authority URL used when building Graph authentication requests. |
| `consented_scopes` | Must include `Group.Read.All` and `User.Read.All`. |
| `secret_reference` | Optional reference to an external secret location. Raw OAuth tokens or client secrets are not rendered back to pages or JSON responses. |

The UI displays the Microsoft Graph permission names so operators know what future tenant setup will require. Until credential retrieval is connected, Graph connector APIs return actionable configuration errors instead of attempting network calls.

## Field Mapping

Directory users are mapped into the simulation target payload through provider-managed field mapping. The default mapping uses:

| Target field | Directory source |
| --- | --- |
| `name` / `display_name` | Directory display name. |
| `email` | Mail address or user principal name. |
| `phone` | Mobile phone or first business phone. |
| `department` | Directory department. |
| `manager` | Directory manager label. |
| `channel` | Email when mail or UPN is available; otherwise SMS. |
| `source` | Always `directory`. |

Custom field mappings can override target fields with supported directory user attributes. Imported targets retain source metadata including provider ID, sync job ID, external user ID, source group IDs, group names, and the directory artifact label.

## Sync Preview

Preview sync creates a `directory_sync_jobs` record and stages candidate users in `staged_directory_users`. Staged rows capture the mapped target payload, validation status, validation errors, group membership, and active state.

Preview does not add users to a campaign. Operators can use the sync job page to review:

- Selected groups and total group/user counts.
- Staged, imported, skipped, invalid, and duplicate counts.
- Per-user validation messages.
- Sync audit events for troubleshooting and compliance review.

## Duplicate Handling

Directory imports use the same campaign target duplicate protections as manual and CSV imports. If an active target with the same email address or phone number already exists in the destination campaign, the directory row is skipped instead of creating a duplicate.

Duplicate checks apply across sources, so a directory-synced user will not duplicate a manually created target or a CSV-imported target in the same campaign. Re-running the same directory sync also avoids duplicate target creation. Skipped duplicates are counted on the sync job and remain visible during review.

## Campaign Targeting And Metrics

Directory-synced targets can be selected and delivered through the same campaign targeting workflow as other targets in [[Simulation-Campaigns]]. Campaign detail filters include source, department, and directory group mapping, which lets operators review imported directory cohorts before delivery.

Because imported rows preserve `source = directory` and group metadata, downstream reporting in [[Simulation-Metrics]] can distinguish directory-synced recipients from manual and CSV-imported recipients while still using the normalized campaign target and event models.
