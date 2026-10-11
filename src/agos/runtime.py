from __future__ import annotations
import time, uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, asdict, field
from threading import Event
from typing import Literal
from .schema import Workflow, Node, Json
from .registry import CapabilityRegistry, ToolContext
from .storage import StateStore
from .manifests import DelegationBudget, ExecutionLimits

NodeStatus = Literal["pending","running","succeeded","failed","skipped","cancelled"]
@dataclass
class NodeState:
    status: NodeStatus = "pending"; attempts: int = 0; output: Json = None; error: str | None = None
@dataclass
class RunState:
    id: str; workflow_id: str; status: str = "running"; nodes: dict[str, NodeState] = field(default_factory=dict)
    cancelled: bool = False
    def dump(self) -> dict[str, Json]:
        return {"id":self.id,"workflow_id":self.workflow_id,"status":self.status,"cancelled":self.cancelled,"nodes":{k:asdict(v) for k,v in self.nodes.items()}}

class Runtime:
    def __init__(self, registry: CapabilityRegistry, store: StateStore, limits: ExecutionLimits = ExecutionLimits()):
        self.registry, self.store, self.limits, self.cancel_event = registry, store, limits, Event()
    def cancel(self) -> None: self.cancel_event.set()
    def run(self, workflow: Workflow, run_id: str | None = None) -> RunState:
        workflow.validate(); rid=run_id or f"run_{uuid.uuid4().hex}"; state=RunState(rid, workflow.id, nodes={n.id:NodeState() for n in workflow.nodes}); budget=DelegationBudget(self.limits)
        by_id={n.id:n for n in workflow.nodes}; self._emit(state,"run.started")
        while any(s.status in ("pending","running") for s in state.nodes.values()):
            if self.cancel_event.is_set():
                state.cancelled=True
                for s in state.nodes.values():
                    if s.status == "pending": s.status="cancelled"
                break
            for n in workflow.nodes:
                ns=state.nodes[n.id]
                if ns.status=="pending" and any(state.nodes[d].status in ("failed","skipped","cancelled") for d in n.depends_on):
                    ns.status="skipped"; self._emit(state,"node.skipped",n.id,{"reason":"dependency"})
            ready=[n for n in workflow.nodes if state.nodes[n.id].status=="pending" and all(state.nodes[d].status=="succeeded" for d in n.depends_on)]
            if not ready:
                if not any(s.status=="pending" for s in state.nodes.values()): break
                continue
            for n in ready: self._execute(n,state,budget)
            self._apply_routes(workflow,state)
        state.status="cancelled" if state.cancelled else ("failed" if any(s.status=="failed" for s in state.nodes.values()) else "succeeded")
        self._emit(state,"run.finished",detail={"status":state.status}); return state
    def _emit(self, state: RunState, kind: str, node_id: str | None=None, detail: Json=None) -> None:
        self.store.event(state.id,{"type":kind,"run_id":state.id,"node_id":node_id,"at":time.time(),"detail":detail}); self.store.checkpoint(state.id,state.dump())
    def _execute(self,n:Node,state:RunState,budget:DelegationBudget)->None:
        ns=state.nodes[n.id]
        try:
            budget.consume(n.delegation_depth,n.delegation_cost)
        except PermissionError as exc:
            ns.status="failed"; ns.error=str(exc); self._emit(state,"node.failed",n.id,{"error":ns.error}); return
        ns.status="running"
        cached=self.store.idempotent(n.idempotency_key) if n.idempotency_key else None
        if cached is not None: ns.status="succeeded"; ns.output=cached; self._emit(state,"node.idempotent",n.id); return
        for attempt in range(1,n.retry.max_attempts+1):
            ns.attempts=attempt; self._emit(state,"node.started",n.id,{"attempt":attempt})
            deadline=time.monotonic()+n.timeout_seconds if n.timeout_seconds else None
            context=ToolContext(state.id,n.id,n.agent_id,self.cancel_event,deadline)
            pool=ThreadPoolExecutor(max_workers=1)
            future=pool.submit(self.registry.invoke,n.tool,n.agent_id,n.input,context)
            try:
                ns.output=future.result(timeout=n.timeout_seconds); ns.status="succeeded"
                if n.idempotency_key: self.store.remember_idempotent(n.idempotency_key,ns.output)
                self._emit(state,"node.succeeded",n.id,{"attempt":attempt}); pool.shutdown(wait=False); return
            except TimeoutError:
                self.cancel_event.set(); state.cancelled=True; ns.error="timeout"; self._emit(state,"node.timed_out",n.id)
            except Exception as exc:
                ns.error=f"{type(exc).__name__}: {exc}"
            finally: pool.shutdown(wait=False)
            if attempt<n.retry.max_attempts and not self.cancel_event.is_set():
                self._emit(state,"node.retrying",n.id,{"attempt":attempt}); time.sleep(n.retry.backoff_seconds)
        ns.status="cancelled" if self.cancel_event.is_set() else "failed"; self._emit(state,"node.failed",n.id,{"error":ns.error})
    def _apply_routes(self,workflow:Workflow,state:RunState)->None:
        for r in workflow.routes:
            source=state.nodes[r.from_node]
            if source.status!="succeeded": continue
            value=source.output.get(r.key) if isinstance(source.output,dict) else None
            chosen=set(r.when.get(str(value),r.default))
            all_targets=set(r.default)
            for targets in r.when.values(): all_targets.update(targets)
            for target in all_targets-chosen:
                if state.nodes[target].status=="pending": state.nodes[target].status="skipped"; self._emit(state,"node.skipped",target,{"reason":"route"})
