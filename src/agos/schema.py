"""Serializable, versioned workflow definitions and structural validation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "agos.workflow/v1"
Json = None | bool | int | float | str | list["Json"] | dict[str, "Json"]

class ValidationError(ValueError): pass

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    def __post_init__(self):
        if self.max_attempts < 1 or self.backoff_seconds < 0: raise ValidationError("invalid retry policy")

@dataclass(frozen=True)
class Node:
    id: str
    tool: str
    agent_id: str
    depends_on: tuple[str, ...] = ()
    input: Json = None
    capability: str | None = None
    timeout_seconds: float | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency_key: str | None = None
    delegation_depth: int = 0
    delegation_cost: int = 0
    def __post_init__(self):
        if not self.id or not self.tool or not self.agent_id: raise ValidationError("node id, tool, and agent_id are required")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0: raise ValidationError("timeout_seconds must be positive")
        if self.delegation_depth < 0 or self.delegation_cost < 0: raise ValidationError("delegation bounds cannot be negative")

@dataclass(frozen=True)
class Route:
    """Select exactly one downstream branch when source output[key] == equals."""
    from_node: str
    key: str
    equals: Json
    when: dict[str, tuple[str, ...]]
    default: tuple[str, ...] = ()

@dataclass(frozen=True)
class Workflow:
    id: str
    nodes: tuple[Node, ...]
    routes: tuple[Route, ...] = ()
    schema_version: str = SCHEMA_VERSION
    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION: raise ValidationError(f"unsupported schema {self.schema_version}")
        if not self.id or not self.nodes: raise ValidationError("workflow id and nodes required")
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes): raise ValidationError("duplicate node id")
        for n in self.nodes:
            if n.id in n.depends_on: raise ValidationError(f"self dependency: {n.id}")
            unknown = set(n.depends_on) - ids
            if unknown: raise ValidationError(f"unknown dependencies for {n.id}: {sorted(unknown)}")
        for r in self.routes:
            if r.from_node not in ids: raise ValidationError(f"route source unknown: {r.from_node}")
            for targets in [*r.when.values(), r.default]:
                if set(targets) - ids: raise ValidationError("route target unknown")
        visiting, visited = set(), set()
        by_id = {n.id: n for n in self.nodes}
        def visit(node_id: str) -> None:
            if node_id in visiting: raise ValidationError(f"workflow contains cycle at {node_id}")
            if node_id not in visited:
                visiting.add(node_id)
                for dep in by_id[node_id].depends_on: visit(dep)
                visiting.remove(node_id); visited.add(node_id)
        for node in self.nodes: visit(node.id)
