# Contributing to AGOS

Thanks for improving the local runtime. AGOS deliberately has a narrow scope: changes should preserve the distinction between what is implemented locally and what is only planned.

## Before you start

- Search existing issues and documentation for related work.
- For a behavior change, open an issue or start a discussion before investing in a large patch.
- Read [the architecture](ARCHITECTURE.md), [deployment boundaries](DEPLOYMENT.md), and [roadmap](docs/ROADMAP.md). Do not document an interface, backend, connector, or deployment mode that the repository does not implement.

## Local setup

AGOS requires Python 3.11 or newer and has no declared runtime dependencies.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m agos.cli research-to-publish-demo --output-dir /tmp/agos-demo
```

You can also use the supplied local test container:

```sh
docker compose -f deploy/compose.yaml run --rm agos-tests
```

The Compose file is local development tooling; it does not start a service.

## Contribution guidelines

### Code and tests

- Keep workflow definitions JSON-safe and validate structural changes at the schema boundary.
- Register tools by name and give each tool a specific capability. Do not bypass `CapabilityRegistry` checks.
- Preserve the local-only contract unless the change explicitly implements, tests, and documents a new boundary.
- Add or update focused tests in `tests/` for behavior changes. Cover rejection and failure paths where relevant.
- Avoid adding dependencies unless the value and maintenance impact are clear.

### Documentation

- Label present behavior as **implemented** and future work as **planned**.
- Do not imply AGOS has workers, a queue, live connectors, an HTTP API, or external publishing when it does not.
- Keep commands runnable from a fresh checkout; state prerequisites and expected local effects.

### Pull requests

Use the pull request template and include:

1. A concise problem statement and approach.
2. Tests run, including their result.
3. Documentation updates when behavior, boundaries, or commands change.
4. Explicit notes on persistence, capability, side-effect, or compatibility impact.

Keep changes focused. If a patch changes the security boundary or introduces external effects, explain the threat model and failure/retry behavior.

## Reporting bugs and security issues

Use the issue templates for reproducible, non-sensitive bugs and proposals. Do not post credentials, private data, or exploitable security details in public issues; see [SECURITY.md](SECURITY.md).

## Community standards

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
