# Getting started with AGOS

AGOS is a local Python reference runtime. This guide runs the implemented fixture-only demo and shows how to inspect local state; it does not deploy a service or contact external systems.

## Requirements

- Python 3.11 or newer.
- A checkout of this repository.

The project declares no runtime dependencies. To use the package from a checkout, set `PYTHONPATH=src`; alternatively install it into an isolated environment with `python3 -m pip install .`.

## Verify the checkout

From the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests cover workflow validation, retries, routes, capabilities, delegation bounds, local memory/state, the approved artifact path, rejection, and invalid provenance claims.

## Run the canonical demo

```sh
PYTHONPATH=src python3 -m agos.cli research-to-publish-demo --output-dir /tmp/agos-demo
```

Expected behavior:

- The command prints a successful run and a successful `publish` node.
- It creates `/tmp/agos-demo/local-workflow-demo.md`.
- The Markdown contains fixture provenance and states that no external publishing occurred.

The demo uses one supplied `SourceFixture` and `DeterministicProvider`; it never fetches a URL or calls an LLM.

Run the rejected path:

```sh
PYTHONPATH=src python3 -m agos.cli research-to-publish-demo --reject --output-dir /tmp/agos-demo
```

Here the approval decision is `rejected`, the `publish` node is skipped, and no Markdown artifact is created.

## Use a file-backed local state store

The demo CLI uses an in-memory state store. To retain run events and checkpoints, construct `Runtime` with `SQLiteStateStore` pointed at a local file in your application code. Then inspect events with:

```sh
PYTHONPATH=src python3 -m agos.cli events ./data/agos-state.db RUN_ID
```

`RUN_ID` is the ID passed to `Runtime.run()`. State files are local SQLite data; protect them according to the sensitivity of workflow inputs and outputs.

## Configure supported local settings

Copy `.env.example` or set the values in your environment. The only implemented backends are:

```text
AGOS_STATE_BACKEND=sqlite
AGOS_MEMORY_BACKEND=sqlite
AGOS_EXECUTION_BACKEND=local
```

`Settings.from_env()` rejects unsupported backend values such as Postgres or queue rather than silently falling back. `AGOS_ENV` accepts `local`, `staging`, or `production` as labels, but changing that label does not create a staging or production topology.

## Next steps

- Read [Architecture](../ARCHITECTURE.md) for contracts and limitations.
- Review [Deployment boundaries](../DEPLOYMENT.md) before treating local tooling as deployable infrastructure.
- See [Roadmap](ROADMAP.md) for work that is planned rather than implemented.
