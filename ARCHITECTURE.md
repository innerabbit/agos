# AGOS architecture

AGOS is a **single-process, local Python vertical slice** for workflow-first agent orchestration. It is intentionally not a distributed scheduler, service platform, security sandbox, or MCP implementation.

## Design constraints

- Workflows are serializable, versioned, and JSON-safe.
- Tools are invoked by registered name and only after a declared agent capability is checked.
- State, events, idempotency results, and durable memory use local SQLite implementations when persistence is needed.
- Unsupported backends are rejected in configuration rather than mapped to an implicit local fallback.
- The canonical workflow has no network client, credential lookup, or live source adapter. An opt-in GitHub-shaped Markdown publisher contract is dependency-injected and is exercised only with deterministic fakes.

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
| `research_to_publish.py` | Canonical example workflow | Fixture-default collection, deterministic draft, claim review, approval input, local Markdown artifacts, plus separately registered opt-in HTTPS and approved GitHub Markdown routes. |
| `sources.py` | Source connector contract | Strict fixture/fake connectors plus an opt-in, credential-free HTTPS connector using exact host/source allowlists, public-IP validation, redirect revalidation, DNS-pinned TLS, and bounded responses. |
| `publishing.py` | Markdown publication boundary | Request validation, dry-run/local adapters, and injected GitHub client/credential contracts. |
| `config.py` | Environment-derived local settings | Validates SQLite state/memory and local execution only. |
| `api.py` | Local demo HTTP boundary | Stdlib localhost-only API for fixed demo state, explicit review actions, dry-run receipts, and server-lifetime append-only history. |

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

- `FixtureSourceAdapter` returns only caller-supplied, allow-listed `SourceFixture` objects. It cannot scrape or live-fetch; this remains the default demo path.
- `HTTPSResearchConnector` is separately registered through `register_https_workflow()` and requires the distinct `research.collect.https` capability. It accepts only pre-registered source IDs and exact HTTPS/443 hosts, resolves every initial and redirect destination, rejects non-public or mixed DNS results, pins the approved address for TLS, and caps time, response bytes, redirects, and content types. It sends no credentials, cookies, or caller headers; provenance records the normalized final URL, UTC timestamp, and SHA-256 digest. Its transport and resolver are injectable for deterministic, offline tests.
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

The files under `deploy/` build an image for the CLI/tests and provide optional local Compose commands. They do not expose an HTTP API or start workers. The `agos serve` CLI command is a separate, direct localhost-only development server, not a deployment topology. See [DEPLOYMENT.md](DEPLOYMENT.md) for production prerequisites that are **planned**, not implemented.

## Local HTTP demo boundary

`agos serve` binds to `127.0.0.1:8765` by default and refuses non-loopback bind addresses before it opens a socket. It exposes only fixed deterministic demo data: `GET /healthz`, `GET /v1/demo`, `POST /v1/demo/review/approve`, `POST /v1/demo/review/reject`, `POST /v1/demo/dry-run`, and `GET /v1/demo/history`. Review actions require an exact empty JSON object; dry-run requires a preceding explicit approval.

The API constructs its own fixture and deterministic-provider inputs. It accepts no credentials, URLs, output directories, arbitrary workflow definitions, or publishing options. Dry-run registers only `DryRunMarkdownPublisher`, so it writes no artifact and has no network or external-publication effect. With `--data-dir`, ordered activity is appended locally as JSONL and is retained across restarts; it remains a local development feed, not an audit-retention system.

The handler caps request bodies at 8 KiB, requires JSON for POST actions, rejects non-empty/unknown schemas, avoids request logging, sends `nosniff` and no-store headers, and applies CORS only to `http://127.0.0.1:3000` (Studio) or the same API port, without credentials. Originless same-machine CLI requests remain supported; non-loopback browser origins are rejected.

## Extension points and non-claims

`StateStore`, `MemoryStore`, `ExecutionBackend`, `Provider`, and the registry/tool protocol are seams for future adapters. Their presence does not mean such adapters exist.

The GitHub-shaped publisher is separately registered and capability-scoped (`publish.github_markdown`). It requires a human-approved route, allow-listed `owner/repository`, traversal-safe Markdown path, successful runtime idempotency key, provenance digest, injected credential source, and injected contents client. AGOS never reads or stores a token and ships no HTTP client, so this repository cannot publish remotely by default. The fake integration tests are the only connector execution included here. A production connector still needs egress enforcement, ambiguous-outcome recovery, audit retention, and a real secret-reference design.
