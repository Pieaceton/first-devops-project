"""Unit-тесты для приложения main.py.

Покрывают три слоя:
  * чистые функции формирования метрик (render_metrics, increment_requests);
  * HTTP-эндпоинты, поднятые на реальном сокете (коды ответов, заголовки, тело);
  * потокобезопасность счётчика запросов.

Запуск: python3 -m unittest discover -v
"""

import contextlib
import io
import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer

import main


def parse_exposition(payload):
    """Разбирает текстовый формат Prometheus в словарь {имя: значение}."""
    values = {}
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, raw_value = line.partition(" ")
        values[name] = float(raw_value)
    return values


class MetricsRenderingTests(unittest.TestCase):
    """Проверки функции формирования метрик."""

    def test_render_metrics_exposes_expected_series(self):
        payload = main.render_metrics()
        self.assertIn("# HELP app_http_requests_total", payload)
        self.assertIn("# TYPE app_http_requests_total counter", payload)
        self.assertIn("# HELP app_uptime_seconds", payload)
        self.assertIn("# TYPE app_uptime_seconds gauge", payload)

    def test_render_metrics_values_are_numeric(self):
        values = parse_exposition(main.render_metrics())
        self.assertIn("app_http_requests_total", values)
        self.assertIn("app_uptime_seconds", values)
        self.assertGreaterEqual(values["app_http_requests_total"], 0)
        self.assertGreater(values["app_uptime_seconds"], 0)

    def test_render_metrics_ends_with_newline(self):
        self.assertTrue(main.render_metrics().endswith("\n"))

    def test_increment_requests_advances_counter(self):
        before = parse_exposition(main.render_metrics())["app_http_requests_total"]
        returned = main.increment_requests()
        after = parse_exposition(main.render_metrics())["app_http_requests_total"]
        self.assertEqual(after, before + 1)
        self.assertEqual(returned, after)

    def test_counter_is_thread_safe(self):
        before = parse_exposition(main.render_metrics())["app_http_requests_total"]
        threads_count = 20
        per_thread = 50

        def worker():
            for _ in range(per_thread):
                main.increment_requests()

        threads = [threading.Thread(target=worker) for _ in range(threads_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        after = parse_exposition(main.render_metrics())["app_http_requests_total"]
        self.assertEqual(after, before + threads_count * per_thread)


class HttpEndpointTests(unittest.TestCase):
    """Проверки HTTP-эндпоинтов на реальном сокете."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), main.SimpleHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        url = "http://127.0.0.1:{}{}".format(self.port, path)
        # Логи handler-а заглушаем, чтобы не засорять вывод unittest.
        with contextlib.redirect_stdout(io.StringIO()):
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")
                return response.status, response.headers.get("Content-Type", ""), body

    def test_health_returns_json_ok(self):
        status, content_type, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_health_ignores_query_string(self):
        status, _, body = self.get("/health?probe=1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_metrics_returns_prometheus_text(self):
        status, content_type, body = self.get("/metrics")
        self.assertEqual(status, 200)
        self.assertIn("text/plain", content_type)
        values = parse_exposition(body)
        self.assertIn("app_http_requests_total", values)
        self.assertIn("app_uptime_seconds", values)

    def test_root_returns_html(self):
        status, content_type, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("<h1>", body)

    def test_unknown_path_falls_back_to_html(self):
        status, content_type, _ = self.get("/no-such-page")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)

    def test_http_request_increments_counter(self):
        before = parse_exposition(self.get("/metrics")[2])["app_http_requests_total"]
        self.get("/health")
        after = parse_exposition(self.get("/metrics")[2])["app_http_requests_total"]
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
