from __future__ import annotations
from dataclasses import dataclass
from threading import Event
from typing import Protocol
from .schema import Json
from .manifests import AgentManifest

class PermissionDenied(PermissionError): pass
@dataclass(frozen=True)
class ToolContext:
    run_id: str; node_id: str; agent_id: str; cancelled: Event; deadline_monotonic: float | None
class Tool(Protocol):
    capability: str
    def invoke(self, value: Json, context: ToolContext) -> Json: ...

class CapabilityRegistry:
    def __init__(self) -> None: self._agents: dict[str, AgentManifest] = {}; self._tools: dict[str, Tool] = {}
    def register_agent(self, manifest: AgentManifest) -> None:
        if manifest.id in self._agents: raise ValueError(f"duplicate agent {manifest.id}")
        self._agents[manifest.id] = manifest
    def register_tool(self, name: str, tool: Tool) -> None:
        if name in self._tools: raise ValueError(f"duplicate tool {name}")
        self._tools[name] = tool
    def invoke(self, name: str, agent_id: str, value: Json, context: ToolContext) -> Json:
        agent = self._agents.get(agent_id); tool = self._tools.get(name)
        if not agent or agent.lifecycle != "active": raise PermissionDenied(f"agent unavailable: {agent_id}")
        if not tool: raise KeyError(f"unknown tool: {name}")
        if tool.capability not in agent.permissions: raise PermissionDenied(f"{agent_id} lacks {tool.capability}")
        return tool.invoke(value, context)
