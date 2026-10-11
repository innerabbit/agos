# ADR 0001: Keep the vertical slice local-first and reject unimplemented backends

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
The runtime presently has local SQLite persistence and one synchronous Python
process. Configuring names such as Postgres or queue without implementations
would create a false production claim and can cause unsafe fallback behavior.

## Decision
Expose `StateStore` and `ExecutionBackend` protocols while retaining only
`SQLiteStateStore` and `LocalExecutionBackend`. `Settings` accepts only their
implemented values and raises `ConfigurationError` for other backend selections.
Documentation describes the intended staging/production topology as planned.

## Consequences
Adapters can be developed against stable boundaries later. Deployers cannot
mistake a configuration flag for a distributed feature. Production deployment
remains blocked until adapters, migrations, authentication, worker lease
semantics, telemetry, and security controls are implemented and tested.
