"""Local-only demo: PYTHONPATH=src python examples/research_to_publish.py --output-dir /tmp/agos-demo"""
from __future__ import annotations
import argparse
from pathlib import Path

from agos import CapabilityRegistry, DeterministicProvider, InMemoryMemoryStore, Runtime, SQLiteStateStore
from agos.research_to_publish import SourceFixture, build_workflow, register_local_workflow


def run(output_dir: str | Path, approval: str = "approved") -> dict[str, object]:
    fixtures = {
        "dag-guide": SourceFixture("dag-guide", "DAG guide", "fixture://dag-guide", "2026-10-11T00:00:00Z", "DAGs make dependencies explicit."),
    }
    brief = {"id": "demo-1", "title": "A local workflow demo", "slug": "local-workflow-demo", "provider_prompt": "demo-draft"}
    memory = InMemoryMemoryStore()
    registry = CapabilityRegistry()
    register_local_workflow(registry, memory, fixtures, DeterministicProvider({"demo-draft": {"markdown": "Dependencies are explicit [dag-guide].", "claims": [{"text": "Dependencies are explicit.", "source_id": "dag-guide"}]}}), output_dir)
    state = Runtime(registry, SQLiteStateStore(":memory:")).run(build_workflow(brief, ["dag-guide"], approval), "research-to-publish-demo")
    return {"status": state.status, "publish": state.nodes["publish"].output, "publish_status": state.nodes["publish"].status}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the AGOS local-only research-to-publish demo")
    parser.add_argument("--output-dir", default="./artifacts/research-to-publish")
    parser.add_argument("--reject", action="store_true", help="exercise the rejection path; no artifact is written")
    args = parser.parse_args()
    print(run(args.output_dir, "rejected" if args.reject else "approved"))
