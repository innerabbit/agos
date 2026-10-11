import unittest

from agos import CapabilityRegistry, DeterministicProvider, InMemoryMemoryStore, Runtime, SQLiteStateStore
from agos.publishing import GitHubMarkdownPublisher, PublicationRequest, validate_markdown_path, validate_repository
from agos.research_to_publish import SourceFixture, build_github_markdown_workflow, register_github_markdown_workflow
from agos.sources import DeterministicFakeSourceConnector, SourceRecord


class FakeCredentialSource:
    def __init__(self):
        self.requests = []

    def credential_for(self, repository):
        self.requests.append(repository)
        return "fake-test-credential"


class FakeGitHubClient:
    def __init__(self):
        self.calls = []

    def put_markdown(self, repository, path, content, credential, idempotency_key):
        self.calls.append((repository, path, content, credential, idempotency_key))
        return {"id": f"fake-{len(self.calls)}", "created": "true"}


class ExternalPublishIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = {"source-a": SourceFixture("source-a", "Fixture", "fixture://source-a", "2026-10-11T00:00:00Z", "Cited fact.")}
        self.brief = {"id": "brief-1", "title": "Fixture report", "slug": "fixture-report", "provider_prompt": "draft-1"}
        self.provider = DeterministicProvider({"draft-1": {"markdown": "Cited fact [source-a].", "claims": [{"text": "Cited fact.", "source_id": "source-a"}]}})
        self.client = FakeGitHubClient()
        self.credentials = FakeCredentialSource()
        self.publisher = GitHubMarkdownPublisher(self.client, self.credentials, frozenset({"owner/docs"}))

    def runtime(self, state=None):
        registry, memory = CapabilityRegistry(), InMemoryMemoryStore()
        register_github_markdown_workflow(registry, memory, self.fixtures, self.provider, self.publisher, "owner/docs", "reports/fixture-report.md")
        return Runtime(registry, state or SQLiteStateStore(":memory:"))

    def test_rejected_approval_never_requests_credential_or_publishes(self):
        result = self.runtime().run(build_github_markdown_workflow(self.brief, ["source-a"], "rejected", "owner/docs", "reports/fixture-report.md"))
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.nodes["publish"].status, "skipped")
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.credentials.requests, [])

    def test_approved_allowlisted_target_uses_injected_fake_and_provenance(self):
        result = self.runtime().run(build_github_markdown_workflow(self.brief, ["source-a"], "approved", "owner/docs", "reports/fixture-report.md"))
        self.assertEqual(result.status, "succeeded")
        publication = result.nodes["publish"].output
        self.assertTrue(publication["external_publish"])
        self.assertEqual(publication["repository"], "owner/docs")
        self.assertTrue(publication["provenance_digest"])
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.credentials.requests, ["owner/docs"])
        self.assertIn("source-a", self.client.calls[0][2])

    def test_successful_publish_is_runtime_idempotent(self):
        state = SQLiteStateStore(":memory:")
        self.runtime(state).run(build_github_markdown_workflow(self.brief, ["source-a"], "approved", "owner/docs", "reports/fixture-report.md"), "first")
        recovered = self.runtime(state).run(build_github_markdown_workflow(self.brief, ["source-a"], "approved", "owner/docs", "reports/fixture-report.md"), "second")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(recovered.nodes["publish"].status, "succeeded")
        self.assertIn("node.idempotent", [event["type"] for event in state.events("second")])

    def test_target_validation_and_source_allowlist(self):
        with self.assertRaises(ValueError):
            validate_repository("owner/docs/extra")
        with self.assertRaises(ValueError):
            validate_repository("owner/..")
        with self.assertRaises(ValueError):
            validate_markdown_path("../escape.md")
        with self.assertRaises(ValueError):
            validate_markdown_path("reports//ambiguous.md")
        fake = DeterministicFakeSourceConnector({"known": SourceRecord("known", "Known", "fixture://known", "2026-10-11T00:00:00Z", "fact")})
        self.assertEqual(fake.collect(["known"])[0]["adapter"], "fake")
        with self.assertRaises(ValueError):
            fake.collect(["unknown"])

    def test_provenance_digest_includes_complete_fixture_record(self):
        original = PublicationRequest("owner/docs", "report.md", "# report", ({"source_id": "a", "url": "fixture://a", "retrieved_at": "2026-10-11T00:00:00Z", "content": "first"},), "request-1")
        changed = PublicationRequest("owner/docs", "report.md", "# report", ({"source_id": "a", "url": "fixture://a", "retrieved_at": "2026-10-11T00:00:00Z", "content": "changed"},), "request-1")
        self.assertNotEqual(original.provenance_digest, changed.provenance_digest)

    def test_non_allowlisted_repository_is_denied_before_credentials_or_client(self):
        request = PublicationRequest("other/docs", "report.md", "# report", (), "request-1")
        with self.assertRaises(PermissionError):
            self.publisher.publish(request)
        self.assertEqual(self.credentials.requests, [])
        self.assertEqual(self.client.calls, [])


if __name__ == "__main__":
    unittest.main()
