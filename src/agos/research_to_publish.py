"""Canonical local-only Autonomous Research-to-Publish MVP.

This module deliberately uses fixture data and deterministic providers.  It never
opens a network connection and its only publication adapter writes Markdown below
a caller-selected local directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Literal

from .manifests import AgentManifest
from .memory import MemoryStore
from .providers import Provider
from .registry import CapabilityRegistry, ToolContext
from .schema import Json, Node, Route, Workflow

ApprovalDecision = Literal["approved", "rejected"]


@dataclass(frozen=True)
class SourceFixture:
    """A supplied, deterministic research source; this is not a fetch adapter."""

    source_id: str
    title: str
    url: str
    retrieved_at: str
    content: str

    def provenance(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
            "content": self.content,
            "adapter": "fixture",
        }


class FixtureSourceAdapter:
    """Returns allow-listed fixtures only; no scraping or live HTTP is possible."""

    def __init__(self, fixtures: dict[str, SourceFixture]):
        self._fixtures = dict(fixtures)

    def collect(self, source_ids: list[str]) -> list[dict[str, str]]:
        missing = [source_id for source_id in source_ids if source_id not in self._fixtures]
        if missing:
            raise ValueError(f"unknown fixture source ids: {missing}")
        return [self._fixtures[source_id].provenance() for source_id in source_ids]


def _scope(context: ToolContext) -> str:
    return f"shared:research-to-publish:{context.run_id}"


def _load(memory: MemoryStore, context: ToolContext, key: str) -> Json:
    value = memory.get(context.agent_id, _scope(context), key)
    if value is None:
        raise ValueError(f"required workflow record {key!r} is absent")
    return value


class CollectSourcesTool:
    capability = "research.collect.fixture"

    def __init__(self, adapter: FixtureSourceAdapter, memory: MemoryStore):
        self.adapter, self.memory = adapter, memory

    def invoke(self, value: Json, context: ToolContext) -> Json:
        if not isinstance(value, dict) or not isinstance(value.get("brief"), dict):
            raise ValueError("collection input requires a brief object")
        source_ids = value.get("source_ids")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
            raise ValueError("collection input requires string source_ids")
        record: dict[str, Json] = {"brief": value["brief"], "sources": self.adapter.collect(source_ids)}
        self.memory.put(context.agent_id, _scope(context), "research", record)
        return {"source_count": len(record["sources"]), "provenance_recorded": True}


class SynthesizeDraftTool:
    capability = "draft.generate.deterministic"

    def __init__(self, provider: Provider, memory: MemoryStore):
        self.provider, self.memory = provider, memory

    def invoke(self, value: Json, context: ToolContext) -> Json:
        research = _load(self.memory, context, "research")
        assert isinstance(research, dict)
        brief = research["brief"]
        assert isinstance(brief, dict)
        prompt = str(brief["provider_prompt"])
        generated = self.provider.complete(prompt)
        if not isinstance(generated, dict) or not isinstance(generated.get("markdown"), str) or not isinstance(generated.get("claims"), list):
            raise ValueError("deterministic provider must return markdown and claims")
        draft: dict[str, Json] = {"brief": brief, "sources": research["sources"], "markdown": generated["markdown"], "claims": generated["claims"]}
        self.memory.put(context.agent_id, _scope(context), "draft", draft)
        return {"draft_ready": True, "claim_count": len(generated["claims"])}


class ClaimReviewTool:
    capability = "review.claims"

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def invoke(self, value: Json, context: ToolContext) -> Json:
        draft = _load(self.memory, context, "draft")
        assert isinstance(draft, dict)
        sources = draft["sources"]
        assert isinstance(sources, list)
        source_ids = {str(source["source_id"]) for source in sources if isinstance(source, dict)}
        claims = draft["claims"]
        assert isinstance(claims, list)
        invalid = [claim for claim in claims if not isinstance(claim, dict) or claim.get("source_id") not in source_ids or not isinstance(claim.get("text"), str)]
        review: dict[str, Json] = {"approved_for_human": not invalid, "invalid_claims": invalid, "source_ids": sorted(source_ids)}
        self.memory.put(context.agent_id, _scope(context), "review", review)
        return review


class HumanApprovalGateTool:
    """Requires an explicit human decision; it cannot auto-approve a draft."""

    capability = "approval.human"

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def invoke(self, value: Json, context: ToolContext) -> Json:
        review = _load(self.memory, context, "review")
        assert isinstance(review, dict)
        if not isinstance(value, dict) or value.get("decision") not in ("approved", "rejected"):
            raise ValueError("human approval requires explicit decision: approved or rejected")
        decision = value["decision"]
        if decision == "approved" and review.get("approved_for_human") is not True:
            raise PermissionError("cannot approve draft with invalid claims")
        approval: dict[str, Json] = {"decision": decision, "reviewed_by": value.get("reviewed_by", "human"), "note": value.get("note", "")}
        self.memory.put(context.agent_id, _scope(context), "approval", approval)
        return approval


class LocalMarkdownPublisherTool:
    """Writes only a local Markdown file, and uses atomic create for idempotency."""

    capability = "publish.local_markdown"

    def __init__(self, output_dir: str | Path, memory: MemoryStore):
        self.output_dir, self.memory = Path(output_dir), memory

    def invoke(self, value: Json, context: ToolContext) -> Json:
        approval = _load(self.memory, context, "approval")
        if not isinstance(approval, dict) or approval.get("decision") != "approved":
            raise PermissionError("local artifact creation requires human approval")
        draft = _load(self.memory, context, "draft")
        assert isinstance(draft, dict)
        brief = draft["brief"]
        assert isinstance(brief, dict)
        slug = str(brief["slug"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug):
            raise ValueError("brief slug must be a safe lowercase filename")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{slug}.md"
        provenance = json.dumps(draft["sources"], indent=2, sort_keys=True)
        document = f"# {brief['title']}\n\n{draft['markdown']}\n\n## Source provenance (fixture data)\n\n```json\n{provenance}\n```\n\n<!-- Local-only artifact. No external publishing occurred. -->\n"
        try:
            with path.open("x", encoding="utf-8") as artifact:
                artifact.write(document)
            created = True
        except FileExistsError:
            created = False
        publication: dict[str, Json] = {"path": str(path), "created": created, "external_publish": False}
        self.memory.put(context.agent_id, _scope(context), "publication", publication)
        return publication


def build_workflow(brief: dict[str, str], source_ids: list[str], approval: ApprovalDecision) -> Workflow:
    """Build the auditable five-step workflow; approval controls the publish route."""
    required = {"id", "title", "slug", "provider_prompt"}
    missing = sorted(required - set(brief))
    if missing:
        raise ValueError(f"brief missing fields: {missing}")
    publish_key = f"local-markdown:{brief['id']}:{brief['slug']}"
    return Workflow(
        "autonomous-research-to-publish",
        (
            Node("collect", "collect_sources", "researcher", input={"brief": brief, "source_ids": source_ids}, delegation_cost=1),
            Node("synthesize", "synthesize_draft", "writer", depends_on=("collect",), delegation_cost=1),
            Node("review", "review_claims", "reviewer", depends_on=("synthesize",), delegation_cost=1),
            Node("human_approval", "human_approval", "approver", depends_on=("review",), input={"decision": approval}, delegation_cost=1),
            Node("publish", "publish_local_markdown", "publisher", depends_on=("human_approval",), idempotency_key=publish_key, delegation_cost=1),
        ),
        (Route("human_approval", "decision", "approved", {"approved": ("publish",), "rejected": ()}),),
    )


def register_local_workflow(registry: CapabilityRegistry, memory: MemoryStore, fixtures: dict[str, SourceFixture], provider: Provider, output_dir: str | Path) -> None:
    """Register narrowly scoped local agents and tools; publisher has no remote capability."""
    registry.register_agent(AgentManifest("researcher", "1", frozenset({"research.collect.fixture"})))
    registry.register_agent(AgentManifest("writer", "1", frozenset({"draft.generate.deterministic"})))
    registry.register_agent(AgentManifest("reviewer", "1", frozenset({"review.claims"})))
    registry.register_agent(AgentManifest("approver", "1", frozenset({"approval.human"})))
    registry.register_agent(AgentManifest("publisher", "1", frozenset({"publish.local_markdown"})))
    registry.register_tool("collect_sources", CollectSourcesTool(FixtureSourceAdapter(fixtures), memory))
    registry.register_tool("synthesize_draft", SynthesizeDraftTool(provider, memory))
    registry.register_tool("review_claims", ClaimReviewTool(memory))
    registry.register_tool("human_approval", HumanApprovalGateTool(memory))
    registry.register_tool("publish_local_markdown", LocalMarkdownPublisherTool(output_dir, memory))
