# Original MVP release checklist

This checklist is for releasing the current **local vertical slice**. Checking
an item records local verification only; it does not authorize deployment or
claim production capability.

## Local release evidence

- [ ] Worktree/repository contains only intended release changes; no secrets,
  local databases, generated artifacts, or credentials are included.
- [ ] README, `project-status.json`, architecture, deployment, and test docs
  accurately describe the local-only scope and planned features.
- [ ] `PYTHONPATH=src python -m unittest discover -s tests -v` passes.
- [ ] `python -m compileall -q src tests examples` passes.
- [ ] Isolated package install smoke test passes (`pip install --no-deps .`,
  `agos --help`, and `agos research-to-publish-demo --dry-run`).
- [ ] `--reject` is confirmed to skip publishing and write no artifact.
- [ ] `--dry-run` is confirmed to execute the approved route without creating
  an artifact or making network/external publishing calls.
- [ ] A normal fixture demo is manually reviewed only if local artifact creation
  is intended; its output directory is controlled and contains no sensitive
  inputs.
- [ ] GitHub Actions CI has run successfully for the commit on Python 3.11,
  3.12, 3.13, and 3.14 after the repository is pushed.
- [ ] Release notes describe this as a local, synchronous, in-process reference
  implementation—never as a hosted service or production deployment.

## Explicitly out of scope for this MVP

Do not mark the following as complete from the checks above:

- production API, authentication, tenancy, queue/workers, leases, or
  distributed cancellation;
- Postgres/object storage, migrations, multi-host recovery, or exactly-once
  external side effects;
- sandboxing/isolation of registered Python tools;
- built-in credential discovery or a live GitHub publishing client;
- load, performance, penetration, dependency/SBOM, container, or disaster
  recovery testing.

## Production gate (not satisfied by this repository)

Any production proposal requires a separately approved design and evidence for
the controls listed in [DEPLOYMENT.md](../DEPLOYMENT.md): authenticated and
authorized admission, isolated tool runners, egress/SSRF controls, managed
durable storage/queue with backup and recovery exercises, secrets as references,
observability, dependency/image scanning, integration tests, incident response,
and rollback procedures. No release of this MVP should be presented as meeting
those requirements.
