# AGOS architecture

AGOS is a **single-process, local Python vertical slice** for workflow-first agent orchestration. It is intentionally not a distributed scheduler, service platform, security sandbox, or MCP implementation.

## Design constraints

- Workflows are serializable, versioned, and JSON-safe.
- Tools are invoked by registered name and only after a declared agent capability is checked.
- State, events, idempotency results, and durable memory use local SQLite implementations when persistence is needed.
- Unsupported backends are rejected in configuration rather than mapped to an implicit local fallback.
- The canonical workflow has no network client, credential flow, live source adapter, or remote publisher.

## Component map

```text
schema ──> manifests, providers, registry, memory
schema ──> storage <── runtime ──> registry/providers/memory
                              ^
                         execution <── CLI/examples
                              ^
                            config
```

| Module | Responsibility | Implemented boundary |
| --- | --- | --- |
| `schema.py` | `Workflow`, `Node`, `Route`, retry policy, and structural validation | Versioned `agos.workflow/v1` DAG definitions with JSON-safe values. |
| `manifests.py` | Agent metadata and execution limits | Agent lifecycle, capabilities, maximum delegation depth, and delegation budget. |
| `registry.py` | Tool registration and dispatch | Looks up an active agent and tool, then checks the tool capability against the agent manifest. |
| `runtime.py` | Workflow execution | Synchronous dependency scheduling, retries, conditional routes, events/checkpoints, and cooperative cancellation. |
| `storage.py` | Run persistence contract | In-memory interface shape plus `SQLiteStateStore` for local run state, events, and successful idempotency results. |
| `memory.py` | Workflow memory | In-memory and SQLite implementations with `private:<agent>` and `shared:<scope>` namespace checks. |
| `execution.py` | Submission/execution seam | `LocalExecutionBackend` directly delegates to `Runtime`; no queue/worker backend exists. |
| `providers.py` | Provider seam | `DeterministicProvider`, a local fixture provider only. |
| `research_to_publish.py` | Canonical example workflow | Fixture collection, deterministic draft, claim review, approval input, and local Markdown artifact creation. |
| `config.py` | Environment-derived local settings | Validates SQLite state/memory and local execution only. |

## Workflow and execution contract

A `Workflow` contains named nodes, dependency edges, and optional routes. Validation rejects unsupported schema versions, empty/duplicate node IDs, unknown dependencies or route targets, self-dependencies, and cycles.

At runtime:

1. A node becomes eligible when all of its dependencies have succeeded.
2. A node is skipped when a dependency fails, is skipped, or is cancelled.
3. Each eligible node consumes its declared delegation cost and must stay within configured depth and total-budget limits.
4. The registry verifies the invoking agent is active and owns the tool's capability.
5. The runtime executes the tool in a one-thread `ThreadPoolExecutor`, recording attempts and structured events.
6. Failed attempts may retry according to `RetryPolicy`. A timeout sets the shared cancellation event; tool code must cooperate with it because arbitrary Python code cannot be safely preempted.
7. A completed source node may select route targets using equality against an output key; non-selected route targets are skipped.
8. The runtime checkpoints state after each emitted event and finishes as `succeeded`, `failed`, or `cancelled`.

## Persistence and recovery semantics

`SQLiteStateStore` stores JSON-encoded run snapshots, ordered events, and successful idempotency results in a local SQLite database. A node with an idempotency key returns a remembered successful result without reinvoking its tool.

This is local durability, not a distributed recovery protocol:

- SQLite does not make tool side effects transactional.
- An idempotency key does not prove exactly-once delivery for effects outside the store.
- There are no leases, shared workers, multi-host coordination, durable cancellation signaling, or remote event transport.
- A SQLite file should reside on a local, access-controlled filesystem appropriate for its data.

`SQLiteMemoryStore` persists JSON values with the same namespace permission model as `InMemoryMemoryStore`. Private namespaces may only be accessed by the matching agent ID; shared namespaces are available to registered workflow participants by the store's current namespace rule. This is not tenant isolation or an authorization service.

## Capability boundary

An `AgentManifest` provides a lifecycle state and a frozen capability set. `CapabilityRegistry.invoke()` verifies that the agent exists, is active, that the tool exists, and that the tool capability is present in the manifest before calling the tool.

These are in-process application checks. Registered tools run as Python code in the same process; AGOS does not provide process isolation, resource sandboxing, egress enforcement, or secret management.

## Canonical local Research-to-Publish workflow

`build_workflow()` constructs five nodes:

```text
collect fixtures → synthesize deterministic draft → review provenance claims
                                                     ↓
                                            explicit approval decision
                                              ├─ approved → local Markdown artifact
                                              └─ rejected → publisher skipped
```

- `FixtureSourceAdapter` returns only caller-supplied, allow-listed `SourceFixture` objects. It cannot scrape or live-fetch.
- `DeterministicProvider` selects caller-provided local responses; it is not an LLM client.
- `ClaimReviewTool` rejects approval when a claim lacks a collected provenance source ID.
- `HumanApprovalGateTool` accepts an explicit `approved` or `rejected` input. The local MVP has no interactive approval service.
- `LocalMarkdownPublisherTool` writes a Markdown file under a caller-selected directory with exclusive file creation and reports `external_publish: false`.

The publisher's workflow node uses a stable idempotency key derived from the brief ID and slug. Re-running a successfully recorded publication skips reinvocation; direct file creation also avoids overwriting an existing artifact.

## Configuration and deployment boundary

`Settings.from_env()` recognizes only these backend values:

```text
AGOS_STATE_BACKEND=sqlite
AGOS_MEMORY_BACKEND=sqlite
AGOS_EXECUTION_BACKEND=local
```

Any other backend choice—including Postgres or a queue—is rejected with `ConfigurationError`. `AGOS_ENV` accepts `local`, `staging`, and `production` labels, but those labels do not provision an environment or alter the implemented local topology.

The files under `deploy/` build an image for the CLI/tests and provide optional local Compose commands. They do not expose an HTTP API or start workers. See [DEPLOYMENT.md](DEPLOYMENT.md) for production prerequisites that are **planned**, not implemented.

## Extension points and non-claims

`StateStore`, `MemoryStore`, `ExecutionBackend`, `Provider`, and the registry/tool protocol are seams for future adapters. Their presence does not mean such adapters exist.

Before adding a connector or remote publishing path, it should be separately registered, capability-scoped, explicitly authorized, and designed for credential handling, egress, idempotency, ambiguous outcomes, auditability, and target allow-listing. No such connector is included in this repository today.
