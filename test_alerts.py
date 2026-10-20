"""Юнит-тесты правил алертинга Prometheus.

Проверяются:
  * структура `alert_rules.yml`: группа `infrastructure_alerts` и три боевых
    алерта (AppDown, HighCpuLoad, LowDiskSpace) с полями `alert`, `expr`,
    `for`, `labels.severity` и `annotations.summary`;
  * подключение файла правил в `prometheus.yml` через `rule_files`;
  * проброс `alert_rules.yml` в контейнер prometheus в `docker-compose.yml`.

YAML разбирается собственным минимальным парсером на стандартной библиотеке,
поэтому тесты не зависят от PyYAML.

Запуск: python3 -m unittest test_alerts -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ALERT_RULES_FILE = REPO_ROOT / "alert_rules.yml"
PROMETHEUS_CONFIG = REPO_ROOT / "prometheus.yml"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

GROUP_NAME = "infrastructure_alerts"
EXPECTED_ALERTS = ("AppDown", "HighCpuLoad", "LowDiskSpace")


def strip_quotes(value):
    """Убирает обрамляющие кавычки из значения."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_alert_rules(text):
    """Разбирает alert_rules.yml в структуру {группа: [правило, ...]}.

    Поддерживается подмножество YAML, используемое в файле правил:
    groups -> name -> rules -> alert/expr/for/labels/annotations.
    """
    groups = {}
    group = None
    rule = None
    section = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- name:"):
            group = strip_quotes(stripped.split(":", 1)[1].strip())
            groups[group] = []
            rule = None
            section = None
            continue
        if stripped.startswith("- alert:"):
            rule = {
                "alert": strip_quotes(stripped.split(":", 1)[1].strip()),
                "labels": {},
                "annotations": {},
            }
            groups.setdefault(group, []).append(rule)
            section = None
            continue
        if rule is None:
            continue
        if stripped.startswith("expr:"):
            rule["expr"] = strip_quotes(stripped.split(":", 1)[1].strip())
            continue
        if stripped.startswith("for:"):
            rule["for"] = strip_quotes(stripped.split(":", 1)[1].strip())
            continue
        if stripped.startswith("labels:"):
            section = "labels"
            continue
        if stripped.startswith("annotations:"):
            section = "annotations"
            continue
        key, separator, value = stripped.partition(":")
        if separator and section:
            rule[section][key.strip()] = strip_quotes(value.strip())
    return groups


def rule_files_entries(text):
    """Возвращает список файлов правил, объявленных в prometheus.yml."""
    entries = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("rule_files:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value:
            for item in value.strip("[]").split(","):
                entries.append(strip_quotes(item.strip()))
            continue
        for follow in lines[index + 1:]:
            if not follow.strip().startswith("-"):
                break
            entries.append(strip_quotes(follow.strip().lstrip("-").strip()))
    return entries


def compose_service_block(text, name):
    """Возвращает строки блока сервиса из docker-compose.yml."""
    lines = text.splitlines()
    header = re.compile(r"^  {}:".format(re.escape(name)))
    next_service = re.compile(r"^  [A-Za-z0-9_.\-]+:")
    start = None
    for index, line in enumerate(lines):
        if start is None:
            if header.match(line):
                start = index
            continue
        if next_service.match(line):
            return lines[start:index]
    if start is None:
        return []
    return lines[start:]


class AlertRulesFileTests(unittest.TestCase):
    """Проверки содержимого alert_rules.yml."""

    @classmethod
    def setUpClass(cls):
        cls.text = ALERT_RULES_FILE.read_text(encoding="utf-8")
        cls.groups = parse_alert_rules(cls.text)
        cls.rules = {rule["alert"]: rule for rule in cls.groups.get(GROUP_NAME, [])}

    def test_alert_rules_file_exists(self):
        """Файл правил обязателен."""
        self.assertTrue(ALERT_RULES_FILE.is_file(), "Не найден alert_rules.yml")

    def test_infrastructure_alerts_group_exists(self):
        """Должна быть группа правил infrastructure_alerts."""
        self.assertIn(GROUP_NAME, self.groups, "Нет группы {}".format(GROUP_NAME))

    def test_all_three_alerts_are_defined(self):
        """В группе должны быть все три алерта."""
        for name in EXPECTED_ALERTS:
            self.assertIn(name, self.rules, "Нет алерта {}".format(name))
        self.assertEqual(len(EXPECTED_ALERTS), len(self.rules))

    def test_every_alert_has_required_fields(self):
        """У каждого алерта должны быть все обязательные поля."""
        for name, rule in self.rules.items():
            self.assertTrue(rule.get("alert"), "У алерта {} нет поля alert".format(name))
            self.assertTrue(rule.get("expr"), "У алерта {} нет поля expr".format(name))
            self.assertTrue(rule.get("for"), "У алерта {} нет поля for".format(name))
            severity = rule["labels"].get("severity")
            self.assertTrue(severity, "У алерта {} нет labels.severity".format(name))
            self.assertIn(
                severity, ("critical", "warning"), "Недопустимый severity у {}".format(name)
            )
            summary = rule["annotations"].get("summary")
            self.assertTrue(summary, "У алерта {} нет annotations.summary".format(name))

    def test_appdown_alert(self):
        """AppDown: python-app не отвечает дольше минуты, severity critical."""
        rule = self.rules["AppDown"]
        self.assertEqual('up{job="python-app"} == 0', rule["expr"])
        self.assertEqual("1m", rule["for"])
        self.assertEqual("critical", rule["labels"]["severity"])

    def test_high_cpu_load_alert(self):
        """HighCpuLoad: CPU выше 85% дольше двух минут, severity warning."""
        rule = self.rules["HighCpuLoad"]
        self.assertIn("node_cpu_seconds_total", rule["expr"])
        self.assertIn("85", rule["expr"])
        self.assertEqual("2m", rule["for"])
        self.assertEqual("warning", rule["labels"]["severity"])

    def test_low_disk_space_alert(self):
        """LowDiskSpace: доступно меньше 15% диска, severity warning."""
        rule = self.rules["LowDiskSpace"]
        self.assertIn("node_filesystem_avail_bytes", rule["expr"])
        self.assertIn("15", rule["expr"])
        self.assertEqual("warning", rule["labels"]["severity"])


class AlertRulesWiringTests(unittest.TestCase):
    """Проверки подключения правил к Prometheus."""

    def test_prometheus_config_loads_rule_file(self):
        """prometheus.yml должен подключать alert_rules.yml через rule_files."""
        text = PROMETHEUS_CONFIG.read_text(encoding="utf-8")
        entries = rule_files_entries(text)
        self.assertTrue(entries, "В prometheus.yml нет секции rule_files")
        self.assertIn("alert_rules.yml", entries)

    def test_alert_rules_mounted_into_prometheus_container(self):
        """docker-compose.yml должен пробрасывать правила в контейнер."""
        text = COMPOSE_FILE.read_text(encoding="utf-8")
        block = compose_service_block(text, "prometheus")
        self.assertTrue(block, "Сервис prometheus не найден в docker-compose.yml")
        mounts = [line for line in block if "alert_rules.yml" in line]
        self.assertTrue(mounts, "alert_rules.yml не смонтирован в контейнер prometheus")
        self.assertRegex(
            mounts[0],
            r"\./alert_rules\.yml:/etc/prometheus/alert_rules\.yml:ro",
            "Файл правил должен монтироваться в режиме read-only",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
