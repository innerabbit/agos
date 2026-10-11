# Testing and evaluation

## What this suite verifies locally

AGOS is a local, single-process reference implementation. The test suite is a
set of deterministic unit and integration-style tests using in-memory SQLite,
fixture sources, fake HTTPS transports, and fake GitHub clients. It verifies:

- workflow validation, capability checks, retries, routing, cancellation, and
  idempotency bookkeeping;
- local SQLite state and memory boundaries;
- fixture-default Research-to-Publish approval and rejection routes;
- HTTPS connector policy enforcement without live network access; and
- the dependency-injected GitHub publishing contract without credentials or a
  real GitHub request.

A passing suite does **not** demonstrate production readiness, process/tool
isolation, multi-host durability, live-provider compatibility, real GitHub
publishing, performance under load, or a security assessment.

## Supported local validation commands

Run these from the repository root on Python 3.11 or newer. CI continuously
exercises Python 3.11, 3.12, 3.13, and 3.14; the project metadata requires
`>=3.11`.

```sh
# deterministic unittest suite
PYTHONPATH=src python -m unittest discover -s tests -v

# syntax/bytecode compilation of maintained Python surfaces
python -m compileall -q src tests examples

# source-checkout demo: approved route writes a local artifact
PYTHONPATH=src python -m agos.cli research-to-publish-demo --output-dir /tmp/agos-demo

# safe paths: neither writes an artifact nor performs network/external publishing
PYTHONPATH=src python -m agos.cli research-to-publish-demo --reject --output-dir /tmp/agos-demo
PYTHONPATH=src python -m agos.cli research-to-publish-demo --dry-run --output-dir /tmp/agos-demo
```

`--reject` tests the workflow's rejection branch, so publishing is skipped.
`--dry-run` tests the approved publishing branch against the no-effect
`DryRunMarkdownPublisher`; it returns a `target: "dry-run"` receipt and creates
no file. Both use fixture inputs and a deterministic provider.

## Install smoke test

Run the installed console script in an isolated virtual environment:

```sh
smoke_dir="$(mktemp -d)"
python -m venv "$smoke_dir/venv"
"$smoke_dir/venv/bin/python" -m pip install --no-deps .
"$smoke_dir/venv/bin/agos" --help
"$smoke_dir/venv/bin/agos" research-to-publish-demo --dry-run --output-dir "$smoke_dir/output"
test ! -e "$smoke_dir/output/local-workflow-demo.md"
rm -rf "$smoke_dir"
```

The CI workflow runs the unittest suite, compile check, and this install smoke
test on every push and pull request. It uses read-only repository permissions
and no credentials.

## Evaluation limits

Do not use this suite as evidence that planned production features exist.
Before enabling a networked or production boundary, perform the requirements in
[DEPLOYMENT.md](../DEPLOYMENT.md), including architecture, security, operational,
integration, and recovery validation appropriate to that boundary.
