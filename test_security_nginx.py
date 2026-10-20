import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
NGINX_CONF = REPO_ROOT / "nginx.conf"
NGINX_TEST_COMMAND = (
    "mkdir -p /etc/nginx/ssl && "
    "if [ ! -s /etc/nginx/ssl/cert.pem ] || "
    "[ ! -s /etc/nginx/ssl/key.pem ]; then "
    "apk add --no-cache openssl >/dev/null && "
    "umask 077 && "
    "openssl req -x509 -nodes -days 1 -newkey rsa:2048 "
    "-keyout /etc/nginx/ssl/key.pem "
    "-out /etc/nginx/ssl/cert.pem -subj /CN=localhost "
    ">/dev/null 2>&1; "
    "fi && nginx -t"
)


class NginxSecurityTests(unittest.TestCase):
    def test_nginx_syntax(self):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "sh",
                "nginx-proxy",
                "-c",
                NGINX_TEST_COMMAND,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            "nginx -t failed:\n{}\n{}".format(result.stdout, result.stderr),
        )

    def test_limit_req_directive(self):
        content = NGINX_CONF.read_text(encoding="utf-8")
        self.assertIn(
            "limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;",
            content,
        )
        self.assertIn("limit_req zone=api_limit burst=20 nodelay;", content)

    def test_ssl_certificate_directive(self):
        content = NGINX_CONF.read_text(encoding="utf-8")
        self.assertIn("ssl_certificate /etc/nginx/ssl/cert.pem;", content)
        self.assertIn("ssl_certificate_key /etc/nginx/ssl/key.pem;", content)


if __name__ == "__main__":
    unittest.main()
