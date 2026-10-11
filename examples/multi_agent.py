"""Run: PYTHONPATH=src python examples/multi_agent.py"""
from agos import *
from agos.registry import ToolContext
class Research:
    capability="research.read"
    def invoke(self, value, context: ToolContext): return {"finding":"validated DAGs make dependencies explicit", "publish":"yes"}
class Writer:
    capability="report.write"
    def invoke(self, value, context: ToolContext): return {"report":"AGOS: local workflow-first orchestration"}
registry=CapabilityRegistry()
registry.register_agent(AgentManifest("scout","1",frozenset({"research.read"})))
registry.register_agent(AgentManifest("writer","1",frozenset({"report.write"})))
registry.register_tool("research",Research()); registry.register_tool("write",Writer())
workflow=Workflow("multi-agent",(Node("research","research","scout"),Node("report","write","writer",depends_on=("research",))),())
state=Runtime(registry,SQLiteStateStore(":memory:")).run(workflow,"multi-agent-demo")
print(state.status, state.nodes["report"].output)
