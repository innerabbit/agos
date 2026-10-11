"""Local-only HTTP API for the deterministic AGOS demo.

The server intentionally exposes no source retrieval, publisher, credential, or
arbitrary workflow endpoints. It is a localhost-bound demonstration surface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from .memory import InMemoryMemoryStore
from .providers import DeterministicProvider
from .registry import CapabilityRegistry
from .research_to_publish import SourceFixture, build_workflow, register_local_workflow
from .runtime import Runtime
from .storage import SQLiteStateStore

MAX_BODY_BYTES = 8 * 1024
LOOPBACK_HOSTS = frozenset({"127.0.0.1"})


class APIError(ValueError):
    """A safe client-facing validation error."""

    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class HistoryEntry:
    sequence: int
    event: str
    review: str
    result: dict[str, Any] | None = None


class DemoService:
    """Append-only local demo state; all workflow runs use dry-run publishing."""

    def __init__(self, history_path: str | Path | None = None) -> None:
        self._review = "pending"
        self._history: list[HistoryEntry] = []
        self._sequence = 0
        self._lock = RLock()
        self._history_path = Path(history_path) if history_path is not None else None
        if self._history_path is not None:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            self._history_path.touch(mode=0o600, exist_ok=True)
            for line in self._history_path.read_text(encoding="utf-8").splitlines():
                entry = HistoryEntry(**json.loads(line))
                self._history.append(entry)
                self._sequence = max(self._sequence, entry.sequence)
            if self._history:
                self._review = self._history[-1].review
        self._append("demo.started")

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "local-demo",
                "review": self._review,
                "dry_run_only": True,
                "history_count": len(self._history),
            }

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(entry) for entry in self._history]

    def decide(self, decision: str) -> dict[str, Any]:
        if decision not in ("approved", "rejected"):
            raise APIError(HTTPStatus.BAD_REQUEST, "decision must be approved or rejected")
        with self._lock:
            self._review = decision
            self._append(f"review.{decision}")
            return self.state()

    def dry_run(self) -> dict[str, Any]:
        with self._lock:
            if self._review != "approved":
                raise APIError(HTTPStatus.CONFLICT, "dry-run requires explicit review approval")
            result = self._run_dry_workflow()
            receipt = {
                "status": result.status,
                "publish_status": result.nodes["publish"].status,
                "publish": result.nodes["publish"].output,
                "external_publish": False,
            }
            self._append("dry_run.completed", receipt)
            return receipt

    def _append(self, event: str, result: dict[str, Any] | None = None) -> None:
        self._sequence += 1
        entry = HistoryEntry(self._sequence, event, self._review, result)
        self._history.append(entry)
        if self._history_path is not None:
            with self._history_path.open("a", encoding="utf-8") as history_file:
                history_file.write(json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")) + "\n")

    @staticmethod
    def _run_dry_workflow():
        fixtures = {
            "dag-guide": SourceFixture(
                "dag-guide", "DAG guide", "fixture://dag-guide",
                "2026-10-11T00:00:00Z", "DAGs make dependencies explicit.",
            )
        }
        brief = {
            "id": "http-demo-1", "title": "A local HTTP API demo",
            "slug": "local-http-api-demo", "provider_prompt": "http-demo-draft",
        }
        provider = DeterministicProvider({"http-demo-draft": {
            "markdown": "Dependencies are explicit [dag-guide].",
            "claims": [{"text": "Dependencies are explicit.", "source_id": "dag-guide"}],
        }})
        registry = CapabilityRegistry()
        register_local_workflow(
            registry, InMemoryMemoryStore(), fixtures, provider, ".", dry_run=True,
        )
        return Runtime(registry, SQLiteStateStore(":memory:")).run(
            build_workflow(brief, ["dag-guide"], "approved"), "http-demo-dry-run",
        )


def _allowed_origins(port: int) -> set[str]:
    # Studio's Next development server is the only browser peer supported.
    return {f"http://{host}:{allowed_port}" for host in LOOPBACK_HOSTS for allowed_port in (3000, port)}


def make_handler(service: DemoService, port: int):
    """Create a handler with a fixed localhost-only CORS policy."""
    allowed_origins = _allowed_origins(port)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AGOSLocalAPI/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            # Do not log request paths, bodies, or headers; this API accepts no secrets.
            return

        def do_GET(self) -> None:
            if not self._origin_is_allowed():
                return
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._send_json(HTTPStatus.OK, {"status": "ok", "local_only": True})
            elif path == "/v1/demo":
                self._send_json(HTTPStatus.OK, service.state())
            elif path == "/v1/demo/history":
                self._send_json(HTTPStatus.OK, {"history": service.history()})
            else:
                self._error(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            if not self._origin_is_allowed():
                return
            try:
                self._read_empty_json_object()
                path = urlsplit(self.path).path
                if path == "/v1/demo/review/approve":
                    self._send_json(HTTPStatus.OK, service.decide("approved"))
                elif path == "/v1/demo/review/reject":
                    self._send_json(HTTPStatus.OK, service.decide("rejected"))
                elif path == "/v1/demo/dry-run":
                    self._send_json(HTTPStatus.OK, service.dry_run())
                else:
                    self._error(HTTPStatus.NOT_FOUND, "not found")
            except APIError as exc:
                self._error(exc.status, exc.message)

        def do_OPTIONS(self) -> None:
            origin = self.headers.get("Origin")
            requested_method = self.headers.get("Access-Control-Request-Method")
            requested_headers = self.headers.get("Access-Control-Request-Headers", "").lower()
            if origin not in allowed_origins or requested_method not in {"GET", "POST"}:
                self._error(HTTPStatus.FORBIDDEN, "origin or method is not allowed")
                return
            if requested_headers and requested_headers != "content-type":
                self._error(HTTPStatus.FORBIDDEN, "request headers are not allowed")
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _origin_is_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            if origin in allowed_origins:
                return True
            self._error(HTTPStatus.FORBIDDEN, "origin is not allowed")
            return False

        def _read_empty_json_object(self) -> None:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise APIError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None or not raw_length.isdigit():
                raise APIError(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
            length = int(raw_length)
            if length > MAX_BODY_BYTES:
                raise APIError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body is too large")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise APIError(HTTPStatus.BAD_REQUEST, "body must be valid UTF-8 JSON") from None
            if payload != {}:
                raise APIError(HTTPStatus.BAD_REQUEST, "body must be an empty JSON object")

        def _cors(self, origin: str | None) -> None:
            if origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self._cors(self.headers.get("Origin"))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._send_json(status, {"error": message})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, history_path: str | Path | None = None) -> None:
    """Run the local API. Network hosts are refused before binding."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError("AGOS HTTP API may bind only to localhost loopback addresses")
    service = DemoService(history_path)
    with ThreadingHTTPServer((host, port), make_handler(service, port)) as server:
        server.serve_forever()
