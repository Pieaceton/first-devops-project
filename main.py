from http.server import HTTPServer, BaseHTTPRequestHandler


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = "<h1>Ура! Мой сервер Ubuntu (192.168.0.218) отдает сайт через связку Nginx + Docker!</h1>"
        self.wfile.write(html.encode("utf-8"))


print("Веб-сервер запущен внутри контейнера на порту 8000...", flush=True)
HTTPServer(("0.0.0.0", 8000), SimpleHandler).serve_forever()
