# AGOS roadmap

This roadmap separates the current local vertical slice from possible future work. A roadmap entry is not a promise, release date, or available feature.

## Implemented in this repository

- Serializable, validated workflow DAGs with dependencies and conditional routes.
- Synchronous single-process execution with retries, cooperative timeout/cancellation behavior, delegation bounds, and local idempotency-result reuse.
- Capability-scoped tool dispatch and agent lifecycle checks.
- Local SQLite checkpoints/events and local SQLite or in-memory memory stores.
- Fixture-only Research-to-Publish demo with provenance review, explicit approval input, and idempotent local Markdown output.
- Local CLI utilities and optional Docker Compose test/event tooling.

## Planned: hardening foundations

- Signed manifests and a workflow migration/version policy.
- Secret references rather than workflow-embedded credentials.
- Audit retention and a clearer data-retention model.
- Process isolation for untrusted tools.

## Planned: scale and service boundaries

- A versioned, authenticated submission/API boundary.
- Postgres state and memory adapters with migrations.
- Queue/worker execution with leases and a defined distributed cancellation model.
- Object storage for large artifacts.
- Remote telemetry export and operational instrumentation.

## Planned: opt-in external effects

- Separately registered adapters for Notion, X, WordPress, or other publishing targets.
- Explicit egress controls, target allow-lists, secret references, idempotency/retry behavior, audit events, and a final human approval tied to the draft and target.

None of these integrations exist today. The implemented canonical workflow accepts deterministic fixtures only and publishes only a local Markdown file.

## Non-goals of the current vertical slice

The current runtime is not a distributed scheduler, hosted multi-tenant service, transaction system, exactly-once delivery mechanism, or security sandbox. See [Architecture](../ARCHITECTURE.md) and [ADR 0001](adr/0001-local-first-deployment-boundaries.md) for the current boundaries.
