import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
NGINX_CONF = REPO_ROOT / "nginx.conf"


class NginxSecurityTests(unittest.TestCase):
    def test_nginx_syntax(self):
        if shutil.which("nginx") is None:
            self.skipTest("nginx not installed")
        result = subprocess.run(
            ["nginx", "-t", "-c", str(NGINX_CONF)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_limit_req_directive(self):
        content = NGINX_CONF.read_text()
        self.assertIn("limit_req", content)

    def test_ssl_certificate_directive(self):
        content = NGINX_CONF.read_text()
        self.assertIn("ssl_certificate", content)


if __name__ == "__main__":
    unittest.main()
