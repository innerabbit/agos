"""Hosted-agency domain boundary, intentionally local-fixture first.

No database driver, HTTP client, credential lookup, or publishing integration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol

Role = Literal["owner", "admin", "member", "viewer"]
_MUTATION_ROLES = frozenset({"owner", "admin", "member"})
_READ_ROLES = frozenset({"owner", "admin", "member", "viewer"})


class AgencyError(ValueError):
    """Safe domain error; callers must not turn it into an authorization bypass."""


class AuthorizationError(AgencyError):
    pass


class PersistenceUnavailable(AgencyError):
    pass


@dataclass(frozen=True)
class DevelopmentIdentity:
    """Non-secret identity used only by the explicit local fixture mode."""
    id: str
    display_name: str


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str


@dataclass(frozen=True)
class WorkspaceMembership:
    workspace_id: str
    identity_id: str
    role: Role


@dataclass(frozen=True)
class AuditEvent:
    workspace_id: str
    sequence: int
    event: str
    actor_id: str
    payload: dict[str, Any] | None
    previous_hash: str
    event_hash: str

    def public(self) -> dict[str, Any]:
        return asdict(self)


class AgencyStore(Protocol):
    """Append-only, workspace-scoped audit persistence contract."""
    def append(self, workspace_id: str, event: str, actor_id: str,
               payload: dict[str, Any] | None = None) -> AuditEvent: ...
    def events(self, workspace_id: str) -> list[AuditEvent]: ...


def _event_hash(workspace_id: str, sequence: int, event: str, actor_id: str,
                payload: dict[str, Any] | None, previous_hash: str) -> str:
    encoded = json.dumps({"workspace_id": workspace_id, "sequence": sequence,
        "event": event, "actor_id": actor_id, "payload": payload,
        "previous_hash": previous_hash}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class JsonlAgencyStore:
    """Local JSONL audit log with per-workspace sequence and hash-chain checks."""
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._events: dict[str, list[AuditEvent]] = {}
        self._lock = RLock()
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch(mode=0o600, exist_ok=True)
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                audit_event = AuditEvent(**json.loads(line))
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersistenceUnavailable(f"invalid local audit log at line {number}") from exc
            events = self._events.setdefault(audit_event.workspace_id, [])
            expected_sequence = len(events) + 1
            previous_hash = events[-1].event_hash if events else ""
            expected_hash = _event_hash(audit_event.workspace_id, audit_event.sequence, audit_event.event,
                audit_event.actor_id, audit_event.payload, audit_event.previous_hash)
            if (audit_event.sequence != expected_sequence or audit_event.previous_hash != previous_hash
                    or audit_event.event_hash != expected_hash):
                raise PersistenceUnavailable(f"tampered or non-contiguous local audit log at line {number}")
            events.append(audit_event)

    def append(self, workspace_id: str, event: str, actor_id: str,
               payload: dict[str, Any] | None = None) -> AuditEvent:
        frozen_payload = json.loads(json.dumps(payload, sort_keys=True)) if payload is not None else None
        with self._lock:
            events = self._events.setdefault(workspace_id, [])
            sequence = len(events) + 1
            previous_hash = events[-1].event_hash if events else ""
            audit_event = AuditEvent(workspace_id, sequence, event, actor_id, frozen_payload, previous_hash,
                _event_hash(workspace_id, sequence, event, actor_id, frozen_payload, previous_hash))
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(asdict(audit_event), sort_keys=True, separators=(",", ":")) + "\n")
                    output.flush()
            events.append(audit_event)
            return audit_event

    def events(self, workspace_id: str) -> list[AuditEvent]:
        with self._lock:
            return [AuditEvent(**json.loads(json.dumps(asdict(event)))) for event in self._events.get(workspace_id, [])]


class PostgresAgencyStore:
    """Unconfigured Postgres boundary: no driver import or connection attempt."""
    def __init__(self, database_url: str | None) -> None:
        if not database_url or not database_url.strip():
            raise PersistenceUnavailable("DATABASE_URL is required for the postgres persistence boundary")
        self.database_url = database_url

    def _unavailable(self) -> None:
        raise PersistenceUnavailable("Postgres persistence is intentionally unconfigured; no database connection was attempted")

    def append(self, workspace_id: str, event: str, actor_id: str,
               payload: dict[str, Any] | None = None) -> AuditEvent:
        self._unavailable()

    def events(self, workspace_id: str) -> list[AuditEvent]:
        self._unavailable()


@dataclass(frozen=True)
class LocalAgencyFixtures:
    """Explicit local-only identities and memberships; never production auth."""
    identities: tuple[DevelopmentIdentity, ...]
    workspaces: tuple[Workspace, ...]
    memberships: tuple[WorkspaceMembership, ...]

    @classmethod
    def default(cls) -> "LocalAgencyFixtures":
        return cls(
            identities=(DevelopmentIdentity("dev-alice", "Alice (local owner)"),
                        DevelopmentIdentity("dev-bob", "Bob (local member)"),
                        DevelopmentIdentity("dev-viewer", "Viewer (local read-only)")),
            workspaces=(Workspace("local-studio", "Local Studio"), Workspace("local-lab", "Local Lab")),
            memberships=(WorkspaceMembership("local-studio", "dev-alice", "owner"),
                         WorkspaceMembership("local-studio", "dev-bob", "member"),
                         WorkspaceMembership("local-lab", "dev-alice", "admin"),
                         WorkspaceMembership("local-lab", "dev-viewer", "viewer")),
        )


class AgencyService:
    """Workspace-isolated service used only by the local fixture boundary."""
    def __init__(self, store: AgencyStore, fixtures: LocalAgencyFixtures | None = None) -> None:
        self._store = store
        self._fixtures = fixtures or LocalAgencyFixtures.default()
        self._workspaces = {workspace.id: workspace for workspace in self._fixtures.workspaces}
        self._identities = {identity.id: identity for identity in self._fixtures.identities}
        self._memberships = {(membership.workspace_id, membership.identity_id): membership
                             for membership in self._fixtures.memberships}

    def _membership(self, identity_id: str, workspace_id: str, allowed: frozenset[str]) -> WorkspaceMembership:
        if identity_id not in self._identities:
            raise AuthorizationError("unknown local development identity")
        membership = self._memberships.get((workspace_id, identity_id))
        if workspace_id not in self._workspaces or membership is None or membership.role not in allowed:
            raise AuthorizationError("workspace access is not allowed")
        return membership

    def workspaces_for(self, identity_id: str) -> list[dict[str, str]]:
        if identity_id not in self._identities:
            raise AuthorizationError("unknown local development identity")
        return [{"id": workspace.id, "name": workspace.name, "role": membership.role}
                for workspace in self._fixtures.workspaces
                if (membership := self._memberships.get((workspace.id, identity_id))) is not None]

    def history(self, identity_id: str, workspace_id: str) -> list[dict[str, Any]]:
        self._membership(identity_id, workspace_id, _READ_ROLES)
        return [event.public() for event in self._store.events(workspace_id)]

    def record_review(self, identity_id: str, workspace_id: str, decision: str) -> dict[str, Any]:
        self._membership(identity_id, workspace_id, _MUTATION_ROLES)
        if decision not in {"approved", "rejected"}:
            raise AgencyError("decision must be approved or rejected")
        return self._store.append(workspace_id, f"review.{decision}", identity_id,
                                  {"decision": decision}).public()
