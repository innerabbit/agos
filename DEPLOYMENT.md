# AGOS deployment plan

## Current truth
AGOS is a **local, single-process Python vertical slice**. Its only runnable
state/memory backends are SQLite and its only execution backend is synchronous
in-process execution. It has no HTTP API, queue, workers, object store, remote
telemetry exporter, leases, or distributed cancellation. The files under
`deploy/` are therefore local developer tooling—not a production deployment.

`project-status.json` is the monitor-facing source of truth. Anything listed in
`planned` is not implemented or deployable from this repository.

## Interfaces and boundaries

| Boundary | Current contract | Current implementation | Production replacement (planned) |
| --- | --- | --- | --- |
| Submission/API → execution | `ExecutionBackend.execute(workflow, run_id)` and `cancel()` | `LocalExecutionBackend` → `Runtime` | authenticated API submits immutable workflow/versioned request to queue |
| Execution → state | `StateStore` checkpoints JSON, appends ordered events, records successful idempotency results | `SQLiteStateStore` | Postgres repository with migrations and transaction boundaries |
| Execution → tools | `CapabilityRegistry.invoke()` checks manifest lifecycle and capability; `ToolContext` carries cancellation/deadline | in-process tools | isolated worker/tool runner with same contract |
| Execution → memory | `MemoryStore.get/put()` enforces private/shared namespace rules | in-memory or local SQLite | Postgres/approved memory service with tenant authorization |
| Artifact payloads | JSON-safe values only; no artifact store interface exists | inline JSON in SQLite | object storage adapter, checksums, retention policy |

There is no public wire/API contract yet. Do not publish or rely on an inferred
HTTP/JSON API until an explicit versioned API module and authentication model
are added.

## Environments

### Local/development
Copy `.env.example`; keep `AGOS_ENV=local`. Run tests with
`python -m unittest discover -s tests -v`. SQLite files must live on a local,
access-controlled filesystem. `docker compose -f deploy/compose.yaml run --rm
agos-tests` is optional local test tooling. It does not start a service.

### Staging (planned topology)
Use a separate cloud account/project and isolated network. A future API service
validates and persists submissions to Postgres; a separate worker deployment
claims jobs using queue visibility timeouts/leases; object storage holds large
artifacts; an OpenTelemetry collector receives traces/metrics/logs. Staging
must use synthetic data and production-equivalent migrations, backups, IAM, and
network policy. This repository currently rejects non-SQLite/non-local backend
configuration, so it cannot run that topology.

### Production (planned topology)
Run independently scalable API and worker workloads behind TLS ingress. Use
managed Postgres (HA, backups/PITR, encrypted connections), a managed durable
queue (DLQ, retry policy, leases), and private encrypted object storage
(lifecycle/retention). Tools execute in constrained, separately identity-bound
runners; they are not safely sandboxed by the current Python runtime. Keep DB,
queue, and bucket private to workloads; no public database endpoints.

## Configuration

`agos.config.Settings.from_env()` is the typed configuration entry point.
Implemented values are deliberately narrow:

- `AGOS_ENV`: `local`, `staging`, or `production` (label only)
- `AGOS_STATE_BACKEND=sqlite`, `AGOS_MEMORY_BACKEND=sqlite`,
  `AGOS_EXECUTION_BACKEND=local` (the only supported values)
- `AGOS_STATE_DB_PATH`, `AGOS_MEMORY_DB_PATH`
- `AGOS_TELEMETRY_MODE=off|logging` (configuration only; no exporter exists)

Secrets must be injected by the deployment platform as references/files and
never committed in `.env`, images, workflow manifests, event records, or logs.
A future production configuration should contain secret *references*, not
credential values.

### Agency beta hosting boundary (not deployed)

The repository now defines a **validated configuration boundary** for a future
hosted agency service. It does not provision infrastructure, install a Postgres
driver, connect to a database, expose a network listener, or authenticate real
users. `HostedAgencySettings.from_env()` fails closed unless all of the
following are supplied by the deployment platform:

- `DATABASE_URL`: a `postgres://` or `postgresql://` URL for the managed
  database. The bundled Postgres adapter deliberately raises before any driver
  import or connection attempt; migrations and a real repository are still
  required.
- `AGOS_SIGNING_SECRET`: a non-empty secret of at least 32 characters supplied
  through the platform's secret manager. Never commit it, add it to `.env`, or
  write it to audit records.
- `AGOS_ALLOWED_ORIGINS`: a comma-separated allowlist of explicit browser
  origins, with no wildcard. Use production HTTPS origins; loopback origins are
  accepted only for local integration development.

The agency domain has local JSONL persistence, hash-chained per-workspace audit
events, and explicit non-secret local fixture identities/memberships solely for
offline development. JSONL is not a hosted audit-retention or database
solution. Hosting remains incomplete until real authentication, Postgres
migrations/transactions, origin enforcement at an API boundary, key rotation,
and operational controls are implemented and reviewed.

## Telemetry and operations (planned)
Instrument API admission, queue latency, lease loss, workflow/node status,
retries, deadline/cancellation, database failures, and tool runner exits.
Propagate a run correlation ID but redact inputs/outputs by default. Define
alerting for failed runs, DLQ growth, unavailable workers, migration failures,
and backup failures. Current events are local SQLite records, not telemetry.

## Security requirements before production

- Authenticate API callers and authorize tenant/workflow/tool capabilities.
- Validate workflow schema, size, versions, and resource limits at admission.
- Use least-privilege workload identities, TLS, encrypted storage, secret
  rotation, audit retention, and dependency/image scanning.
- Isolate untrusted tools in resource-limited runners; cooperative Python
  timeouts are **not** a security boundary.
- Threat-model idempotency keys, replay, tenant isolation, SSRF/egress, and
  artifact access before enabling external tool execution.

## CI/CD, migrations, rollback (planned process)

CI should run unit tests, package build, static checks, SBOM/dependency and
container scans, then integration tests against ephemeral Postgres/queue/object
storage adapters once implemented. Promote immutable image digests through
staging before production. Apply forward-only, reviewed database migrations as
a separately observable release step after backup/PITR verification. Use
expand/contract schema changes and compatible application releases. Roll back
application image/config first; do not auto-down-migrate data. Restore only
through an approved, rehearsed PITR process. Queue consumers need explicit
pause/drain and idempotency verification during rollback.
