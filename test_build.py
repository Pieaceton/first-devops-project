"""Тесты сборочного конвейера: build.sh должен собирать три релизных формата.

Проверяются:
  * успешная генерация dist/app-release.tar.gz, dist/devops-app.pyz и
    dist/devops-app_1.0.0_all.deb;
  * структура tar-архива (исходники, BUILD_INFO.txt с номером коммита, байткод);
  * корректность zipapp: shebang, точка входа main:main, права на исполнение
    и фактический запуск файла как самостоятельного приложения;
  * метаданные установочного пакета через dpkg-deb --info и его содержимое
    через dpkg-deb --contents.

Запуск: python3 -m unittest test_build -v
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BUILD_SCRIPT = REPO_ROOT / "build.sh"
DIST_DIR = REPO_ROOT / "dist"
TARBALL = DIST_DIR / "app-release.tar.gz"
PYZ = DIST_DIR / "devops-app.pyz"
BUILD_VERSION = "1.0.0"
DEB = DIST_DIR / "devops-app_{}_all.deb".format(BUILD_VERSION)


def run_command(command, cwd=None, env=None):
    """Запускает команду и возвращает результат без проверки кода возврата."""
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def ensure_built(artifact):
    """Собирает артефакт, если его ещё нет."""
    if not artifact.is_file():
        run_command(["bash", str(BUILD_SCRIPT)], cwd=REPO_ROOT)


def free_port():
    """Возвращает свободный TCP-порт для запуска тестового экземпляра."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BuildArtifactsTests(unittest.TestCase):
    """Проверки результатов работы build.sh."""

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["VERSION"] = BUILD_VERSION
        cls.build_result = run_command(
            ["bash", str(BUILD_SCRIPT)], cwd=REPO_ROOT, env=env
        )

    def test_build_script_finished_successfully(self):
        """build.sh должен завершиться с кодом 0."""
        self.assertEqual(
            0,
            self.build_result.returncode,
            "build.sh завершился с ошибкой:\n{}".format(self.build_result.stdout),
        )

    def test_all_three_artifacts_are_generated(self):
        """Сборка должна создать .tar.gz, .pyz и .deb."""
        for artifact in (TARBALL, PYZ, DEB):
            self.assertTrue(
                artifact.is_file(), "Не создан артефакт {}".format(artifact.name)
            )
            self.assertGreater(
                artifact.stat().st_size, 0, "Артефакт {} пустой".format(artifact.name)
            )

    def test_build_output_lists_all_artifacts(self):
        """Скрипт сборки должен сообщать обо всех трёх артефактах."""
        output = self.build_result.stdout
        for name in ("app-release.tar.gz", "devops-app.pyz", "devops-app_1.0.0_all.deb"):
            self.assertIn(name, output)


class TarballContentTests(unittest.TestCase):
    """Проверки содержимого dist/app-release.tar.gz."""

    @classmethod
    def setUpClass(cls):
        ensure_built(TARBALL)
        cls.tar = tarfile.open(str(TARBALL), "r:gz")
        cls.names = cls.tar.getnames()

    @classmethod
    def tearDownClass(cls):
        cls.tar.close()

    def test_archive_contains_main_py(self):
        """В архиве должен быть исходник приложения."""
        self.assertIn("app-release/main.py", self.names)

    def test_archive_contains_build_info(self):
        """В архиве должны быть метаданные сборки."""
        self.assertIn("app-release/BUILD_INFO.txt", self.names)

    def test_archive_contains_compiled_bytecode(self):
        """В архиве должен быть скомпилированный байткод Python."""
        bytecode = [name for name in self.names if name.endswith(".pyc")]
        self.assertTrue(bytecode, "В архиве нет скомпилированного байткода")

    def test_build_info_contains_commit(self):
        """BUILD_INFO.txt должен содержать номер коммита сборки."""
        handle = self.tar.extractfile("app-release/BUILD_INFO.txt")
        content = handle.read().decode("utf-8")
        self.assertIn("commit:", content)
        self.assertIn("version: {}".format(BUILD_VERSION), content)
        if shutil.which("git"):
            head = run_command(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
            self.assertIn(head, content, "BUILD_INFO.txt содержит неверный коммит")


class ZipappArtifactTests(unittest.TestCase):
    """Проверки исполняемого файла dist/devops-app.pyz."""

    @classmethod
    def setUpClass(cls):
        ensure_built(PYZ)
        cls.zip = zipfile.ZipFile(str(PYZ))

    @classmethod
    def tearDownClass(cls):
        cls.zip.close()

    def test_pyz_starts_with_shebang(self):
        """Первой строкой файла должен идти shebang python3."""
        with PYZ.open("rb") as handle:
            first_line = handle.readline().decode("utf-8").strip()
        self.assertEqual("#!/usr/bin/env python3", first_line)

    def test_pyz_is_executable(self):
        """Файл должен иметь права на исполнение."""
        if os.name == "posix":
            self.assertTrue(os.access(str(PYZ), os.X_OK), "Нет прав на исполнение")

    def test_pyz_contains_entry_point(self):
        """В архиве должны быть main.py и сгенерированная точка входа."""
        names = self.zip.namelist()
        self.assertIn("main.py", names)
        self.assertIn("__main__.py", names)
        entry = self.zip.read("__main__.py").decode("utf-8")
        self.assertIn("import main", entry)
        self.assertIn("main.main()", entry)

    def test_pyz_runs_as_standalone_application(self):
        """Файл должен запускаться напрямую и отдавать /health."""
        port = free_port()
        env = dict(os.environ, APP_HOST="127.0.0.1", APP_PORT=str(port))
        command = [str(PYZ)] if os.name == "posix" else [sys.executable, str(PYZ)]
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        try:
            payload = self.wait_for_health(port)
            self.assertEqual(200, payload[0])
            self.assertEqual({"status": "ok"}, json.loads(payload[1]))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    def wait_for_health(self, port, timeout=30):
        """Ждёт ответа /health от запущенного приложения."""
        url = "http://127.0.0.1:{}/health".format(port)
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    return response.status, response.read().decode("utf-8")
            except Exception as error:
                last_error = error
                time.sleep(0.5)
        self.fail("Приложение из .pyz не запустилось: {}".format(last_error))


class DebianPackageTests(unittest.TestCase):
    """Проверки установочного пакета dist/devops-app_1.0.0_all.deb."""

    @classmethod
    def setUpClass(cls):
        ensure_built(DEB)

    def setUp(self):
        if not shutil.which("dpkg-deb"):
            self.skipTest("dpkg-deb недоступен в этой системе")

    def test_dpkg_deb_info_returns_package_metadata(self):
        """dpkg-deb --info должен вернуть корректные метаданные пакета."""
        result = run_command(["dpkg-deb", "--info", str(DEB)])
        self.assertEqual(
            0,
            result.returncode,
            "dpkg-deb --info вернул ошибку:\n{}".format(result.stdout),
        )
        for field in (
            "Package: devops-app",
            "Version: {}".format(BUILD_VERSION),
            "Architecture: all",
            "Maintainer:",
            "Description:",
        ):
            self.assertIn(field, result.stdout, "Нет поля '{}' в метаданных".format(field))

    def test_package_contains_launcher_and_systemd_unit(self):
        """Пакет должен содержать лаунчер и unit-файл systemd."""
        result = run_command(["dpkg-deb", "--contents", str(DEB)])
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("./usr/local/bin/devops-app", result.stdout)
        self.assertIn("./etc/systemd/system/devops-app.service", result.stdout)
        self.assertIn("./opt/devops-app/main.py", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
