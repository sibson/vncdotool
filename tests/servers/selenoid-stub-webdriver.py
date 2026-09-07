#!/usr/bin/env python3
"""A WebDriver server that owns no browser, for Selenoid's driver mode.

Selenoid spawns it with `--port=N`, from the command line in browsers.json.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# Must match SELENOID_SESSION_ID in tests/functional/utils.py: Selenoid puts
# this straight into the /vnc/<id> path the test connects to, and nothing
# checks that the two agree.
SESSION_ID = "c2ec57a377e94f515b35b2a57caad26e"


class StubWebDriver(BaseHTTPRequestHandler):
    def _respond(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        # Selenoid polls the root until it answers; that is the readiness gate.
        self._respond({"value": {"ready": True, "message": "stub"}})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        # Both shapes: Selenoid reads the W3C body, older clients the flat one.
        self._respond(
            {
                "value": {"sessionId": SESSION_ID, "capabilities": {}},
                "sessionId": SESSION_ID,
                "status": 0,
            }
        )

    def do_DELETE(self) -> None:
        self._respond({"value": None})

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    HTTPServer(("127.0.0.1", args.port), StubWebDriver).serve_forever()
