"""Execution boundary for the local runtime.

Queue, worker-lease, and remote execution implementations are intentionally not
provided.  Callers depend on this protocol so those can be added explicitly.
"""
from __future__ import annotations

from typing import Protocol

from .runtime import RunState, Runtime
from .schema import Workflow


class ExecutionBackend(Protocol):
    """Boundary between a submission/API adapter and workflow execution."""

    def execute(self, workflow: Workflow, run_id: str | None = None) -> RunState: ...
    def cancel(self) -> None: ...


class LocalExecutionBackend:
    """In-process, synchronous backend backed by :class:`Runtime`."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def execute(self, workflow: Workflow, run_id: str | None = None) -> RunState:
        return self.runtime.run(workflow, run_id)

    def cancel(self) -> None:
        self.runtime.cancel()
