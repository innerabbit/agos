import tempfile
import unittest
import io
import json
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from agos import (
    CapabilityRegistry,
    DeterministicProvider,
    ExecutionLimits,
    InMemoryMemoryStore,
    Runtime,
    SQLiteMemoryStore,
    SQLiteStateStore,
)
from agos.research_to_publish import SourceFixture, build_workflow, register_local_workflow


class ResearchToPublishIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = {
            "source-a": SourceFixture("source-a", "Fixture A", "fixture://source-a", "2026-10-11T00:00:00Z", "A cited fact."),
        }
        self.brief = {"id": "brief-1", "title": "Fixture report", "slug": "fixture-report", "provider_prompt": "draft-1"}
        self.provider = DeterministicProvider({"draft-1": {"markdown": "A cited fact [source-a].", "claims": [{"text": "A cited fact.", "source_id": "source-a"}]}})

    def make_runtime(self, output_dir, state=None, memory=None, limits=ExecutionLimits()):
        registry = CapabilityRegistry()
        memory = memory or InMemoryMemoryStore()
        register_local_workflow(registry, memory, self.fixtures, self.provider, output_dir)
        return Runtime(registry, state or SQLiteStateStore(":memory:"), limits), memory

    def test_approved_flow_writes_local_provenance_artifact_and_events(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = SQLiteStateStore(":memory:")
            runtime, memory = self.make_runtime(directory, state_store)
            result = runtime.run(build_workflow(self.brief, ["source-a"], "approved"), "approved-run")
            self.assertEqual(result.status, "succeeded")
            artifact = Path(result.nodes["publish"].output["path"])
            self.assertTrue(artifact.exists())
            text = artifact.read_text()
            self.assertIn('"source_id": "source-a"', text)
            self.assertIn("No external publishing occurred", text)
            self.assertFalse(result.nodes["publish"].output["external_publish"])
            self.assertTrue(state_store.load("approved-run"))
            event_types = [event["type"] for event in state_store.events("approved-run")]
            self.assertIn("node.succeeded", event_types)
            self.assertEqual(memory.get("reviewer", "shared:research-to-publish:approved-run", "research")["sources"][0]["adapter"], "fixture")

    def test_rejection_routes_away_from_publish_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.make_runtime(directory)
            result = runtime.run(build_workflow(self.brief, ["source-a"], "rejected"), "rejected-run")
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.nodes["human_approval"].output["decision"], "rejected")
            self.assertEqual(result.nodes["publish"].status, "skipped")
            self.assertFalse((Path(directory) / "fixture-report.md").exists())

    def test_publisher_is_idempotent_across_recovery_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SQLiteStateStore(":memory:")
            first, _ = self.make_runtime(directory, state)
            result = first.run(build_workflow(self.brief, ["source-a"], "approved"), "first")
            artifact = Path(result.nodes["publish"].output["path"])
            original = artifact.read_text()
            second, _ = self.make_runtime(directory, state)
            recovered = second.run(build_workflow(self.brief, ["source-a"], "approved"), "recovered")
            self.assertEqual(recovered.nodes["publish"].status, "succeeded")
            self.assertEqual(artifact.read_text(), original)
            self.assertIn("node.idempotent", [event["type"] for event in state.events("recovered")])

    def test_invalid_claim_cannot_receive_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = DeterministicProvider({"draft-1": {"markdown": "Unsupported.", "claims": [{"text": "Unsupported.", "source_id": "not-in-provenance"}]}})
            registry = CapabilityRegistry(); memory = InMemoryMemoryStore()
            register_local_workflow(registry, memory, self.fixtures, provider, directory)
            result = Runtime(registry, SQLiteStateStore(":memory:")).run(build_workflow(self.brief, ["source-a"], "approved"), "bad-claim")
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.nodes["human_approval"].status, "failed")
            self.assertEqual(result.nodes["publish"].status, "skipped")

    def test_budget_and_durable_memory_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.make_runtime(directory, limits=ExecutionLimits(delegation_budget=4))
            result = runtime.run(build_workflow(self.brief, ["source-a"], "approved"), "budget-run")
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.nodes["publish"].status, "failed")
            memory_path = Path(directory) / "memory.db"
            memory = SQLiteMemoryStore(memory_path)
            runtime, _ = self.make_runtime(directory, memory=memory)
            self.assertEqual(runtime.run(build_workflow(self.brief, ["source-a"], "rejected"), "durable-run").status, "succeeded")
            memory.close()
            with SQLiteMemoryStore(memory_path) as reopened:
                self.assertEqual(reopened.get("publisher", "shared:research-to-publish:durable-run", "approval")["decision"], "rejected")


class CliSafetyTests(unittest.TestCase):
    def test_dry_run_executes_approved_path_without_creating_an_artifact(self):
        from agos.cli import main

        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch("sys.argv", ["agos", "research-to-publish-demo", "--dry-run", "--output-dir", directory]), redirect_stdout(output):
                main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["publish_status"], "succeeded")
            self.assertEqual(result["publish"]["target"], "dry-run")
            self.assertFalse(result["publish"]["external_publish"])
            self.assertFalse((Path(directory) / "local-workflow-demo.md").exists())


if __name__ == "__main__":
    unittest.main()
