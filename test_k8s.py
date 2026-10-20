"""Syntax tests for Kubernetes YAML manifests."""

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent
K8S_DIR = REPO_ROOT / "k8s"


class KubernetesManifestTests(unittest.TestCase):
    def test_manifest_files_exist(self):
        manifest_files = sorted(K8S_DIR.glob("*.yml"))
        self.assertTrue(manifest_files, "No Kubernetes YAML manifests found")

    def test_manifest_yaml_syntax(self):
        manifest_files = sorted(K8S_DIR.glob("*.yml"))
        self.assertTrue(manifest_files, "No Kubernetes YAML manifests found")
        for manifest_file in manifest_files:
            with self.subTest(manifest=manifest_file.name):
                with manifest_file.open(encoding="utf-8") as stream:
                    manifest = yaml.safe_load(stream)
                self.assertIsInstance(manifest, dict)
                self.assertIn("apiVersion", manifest)
                self.assertIn("kind", manifest)


if __name__ == "__main__":
    unittest.main()
