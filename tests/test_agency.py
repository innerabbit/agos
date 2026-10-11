import json
import tempfile
import unittest
from pathlib import Path

from agos.agency import (AgencyService, AuthorizationError, JsonlAgencyStore,
                         PersistenceUnavailable, PostgresAgencyStore)
from agos.config import ConfigurationError, HostedAgencySettings


class WorkspaceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.service = AgencyService(JsonlAgencyStore())

    def test_memberships_are_explicit_and_workspace_scoped(self):
        self.assertEqual(self.service.workspaces_for("dev-bob"), [
            {"id": "local-studio", "name": "Local Studio", "role": "member"},
        ])
        with self.assertRaises(AuthorizationError):
            self.service.history("dev-bob", "local-lab")
        with self.assertRaises(AuthorizationError):
            self.service.history("unknown", "local-studio")

    def test_viewer_can_read_but_cannot_mutate(self):
        self.assertEqual(self.service.history("dev-viewer", "local-lab"), [])
        with self.assertRaises(AuthorizationError):
            self.service.record_review("dev-viewer", "local-lab", "approved")

    def test_member_can_create_only_in_own_workspace(self):
        event = self.service.record_review("dev-bob", "local-studio", "approved")
        self.assertEqual((event["workspace_id"], event["sequence"], event["actor_id"]),
                         ("local-studio", 1, "dev-bob"))
        with self.assertRaises(AuthorizationError):
            self.service.record_review("dev-bob", "local-lab", "approved")


class AuditPersistenceTests(unittest.TestCase):
    def test_sequences_are_per_workspace_and_payload_is_immutable(self):
        store = JsonlAgencyStore()
        payload = {"decision": "approved"}
        first = store.append("one", "review.approved", "dev-alice", payload)
        payload["decision"] = "rejected"
        second = store.append("one", "review.rejected", "dev-alice", {"decision": "rejected"})
        other = store.append("two", "review.approved", "dev-alice")
        self.assertEqual([entry.sequence for entry in store.events("one")], [1, 2])
        self.assertEqual(other.sequence, 1)
        self.assertEqual(store.events("one")[0].payload, {"decision": "approved"})
        returned = store.events("one")
        returned[0].payload["decision"] = "altered"  # type: ignore[index]
        self.assertEqual(store.events("one")[0].payload, {"decision": "approved"})
        self.assertEqual(second.previous_hash, first.event_hash)

    def test_tampering_or_sequence_gap_fails_closed_on_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            store = JsonlAgencyStore(path)
            store.append("one", "review.approved", "dev-alice")
            record = json.loads(path.read_text())
            record["sequence"] = 3
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(PersistenceUnavailable):
                JsonlAgencyStore(path)

    def test_postgres_boundary_never_connects_and_fails_closed(self):
        store = PostgresAgencyStore("postgresql://example.invalid/agos")
        with self.assertRaises(PersistenceUnavailable) as raised:
            store.events("workspace")
        self.assertIn("no database connection was attempted", str(raised.exception))
        with self.assertRaises(PersistenceUnavailable):
            PostgresAgencyStore(None)


class HostedConfigurationTests(unittest.TestCase):
    def test_hosted_configuration_requires_all_explicit_values(self):
        for env in ({}, {"DATABASE_URL": "postgresql://db/agos"},
                    {"DATABASE_URL": "postgresql://db/agos", "AGOS_SIGNING_SECRET": "x" * 32}):
            with self.assertRaises(ConfigurationError):
                HostedAgencySettings.from_env(env)

    def test_hosted_configuration_rejects_wildcard_origin_and_accepts_explicit_origin(self):
        base = {"DATABASE_URL": "postgresql://db/agos", "AGOS_SIGNING_SECRET": "x" * 32}
        with self.assertRaises(ConfigurationError):
            HostedAgencySettings.from_env({**base, "AGOS_ALLOWED_ORIGINS": "*"})
        settings = HostedAgencySettings.from_env({**base, "AGOS_ALLOWED_ORIGINS": "https://studio.example.test"})
        self.assertEqual(settings.allowed_origins, ("https://studio.example.test",))


if __name__ == "__main__":
    unittest.main()
