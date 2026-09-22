---
type: reference
title: AI Scenario Generation
created: 2026-09-22
tags:
  - ai
  - simulations
  - training
related:
  - '[[Simulation-Campaigns]]'
  - '[[AI-Provider-Configuration]]'
  - '[[Simulation-Metrics]]'
---

# AI Scenario Generation

The AI Scenario Builder creates authorized training drafts for [[Simulation-Campaigns]] across email, SMS, and voice channels. It uses provider settings managed through the GUI in [[AI-Provider-Configuration]], applies safety checks before and after generation, and preserves approved draft history for campaign review and [[Simulation-Metrics]] workflows.

## GUI Workflow

Operators open `/simulations/ai-builder` from a campaign detail page or the simulation navigation. The builder form captures campaign, provider, audience, scenario objective, channels, tone, difficulty, and an optional training reminder.

Generated content is returned as separate preview panes for:

| Channel | Generated fields |
| --- | --- |
| Email | Subject and body |
| SMS | SMS body |
| Voice | Voice script |
| Training support | Landing text and training text |

The preview also shows risk flags and safety notes before the operator saves selected channel drafts. Saving writes a new campaign-linked draft record instead of overwriting earlier drafts, so each campaign can retain multiple channel-specific content versions over time.

## Provider Configuration

Provider settings are edited at `/ai-settings` and stored in the UI-managed AI provider configuration table. The generation layer reads provider metadata from that database configuration rather than environment variables or hard-coded secrets.

Supported provider shapes are:

| Provider shape | Status | Notes |
| --- | --- | --- |
| Local mock | Active | Deterministic offline provider for safe awareness-training drafts. |
| OpenAI-compatible HTTP | Configuration-ready shell | Builds a guarded chat/completions-style payload, then fails closed until UI-managed credential retrieval is implemented. |
| Local HTTP model server | Configuration-ready shell | Builds a guarded local-server prompt payload, then fails closed until response parsing is implemented. |

Disabled providers cannot be selected for generation. Cloud provider secrets are write-only: the settings API accepts a replacement secret and records only whether one is configured, while pages and JSON responses do not render the secret value.

## Safety Guardrails

Every generated artifact is labeled with `authorized_security_awareness_training` in metadata. The generation contract blocks requests or outputs that ask for credential harvesting, real-brand impersonation defaults, or instructions that increase offensive capability outside training simulations.

Generation responses include:

- Provider and model identifiers.
- Channel coverage.
- Draft content for requested channels.
- Risk flags for reviewer attention.
- Safety notes describing relevant constraints.
- Metadata that excludes provider credentials.

Generation attempts are audited with the prompt request, selected provider, generated output when available, risk flags, safety notes, status, error reason, and timestamp. Blocked generations are recorded as blocked audit entries so reviewers can see why a request failed without exposing secrets.

## Local Mock Behavior

The local mock provider is deterministic and does not make network calls. It produces plain-language training content that explicitly identifies the exercise as authorized security awareness training, reminds participants not to share credentials, and includes landing/training text for reviewer use.

The mock provider is intended for development, demonstrations, and safe operation without external credentials. It still passes through the same request validation, response validation, audit logging, risk flag, and draft-save paths used by other provider shapes.
