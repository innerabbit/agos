# AGOS roadmap

This roadmap separates the current local vertical slice from possible future work. A roadmap entry is not a promise, release date, or available feature.

## Implemented in this repository

- Serializable, validated workflow DAGs with dependencies and conditional routes.
- Synchronous single-process execution with retries, cooperative timeout/cancellation behavior, delegation bounds, and local idempotency-result reuse.
- Capability-scoped tool dispatch and agent lifecycle checks.
- Local SQLite checkpoints/events and local SQLite or in-memory memory stores.
- Fixture/fake-default Research-to-Publish demo with strict source allowlists, provenance review, explicit approval input, and idempotent local Markdown output. An opt-in `research.collect.https` source uses pre-registered IDs, exact HTTPS host allowlists, public-IP and redirect validation, TLS-pinned stdlib transport, response/type caps, and digest provenance; tests inject fakes and make no live web requests. The injected GitHub Markdown adapter is also fake-tested.
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

- Production implementations for Notion, X, WordPress, or other publishing targets.
- A production GitHub client with explicit egress controls, secret references, ambiguous-outcome recovery, audit retention, and an approval record cryptographically bound to draft and target.

The implemented canonical workflow keeps deterministic fixtures as its default and publishes locally. HTTPS retrieval is separately opt-in and has no credential behavior; the connector uses a bounded stdlib transport while tests inject fakes. The optional GitHub-shaped adapter is a dependency-injected contract with no bundled credential source; its tests use fakes only.

## Non-goals of the current vertical slice

The current runtime is not a distributed scheduler, hosted multi-tenant service, transaction system, exactly-once delivery mechanism, or security sandbox. See [Architecture](../ARCHITECTURE.md) and [ADR 0001](adr/0001-local-first-deployment-boundaries.md) for the current boundaries.
