"""Bounded Markdown publication adapters.

Adapters are dependency-injected and contain no HTTP client or credential lookup.
The GitHub-shaped adapter is therefore testable with a deterministic fake and cannot
perform network I/O unless an application explicitly injects a client that does so.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Protocol

from .schema import Json

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validate_repository(repository: str) -> str:
    if not _REPOSITORY.fullmatch(repository) or any(part in {".", ".."} for part in repository.split("/")):
        raise ValueError("repository must be a canonical owner/repository name")
    return repository


def validate_markdown_path(path: str) -> str:
    candidate = PurePosixPath(path)
    canonical = candidate.as_posix()
    if (
        not path
        or path != canonical
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.suffix.lower() not in (".md", ".markdown")
    ):
        raise ValueError("path must be a canonical relative Markdown path without traversal")
    return canonical


@dataclass(frozen=True)
class PublicationRequest:
    repository: str
    path: str
    content: str
    provenance: tuple[dict[str, str], ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_repository(self.repository)
        validate_markdown_path(self.path)
        if not self.idempotency_key:
            raise ValueError("publication idempotency key is required")

    @property
    def provenance_digest(self) -> str:
        """Stable digest over complete provenance records, including fixture content."""
        import json

        canonical = json.dumps(self.provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MarkdownPublisher(Protocol):
    """Effect boundary: implementations return JSON-safe publication receipts."""

    def publish(self, request: PublicationRequest) -> dict[str, Json]: ...


class CredentialSource(Protocol):
    """Injected credential reference resolver; values are never stored by AGOS."""

    def credential_for(self, repository: str) -> str: ...


class GitHubContentsClient(Protocol):
    """Injected client contract. AGOS supplies no implementation and makes no HTTP calls."""

    def put_markdown(self, repository: str, path: str, content: str, credential: str, idempotency_key: str) -> dict[str, str]: ...


class DryRunMarkdownPublisher:
    """Local, no-effect adapter used for planning and deterministic tests."""

    def publish(self, request: PublicationRequest) -> dict[str, Json]:
        return {
            "target": "dry-run",
            "repository": request.repository,
            "path": request.path,
            "created": False,
            "external_publish": False,
            "provenance_digest": request.provenance_digest,
        }


class LocalMarkdownPublisher:
    """Local-only Markdown artifact adapter with exclusive create semantics."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)

    def publish(self, request: PublicationRequest) -> dict[str, Json]:
        # The request path is validated as POSIX and then confined below output_dir.
        destination = self.output_dir.joinpath(*PurePosixPath(request.path).parts)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("x", encoding="utf-8") as artifact:
                artifact.write(request.content)
            created = True
        except FileExistsError:
            created = False
        return {
            "target": "local",
            "repository": request.repository,
            "path": str(destination),
            "created": created,
            "external_publish": False,
            "provenance_digest": request.provenance_digest,
        }


class GitHubMarkdownPublisher:
    """External-effect adapter requiring injected allowlist, client, and credential source."""

    def __init__(self, client: GitHubContentsClient, credentials: CredentialSource, allowed_repositories: frozenset[str]) -> None:
        self.client = client
        self.credentials = credentials
        self.allowed_repositories = frozenset(validate_repository(item) for item in allowed_repositories)

    def publish(self, request: PublicationRequest) -> dict[str, Json]:
        if request.repository not in self.allowed_repositories:
            raise PermissionError("repository is not allow-listed for GitHub publication")
        credential = self.credentials.credential_for(request.repository)
        if not credential:
            raise PermissionError("credential source returned no credential")
        receipt = self.client.put_markdown(request.repository, request.path, request.content, credential, request.idempotency_key)
        return {
            "target": "github",
            "repository": request.repository,
            "path": request.path,
            "created": receipt.get("created") == "true",
            "external_publish": True,
            "receipt_id": receipt.get("id", ""),
            "provenance_digest": request.provenance_digest,
        }
