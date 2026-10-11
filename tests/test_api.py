import http.client
import json
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agos.api import DemoService, make_handler, serve


class LocalAPITests(unittest.TestCase):
    def setUp(self):
        self.service = DemoService()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.server.RequestHandlerClass = make_handler(self.service, self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        request_headers = headers or {}
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, dict(response.getheaders()), json.loads(payload.decode("utf-8")) if payload else None)
        connection.close()
        return result

    def post(self, path, body=b"{}", headers=None):
        request_headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        request_headers.update(headers or {})
        return self.request("POST", path, body, request_headers)

    def test_explicit_review_then_dry_run_records_append_only_history(self):
        status, _, state = self.request("GET", "/v1/demo")
        self.assertEqual(status, 200)
        self.assertEqual(state["review"], "pending")
        self.assertTrue(state["dry_run_only"])

        status, _, receipt = self.post("/v1/demo/dry-run")
        self.assertEqual(status, 409)
        self.assertIn("explicit review approval", receipt["error"])

        status, _, state = self.post("/v1/demo/review/approve")
        self.assertEqual(status, 200)
        self.assertEqual(state["review"], "approved")

        status, _, receipt = self.post("/v1/demo/dry-run")
        self.assertEqual(status, 200)
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(receipt["publish"]["target"], "dry-run")
        self.assertFalse(receipt["external_publish"])

        status, _, history = self.request("GET", "/v1/demo/history")
        self.assertEqual(status, 200)
        self.assertEqual([entry["event"] for entry in history["history"]], [
            "demo.started", "review.approved", "dry_run.completed",
        ])
        self.assertEqual([entry["sequence"] for entry in history["history"]], [1, 2, 3])

    def test_rejection_is_explicit_and_prevents_dry_run(self):
        self.assertEqual(self.post("/v1/demo/review/reject")[0], 200)
        status, _, payload = self.post("/v1/demo/dry-run")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "dry-run requires explicit review approval")

    def test_post_schema_content_type_and_body_are_strict(self):
        status, _, payload = self.request("POST", "/v1/demo/review/approve", b"{}")
        self.assertEqual(status, 415)
        self.assertIn("Content-Type", payload["error"])

        status, _, payload = self.post("/v1/demo/review/approve", b'{"decision":"approved"}')
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "body must be an empty JSON object")

        status, _, payload = self.post("/v1/demo/review/approve", b"{" + b" " * 9000 + b"}")
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "request body is too large")

    def test_cors_allows_only_same_local_origin_and_preflight(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, headers, _ = self.request("GET", "/v1/demo", headers={"Origin": origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
        self.assertEqual(headers["Vary"], "Origin")

        status, _, payload = self.request("GET", "/v1/demo", headers={"Origin": "https://example.test"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "origin is not allowed")

        status, headers, payload = self.request("OPTIONS", "/v1/demo", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(status, 204)
        self.assertIsNone(payload)
        self.assertEqual(headers["Access-Control-Allow-Methods"], "GET, POST")

    def test_network_bindings_are_refused(self):
        with self.assertRaises(ValueError):
            serve("0.0.0.0", 8765)

    def test_history_is_append_only_when_a_local_file_is_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/activity.jsonl"
            service = DemoService(path)
            service.decide("approved")
            self.assertEqual([entry["sequence"] for entry in service.history()], [1, 2])
            restarted = DemoService(path)
            self.assertEqual([entry["event"] for entry in restarted.history()], ["demo.started", "review.approved", "demo.started"])

    def test_studio_development_origin_is_allowed(self):
        origin = "http://127.0.0.1:3000"
        status, headers, _ = self.request("GET", "/v1/demo", headers={"Origin": origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], origin)


if __name__ == "__main__":
    unittest.main()
