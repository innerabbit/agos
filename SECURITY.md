# Security Policy

## Supported versions

AGOS is currently a pre-1.0 local vertical slice. Security fixes, if made, target the latest code in this repository; no long-term support policy is established.

## Report a vulnerability privately

**Do not open a public issue for a suspected vulnerability.** Use GitHub's private vulnerability reporting for this repository when it is available. If it is not enabled, contact the repository maintainer through a private contact channel listed on the repository or maintainer profile.

Include:

- A clear description of the issue and affected revision.
- Reproduction steps or a minimal proof of concept.
- Impact and any assumptions required to exploit it.
- Suggested remediation, if you have one.

Do not include real credentials, private data, or destructive payloads. Allow maintainers time to investigate before public disclosure.

## Security boundaries in the current implementation

AGOS is not a security sandbox or multi-tenant service. The current runtime is one Python process using local SQLite files. It has no HTTP API, credential system, or live remote publisher. The only bundled network path is an opt-in HTTPS research connector; the optional GitHub-shaped Markdown publisher remains an injected-client contract exercised with deterministic fakes in this repository.

The HTTPS connector is capability-scoped (`research.collect.https`) and requires pre-registered source IDs plus exact host allowlists. It permits HTTPS on port 443 only, resolves and rejects non-public/mixed DNS destinations, revalidates every redirect, pins the accepted address for TLS, limits request time/response size/redirects/content types, and has no credential, cookie, or caller-header API. It is not a general-purpose egress control or a sandbox.

Current controls include capability checks for registered tools, private/shared memory namespace checks, explicit approval routing, allow-listed publication targets, local SQLite persistence, and cooperative timeout/cancellation signals. These controls do **not** isolate arbitrary tool code, make side effects transactional, provide general egress enforcement, or provide distributed exactly-once execution.

When adding functionality, pay particular attention to capability escalation, untrusted tool execution, unsafe file paths, workflow inputs and provenance, SQLite file access, idempotency collisions, secrets in state/events/artifacts, and any future egress or external publishing behavior.
