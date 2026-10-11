import tempfile, time, unittest
from pathlib import Path
from agos import *
from agos.registry import ToolContext
from agos.memory import InMemoryMemoryStore
from agos.providers import DeterministicProvider

class Echo:
    capability="run"
    def __init__(self): self.calls=0
    def invoke(self,value,context): self.calls+=1; return value
class Flaky(Echo):
    def invoke(self,value,context):
        self.calls+=1
        if self.calls==1: raise RuntimeError("temporary")
        return "ok"
class Slow(Echo):
    def invoke(self,value,context): time.sleep(.08); return value

def runtime(tool, permissions=frozenset({"run"}), path=":memory:"):
    r=CapabilityRegistry(); r.register_agent(AgentManifest("a","1",permissions)); r.register_tool("tool",tool)
    return Runtime(r,SQLiteStateStore(path))

class SchemaTests(unittest.TestCase):
    def test_cycle_rejected(self):
        with self.assertRaises(ValidationError): Workflow("x",(Node("a","t","a",("b",)),Node("b","t","a",("a",)))).validate()
    def test_unknown_dependency_rejected(self):
        with self.assertRaises(ValidationError): Workflow("x",(Node("a","t","a",("z",)),)).validate()

class RuntimeTests(unittest.TestCase):
    def test_retries_checkpoints_and_idempotency(self):
        tool=Flaky(); rt=runtime(tool); flow=Workflow("w",(Node("n","tool","a",retry=RetryPolicy(2),idempotency_key="k"),))
        state=rt.run(flow,"r1"); self.assertEqual(state.status,"succeeded"); self.assertEqual(state.nodes["n"].attempts,2)
        self.assertTrue(rt.store.load("r1")); self.assertEqual(len(rt.store.events("r1")) >= 4,True)
        state=rt.run(flow,"r2"); self.assertEqual(tool.calls,2); self.assertEqual(state.nodes["n"].status,"succeeded")
    def test_permission_and_budget_bounds(self):
        state=runtime(Echo(),frozenset()).run(Workflow("w",(Node("n","tool","a"),)))
        self.assertEqual(state.status,"failed")
        rt=runtime(Echo()); rt.limits=ExecutionLimits(delegation_budget=0)
        self.assertEqual(rt.run(Workflow("w",(Node("n","tool","a",delegation_cost=1),))).status,"failed")
    def test_route_skips_unselected_branch(self):
        tool=Echo(); rt=runtime(tool)
        flow=Workflow("w",(Node("source","tool","a",input={"decision":"yes"}),Node("yes","tool","a",("source",)),Node("no","tool","a",("source",))), (Route("source","decision","yes",{"yes":("yes",),"no":("no",)}),))
        state=rt.run(flow); self.assertEqual(state.nodes["yes"].status,"succeeded"); self.assertEqual(state.nodes["no"].status,"skipped")
    def test_timeout_marks_cancelled(self):
        state=runtime(Slow()).run(Workflow("w",(Node("n","tool","a",timeout_seconds=.01),)))
        self.assertEqual(state.status,"cancelled")
    def test_deterministic_provider_is_local_fixture(self):
        self.assertEqual(DeterministicProvider({"prompt":{"answer":42}}).complete("prompt"), {"answer":42})
    def test_memory_scope(self):
        m=InMemoryMemoryStore(); m.put("a","private:a","x",1); self.assertEqual(m.get("a","private:a","x"),1)
        with self.assertRaises(PermissionError): m.get("b","private:a","x")
    def test_sqlite_memory_is_durable_and_shared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "memory.db")
            m = SQLiteMemoryStore(path); m.put("a", "shared:team", "brief", {"v": 1}); m.close()
            with SQLiteMemoryStore(path) as reopened:
                self.assertEqual(reopened.get("b", "shared:team", "brief"), {"v": 1})
                with self.assertRaises(PermissionError): reopened.get("b", "private:a", "x")

if __name__ == "__main__": unittest.main()

class DeploymentBoundaryTests(unittest.TestCase):
    def test_settings_defaults_to_supported_local_backends(self):
        settings = Settings.from_env({})
        self.assertEqual(settings.environment, "local")
        self.assertEqual(settings.state_backend, "sqlite")
        self.assertEqual(settings.execution_backend, "local")

    def test_settings_rejects_unimplemented_distributed_backends(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"AGOS_STATE_BACKEND": "postgres"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"AGOS_EXECUTION_BACKEND": "queue"})

    def test_local_execution_backend_delegates_to_runtime(self):
        tool = Echo()
        backend = LocalExecutionBackend(runtime(tool))
        result = backend.execute(Workflow("w", (Node("n", "tool", "a"),)))
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(tool.calls, 1)
