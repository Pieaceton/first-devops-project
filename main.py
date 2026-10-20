import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

HOST = os.environ.get("APP_HOST", "0.0.0.0")
PORT = int(os.environ.get("APP_PORT", "8000"))
START_TIME = time.time()

_counter_lock = threading.Lock()
_counters = {"http_requests_total": 0}


def increment_requests():
    with _counter_lock:
        _counters["http_requests_total"] += 1
        return _counters["http_requests_total"]


def render_metrics():
    uptime = time.time() - START_TIME
    lines = [
        "# HELP app_http_requests_total Total number of HTTP requests handled by the application.",
        "# TYPE app_http_requests_total counter",
        "app_http_requests_total {}".format(_counters["http_requests_total"]),
        "# HELP app_uptime_seconds Application uptime in seconds.",
        "# TYPE app_uptime_seconds gauge",
        "app_uptime_seconds {:.3f}".format(uptime),
    ]
    return "\n".join(lines) + "\n"


class SimpleHandler(BaseHTTPRequestHandler):
    server_version = "SimpleApp/1.0"

    def _respond(self, status, body, content_type):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        increment_requests()
        path = urlparse(self.path).path

        if path == "/health":
            self._respond(200, json.dumps({"status": "ok"}), "application/json")
        elif path == "/metrics":
            self._respond(200, render_metrics(), "text/plain; version=0.0.4; charset=utf-8")
        else:
            html = (
                "<h1>Ура! Мой сервер Ubuntu (192.168.0.218) отдает сайт через связку Nginx + Docker!</h1>"
                '<p>Health check: <a href="/health">/health</a> | Metrics: <a href="/metrics">/metrics</a></p>'
            )
            self._respond(200, html, "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        print("{} - {}".format(self.address_string(), fmt % args), flush=True)


def main():
    """Точка входа приложения (используется в том числе zipapp-артефактом)."""
    print("Веб-сервер запущен внутри контейнера на порту {}...".format(PORT), flush=True)
    HTTPServer((HOST, PORT), SimpleHandler).serve_forever()


if __name__ == "__main__":
    main()
