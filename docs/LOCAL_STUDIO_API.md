# Local Studio API

`agos serve` is a **local development boundary**, not a production server or a deployment target. It binds to `127.0.0.1` only and exposes one deterministic, fixture-only Research-to-Publish demo for AGOS Studio.

## Two-process startup

Terminal 1, from `agos`:

```sh
PYTHONPATH=src python3 -m agos.cli serve --host 127.0.0.1 --port 8765 --data-dir .agos-local-api
```

Terminal 2, from `agos-studio`:

```sh
printf 'NEXT_PUBLIC_AGOS_LOCAL_API_BASE_URL=http://127.0.0.1:8765\n' > .env.local
npm run dev
```

Open `http://127.0.0.1:3000`. If the API is not configured or unavailable, Studio remains visibly in its static local demo mode.

## Deliberately narrow API

- `GET /v1/demo` — deterministic demo run state.
- `POST /v1/demo/review/approve` — explicit approval, body exactly `{}`.
- `POST /v1/demo/review/reject` — explicit rejection, body exactly `{}`.
- `POST /v1/demo/dry-run` — performs the existing fixture workflow using its dry-run publisher; it requires approval and body exactly `{}`.
- `GET /v1/demo/history` — append-only local activity feed.

The server accepts JSON bodies up to 8 KiB, validates request shape and content type, applies `no-store` and `nosniff` response headers, and allows browser origins only from `http://127.0.0.1:3000` and the same local API port. Activity is JSONL at `.agos-local-api/activity.jsonl`, with local filesystem permissions; treat it as local development data.

## Safety limitations

This surface has **no endpoint** for live HTTPS retrieval, arbitrary URLs, GitHub, credentials, remote publishing, arbitrary workflow submission, or remote binding. Every workflow execution uses supplied fixtures and the dry-run publisher; no artifact file or network write is created. It is a synchronous single-process developer tool, not authentication, tenant isolation, a sandbox, or a production service.
