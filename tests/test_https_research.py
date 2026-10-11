from datetime import UTC, datetime
import hashlib
import unittest

from agos import CapabilityRegistry, DeterministicProvider, InMemoryMemoryStore, Runtime, SQLiteStateStore
from agos.research_to_publish import build_https_workflow, register_https_workflow
from agos.sources import HTTPResponse, HTTPSResearchConnector, HTTPSResearchSource, ResearchSourceError, normalize_https_url
import tempfile


PUBLIC_IP = "93.184.216.34"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def fetch(self, url, *, timeout, max_bytes, resolved_ip):
        self.calls.append((url, timeout, max_bytes, resolved_ip))
        return self.responses.pop(0)


def resolver_for(*addresses):
    def resolve(host, port):
        return list(addresses)
    return resolve


class HTTPSResearchConnectorTests(unittest.TestCase):
    def make_connector(self, responses, *, url="https://Example.TEST/report#fragment", resolver=resolver_for(PUBLIC_IP), **kwargs):
        return HTTPSResearchConnector(
            {"report": HTTPSResearchSource("report", "Report", url)},
            frozenset({"example.test", "redirect.test"}),
            transport=FakeTransport(responses),
            resolver=resolver,
            clock=lambda: datetime(2026, 10, 11, 12, 0, tzinfo=UTC),
            **kwargs,
        )

    def test_collects_normalized_bounded_content_with_sanitized_provenance(self):
        body = b"verified research"
        connector = self.make_connector([HTTPResponse(200, {"Content-Type": "text/plain; charset=utf-8"}, body)])
        record = connector.collect(["report"])[0]
        self.assertEqual(record["url"], "https://example.test/report")
        self.assertEqual(record["retrieved_at"], "2026-10-11T12:00:00Z")
        self.assertEqual(record["digest"], f"sha256:{hashlib.sha256(body).hexdigest()}")
        self.assertEqual(record["adapter"], "https-research")
        self.assertEqual(record["content"], "verified research")

    def test_redirect_destination_is_revalidated(self):
        transport = FakeTransport([
            HTTPResponse(302, {"Location": "https://redirect.test/final"}, b""),
            HTTPResponse(200, {"Content-Type": "application/json"}, b"{}"),
        ])
        connector = HTTPSResearchConnector(
            {"report": HTTPSResearchSource("report", "Report", "https://example.test/start")},
            frozenset({"example.test", "redirect.test"}), transport=transport,
            resolver=resolver_for(PUBLIC_IP), clock=lambda: datetime(2026, 10, 11, tzinfo=UTC),
        )
        self.assertEqual(connector.collect(["report"])[0]["url"], "https://redirect.test/final")
        self.assertEqual([call[0] for call in transport.calls], ["https://example.test/start", "https://redirect.test/final"])

    def test_rejects_private_and_mixed_dns_results_before_transport(self):
        transport = FakeTransport([])
        connector = HTTPSResearchConnector(
            {"report": HTTPSResearchSource("report", "Report", "https://example.test/")},
            frozenset({"example.test"}), transport=transport, resolver=resolver_for(PUBLIC_IP, "127.0.0.1"),
        )
        with self.assertRaisesRegex(ResearchSourceError, "public IP"):
            connector.collect(["report"])
        self.assertEqual(transport.calls, [])

    def test_rejects_redirect_to_unallowlisted_or_private_destination(self):
        connector = self.make_connector([HTTPResponse(302, {"Location": "https://evil.test/"}, b"")])
        with self.assertRaisesRegex(ResearchSourceError, "allow-listed"):
            connector.collect(["report"])
        def redirect_private_resolver(host, port):
            return ["169.254.1.1"] if host == "redirect.test" else [PUBLIC_IP]
        connector = self.make_connector([HTTPResponse(302, {"Location": "https://redirect.test/"}, b"")], resolver=redirect_private_resolver)
        with self.assertRaisesRegex(ResearchSourceError, "public IP"):
            connector.collect(["report"])
        self.assertEqual(len(connector._transport.calls), 1)

    def test_rejects_oversize_and_unapproved_content_types(self):
        connector = self.make_connector([HTTPResponse(200, {"Content-Type": "text/plain"}, b"12345")], max_bytes=4)
        with self.assertRaisesRegex(ResearchSourceError, "byte cap"):
            connector.collect(["report"])
        connector = self.make_connector([HTTPResponse(200, {"Content-Type": "image/png"}, b"ok")])
        with self.assertRaisesRegex(ResearchSourceError, "content type"):
            connector.collect(["report"])

    def test_rejects_bad_urls_and_requires_explicit_allowlist(self):
        with self.assertRaisesRegex(ValueError, "non-empty host allowlist"):
            HTTPSResearchConnector({}, frozenset())
        for url in ("http://example.test/", "https://user@example.test/", "https://example.test:444/"):
            with self.assertRaises(ResearchSourceError):
                normalize_https_url(url)
        self.assertEqual(normalize_https_url("HTTPS://EXAMPLE.TEST:443/a#drop"), "https://example.test/a")

    def test_opt_in_workflow_uses_distinct_https_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport([HTTPResponse(200, {"Content-Type": "text/plain"}, b"Cited fact.")])
            connector = HTTPSResearchConnector(
                {"report": HTTPSResearchSource("report", "Report", "https://example.test/report")},
                frozenset({"example.test"}), transport=transport, resolver=resolver_for(PUBLIC_IP),
                clock=lambda: datetime(2026, 10, 11, tzinfo=UTC),
            )
            registry = CapabilityRegistry()
            register_https_workflow(
                registry, InMemoryMemoryStore(), {"report": HTTPSResearchSource("report", "Report", "https://example.test/report")},
                DeterministicProvider({"draft": {"markdown": "Cited fact [report].", "claims": [{"text": "Cited fact.", "source_id": "report"}]}}),
                directory, frozenset({"example.test"}), connector=connector,
            )
            result = Runtime(registry, SQLiteStateStore(":memory:")).run(
                build_https_workflow({"id": "b", "title": "HTTPS", "slug": "https", "provider_prompt": "draft"}, ["report"], "rejected"), "https-run"
            )
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.nodes["collect"].status, "succeeded")
            self.assertEqual(transport.calls[0][0], "https://example.test/report")

    def test_source_ids_are_pre_registered_and_unique(self):
        connector = self.make_connector([])
        with self.assertRaisesRegex(ValueError, "duplicates"):
            connector.collect(["report", "report"])
        with self.assertRaisesRegex(ValueError, "not allow-listed"):
            connector.collect(["other"])


if __name__ == "__main__":
    unittest.main()
