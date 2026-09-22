# Phase 03: AI Scenario Generation

This phase adds an implementation-neutral AI layer for creating authorized training scenarios and message drafts across phishing, smishing, and vishing simulations. It keeps provider configuration in the GUI, supports cloud and local model shapes, and includes a safe local mock provider so the feature works without credentials.

## Tasks

<!-- MAESTRO:MODEL tier="high" effort="high" reason="This phase designs the abstraction that all local and cloud AI providers will depend on. A careful interface prevents provider lock-in and keeps future model additions from becoming siloed features." -->

- [x] Design the AI provider interface and generation contract:
  - Review the Phase 01 AI settings model and existing project service style
  - Define a provider-neutral request shape for scenario goal, audience, channel, tone, difficulty, safety constraints, and optional campaign context
  - Define a provider-neutral response shape for email subject/body, SMS body, voice script, recommended landing/training text, and risk flags
  - Document the contract in code comments near the interface, not in a separate-only design document

- [x] Implement provider adapters:
  - Add a deterministic local mock provider that produces safe training drafts without network access
  - Add configuration-ready adapter shells for OpenAI-compatible HTTP APIs and local HTTP model servers without hard-coding provider-specific secrets
  - Read provider settings only from the database/UI-managed configuration created in earlier phases
  - Ensure disabled providers cannot be used for generation

- [x] Add safety and compliance guardrails to generation:
  - Require every generated artifact to be labeled as authorized security awareness training in metadata
  - Block credential harvesting language, real brand impersonation defaults, and instructions that increase offensive capability outside training simulations
  - Store generation prompts, selected provider, generated outputs, risk flags, and timestamps in a database table for auditability
  - Avoid logging secrets or full provider credentials

- [x] Add authenticated AI generation routes:
  - `GET /simulations/ai-builder` renders the scenario generation UI
  - `POST /api/simulations/ai/generate` generates drafts for selected channels
  - `POST /api/simulations/ai/save-draft` saves approved drafts to a campaign as simulation content
  - Return structured JSON errors for missing provider configuration, blocked content, and provider failures
  - Added authenticated routes in `SocialFish.py` for the AI Builder page, guarded generation API, and approved draft save API.
  - Added `ai_campaign_drafts` schema plus service helpers so saved AI drafts are persisted as campaign-linked simulation content without overwriting history.
  - Added route tests for builder rendering, local mock generation, draft saving, blocked content errors, disabled provider errors, and secret redaction.

- [x] Build the AI scenario builder UI:
  - Add a form for campaign, audience, channel selection, tone, difficulty, scenario objective, and training reminder
  - Show separate preview panes for email, SMS, and voice outputs
  - Show risk flags and safety notes next to generated drafts
  - Provide a save-to-campaign action that stores selected drafts without requiring CLI configuration

- [x] Integrate generated drafts with campaign detail pages:
  - Show saved AI drafts on the campaign detail page
  - Allow a campaign to have channel-specific content versions
  - Preserve draft history instead of overwriting prior generated content
  - Add UI links between campaign detail, AI Builder, and AI Settings
  - Completed by adding AI draft history to campaign detail data, rendering channel-specific saved versions with timestamps and review signals, deep-linking AI Builder to campaign details, and covering draft history in service and route tests.

- [x] Add structured feature documentation while implementing the UI:
  - Create `docs/features/ai-scenario-generation.md` with YAML front matter using type `reference`, tags for `ai`, `simulations`, and `training`
  - Include wiki-links to `[[Simulation-Campaigns]]`, `[[AI-Provider-Configuration]]`, and `[[Simulation-Metrics]]`
  - Document GUI configuration, supported provider shapes, safety guardrails, and local mock behavior

- [ ] Add automated coverage for AI generation:
  - Test local mock generation for email, SMS, and voice channels
  - Test disabled provider handling
  - Test risk flag persistence and draft history
  - Test that secrets are never returned by generation or settings APIs

- [ ] Run AI generation verification:
  - Run all new AI tests
  - Use automated HTTP requests to render `/simulations/ai-builder`, generate local mock content, save a draft to a campaign, and reload the campaign detail page
  - Fix any route, template, service, or schema failures discovered during verification
