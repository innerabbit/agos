from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class AgentManifest:
    id: str
    version: str
    permissions: frozenset[str]
    lifecycle: Literal["active", "suspended", "retired"] = "active"
    def __post_init__(self):
        if not self.id or not self.version: raise ValueError("agent id/version required")

@dataclass(frozen=True)
class ExecutionLimits:
    max_delegation_depth: int = 2
    delegation_budget: int = 10
    def __post_init__(self):
        if self.max_delegation_depth < 0 or self.delegation_budget < 0: raise ValueError("limits must be non-negative")

@dataclass
class DelegationBudget:
    limits: ExecutionLimits
    spent: int = 0
    def consume(self, depth: int, cost: int) -> None:
        if depth > self.limits.max_delegation_depth: raise PermissionError("delegation depth limit exceeded")
        if self.spent + cost > self.limits.delegation_budget: raise PermissionError("delegation budget exhausted")
        self.spent += cost
