"""Canonical local-only Autonomous Research-to-Publish MVP.

This module deliberately uses fixture data and deterministic providers.  It never
opens a network connection and its only publication adapter writes Markdown below
a caller-selected local directory.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Literal

from .manifests import AgentManifest
from .memory import MemoryStore
from .providers import Provider
from .publishing import DryRunMarkdownPublisher, LocalMarkdownPublisher, MarkdownPublisher, PublicationRequest
from .registry import CapabilityRegistry, ToolContext
from .schema import Json, Node, Route, Workflow
from .sources import AllowlistedFixtureConnector, HTTPSResearchConnector, HTTPSResearchSource, SourceConnector, SourceRecord

ApprovalDecision = Literal["approved", "rejected"]


SourceFixture = SourceRecord


class FixtureSourceAdapter(AllowlistedFixtureConnector):
    """Compatibility name for the strict, fixture-only connector."""


def _scope(context: ToolContext) -> str:
    return f"shared:research-to-publish:{context.run_id}"


def _load(memory: MemoryStore, context: ToolContext, key: str) -> Json:
    value = memory.get(context.agent_id, _scope(context), key)
    if value is None:
        raise ValueError(f"required workflow record {key!r} is absent")
    return value


class CollectSourcesTool:
    capability = "research.collect.fixture"

    def __init__(self, adapter: SourceConnector, memory: MemoryStore):
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


class HTTPSCollectSourcesTool(CollectSourcesTool):
    """Separate capability prevents HTTPS retrieval from inheriting fixture permission."""

    capability = "research.collect.https"


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
    """Writes a local Markdown file, or reports a no-effect dry-run receipt."""

    capability = "publish.local_markdown"

    def __init__(self, output_dir: str | Path, memory: MemoryStore, publisher: MarkdownPublisher | None = None):
        self.output_dir, self.memory = Path(output_dir), memory
        self.publisher = publisher or LocalMarkdownPublisher(self.output_dir)

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
        provenance = json.dumps(draft["sources"], indent=2, sort_keys=True)
        document = f"# {brief['title']}\n\n{draft['markdown']}\n\n## Source provenance (fixture data)\n\n```json\n{provenance}\n```\n\n<!-- Local-only artifact. No external publishing occurred. -->\n"
        request = PublicationRequest("local/artifacts", f"{slug}.md", document, tuple(draft["sources"]), f"local-markdown:{brief['id']}:{slug}")
        publication = self.publisher.publish(request)
        self.memory.put(context.agent_id, _scope(context), "publication", publication)
        return publication


class ApprovedMarkdownPublisherTool:
    """Capability-scoped publisher wrapper that binds approval, provenance, and target."""

    capability = "publish.github_markdown"

    def __init__(self, publisher: MarkdownPublisher, memory: MemoryStore, repository: str, path: str):
        self.publisher, self.memory = publisher, memory
        self.repository, self.path = repository, path

    def invoke(self, value: Json, context: ToolContext) -> Json:
        approval = _load(self.memory, context, "approval")
        if not isinstance(approval, dict) or approval.get("decision") != "approved":
            raise PermissionError("external Markdown publication requires explicit human approval")
        draft = _load(self.memory, context, "draft")
        assert isinstance(draft, dict)
        brief, sources = draft["brief"], draft["sources"]
        assert isinstance(brief, dict) and isinstance(sources, list)
        document = f"# {brief['title']}\n\n{draft['markdown']}\n\n## Source provenance\n\n```json\n{json.dumps(sources, indent=2, sort_keys=True)}\n```\n"
        request = PublicationRequest(
            self.repository, self.path, document, tuple(sources),
            f"github-markdown:{self.repository}:{self.path}:{brief['id']}",
        )
        publication = self.publisher.publish(request)
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


def build_https_workflow(brief: dict[str, str], source_ids: list[str], approval: ApprovalDecision) -> Workflow:
    """Build the reviewed local-publish flow with an explicitly opt-in HTTPS collector."""
    required = {"id", "title", "slug", "provider_prompt"}
    missing = sorted(required - set(brief))
    if missing:
        raise ValueError(f"brief missing fields: {missing}")
    publish_key = f"local-markdown:{brief['id']}:{brief['slug']}"
    return Workflow(
        "https-research-to-publish",
        (
            Node("collect", "collect_https_sources", "researcher", input={"brief": brief, "source_ids": source_ids}, delegation_cost=1),
            Node("synthesize", "synthesize_draft", "writer", depends_on=("collect",), delegation_cost=1),
            Node("review", "review_claims", "reviewer", depends_on=("synthesize",), delegation_cost=1),
            Node("human_approval", "human_approval", "approver", depends_on=("review",), input={"decision": approval}, delegation_cost=1),
            Node("publish", "publish_local_markdown", "publisher", depends_on=("human_approval",), idempotency_key=publish_key, delegation_cost=1),
        ),
        (Route("human_approval", "decision", "approved", {"approved": ("publish",), "rejected": ()}),),
    )


def build_github_markdown_workflow(brief: dict[str, str], source_ids: list[str], approval: ApprovalDecision, repository: str, path: str) -> Workflow:
    """Build the same reviewed flow with a separately capability-scoped GitHub target."""
    required = {"id", "title", "slug", "provider_prompt"}
    missing = sorted(required - set(brief))
    if missing:
        raise ValueError(f"brief missing fields: {missing}")
    publish_key = f"github-markdown:{repository}:{path}:{brief['id']}"
    return Workflow(
        "approved-github-markdown-publish",
        (
            Node("collect", "collect_sources", "researcher", input={"brief": brief, "source_ids": source_ids}, delegation_cost=1),
            Node("synthesize", "synthesize_draft", "writer", depends_on=("collect",), delegation_cost=1),
            Node("review", "review_claims", "reviewer", depends_on=("synthesize",), delegation_cost=1),
            Node("human_approval", "human_approval", "approver", depends_on=("review",), input={"decision": approval}, delegation_cost=1),
            Node("publish", "publish_github_markdown", "github_publisher", depends_on=("human_approval",), idempotency_key=publish_key, delegation_cost=1),
        ),
        (Route("human_approval", "decision", "approved", {"approved": ("publish",), "rejected": ()}),),
    )


def register_local_workflow(
    registry: CapabilityRegistry,
    memory: MemoryStore,
    fixtures: dict[str, SourceFixture],
    provider: Provider,
    output_dir: str | Path,
    *,
    dry_run: bool = False,
) -> None:
    """Register local agents and tools; dry-run retains approval flow but writes nothing."""
    registry.register_agent(AgentManifest("researcher", "1", frozenset({"research.collect.fixture"})))
    registry.register_agent(AgentManifest("writer", "1", frozenset({"draft.generate.deterministic"})))
    registry.register_agent(AgentManifest("reviewer", "1", frozenset({"review.claims"})))
    registry.register_agent(AgentManifest("approver", "1", frozenset({"approval.human"})))
    registry.register_agent(AgentManifest("publisher", "1", frozenset({"publish.local_markdown"})))
    registry.register_tool("collect_sources", CollectSourcesTool(FixtureSourceAdapter(fixtures), memory))
    registry.register_tool("synthesize_draft", SynthesizeDraftTool(provider, memory))
    registry.register_tool("review_claims", ClaimReviewTool(memory))
    registry.register_tool("human_approval", HumanApprovalGateTool(memory))
    publisher: MarkdownPublisher = DryRunMarkdownPublisher() if dry_run else LocalMarkdownPublisher(output_dir)
    registry.register_tool("publish_local_markdown", LocalMarkdownPublisherTool(output_dir, memory, publisher))


def register_https_workflow(
    registry: CapabilityRegistry,
    memory: MemoryStore,
    sources: dict[str, HTTPSResearchSource],
    provider: Provider,
    output_dir: str | Path,
    allowed_hosts: frozenset[str],
    *,
    connector: HTTPSResearchConnector | None = None,
) -> None:
    """Register the opt-in HTTPS source with a distinct capability and local publisher.

    Callers must provide the source-ID mapping and an explicit host allowlist. The
    connector can be injected for deterministic tests; no credentials are accepted.
    """
    research_connector = connector or HTTPSResearchConnector(sources, allowed_hosts)
    registry.register_agent(AgentManifest("researcher", "1", frozenset({"research.collect.https"})))
    registry.register_agent(AgentManifest("writer", "1", frozenset({"draft.generate.deterministic"})))
    registry.register_agent(AgentManifest("reviewer", "1", frozenset({"review.claims"})))
    registry.register_agent(AgentManifest("approver", "1", frozenset({"approval.human"})))
    registry.register_agent(AgentManifest("publisher", "1", frozenset({"publish.local_markdown"})))
    registry.register_tool("collect_https_sources", HTTPSCollectSourcesTool(research_connector, memory))
    registry.register_tool("synthesize_draft", SynthesizeDraftTool(provider, memory))
    registry.register_tool("review_claims", ClaimReviewTool(memory))
    registry.register_tool("human_approval", HumanApprovalGateTool(memory))
    registry.register_tool("publish_local_markdown", LocalMarkdownPublisherTool(output_dir, memory))


def register_github_markdown_workflow(registry: CapabilityRegistry, memory: MemoryStore, fixtures: dict[str, SourceFixture], provider: Provider, publisher: MarkdownPublisher, repository: str, path: str) -> None:
    """Register an opt-in external adapter; caller owns client and credential injection."""
    registry.register_agent(AgentManifest("researcher", "1", frozenset({"research.collect.fixture"})))
    registry.register_agent(AgentManifest("writer", "1", frozenset({"draft.generate.deterministic"})))
    registry.register_agent(AgentManifest("reviewer", "1", frozenset({"review.claims"})))
    registry.register_agent(AgentManifest("approver", "1", frozenset({"approval.human"})))
    registry.register_agent(AgentManifest("github_publisher", "1", frozenset({"publish.github_markdown"})))
    registry.register_tool("collect_sources", CollectSourcesTool(FixtureSourceAdapter(fixtures), memory))
    registry.register_tool("synthesize_draft", SynthesizeDraftTool(provider, memory))
    registry.register_tool("review_claims", ClaimReviewTool(memory))
    registry.register_tool("human_approval", HumanApprovalGateTool(memory))
    registry.register_tool("publish_github_markdown", ApprovedMarkdownPublisherTool(publisher, memory, repository, path))
