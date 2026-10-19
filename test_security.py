"""DevSecOps-проверки безопасности репозитория.

Тесты написаны только на стандартной библиотеке Python, поэтому одинаково
запускаются на локальной машине, на GitHub Actions и на целевой VM:

    python3 -m unittest test_security -v

Набор проверок:

  * SecretScanningTests        - в репозитории не должно быть приватных ключей,
                                 токенов (GitHub, AWS, Slack, OpenAI), JWT и
                                 захардкоженных паролей;
  * DockerComposeSecurityTests - базовые практики безопасности docker-compose.yml;
  * DockerfileSecurityTests    - базовые практики безопасности Dockerfile;
  * PipelinePolicyTests        - политика пайплайна: security-тесты запускаются
                                 до сборки, релиз публикуется по тегу v*.

Документация (.md) проверяется только по правилам с высокой уверенностью
(приватные ключи и токены), а правило «захардкоженный пароль» к ней не
применяется: в документации допустимо приводить примеры значений.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "static",
    "venv",
}

# Файл сканера исключён из проверки: в нём записаны сами искомые шаблоны.
SKIP_FILES = {"test_security.py"}

SCAN_SUFFIXES = {
    ".cfg",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".properties",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

SCAN_NAMES = {".env", "Dockerfile"}

DOC_SUFFIXES = {".md", ".rst", ".txt"}

MAX_FILE_SIZE = 512 * 1024

SECRET_PATTERNS = (
    ("приватный ключ (PEM)", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("токен GitHub (classic)", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("токен GitHub (fine-grained)", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("токен Slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("API-ключ OpenAI", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<key>[A-Za-z0-9_.\-]*"
    r"(?:password|passwd|passphrase|secret|token|api[_-]?key|apikey|access[_-]?key|credential)"
    r"[A-Za-z0-9_.\-]*)\b\s*[:=]\s*"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s#]+)"
)

ENV_ASSIGNMENT_RE = re.compile(
    r"(?i)^\s*-\s*(?P<key>[A-Za-z0-9_.\-]*"
    r"(?:password|passwd|passphrase|secret|token|api[_-]?key|apikey|access[_-]?key|credential)"
    r"[A-Za-z0-9_.\-]*)\s*=\s*(?P<value>.*)$"
)

VOLUME_RE = re.compile(
    r"^\s*-\s*[\"']?(?P<source>(?:\.{1,2}/|/)[^:\s]*)"
    r":(?P<target>/[^:\s]*)(?::(?P<mode>\w+))?[\"']?\s*$"
)

# Значения-заглушки: не считаются «реальным» паролем.
PLACEHOLDER_VALUES = {
    "admin",
    "changeme",
    "change_me",
    "example",
    "none",
    "null",
    "redacted",
    "secret",
    "unset",
    "your_password_here",
}

VARIABLE_REFERENCE_MARKERS = ("${", "${{", "{{", "$(")

BARE_VARIABLE_RE = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$")

# Монтирования, которым по назначению нужен режим read-write.
ALLOWED_RW_MOUNTS = {"/var/lib/docker", "/var/run/docker.sock"}

DANGEROUS_CAPABILITIES = {
    "ALL",
    "DAC_READ_SEARCH",
    "NET_ADMIN",
    "SYS_ADMIN",
    "SYS_MODULE",
    "SYS_PTRACE",
}


def strip_quotes(value):
    """Убирает обрамляющие кавычки из значения."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def is_variable_reference(value):
    """Проверяет, что значение берётся из переменной окружения, а не задано вручную."""
    if any(marker in value for marker in VARIABLE_REFERENCE_MARKERS):
        return True
    return bool(BARE_VARIABLE_RE.match(value))


def iter_scannable_files():
    """Возвращает файлы репозитория, которые нужно проверить на секреты."""
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES and path.name not in SCAN_NAMES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue
        yield path


def read_lines(path):
    """Читает файл как список строк, игнорируя ошибки декодирования."""
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


class SecretScanningTests(unittest.TestCase):
    """Проверки отсутствия секретов в файлах репозитория."""

    def scan_for_pattern(self, pattern):
        """Ищет паттерн во всех сканируемых файлах и возвращает список находок."""
        findings = []
        for path in iter_scannable_files():
            for number, line in enumerate(read_lines(path), start=1):
                if pattern.search(line):
                    findings.append("{}:{}".format(path.relative_to(REPO_ROOT), number))
        return findings

    def test_no_private_keys_in_repository(self):
        """Приватные SSH/RSA-ключи не должны попадать в репозиторий."""
        findings = self.scan_for_pattern(SECRET_PATTERNS[0][1])
        self.assertEqual(
            [],
            findings,
            "Найдены приватные ключи (PEM) в файлах: {}".format(", ".join(findings)),
        )

    def test_no_github_tokens_in_repository(self):
        """Токены GitHub (classic и fine-grained) не должны попадать в репозиторий."""
        findings = []
        for _, pattern in SECRET_PATTERNS[1:3]:
            findings.extend(self.scan_for_pattern(pattern))
        self.assertEqual(
            [],
            findings,
            "Найдены токены GitHub в файлах: {}".format(", ".join(findings)),
        )

    def test_no_cloud_and_service_tokens_in_repository(self):
        """Ключи облачных провайдеров и сервисов не должны попадать в репозиторий."""
        findings = []
        for _, pattern in SECRET_PATTERNS[3:]:
            findings.extend(self.scan_for_pattern(pattern))
        self.assertEqual(
            [],
            findings,
            "Найдены токены облачных сервисов в файлах: {}".format(", ".join(findings)),
        )

    def test_no_hardcoded_passwords_in_repository(self):
        """Пароли и другие секреты должны задаваться через переменные окружения."""
        findings = []
        for path in iter_scannable_files():
            if path.suffix.lower() in DOC_SUFFIXES:
                continue
            for number, line in enumerate(read_lines(path), start=1):
                for match in SECRET_ASSIGNMENT_RE.finditer(line):
                    value = strip_quotes(match.group("value")).strip()
                    if not value:
                        continue
                    if is_variable_reference(value):
                        continue
                    if value.lower() in PLACEHOLDER_VALUES:
                        continue
                    findings.append(
                        "{}:{} ({})".format(
                            path.relative_to(REPO_ROOT), number, match.group("key")
                        )
                    )
        self.assertEqual(
            [],
            findings,
            "Найдены захардкоженные пароли/секреты: {}".format(", ".join(findings)),
        )


class DockerComposeSecurityTests(unittest.TestCase):
    """Базовые практики безопасности в docker-compose.yml."""

    @classmethod
    def setUpClass(cls):
        cls.text = COMPOSE_FILE.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_compose_file_exists(self):
        """Файл описания стека обязателен."""
        self.assertTrue(COMPOSE_FILE.is_file(), "Не найден docker-compose.yml")

    def test_no_privileged_containers(self):
        """Контейнеры не должны запускаться в привилегированном режиме."""
        offenders = [
            number
            for number, line in enumerate(self.lines, start=1)
            if re.search(r"^\s*privileged:\s*true", line, re.IGNORECASE)
        ]
        self.assertEqual(
            [], offenders, "Привилегированные контейнеры в строках: {}".format(offenders)
        )

    def test_no_host_network_namespace(self):
        """Использование host-сети расширяет поверхность атаки."""
        offenders = [
            number
            for number, line in enumerate(self.lines, start=1)
            if re.search(r"^\s*network_mode:\s*[\"']?host", line, re.IGNORECASE)
        ]
        self.assertEqual([], offenders, "host-сеть в строках: {}".format(offenders))

    def test_no_dangerous_capabilities(self):
        """Опасные Linux capabilities не должны выдаваться контейнерам."""
        offenders = [
            capability
            for capability in self.collect_capabilities()
            if capability.upper() in DANGEROUS_CAPABILITIES
        ]
        self.assertEqual(
            [], offenders, "Опасные capabilities: {}".format(", ".join(offenders))
        )

    def collect_capabilities(self):
        """Собирает все capability, объявленные в секциях cap_add."""
        capabilities = []
        collecting = False
        for line in self.lines:
            match = re.match(r"^\s*cap_add:\s*(?P<value>.*)$", line, re.IGNORECASE)
            if match:
                collecting = True
                value = match.group("value").strip()
                if value:
                    capabilities.extend(item.strip() for item in value.split(","))
                continue
            if collecting:
                item = re.match(r"^\s*-\s*(?P<value>[A-Za-z0-9_]+)\s*$", line)
                if item:
                    capabilities.append(item.group("value"))
                    continue
                collecting = False
        return capabilities

    def service_block(self, name):
        """Возвращает строки, относящиеся к сервису с указанным именем."""
        header = re.compile(r"^\s{{2}}{}:".format(re.escape(name)))
        next_service = re.compile(r"^\s{2}[A-Za-z0-9_.\-]+:")
        start = None
        for index, line in enumerate(self.lines):
            if start is None:
                if header.match(line):
                    start = index
                continue
            if next_service.match(line):
                return self.lines[start:index]
        if start is None:
            return []
        return self.lines[start:]

    def test_secrets_are_taken_from_environment(self):
        """Пароли и токены в environment должны приходить из переменных окружения."""
        offenders = []
        for number, line in enumerate(self.lines, start=1):
            match = ENV_ASSIGNMENT_RE.match(line)
            if not match:
                continue
            value = strip_quotes(match.group("value").strip()).strip()
            if not value:
                continue
            if not is_variable_reference(value):
                offenders.append("{}:{} ({})".format(number, match.group("key"), value))
        self.assertEqual(
            [],
            offenders,
            "Секреты заданы вручную вместо переменных окружения: {}".format(
                ", ".join(offenders)
            ),
        )

    def test_grafana_auto_login_disabled(self):
        """Автологин Grafana отключает аутентификацию - использовать нельзя."""
        offenders = [
            number
            for number, line in enumerate(self.lines, start=1)
            if re.search(r"GF_AUTH_AUTO_LOGIN_ENABLED\s*=\s*[\"']?true", line, re.IGNORECASE)
        ]
        self.assertEqual(
            [], offenders, "Включён автологин Grafana в строках: {}".format(offenders)
        )

    def test_host_mounts_are_read_only(self):
        """Монтирования каталогов хоста должны быть доступны только на чтение."""
        offenders = []
        for number, line in enumerate(self.lines, start=1):
            match = VOLUME_RE.match(line)
            if not match:
                continue
            source = match.group("source")
            mode = (match.group("mode") or "rw").lower()
            normalized = source.rstrip("/") or "/"
            if mode == "ro":
                continue
            if normalized in ALLOWED_RW_MOUNTS:
                continue
            offenders.append("{}:{} ({})".format(number, source, mode))
        self.assertEqual(
            [],
            offenders,
            "Каталоги хоста смонтированы в режиме read-write: {}".format(
                ", ".join(offenders)
            ),
        )

    def test_app_service_has_healthcheck(self):
        """Сервис приложения должен иметь healthcheck."""
        block = self.service_block("python-app")
        self.assertTrue(block, "Сервис python-app не найден в docker-compose.yml")
        has_healthcheck = any(
            re.match(r"^\s+healthcheck:\s*$", line) for line in block
        )
        self.assertTrue(has_healthcheck, "У сервиса python-app нет healthcheck")


class DockerfileSecurityTests(unittest.TestCase):
    """Базовые практики безопасности в Dockerfile."""

    @classmethod
    def setUpClass(cls):
        cls.text = DOCKERFILE.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_dockerfile_exists(self):
        """Файл сборки образа обязателен."""
        self.assertTrue(DOCKERFILE.is_file(), "Не найден Dockerfile")

    def test_base_image_is_pinned(self):
        """Базовый образ должен быть зафиксирован конкретной версией."""
        from_lines = [line for line in self.lines if re.match(r"^\s*FROM\s+", line, re.IGNORECASE)]
        self.assertTrue(from_lines, "В Dockerfile нет инструкции FROM")
        for line in from_lines:
            image = line.split()[1]
            self.assertIn(":", image, "Образ {} не зафиксирован версией".format(image))
            self.assertNotIn(":latest", image, "Образ {} использует тег latest".format(image))

    def test_container_runs_as_non_root(self):
        """Процесс в контейнере не должен работать от имени root."""
        users = [
            line.split()[1]
            for line in self.lines
            if re.match(r"^\s*USER\s+", line, re.IGNORECASE) and line.split()
        ]
        self.assertTrue(users, "В Dockerfile нет инструкции USER")
        self.assertNotIn("root", users, "Контейнер запускается от root")

    def test_no_remote_add_instruction(self):
        """ADD с внешним URL не проверяется контрольными суммами - используем COPY."""
        offenders = [
            number
            for number, line in enumerate(self.lines, start=1)
            if re.match(r"^\s*ADD\s+(https?://|ftp://)", line, re.IGNORECASE)
        ]
        self.assertEqual([], offenders, "ADD с внешним URL в строках: {}".format(offenders))

    def test_no_secrets_in_build_instructions(self):
        """Секреты не должны попадать в образ через ENV/ARG."""
        offenders = []
        for number, line in enumerate(self.lines, start=1):
            if not re.match(r"^\s*(ENV|ARG)\s+", line, re.IGNORECASE):
                continue
            for match in SECRET_ASSIGNMENT_RE.finditer(line):
                value = strip_quotes(match.group("value")).strip()
                if not value or is_variable_reference(value):
                    continue
                if value.lower() in PLACEHOLDER_VALUES:
                    continue
                offenders.append("{}:{}".format(number, match.group("key")))
        self.assertEqual([], offenders, "Секреты в инструкциях сборки: {}".format(offenders))

    def test_healthcheck_is_defined(self):
        """Образ должен содержать HEALTHCHECK."""
        found = any(
            re.match(r"^\s*HEALTHCHECK\s+", line, re.IGNORECASE) for line in self.lines
        )
        self.assertTrue(found, "В Dockerfile нет инструкции HEALTHCHECK")

    def test_dockerignore_excludes_git_directory(self):
        """Каталог .git не должен попадать в контекст сборки."""
        self.assertTrue(DOCKERIGNORE.is_file(), "Не найден .dockerignore")
        entries = {
            line.strip()
            for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        self.assertIn(".git", entries, "В .dockerignore не исключён каталог .git")


class PipelinePolicyTests(unittest.TestCase):
    """Политика пайплайна: security-тесты до сборки, релиз по тегу v*."""

    @classmethod
    def setUpClass(cls):
        cls.text = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_workflow_file_exists(self):
        """Файл пайплайна обязателен."""
        self.assertTrue(CI_WORKFLOW.is_file(), "Не найден .github/workflows/ci.yml")

    def test_security_tests_run_before_build(self):
        """Security-тесты должны выполняться до сборки релиза."""
        security_line = None
        build_line = None
        for number, line in enumerate(self.lines, start=1):
            if security_line is None and "test_security" in line:
                security_line = number
            if build_line is None and "./build.sh" in line:
                build_line = number
        self.assertIsNotNone(security_line, "В пайплайне нет запуска security-тестов")
        self.assertIsNotNone(build_line, "В пайплайне нет шага сборки")
        self.assertLess(
            security_line,
            build_line,
            "Security-тесты должны запускаться до сборки (строки {} и {})".format(
                security_line, build_line
            ),
        )

    def test_release_is_triggered_by_version_tag(self):
        """Релиз должен публиковаться по тегу версии вида v1.0.0."""
        self.assertIn("tags:", self.text, "В пайплайне нет триггера по тегам")
        self.assertRegex(self.text, r"tags:\s*\[.*v\*.*\]", "Нет триггера по тегам v*")
        self.assertIn("softprops/action-gh-release", self.text, "Нет шага публикации релиза")

    def test_release_job_has_write_permissions(self):
        """Для публикации релиза нужны права contents: write."""
        self.assertIn("contents: write", self.text, "У job-а релиза нет прав contents: write")
